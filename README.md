# 抽奖小屋

Python + Flask + Supabase PostgreSQL 的本地抽奖网站，界面使用繁体中文。后端通过 `.env` 中已有的 `DATABASE_URL` 连接 Supabase；浏览器不会收到数据库凭证，也不会读取 Discord token。

## 启动

第一次安装（Windows PowerShell）：

```powershell
python -m venv .venv
python -m pip --python .venv/Scripts/python.exe install -r requirements.txt
.venv/Scripts/python.exe manage.py init-db
```

日常启动：

```powershell
.venv/Scripts/python.exe app.py
```

也可以运行 `./start.ps1`。打开 **http://127.0.0.1:5000**。默认只监听本机，使用 Waitress；按 Ctrl+C 停止。

如果数据库未连接，页面仍可试玩；正式抽奖会提示错误，不会假装保存成功。当前版本是单个操作者在本机使用的工作台，尚未提供登录或远程管理员权限。对外部署和 Discord 接入留待后续版本。

## 玩法

1. 填写抽奖标题、主办人、奖品、抽奖时间以及参与者名单。每场 2–100 人，每人一个 1–100 的整数号码，名字和号码都不能重复。
2. 选择淘汰式或即中式；也可以批次贴上名单，每行 `名字, 号码`。
3. 「先试玩一下」只在服务器内存中操作，两小时后过期，重启服务器后消失，完全不访问数据库。
   试玩中随时可以按「重新试玩并洗牌」建立新局、重新随机分配号码。刷新页面只恢复本局，不会洗牌。随机允许重复排列：例如 3 人共有 6 种排列，两局完全相同的概率是 1/6；不会人为排除上一次排列。
4. 「建立正式抽奖」立即保存设置，时间到后按「开始抽奖」。卡片由 Python 的系统随机源打乱，未选择的号码位置不会提前送到浏览器。
5. 按住鼠标或手指移动，真实擦除 Canvas 涂层。卡片一旦选择就锁定，刮开约 47% 后确认结果；刮完之前不能改选。也有逐条擦除的键盘操作按钮。
6. 淘汰式刮中者淘汰，剩最后一人时自动获奖；即中式第一张刮完的卡片对应参与者获奖。每场只有一名获奖者。
7. 正式结果由 Python 后端判定，Supabase 事务保存；重复确认同一张卡不会重复结算。历史记录提供最近 100 场，可以恢复未完成的正式抽奖。

时间以带时区的 ISO 8601 写入数据库，界面按设备时区显示。正式抽奖不会早于设定时间开场，试玩没有此限制。刷新后可从当前链接或历史记录恢复正式进度；已选中但未刮完的卡片仍锁定，涂层需要重新刮。

## 数据库与代码

`schema.sql` 只建立独立的 `lottery_app` schema 和 `draws` 表，不迁移现有 bot 表。该 schema 不需要加入 Supabase 的 exposed schemas；开启 RLS 且不添加客户端策略。数据仅通过 Python 后端使用数据库连接串访问。

每场的 JSONB `state` 包含标题、主办人、奖品、名单、设定时间、模式、卡片顺序、已选卡片、淘汰记录、得奖者、创建/开始/结束时间。选择及结算使用 `SELECT ... FOR UPDATE` 防止同时操作覆盖结果。

- `lottery.py`：独立抽奖逻辑；后续 Discord bot 可复用这些函数。
- `storage.py`：PostgreSQL 持久化与独立的内存试玩存储。
- `app.py`：Flask 页面、API、同源 CSRF 校验与本机服务。
- `templates/`、`static/`：原生 HTML/CSS/JavaScript，无 Node.js 构建依赖。

`.env`、本机 session 密钥和测试产物都已加入 `.gitignore`。`instance/.secret_key` 会自动生成，使本机浏览器会话在服务器重启后仍有效；也可通过 `FLASK_SECRET_KEY` 指定密钥。

## 验证

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_lottery.py -v
# 真实 Supabase 读写验证：测试事务最终回滚，不留下测试抽奖
.venv/Scripts/python.exe -m unittest discover -s tests -p test_postgres.py -v
```

可选浏览器验证依赖见 `requirements-dev.txt`；`tests/browser_smoke.py` 使用本机已安装的 Microsoft Edge 验证实际刮卡、刷新恢复和移动版布局。

实现依据：[Flask 文档](https://flask.palletsprojects.com/en/stable/)、[Supabase PostgreSQL 连接文档](https://supabase.com/docs/guides/database/connecting-to-postgres)、[Psycopg 事务文档](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)。
