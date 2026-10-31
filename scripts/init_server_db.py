# -*- coding: utf-8 -*-
r"""
服务器端一键初始化数据库
用法（服务器上）：
    cd ~/chuan_zhi_web
    source venv/bin/activate
    python scripts/init_server_db.py

做什么：
  1. 建 STUDENTS2603 表（含 username / password / role）
  2. 灌入 50 个学生（登录名 = 学号，初始密码见下方 STUDENT_PWD）
  3. 建 2 个管理员账号：
        only_user  唯一用户
        superuser  超级管理员
     ★ 管理员密码从 .env 读（ADMIN_PWD_ONLY_USER / ADMIN_PWD_SUPERUSER）
       没配置就随机生成一个并打印出来，不会在代码里写死
  4. 顺便建好 MONEY2603 / CLASS_FUNDS2603（如果不存在）

本脚本可重复执行，不会报错，也不会重复插入。
"""
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
from werkzeug.security import generate_password_hash, check_password_hash

# 先把 .env 读进来，数据库密码和管理员密码都在里面
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# 数据库连接：密码必须来自 .env，代码里不留默认值
MYSQL_PWD = os.getenv("MYSQL_PASSWORD", "")
if not MYSQL_PWD:
    print("❌ .env 里没有配置 MYSQL_PASSWORD，请先补上")
    print(f"   配置文件路径：{Path(__file__).resolve().parent.parent / '.env'}")
    sys.exit(1)

CONN = dict(
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=MYSQL_PWD,
    database=os.getenv("MYSQL_DB", "class2603"),
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)

# 学生初始密码：可以在 .env 里改
STUDENT_PWD = os.getenv("STUDENT_INIT_PWD", "123456")

# 50 个学生：学号从 20260301 开始
STUDENT_NAMES = [
    "张伟", "王芳", "李娜", "刘洋", "陈静", "杨帆", "赵磊", "黄敏", "周杰", "吴倩",
    "徐鹏", "孙丽", "马超", "朱婷", "胡军", "郭强", "何雪", "高翔", "林峰", "罗琳",
    "郑浩", "梁爽", "谢婷", "宋佳", "唐宇", "许诺", "韩雪", "冯磊", "邓超", "曹颖",
    "彭博", "曾静", "肖楠", "田甜", "董浩", "袁敏", "潘婷", "于洋", "蒋雯", "蔡明",
    "余乐", "杜宇", "叶琳", "程浩", "苏晴", "魏然", "吕鑫", "丁蕊", "任杰", "沈悦",
]


def _admin_password(env_key):
    """管理员密码：优先读 .env，没配置就随机生成一个并打印提醒"""
    pwd = os.getenv(env_key, "").strip()
    if pwd:
        return pwd
    pwd = secrets.token_urlsafe(9)      # 约 12 位随机字符串
    print(f"   ⚠️  .env 没配 {env_key}，已随机生成：{pwd}")
    print(f"       请记下来，或写进 .env 后重新运行本脚本")
    return pwd


# 管理员：学号 1 / 2（不占用学生学号段）
ADMINS = [
    # (student_id, username, name, role, env_key)
    (1, "only_user", "唯一用户",  "only_user", "ADMIN_PWD_ONLY_USER"),
    (2, "superuser", "超级管理员", "admin",     "ADMIN_PWD_SUPERUSER"),
]

DDL = {
    "money": """
        CREATE TABLE IF NOT EXISTS MONEY2603 (
            id INT AUTO_INCREMENT PRIMARY KEY,
            content VARCHAR(255),
            money DECIMAL(10, 2),
            time DATE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    "funds": """
        CREATE TABLE IF NOT EXISTS CLASS_FUNDS2603 (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID，自增',
            student_id INT UNSIGNED NOT NULL COMMENT '学号，整数',
            name VARCHAR(50) NOT NULL COMMENT '姓名',
            picture MEDIUMBLOB COMMENT '图片二进制数据',
            six_day_reason VARCHAR(255) NOT NULL COMMENT '请假理由',
            `time` DATE NOT NULL COMMENT '请假时间',
            PRIMARY KEY (id),
            UNIQUE KEY uk_student_id (student_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='班级请假表2603';
    """,
    "students": """
        CREATE TABLE IF NOT EXISTS STUDENTS2603 (
            student_id INT UNSIGNED NOT NULL COMMENT '学号',
            username   VARCHAR(50)  NOT NULL COMMENT '登录名',
            name       VARCHAR(50)  NOT NULL COMMENT '姓名',
            password   VARCHAR(255) NOT NULL DEFAULT '' COMMENT '密码哈希',
            role       VARCHAR(20)  NOT NULL DEFAULT 'student' COMMENT '角色：student/admin/only_user',
            PRIMARY KEY (student_id),
            UNIQUE KEY uk_username (username)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='班级学生账号表2603';
    """,
}


def main():
    conn = pymysql.connect(**CONN)
    try:
        with conn.cursor() as cur:
            # ---------- 1. 建表 ----------
            print("① 检查/创建数据表")
            for name, ddl in DDL.items():
                cur.execute(ddl)
                print(f"   ✅ {name}")
            conn.commit()

            # ---------- 2. 先清空角色（保证只有 1 超管 + 1 唯一用户）----------
            cur.execute("UPDATE STUDENTS2603 SET role = 'student'")

            # ---------- 3. 50 个学生 ----------
            print("\n② 写入 50 个学生账号")
            added = 0
            for i, nm in enumerate(STUDENT_NAMES, start=1):
                sid = 20260300 + i                     # 20260301 ~ 20260350
                username = str(sid)
                h = generate_password_hash(STUDENT_PWD)
                cur.execute(
                    """INSERT INTO STUDENTS2603 (student_id, username, name, password, role)
                       VALUES (%s, %s, %s, %s, 'student')
                       ON DUPLICATE KEY UPDATE
                           username = VALUES(username),
                           name     = VALUES(name),
                           password = VALUES(password),
                           role     = 'student'""",
                    (sid, username, nm, h),
                )
                added += 1
            conn.commit()
            print(f"   ✅ {added} 个学生，登录名 = 学号，密码 {STUDENT_PWD}")

            # ---------- 4. 两个管理员 ----------
            print("\n③ 写入管理员账号")
            # 记下这次实际用的密码，最后校验时要用
            used_pwd = {}
            for sid, username, nm, role, env_key in ADMINS:
                plain = _admin_password(env_key)
                used_pwd[username] = plain
                h = generate_password_hash(plain)
                cur.execute(
                    """INSERT INTO STUDENTS2603 (student_id, username, name, password, role)
                       VALUES (%s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           username = VALUES(username),
                           name     = VALUES(name),
                           password = VALUES(password),
                           role     = VALUES(role)""",
                    (sid, username, nm, h, role),
                )
                # 密码不在日志里明文打印，只说长度
                print(f"   ✅ {username:<12} {nm:<8} 角色 {role:<10} "
                      f"密码已设置（{len(plain)} 位）")
            conn.commit()

            # ---------- 5. 汇总 ----------
            print("\n④ 最终结果")
            cur.execute("SELECT role, COUNT(*) AS n FROM STUDENTS2603 GROUP BY role ORDER BY n DESC")
            for r in cur.fetchall():
                print(f"   {r['role']:<12} {r['n']} 人")

            print("\n⑤ 账号校验")
            cur.execute(
                "SELECT username, name, role, password FROM STUDENTS2603 "
                "WHERE username IN ('only_user','superuser') ORDER BY role"
            )
            for r in cur.fetchall():
                plain = used_pwd.get(r["username"], "")
                ok = check_password_hash(r["password"], plain) if plain else False
                print(f"   {r['username']:<12} {r['name']:<8} {r['role']:<10} "
                      f"密码校验 {'✅ 通过' if ok else '❌ 失败'}")

            cur.execute(
                "SELECT username, name, password FROM STUDENTS2603 "
                "WHERE role='student' ORDER BY student_id LIMIT 3"
            )
            for r in cur.fetchall():
                ok = check_password_hash(r["password"], STUDENT_PWD)
                print(f"   {r['username']:<12} {r['name']:<8} student   密码校验 "
                      f"{'✅ 通过' if ok else '❌ 失败'}")

        print("\n🎉 数据库初始化完成")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
