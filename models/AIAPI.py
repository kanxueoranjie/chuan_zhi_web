import os
import random
import time
import logging

from openai import (
    APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError,
)
from pathlib import Path
from dotenv import load_dotenv

# 这几种错误值得重试：超时、连不上、被限流
RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError)

# 没配 DEEPSEEK_MODEL 时用这个
DEFAULT_MODEL = "deepseek-flash"

# 先把 .env 里的 API Key 读进来
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class AI:
    def __init__(self):
        # 取 Key，没有就直接报错，别让人猜哪里出了问题
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise ValueError("请先设置环境变量 DEEPSEEK_API_KEY")
        # 建客户端，把地址指到 DeepSeek
        self.client = OpenAI(
            api_key=key,
            base_url="https://api.deepseek.com",
        )

        # 日志：之前只拿到 logger 没加 handler，重试过程全被丢掉了看不见
        self.log = logging.getLogger("llm")
        if not self.log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%H:%M:%S",
            ))
            self.log.addHandler(handler)
        self.log.setLevel(logging.INFO)

    # 问 AI 一个问题
    # super_order 是"你是谁、怎么回答"，user_order 是用户真正问的内容
    def get_ai(self, super_order, user_order):
        try:
            response = self.client.chat.completions.create(
                # 用 flash 模型，速度快、便宜
                model=DEFAULT_MODEL,

                # 两条消息：一条是身份设定，一条是用户问题
                messages=[
                    {"role": "system", "content": super_order},
                    {"role": "user", "content": user_order},
                ],

                # 1.3 偏活泼一点，适合聊天
                temperature=1.3,

                # 最多生成 2000 字，防止回复无限长
                max_tokens=2000,

                # 等全部生成完再一起返回，不做流式输出
                stream=False,

                # 打开深度思考，回答质量会好一些（会多花一点 token）
                reasoning_effort="high",
                extra_body={"thinking": {"type": "enabled"}},
            )

            # 把返回结果里的文字取出来
            reply = response.choices[0].message.content
            return reply

        except Exception as e:
            # 调 AI 失败不要崩，把原因当文本返回，页面还能正常显示
            return f"AI 调用失败：{e}"

    # 判断这个异常值不值得重试
    def _retryable(self, exc: Exception) -> bool:
        # 超时、连不上、限流 → 重试
        if isinstance(exc, RETRYABLE):
            return True
        # 服务端 5xx → 重试；4xx 是我们自己的问题（比如 Key 错了），重试没用
        if isinstance(exc, APIStatusError):
            return exc.status_code >= 500
        return False

    def chat(
        self,
        messages,                    # 对话内容，一个列表
        *,                           # 后面的参数必须写名字传，防止写错位置
        model: str | None = None,    # 用哪个模型
        temperature: float = 0.2,    # 随机性，0 最稳，1 最飘
        max_tokens: int = 800,       # 最多生成多少 token
        thinking: bool = True,       # 是否开启思考模式
        retries: int = 3,            # 失败后最多重试几次
        timeout: int = 30,           # 单次请求超时秒数
        tools=None,                  # 给 agent 用的工具清单，普通问答传 None
        tool_choice=None,            # "auto" 让模型自己决定要不要调工具
    ):
        """多轮对话 + 自动重试。返回 message 对象（不是文字），因为要拿 tool_calls"""
        model = model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "extra_body": {"thinking": {"type": "enabled" if thinking else "disabled"}},
        }
        # 只有真要用工具时才带上这两个参数，不然普通问答没必要传
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        for attempt in range(retries + 1):
            started = time.perf_counter()

            try:
                resp = self.client.chat.completions.create(**kwargs)

            # 之前这里只捕获 RETRYABLE，APIStatusError(5xx) 根本进不来，
            # 所以 _retryable() 里"5xx 可重试"的判断永远走不到
            except Exception as exc:
                is_last = attempt == retries

                if not self._retryable(exc) or is_last:
                    # 之前这行格式串写错了：attemp=%d%d 少了斜杠，
                    # wait 的位置又传的是异常对象，日志格式化会直接报错
                    self.log.error(
                        "fail model=%s attempt=%d/%d %s error=%s",
                        model, attempt + 1, retries, type(exc).__name__, exc,
                    )
                    raise

                wait = 2 ** attempt + random.random()
                self.log.warning(
                    "retry model=%s attempt=%d/%d %s wait=%.1fs",
                    model, attempt + 1, retries, type(exc).__name__, wait,
                )
                time.sleep(wait)
                continue

            usage = resp.usage
            self.log.info(
                "ok model=%s attempt=%d %.0fms prompt=%d completion=%d finish=%s",
                resp.model,
                attempt + 1,
                (time.perf_counter() - started) * 1000,
                usage.prompt_tokens,
                usage.completion_tokens,
                resp.choices[0].finish_reason,
            )
            return resp.choices[0].message

        # 正常走不到这里（循环里要么 return 要么 raise），留着兜底
        raise RuntimeError("chat() 没有返回值")
