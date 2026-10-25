import threading
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

from models.CLASSSQL import ClassSQL
from models.AIAPI import AI

import json
import hashlib

# 先把 .env 里的配置读进来
load_dotenv(Path(__file__).resolve().parent / ".env")

# 创建 Flask 应用
app = Flask(__name__)

# 存上一次的 AI 分析结果，数据没变就不用再花钱调用
_ai_cache = {"signature": None, "text": None, "rows": 0}
# 加个锁，防止两个请求同时改缓存
_ai_lock = threading.Lock()

# 让 AI 按班费数据写一段分析
AI_SYSTEM_PROMPT = "这是班费的数据，请分析"

# 把数据转成字符串，顺便算个"指纹"
def encrypt(datas):
    # 数据一样，算出来的指纹就一样
    row = json.dumps(datas, ensure_ascii=False, default=str, indent=2)
    sig = hashlib.md5(row.encode("utf-8")).hexdigest()
    return row, sig

# 对比指纹，决定要不要重新问 AI
def compare(datas):
    row, sig = encrypt(datas)

    # 指纹和上次一样，直接用上次的结果
    with _ai_lock:
        if _ai_cache["signature"] == sig and _ai_cache["text"]:
            return _ai_cache["text"], True

    # 指纹变了，重新调一次 AI
    ai = AI()
    text = ai.get_ai(AI_SYSTEM_PROMPT, row)

    # 调用成功才存缓存，失败的不要存
    if not str(text).startswith("AI 调用失败"):
        with _ai_lock:
            _ai_cache["signature"] = sig
            _ai_cache["text"] = text
            _ai_cache["rows"] = len(datas)

    return text, False

# 工作台首页
@app.route('/')
def index():
    return render_template("index.html")

# 班费公示界面
@app.route('/class_funds')
def class_funds():
    # 连数据库
    sql = ClassSQL()
    try:
        # 取班费数据，表里没数据也给个空列表
        datas = sql.get_table() or []
    finally:
        sql.close()

    # 让 AI 分析一次，数据没变就用缓存
    ai_data, cached = compare(datas)
    return render_template("class_funds.html",
                           datas=datas,
                           ai=ai_data,
                           ai_cached=cached
                           )

# 请假界面
@app.route('/six_day', methods=["GET", "POST"])
def six_day():
    # GET 就是打开请假表单
    if request.method == "GET":
        return render_template("six_day.html")

    student_id = request.form.get("student_id")        # 学号
    name = request.form.get('name')                    # 姓名
    six_day_reason = request.form.get('six_day_reason')  # 请假理由
    leave_time = request.form.get('time')              # 请假时间
    file = request.files.get('picture')                # 证明图片

    # 五项缺一项就不让提交
    if not student_id or not name or not leave_time or not file or not six_day_reason:
        return jsonify({'message': '不能为空'}), 400

    # 只收图片，别的文件一律拒绝
    if not (file.mimetype or "").startswith('image/'):
        return jsonify({'message': '只能上传图片'}), 400

    # 图片读成二进制，等下直接存进数据库
    picture_bytes = file.read()

    # 连数据库
    sql = ClassSQL()
    try:
        # 表不存在就先建好
        sql.create_table(sql.class_funds_sql)
        # 把这次请假存进去
        sql.take_class_funds_sql(student_id, name, picture_bytes, six_day_reason, leave_time)

    finally:
        sql.close()

    # 成功返回 JSON，前端好处理
    return jsonify({'message': '提交成功'})


# 本地运行时用这个入口，正式上线是 gunicorn 启动的
if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5000, debug=True)
