import pymysql
import os
from pathlib import Path
from dotenv import load_dotenv

# 先把 .env 里的配置读进来
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 数据库的五个配置项，都从 .env 里取
host = os.getenv("MYSQL_HOST")
port = int(os.getenv("MYSQL_PORT", "3306"))
user = os.getenv("MYSQL_USER")
pwd = os.getenv("MYSQL_PASSWORD")
db = os.getenv("MYSQL_DB")


class ClassSQL:
    def __init__(self):
        # 启动时先检查一遍配置，缺了什么直接说清楚
        missing = [k for k in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER",
                           "MYSQL_PASSWORD", "MYSQL_DB")
                   if not os.getenv(k) ]
        if missing:
            raise RuntimeError(
                f".env 缺少数据库配置：{', '.join(missing)}\n"
                f"请检查 {Path(__file__).resolve().parent.parent / '.env'}"
            )

        # 连上数据库
        self.conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=pwd,
            database=db,
            charset='utf8mb4',
            # 让查询结果变成字典，可以用 r["name"] 这样取值
            cursorclass=pymysql.cursors.DictCursor,
        )

        # 记下库名，建库的时候要用
        self.db_name = os.getenv("MYSQL_DB")

        # 班费表：内容、金额、收支类型、日期
        self.money_sql = """CREATE TABLE IF NOT EXISTS MONEY2603 (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    content VARCHAR(255),
                    money DECIMAL(10, 2),
                    kind VARCHAR(10) NOT NULL DEFAULT 'out' COMMENT '收支方向：in=收入 / out=支出',
                    time DATE
                );"""

        # 请假表：谁请的、理由、时间、证明图片
        self.class_funds_sql = """
        CREATE TABLE IF NOT EXISTS CLASS_FUNDS2603 (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID，自增',
            student_id INT UNSIGNED NOT NULL COMMENT '学号，整数',
            name VARCHAR(50) NOT NULL COMMENT '姓名',
            picture MEDIUMBLOB COMMENT '图片二进制数据',
            six_day_reason VARCHAR(255) NOT NULL COMMENT '请假理由',
            `time` DATE NOT NULL COMMENT '请假时间',
            PRIMARY KEY (id),
            KEY idx_student_id (student_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='班级请假表2603';
        """


    # 建数据库，平时用不到，库已经在 .env 里配好了
    def create_database(self):
        try:
            with self.conn.cursor() as cursor:
                # 先看看库在不在
                cursor.execute("SHOW DATABASES LIKE %s",(self.db_name,))
                if cursor.fetchone():
                    print(f"数据库{self.db_name}已存在")
                    return
                # 不在才建
                cursor.execute(f"CREATE DATABASE `{self.db_name}` "
                               f"DEFAULT CHARACTER SET utf8mb4 "
                               f"COLLATE utf8mb4_unicode_ci")

        except pymysql.MySQLError as e:
            print(f"创建失败{self.db_name}:{e}")

    # 建表，表已经在了就会跳过
    def create_table(self,sql):
            cursor = self.conn.cursor()
            cursor.execute(sql)

    # 往班费表里加一条
    def take_money_sql(self,content,money,time, kind="out"):
            cursor = self.conn.cursor()
            # 用 %s 占位再把值传进去，别自己拼字符串，这样能防注入
            sql = """INSERT INTO MONEY2603 (content, money, kind, time)
                        VALUES (%s, %s, %s, %s);"""
            cursor.execute(sql,(content,money,kind,time))
            # 记得提交，不提交等于没存
            self.conn.commit()

    # 查全部班费记录
    def get_table(self):
        cursor = self.conn.cursor()
        sql = """SELECT * FROM MONEY2603 """
        try:
            cursor.execute(sql)
            results = cursor.fetchall()
            return results

        except pymysql.MySQLError as e:
            print(e)

    # 往请假表里加一条
    def take_class_funds_sql(self,student_id,name,picture,six_day_reason,leave_time):
        cursor = self.conn.cursor()
        sql = """INSERT INTO CLASS_FUNDS2603 (student_id, name, picture, six_day_reason, `time`)
                 VALUES (%s, %s, %s, %s, %s);"""
        cursor.execute(sql, (student_id, name, picture, six_day_reason, leave_time))
        self.conn.commit()


    # 查全部请假记录
    def get_class_funds_sql(self):
        cursor = self.conn.cursor()
        sql = """SELECT * FROM CLASS_FUNDS2603 """
        try:
            cursor.execute(sql)
            results = cursor.fetchall()
            return results

        except pymysql.MySQLError as e:
            print(e)
            # 查失败返回空列表，上层就不用再判断 None
            return []

    # 用完把连接关掉，不然连接会越攒越多
    def close(self):
        if self.conn and self.conn.open:
            self.conn.close()
