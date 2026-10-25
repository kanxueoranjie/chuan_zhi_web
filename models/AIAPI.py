from openai import OpenAI
from pathlib import Path
from dotenv import load_dotenv
import os

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
            api_key = key,
            base_url = "https://api.deepseek.com",
        )

    # 问 AI 一个问题
    # super_order 是"你是谁、怎么回答"，user_order 是用户真正问的内容
    def get_ai(self,super_order,user_order):
        try:
            response = self.client.chat.completions.create(
                # 用 flash 模型，速度快、便宜
                model="deepseek-flash",

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
            print(reply)                  # 调试用，正式上线可以删

            return reply

        except Exception as e:
            # 调 AI 失败不要崩，把原因当文本返回，页面还能正常显示
            return f"AI 调用失败：{e}"
