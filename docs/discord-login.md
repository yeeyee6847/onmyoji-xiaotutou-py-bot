# Discord 与网站登录

已在当前 Supabase 执行 `migrations/003_discord_login.sql`，新增 4 张私有表：`login_tokens`、`password_credentials`、`web_sessions`、`login_rate_limits`，均启用 RLS，未向匿名客户端开放。玩家仍使用已有 `players` 和 `player_identities(provider='discord')`；Discord ID 是字符串，不用显示名称关联账号。其他项目先执行 `python manage.py init-auth`（要求已建立 `onmyoji_shards.players` 等基础表）。

## 使用方式

1. 玩家在 Discord 对 Bot 执行 `/login`，Bot 私密回复一次性按钮。
2. 链接只带随机凭证，不包含 Discord user ID。打开页面并按「确认并登入」时才消费，不会因为链接预览的 GET 请求就失效。
3. 未设置密码时登入后进入 `/account`，15 分钟内设置 12–128 字符的网站密码，保存后自动进入 `/shards`。已经设过密码的账号，无论密码登录还是 Discord 链接登录，都直接进入 `/shards`。
4. 之后在 `/login` 使用 Discord user ID 和密码登入；不能自行注册任意 Discord ID，也没有默认密码。
5. 忘记密码时重新使用 Discord `/login`。密码重设会撤销其他网站会话和未使用链接。

链接 10 分钟有效，原子消费，两个同时使用的请求也只能成功一个；同一个人重新 `/login` 会使之前未使用的链接失效。任何拿到链接的人都能以该身份登录，因此不应转发。数据库只保存链接和网站会话的 SHA-256 摘要；密码使用 Werkzeug scrypt 哈希。网站会话 7 天有效，登出在服务器撤销；密码登录不能取得改密权限。

链接凭证放 URL fragment，页面脚本立即清除，避免出现在 HTTP 请求地址和服务器访问日志中。真正消费由带 CSRF 的 POST 完成；只是刷新链接页面会丢失待用凭证，需要重新打开原链接。登录时轮换会话和 CSRF。登录、消费链接和改密均有限速。

网站功能（包括式神图鉴、抽奖及其接口）均需登录；匿名页面请求跳到 `/login`，功能接口返回 401。首次尚未设置密码的账号需先完成设置。登录页、登录接口及其静态资源保留可访问，`/healthz` 保持公开供 Render 检查。账号设置可从导航主动进入，不再作为已有密码账号的登录落地页。碎片任务按玩家 ID 隔离，上传时绑定自己的游戏账号；核对后点击保存才将确认清单写入 Supabase，详见 [游戏账号](game-accounts.md)。演示身份不能改变真实账号角色，正式图鉴依旧只读。

## 接到现有 discord.py Bot

在相同 Python 环境安装：

```powershell
python -m pip install -r requirements-bot.txt
```

现有 Bot 的 `setup_hook` 加入：

```python
await bot.load_extension("discord_login")
# 在现有 Bot 的正常指令同步流程中同步，不要另启第二个 Bot 来覆盖原有指令。
```

该扩展仅从 Discord 验证过的 `interaction.user.id` 创建链接，没有让网页匿名传入 user ID 来签发链接的接口。异步指令用线程执行数据库操作，不阻塞 Bot 的事件循环。不需要 Message Content Intent。

本仓库也提供独立启动文件：

```powershell
python discord_bot.py
```

这会连接 `.env` / 运行环境里的 `DISCORD_TOKEN`，使用 Discord 的单条命令接口新增或更新 `/login`，不批量覆盖其他命令。如果该 token 对应一个正在运行的 Bot，请将扩展加载到原程序，避免同一 Bot 同时运行两份程序。`DISCORD_GUILD_ID` 可用于指定测试服务器，否则注册全局指令。安装 Bot 时需要 `bot` 和 `applications.commands` 授权。

## 动态网站地址与部署

**同一个 Render Web Service 同时运行网站和 Bot：**

```text
Build Command: pip install -r requirements-ocr.txt && python prepare_ocr.py
Start Command: python run_all.py
Health Check Path: /healthz
```

环境变量设置 `DATABASE_URL`、`FLASK_SECRET_KEY`、`DISCORD_TOKEN`、`DISCORD_TRADE_MODE=dm` 及 `DISCORD_TRADE_CHANNEL_ID=1504352387635216545`。同服务默认使用 Render 自动提供的 `RENDER_EXTERNAL_URL`，不用手写域名。`run_all.py` 监督两个子进程，任一意外退出就终止另一进程并以失败状态退出，让平台重启；收到关闭信号时清理两个进程。不要再额外启动同 token 的另一份 Bot。

`render.yaml` 已改为统一启动；手动创建的服务需在 Dashboard 修改 Start Command。免费 Web Service 空闲休眠时两个进程都会停止，不能保证 Bot 全天在线。单独部署仍可使用下面的方式。

默认 `requirements.txt` 已包含 `discord.py`。单独部署 Bot 时，Build Command 使用 `pip install -r requirements.txt`（也兼容 `requirements-bot.txt`），Start Command 使用 `python discord_bot.py`，服务类型用 Background Worker；单独网站则使用 `python app.py`。同一 Web Service 同时运行二者时使用上面的 `python run_all.py`。修改依赖后需要重新构建部署，仅 Restart 不会安装新增依赖。

每次 `/login` 都读取当前运行环境，不在代码写死域名：

1. 若设置 `WEBSITE_URL`，优先使用它（适合 Bot 与网站分别部署）。
2. 否则使用 Render 自动提供的 `RENDER_EXTERNAL_URL`。
3. 本机使用当前 `HOST` / `PORT`，监听所有地址时生成 `127.0.0.1` 链接。

本机地址只能从同一台电脑打开。若 Bot 在另一台机器或单独的 Render Worker 上，它无法自动得知网站在哪个域名，需要将网站的地址填入那个 Bot 服务的 `WEBSITE_URL`，而不是使用 Worker 自己的地址。可从网站服务的 `RENDER_EXTERNAL_URL` 复制。网站和 Bot 必须连接同一个 Supabase `DATABASE_URL`。

Render Web Service 继续运行 `python app.py`，不要用 Bot 进程取代 Web 启动命令。Bot 需要持续运行的独立进程/Worker，或加载进已有 Bot。`FLASK_SECRET_KEY` 必须保持稳定。此次实现没有连接 Discord、发布指令或替换现有 Bot。

## 验证

```powershell
python -m unittest discover -s tests -p auth_postgres_checks.py
python tests/browser_auth.py
```

前者验证真实 PostgreSQL 的单次消费、并发、过期、重发、密码、撤销与 CSRF；大部分资料回滚，并发检查只暂存一个测试身份并在 finally 删除。浏览器检查创建可清理的测试身份，不连接 Discord。截图保存在忽略的 `artifacts/`。

参考：[discord.py interactions](https://discordpy.readthedocs.io/en/stable/interactions/api.html)、[Werkzeug 密码哈希](https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash)。
