import sys
from lottery import DrawError
from storage import PostgresStore

if __name__ == "__main__":
    if sys.argv[1:] != ["init-db"]:
        raise SystemExit("用法：python manage.py init-db")
    try:
        PostgresStore().initialize()
        print("抽奖专用 schema 和表已建立，现有表保持不变。")
    except DrawError as error:
        raise SystemExit(str(error)) from None
