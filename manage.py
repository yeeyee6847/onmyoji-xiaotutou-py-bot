import sys
from pathlib import Path
from lottery import DrawError
from storage import PostgresStore

if __name__ == "__main__":
    if sys.argv[1:] not in (["init-db"], ["init-auth"], ["init-fragments"], ["init-trades"]):
        raise SystemExit("用法：python manage.py init-db / init-auth / init-fragments / init-trades")
    try:
        if sys.argv[1:] == ['init-trades']:
            with PostgresStore().connection() as connection:
                connection.execute((Path(__file__).parent / 'migrations/005_trades.sql').read_text(encoding='utf-8'))
            print('交换表与通知队列已建立。')
        elif sys.argv[1:] == ['init-fragments']:
            with PostgresStore().connection() as connection:
                connection.execute((Path(__file__).parent / 'migrations/004_fragment_management.sql').read_text(encoding='utf-8'))
            print('碎片管理与头像参考库已建立。')
        elif sys.argv[1:] == ['init-auth']:
            with PostgresStore().connection() as connection:
                connection.execute((Path(__file__).parent / 'migrations/003_discord_login.sql').read_text(encoding='utf-8'))
            print('Discord 登录表已建立。')
        else:
            PostgresStore().initialize()
            print("抽奖专用 schema 和表已建立，现有表保持不变。")
    except DrawError as error:
        raise SystemExit(str(error)) from None
