# -*- coding: utf-8 -*-
r"""
服务器数据库迁移脚本（升级到最新版时用一次）

用法（服务器上）：
    cd ~/chuan_zhi_web
    source venv/bin/activate
    python scripts/migrate_server.py

做了什么：
  1. MONEY2603 加 kind 字段（收入/支出），并按内容回填已有数据
  2. CLASS_FUNDS2603 把「一人一条」的唯一索引改成普通索引
  3. STUDENTS2603 补 username 唯一索引（如果没有）

本脚本可以重复执行，每一步都先检查再改，不会报错。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

# 读 .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

DB = os.getenv("MYSQL_DB", "class2603")
PWD = os.getenv("MYSQL_PASSWORD", "")

if not PWD:
    print("❌ .env 里没有配置 MYSQL_PASSWORD，请先补上")
    sys.exit(1)

CONN = dict(
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=PWD,
    database=DB,
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)


def has_column(cur, table, column):
    cur.execute(
        """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s""",
        (DB, table, column),
    )
    return cur.fetchone()["n"] > 0


def has_index(cur, table, index_name):
    cur.execute(
        """SELECT COUNT(*) AS n FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s""",
        (DB, table, index_name),
    )
    return cur.fetchone()["n"] > 0


def index_unique(cur, table, index_name):
    """返回索引是不是唯一索引；索引不存在返回 None"""
    cur.execute(
        """SELECT NON_UNIQUE FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s LIMIT 1""",
        (DB, table, index_name),
    )
    row = cur.fetchone()
    if not row:
        return None
    return row["NON_UNIQUE"] == 0     # True = 唯一


def main():
    conn = pymysql.connect(**CONN)
    try:
        with conn.cursor() as cur:

            # ---------- 1. MONEY2603 加 kind ----------
            print("① 班费表：补 kind 字段（收入/支出）")
            if has_column(cur, "MONEY2603", "kind"):
                print("   ⏭  kind 已存在，跳过")
            else:
                cur.execute(
                    """ALTER TABLE MONEY2603
                       ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'out'
                       COMMENT '收支方向：in=收入 / out=支出' AFTER money"""
                )
                print("   ✅ 已添加 kind 字段")

                # 按内容关键词回填已有数据
                cur.execute(
                    """UPDATE MONEY2603 SET kind='in'
                       WHERE content LIKE '%收入%' OR content LIKE '%收%'
                          OR content LIKE '%充%'   OR content LIKE '%补贴%'
                          OR content LIKE '%缴%'"""
                )
                n_in = cur.rowcount
                cur.execute(
                    """UPDATE MONEY2603 SET kind='out'
                       WHERE content LIKE '%支出%' OR content LIKE '%花%'
                          OR content LIKE '%买%'   OR content LIKE '%付%'
                          OR content LIKE '%退%'"""
                )
                n_out = cur.rowcount
                print(f"   ✅ 已回填：{n_in} 条收入 / {n_out} 条支出"
                      f"（其余保持默认 out，可手动改）")
            conn.commit()

            # ---------- 2. CLASS_FUNDS2603 索引 ----------
            print("\n② 请假表：把「一人一条」的唯一索引改成普通索引")
            uniq = index_unique(cur, "CLASS_FUNDS2603", "uk_student_id")
            has_plain = has_index(cur, "CLASS_FUNDS2603", "idx_student_id")
            if uniq is None:
                if has_plain:
                    print("   ⏭  uk_student_id 不存在，idx_student_id 已在，跳过")
                else:
                    cur.execute("ALTER TABLE CLASS_FUNDS2603 ADD INDEX idx_student_id (student_id)")
                    print("   ✅ 已添加普通索引 idx_student_id")
            elif uniq is False:
                print("   ⏭  已经是普通索引，跳过")
            else:
                if has_plain:
                    cur.execute("ALTER TABLE CLASS_FUNDS2603 DROP INDEX uk_student_id")
                    print("   ✅ 已删除唯一索引 uk_student_id")
                else:
                    cur.execute(
                        """ALTER TABLE CLASS_FUNDS2603
                           DROP INDEX uk_student_id,
                           ADD INDEX idx_student_id (student_id)"""
                    )
                    print("   ✅ 唯一索引已改成普通索引，现在允许同一人多次请假")
            conn.commit()

            # ---------- 3. STUDENTS2603 唯一索引 ----------
            print("\n③ 账号表：确认 username 唯一索引")
            if has_index(cur, "STUDENTS2603", "uk_username"):
                print("   ⏭  uk_username 已存在，跳过")
            else:
                # 先检查有没有重复登录名，有的话不能直接加唯一索引
                cur.execute(
                    """SELECT username, COUNT(*) AS n FROM STUDENTS2603
                       GROUP BY username HAVING n > 1"""
                )
                dups = cur.fetchall()
                if dups:
                    print("   ❌ 存在重复登录名，先手动清理再重跑：")
                    for d in dups:
                        print(f"      {d['username']} 出现 {d['n']} 次")
                else:
                    cur.execute("ALTER TABLE STUDENTS2603 ADD UNIQUE KEY uk_username (username)")
                    print("   ✅ 已添加唯一索引 uk_username")
            conn.commit()

            # ---------- 4. 结果汇总 ----------
            print("\n④ 迁移后结构确认")
            for t in ("MONEY2603", "CLASS_FUNDS2603", "STUDENTS2603"):
                cur.execute(f"SHOW COLUMNS FROM {t}")
                cols = [r["Field"] for r in cur.fetchall()]
                print(f"   {t:<18} {', '.join(cols)}")

            print("\n⑤ 索引确认")
            cur.execute(
                """SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, COLUMN_NAME
                   FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN
                         ('MONEY2603','CLASS_FUNDS2603','STUDENTS2603')
                   ORDER BY TABLE_NAME, INDEX_NAME""",
                (DB,),
            )
            for r in cur.fetchall():
                kind = "唯一" if r["NON_UNIQUE"] == 0 else "普通"
                print(f"   {r['TABLE_NAME']:<18} {r['INDEX_NAME']:<16} "
                      f"{kind:<4} ({r['COLUMN_NAME']})")

        print("\n🎉 数据库迁移完成")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
