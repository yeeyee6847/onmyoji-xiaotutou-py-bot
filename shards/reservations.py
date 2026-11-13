from lottery import DrawError


def reserved(conn,account,shikigami,target):
    return conn.execute('''SELECT coalesce(sum(quantity),0) FROM onmyoji_shards.trade_reservations
     WHERE game_account_id=%s AND shikigami_id=%s AND target=%s''',(account,shikigami,target)).fetchone()[0]


def guard_quantity(conn,account,shikigami,target,quantity):
    if quantity<reserved(conn,account,shikigami,target):
        raise DrawError('数量不能低于进行中交换的预留数量，请先取消交换以释放预留。',409)
