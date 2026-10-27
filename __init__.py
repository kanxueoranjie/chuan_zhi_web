import os
import threading
from functools import wraps
from pathlib import Path

from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

from models.CLASSSQL import ClassSQL
from models.AIAPI import AI

import json
import hashlib
import base64

# 先把 .env 里的配置读进来
load_dotenv(Path(__file__).resolve().parent / ".env")

# 创建 Flask 应用
app = Flask(__name__)

# 登录状态靠它加密，不设会报错
app.secret_key = os.getenv("SECRET_KEY", "chuan_zhi_web_dev_key_2026")

# 存上一次的 AI 分析结果，数据没变就不用再花钱调用
_ai_cache = {"signature": None, "text": None, "rows": 0}
# 加个锁，防止两个请求同时改缓存
_ai_lock = threading.Lock()

# 让 AI 按班费数据写一段分析
AI_SYSTEM_PROMPT = "这是班费的数据，请分析"

# ==================== 角色与权限 ====================
# 数字越大权限越高，判断权限时比大小就行
# student    普通用户   → 除 /superuser、/only_user 外都能进
# admin      超级用户   → 除 /only_user 外都能进
# only_user  唯一用户   → 全都能进
ROLE_LEVEL = {
    "student":   1,
    "admin":     2,
    "only_user": 3,
}


def role_required(min_role):
    """要求最低角色等级。未登录跳登录页，等级不够返回 403。"""
    # 查这个页面最低要几级
    need = ROLE_LEVEL.get(min_role, 999)

    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # 1) 没登录 → 先去登录页，并记住他本来想访问哪
            if not session.get("student_id"):
                return redirect(url_for("login", next=request.path))

            # 2) 看当前用户是几级，不够就拦下来
            level = ROLE_LEVEL.get(session.get("role"), 0)
            if level < need:
                # 接口返回 JSON，页面返回 403 页面
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "msg": "权限不足"}), 403
                return render_template(
                    "403.html",
                    need=min_role,
                    my=session.get("role"),
                    my_name=session.get("name"),
                ), 403

            return f(*args, **kwargs)
        return wrapper
    return deco


# 兼容旧写法：只要求登录
login_required = role_required("student")


# ==================== 全站强制登录 ====================
# 不需要登录就能访问的页面（这里写的是函数名，不是网址）
PUBLIC_ENDPOINTS = {
    "login",     # 登录页
    "logout",    # 登出（登录过期了也要能点）
    "static",    # 静态文件（CSS/JS，不放行的话登录页样式全丢）
}


@app.before_request
def require_login_everywhere():
    """全站登录拦截：除白名单外，一律要求已登录"""
    # 1) 白名单里的直接放行
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None

    # 2) 没登录的话，接口返回 401，页面跳登录页
    #    这里先判断登录，不因为地址写错就放过去
    if not session.get("student_id"):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "msg": "未登录"}), 401
        return redirect(url_for("login", next=request.path))

    return None

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

# ==================== 角色 → 默认首页 ====================
# 现在还没有各角色专属的页面，所以先统一回工作台
# 等后台录入和控制台做出来，再按身份分开跳
def _home_of(role):
    """每个角色登录后的默认落地页"""
    return url_for("index")


# 判断这个角色能不能进某个地址
def _can_access(path, role):
    """判断某路径当前角色能不能进（给登录后的 next 用）"""
    level = ROLE_LEVEL.get(role, 0)
    if path.startswith("/only_user"):
        return level >= ROLE_LEVEL["only_user"]
    if path.startswith("/superuser") or path.startswith("/api/add_student"):
        return level >= ROLE_LEVEL["admin"]
    return True


# ==================== 登录 ====================
@app.route('/login', methods=["GET", "POST"])
def login():
    # 已经登录了，直接送去他自己的首页
    if session.get("student_id"):
        return redirect(_home_of(session.get("role")))

    # GET 就是打开登录页
    if request.method == "GET":
        return render_template("login.html")

    # ----- POST：校验账号密码 -----
    # 取出用户填的内容，去掉首尾空格
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    # 空着就不用往下查数据库了
    if not username or not password:
        return render_template("login.html",
                               error="账号和密码不能为空",
                               username=username), 400

    # 连数据库，按账号查这一条
    sql = ClassSQL()
    try:
        user = sql.get_user_by_username(username)
    finally:
        sql.close()

    # 账号不存在 / 密码错 → 提示统一写"账号或密码错误"
    # 这样别人猜不出到底是账号错了还是密码错了
    if not user or not check_password_hash(user["password"], password):
        return render_template("login.html",
                               error="账号或密码错误",
                               username=username), 401

    # ----- 成功：把身份记到 session 里 -----
    session["student_id"] = user["student_id"]
    session["username"]   = user["username"]
    session["name"]       = user["name"]
    session["role"]       = user["role"]

    # 优先送他回原来想去的页面
    # 只接受站内地址（以 / 开头），防止被跳去外站
    nxt = request.args.get("next") or request.form.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//") and _can_access(nxt, user["role"]):
        return redirect(nxt)

    return redirect(_home_of(user["role"]))


# ==================== 登出 ====================
@app.route('/logout')
def logout():
    # 清空登录状态，再回登录页
    session.clear()
    return redirect(url_for("login"))

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
