# QQ CS2 赛事播报机器人

使用 PandaScore 查询职业赛事赛程与赛果，通过本机 NapCat 小号响应 `#` 指令并发送赛后播报；也可推送 CS2 官方更新。完美平台战绩和 Steam 绑定由[独立官方机器人项目](https://github.com/Qing-Seiyuki/perfectworld-cs2-qq-bot)负责。

## 本机启动

需要 Python 3.15（其他版本尚未验证）和已运行的 NapCat。在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 填入 `PANDASCORE_TOKEN` 和 `NAPCAT_ACCESS_TOKEN`。两项令牌与数据库不要提交到 GitHub。启动：

```powershell
.\.venv\Scripts\python.exe -u -m qq_cs2_bot.esports_service
```

可选的 `#绑定链接` 需要与官方机器人运行在可访问同一 SQLite 数据库的电脑上：设置 `QQ_BINDINGS_DB` 为官方项目 `data/bot.sqlite3` 的**绝对路径**，并设置与官方项目相同的 `STEAM_VERIFY_PUBLIC_URL`。不设置时赛事查询和播报仍可使用，绑定链接指令不会返回链接。

命令和数据源设置见 `docs/`。测试命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`data/` 保存订阅与去重记录；`.env`、`data/`、`output/` 和虚拟环境已被 Git 忽略。发布仓库不会启动机器人，运行电脑仍需保持联网。
