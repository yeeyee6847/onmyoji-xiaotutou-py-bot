# 游戏账号与碎片归属

每个 Discord 登录身份对应一个 `players` 记录，可创建多条 `game_accounts`。在 `/game-accounts` 或上传页「新增游戏账号」填写账号名字，服务器选填。账号保存到 Supabase；不同玩家可以使用相同名字，同一玩家的同名同服务器账号不重复创建。

`players.role` 默认 `user`，管理员可在 Supabase 手动改成 `admin`。每次请求从数据库读取，不提供自行修改角色的接口；账号页显示当前身份。Admin 可管理图鉴和头像参考，但写用户碎片时仍只能选择自己的游戏账号。

上传真实图片必须提交属于当前玩家且启用的 `game_account_id`。服务端校验归属，账号被固定到该次识别任务；修改上传页的选择不会改变已有任务归属。演示流程不绑定账号，不能保存。

逐项人工确认后点击「保存到游戏账号」，后端在单个事务中再次检查归属、账号启用状态、图鉴、数量、重复条目与确认状态。通过后写入现有 `fragment_imports(status='confirmed')` 和 `fragment_import_rows`；保存重试不会重复插入，已保存任务不能直接编辑。原图与临时 OCR 任务仍保存在进程内存，重启会失效；账号及已保存的文字/数量、原始 OCR 文字、坐标和确认记录保存在 Supabase，不保存原图文件。

长图支持「可提供的碎片」及「我想要的碎片」两个区域。先按卡片行之间的大间隔寻找区域，再读取区域标题；第二个区域标题读不出时标为待确认分类。每条核对记录有 `target=offers/wants/unknown`，用户可修正，未分类条目不能确认保存。核对页可分别筛选两种清单，同一式神在提供与想要中可各出现一次；同一清单中仍不允许重复。

保存时按类别写入两个独立的导入批次（`fragment_imports.target`），在一个事务完成；需求批次使用原任务 UUID 派生的稳定 UUID，重试不产生重复批次。查看游戏账号时按 `(类别,式神)` 各自读取最新确认数量，提供与想要不会互相覆盖；JSON 导出也保留每条记录的类别。本次沿用已有表，不需要新建 schema 或修改列。

账号页按式神显示当前数量。新图只覆盖出现且确认的式神，不出现的旧记录保留；重复上传不会累加。已接入 `fragment_current` 统一承载人工与图片汇入的当前提供／需求数量，旧的 `fragment_offers` / `fragment_wants` 表暂不使用。人工整理、全站搜索和图鉴统计见 [碎片工作台](fragment-workspace.md)。

没有新增表或修改玩家角色，不需要执行新 schema。

接口：

- `GET /api/game-accounts`：仅列出自己的启用游戏账号。
- `POST /api/game-accounts`：创建自己的账号，字段 `nickname`、可选 `server_name`。
- `GET /api/game-accounts/<id>/fragments`：仅查看自己账号的已确认碎片。
- `POST /api/shards/uploads`：表单字段 `image`、`game_account_id`。
- `POST /api/shards/jobs/<id>/save`：保存已核对的真实上传清单。

显式集成测试：`python -m unittest discover -s tests -p game_accounts_postgres_checks.py`，测试数据回滚。浏览器测试 `python tests/browser_game_accounts.py` 用可清理测试账号及标记的假 OCR，验证多账号与真实数据库保存，不代表 OCR 准确率测试。
