# 抽奖小屋 / 结缘帖原型

Python + Flask + Supabase PostgreSQL 抽奖网站，支持本机运行和 Render 部署，界面使用繁体中文。后端通过环境变量 `DATABASE_URL` 连接 Supabase，本机可使用 `.env`；浏览器不会收到数据库凭证，也不会读取 Discord token。

## Discord 网站登录

同一个 Render Web Service 同时运行网站和 Bot：Build Command 使用 `pip install -r requirements-ocr.txt && python prepare_ocr.py`，Start Command 使用 `python run_all.py`，健康检查 `/healthz`。设置数据库、Flask 密钥和 Discord token；域名由 Render 自动提供。两个子进程由启动程序统一管理。免费服务休眠时 Bot 也会离线，详见 [部署说明](docs/discord-login.md)。

支持 Bot `/login` 一次性链接和 Discord user ID + 密码登录。每次 Discord `/login` 同步当前显示名；登录后直接进入 `/shards`，设置密码可跳过，未设置时显示提醒。密码 8–128 字符，可日后在 `/account` 首次设置。Render 自动使用当前部署地址；Bot 与 Web 分开部署时可用 `WEBSITE_URL` 指定网站地址。全站功能及接口仍需登录，详见 [Discord 登录](docs/discord-login.md)。

## 碎片交换原型

交换申请与进行中列表位于 `/trades`，支持对方接受／拒绝、接受后预留、双方网页确认完成及完成前取消释放。搜索页可直接选择对方账号；图鉴可用量排除预留，原始库存直到双方完成才扣除。Bot 新增 `discord_trades` 扩展和 `/fragments rarity name` 搜索指令。通知方式需要配置 `DISCORD_TRADE_MODE`（`private_thread` 或 `dm`），频道由 `DISCORD_TRADE_CHANNEL_ID` 指定。

新增[碎片工作台与头像参考库](docs/fragment-workspace.md)：`/my-fragments` 人工汇入与整理、`/search-fragments` 全站搜索、图鉴当前总量及持有人明细、Admin 图鉴新增编辑和 `/admin/samples` 裁切审核。选择器支持搜索和 Rarity 筛选，图片与人工数量统一覆盖保存。已执行 `004_fragment_management.sql`；其他部署需运行 `python manage.py init-fragments`。

支持多个游戏账号：在 `/game-accounts` 或上传页新增账号，上传前选择归属账号，逐项核对后点击「保存到游戏账号」。账号与确认清单存入 Supabase；账号页显示各式神最近确认的数量，不累加。临时 OCR 任务及原图仍会随重启失效，演示资料不可保存。管理员角色由 `players.role` 在数据库管理，网页不提供提升权限的入口。详见 [游戏账号与碎片归属](docs/game-accounts.md)。

长图中下方「我想要的碎片」也会进入核对，使用标题和区域位置区分提供／想要；类别可人工更正，无法确定时标为待分类。两种清单分开保存、查看和导出，同一式神的提供数量与想要数量不会互相覆盖。

正式数据库的独立建表文件：[schema_shards.sql](schema_shards.sql)，关系与规则见 [碎片数据结构说明](docs/shards-database.md)。已建立基础表、认证迁移及碎片管理迁移。打开 `/shards#catalog` 查看图鉴，Admin 可在网页管理名字、分类、HTTPS 图片网址、排序和别名。真实上传经逐项确认后可保存到游戏账号，演示资料只可导出。

启动服务后打开 **http://127.0.0.1:5000/shards**，或从抽奖页面点击「碎片交换」。后台读取 Supabase，启动时不自动运行迁移，也不改动抽奖记录。

- 一般用户：上传游戏原始碎片长图、查看逐格裁切和 OCR 原文、选择正确式神、修正数量、逐项确认或排除，最后导出 JSON。
- Admin：由 `players.role` 控制，可新增、编辑、停用式神，审核头像参考；测试 Mock 的演示身份不会更改真实权限。
- 默认图鉴读取 Supabase 的启用式神和别名；未保存的识别任务和原图在服务器进程中暂存，重启会丢失。已确认保存的清单保存在 Supabase，按玩家和游戏账号隔离。
- 真实图鉴隐藏演示身份，编辑按钮仅向 Admin 显示且接口检查角色；测试临时目录仍使用独立 Mock。

图片处理基础依赖已加入 `requirements.txt`。要启用本地中文 OCR，安装：

```powershell
python -m pip --python .venv/Scripts/python.exe install -r requirements-ocr.txt
```

处理流程为 OpenCV 定位红色/金色卡框 → 分别裁切名字和数量 → 放大后调用 RapidOCR（ONNX Runtime CPU、PP-OCRv4 mobile 识别模型）→ 用图鉴繁体名、简体名、别名配对。OpenCC 统一繁简混合文字，每次导入预建名字索引；未精确匹配的名字重试三种裁切，模糊匹配仅作为候选。数量采用五种裁切，至少两次高分读数一致才填入，否则留空人工核对；OCR 分数不等于准确概率。本机第一次识别会从 RapidAI 的模型源下载识别模型，Render 则在构建时准备模型；输入图片始终在当前 Python 服务器处理，不会上传给外部 OCR 服务。

每条结果保留原图裁切、OCR 原文及分数。不精确匹配时只提供候选，不自动认定名字；不确定的数量留空，不把 `I3` 或 `1?` 擅自改成数字。所有记录最初都需要人工确认。自动定位不准时，可在上传页展开「调整切格」设置行列和百分比范围。

「载入演示结果」只生成固定演示资料，页面会明确标记，不能当作真实 OCR 结果。没有 OCR 依赖或模型下载失败时仍提供切格和人工核对，页面会提示原因。导出要求所有保留条目都已确认；同一式神重复出现会阻止导出，不会擅自累计数量。

已使用本机 Downloads 中与附件一致的 `herodebris_long_share.jpg`（639×3110）做单图开发实测，并逐格人工转录对照。定位 121 张，改进前名字正确 51 张、数量正确 81 张（另有 10 个误读数量）；改进后名字正确 92 张、数量正确 79 张（1 个误读、41 个留空），两项同时正确 60 张。本机约 11 秒；尚未测试 Render 的性能。这张图参与了裁切调试，因此结果不是独立测试集准确率，也不能推广到其他截图。图中两面佛、不相狐禅、洛天依、言和未收录，不能自动绑定。所有行仍需人工确认，未写入玩家库存或识别别名。

可复测：`python benchmark_shards.py "原图路径"`。脚本只读 Supabase 图鉴，核验原图 SHA-256，输出 `artifacts/shards-ocr/report.html`、CSV 与 JSON；对照标注位于 `tests/shards_screenshot_reference.json`。`collaboration_name` 保留联动作品含义，OCR 别名应使用 `shikigami_aliases`，不能自动把未核实错字写入。

本机真实 OCR 合成探测读对了清晰的「不知火」「花鸟卷」和 `1307`，但单独的 `0` 曾读为字母 `o`（低分），会留待人工确认；这不是游戏截图的准确率评测。可运行 `python tests/ocr_probe.py` 复测，本机探测脚本使用 Windows 的微软雅黑字体。

`shards/vision.py` 和 `shards/catalog.py` 不依赖 Flask 或 Discord：之后 Discord bot 读取附件 bytes 后，可以在线程里调用 `load_image(bytes)` 和 `inspect_image(image, catalog)` 复用同一识别流程。当前没有启用真实交换撮合或库存入库。

Render Blueprint 已启用 OCR，构建命令为 `pip install -r requirements-ocr.txt && python prepare_ocr.py`，启动命令保持 `python app.py`。`prepare_ocr.py` 会在构建时下载并加载 CPU 识别模型，使用生成的数字小图验证模型可用；不读取数据库或用户图片。模型文件保留在构建产物内的 `instance/shards/models/`，不上传 Git。

如果之前通过 Render 的 Web Service 手动创建服务，请在 Dashboard 的 Settings 中更新 Build Command；修改 `render.yaml` 不会自动覆盖手动服务设置。更新代码并重新部署后，识别仍在 Render 的服务器上执行，你的电脑不需要保持开机。目前已通过本机模型和流程验证，但尚未在 Render 上做实际内存、速度和长图压测；免费实例能否稳定处理你的长图仍需部署后验证。

真实图鉴保存在 Supabase；上传结果及测试 Mock 图鉴仍为临时资料。Render 服务重启或重新部署后，运行时新增的本机文件及内存结果可能丢失。

参考：[RapidOCR 官方使用文档](https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/usage/)。

碎片模块测试：`.venv/Scripts/python.exe -m unittest discover -s tests -p test_shards.py -v`。测试将数据库对象替换为禁止访问的实现；OpenCV 分格使用合成的五列卡框，Web 上传流程使用明确标记的测试识别器。完整浏览器测试先启动 `tests/shards_server.py`，再运行 `tests/browser_shards.py`，测试图鉴写入独立临时目录并在结束后清理。

## 本机启动

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

数据库连接用于登录、游戏账号及正式记录；连接失败会提示错误，不会假装保存成功。网站页面和功能接口均需要登录，支持 Discord /login 一次性链接及网站密码。

## Render 部署

仓库内提供 `render.yaml`。在 Render 选择 **New → Blueprint**，连接此 GitHub 仓库，按提示填写 `DATABASE_URL` 即可使用现有 Supabase 数据库。Blueprint 会生成 `FLASK_SECRET_KEY`，实际值在服务的 **Environment** 中查看。

如果选择 **New → Web Service** 手动创建，使用以下设置：

| 项目 | 值 |
| --- | --- |
| Language | Python 3 |
| Branch | main |
| Build Command | `pip install -r requirements-ocr.txt && python prepare_ocr.py` |
| Start Command | `python app.py` |
| Health Check Path | `/healthz` |
| Instances | 1 |

手动部署需要在 **Environment** 设置：

- `DATABASE_URL`：从本机 `.env` 复制对应值。不要上传整个 `.env` 或 Discord token。
- `FLASK_SECRET_KEY`：固定的随机长密钥，用来保持会话。不要在每次部署时更换。

Render 会提供 `PORT`，程序自动监听 `0.0.0.0:$PORT`，不需要填写 `HOST` 或 `PORT`。`.python-version` 选择 Python 3.14 系列。页面和抽奖功能直接开放，无需账号密码。`FLASK_SECRET_KEY` 用于浏览器会话及 CSRF 校验，不是登录密码。`/healthz` 用于 Render 的健康检查，不含业务数据。

如果旧部署曾设置 `ADMIN_PASSWORD`，可以从 Render 的 Environment 删除；新版程序不再读取此设置，保留旧变量也不会弹出登录框。

Render 上完全从 **Environment** 读取配置，不加载本机 `.env`，也不需要本机的 `instance/` 密钥文件。`start.ps1` 仅供 Windows 本机使用；在 Render 使用上表的 `python app.py`，不要使用 PowerShell 启动文件或 Flask 的开发服务器。Render 会固定使用 `0.0.0.0`，忽略本机的 `HOST=127.0.0.1` 设置。

如果 GitHub 分支仍只有最初的 `first commit`，请先把最新部署修改推送到 Render 所绑定的分支，再在 Render 选择 **Manual Deploy → Deploy latest commit**。仅修改本机文件不会更新远端部署。

数据库表已在当前 Supabase 建立。如果之后换成新数据库，需在 Supabase SQL Editor 执行 `schema.sql`，或设置连接串后执行 `python manage.py init-db`。如果 Render 无法连接 `db.…supabase.co` 的直连地址，改用 Supabase **Connect → Session pooler** 的连接串；密码中的特殊字符需 URL 编码。

正式抽奖持久保存在 Supabase；试玩保存在单个 Python 进程内存中，因此当前配置使用单实例 Waitress。Render 重启、休眠或重新部署后，试玩会消失；正式抽奖可从历史记录继续。不要把启动命令改成多个 worker，也不要扩到多个实例，否则试玩请求可能落到不同内存存储。

部署配置依据：[Render Flask 部署](https://render.com/docs/deploy-flask)、[端口要求](https://render.com/docs/web-services#port-binding)、[Blueprint 配置](https://render.com/docs/blueprint-spec)、[Python 版本](https://render.com/docs/python-version)。

## 玩法

1. 填写抽奖标题、主办人、奖品、抽奖时间以及参与者名单。每场 2–100 人，每人一个 1–100 的整数号码，名字和号码都不能重复。
2. 选择淘汰式或即中式；也可以批次贴上名单，每行 `名字, 号码`。
3. 「先试玩一下」只在服务器内存中操作，两小时后过期，重启服务器后消失，完全不访问数据库。
   试玩中随时可以按「重新试玩并洗牌」建立新局、重新随机分配号码。刷新页面只恢复本局，不会洗牌。随机允许重复排列：例如 3 人共有 6 种排列，两局完全相同的概率是 1/6；不会人为排除上一次排列。
4. 「建立正式抽奖」立即保存设置，时间到后按「开始抽奖」。卡片由 Python 的系统随机源打乱，未选择的号码位置不会提前送到浏览器。
5. 按住鼠标或手指移动，真实擦除 Canvas 涂层。卡片一旦选择就锁定，刮开约 47% 后确认结果；刮完之前不能改选。也有逐条擦除的键盘操作按钮。
6. 淘汰式刮中者淘汰，剩最后一人时自动获奖；即中式第一张刮完的卡片对应参与者获奖。每场只有一名获奖者。
7. 正式结果由 Python 后端判定，Supabase 事务保存；重复确认同一张卡不会重复结算。历史记录提供最近 100 场，可以恢复未完成的正式抽奖。

## 修改已有抽奖

在刮奖现场点击「返回抽奖设置」，或在抽奖记录点击「编辑设置」，表单会载入原抽奖，按钮变成「储存修改」。保存会更新原本同一笔记录，保留编号、创建时间，不会新增一场。若想另外建一场，明确点击「另建新抽奖」后再提交。

开始前可以修改标题、主办人、奖品、时间、模式和名单；修改名单会重新随机分配卡片，仅修改标题等资料会保留卡片位置。开始后（包括已结束）可以修正标题、主办人和奖品，但名单、模式、时间及已揭晓结果保持锁定。限制同时由后端检查，避免其他页面已经开始抽奖后，旧设置页覆盖结果。

编辑正式抽奖时仍可先试玩；试玩只建立内存中的预览，返回设置后仍可保存原正式抽奖。修改不需要执行新的数据库建表脚本。

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
