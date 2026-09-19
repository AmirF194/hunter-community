# 02 · 演示站端到端测试报告(fin-r1)

> 演示站:https://hunter-community.agentpit.io · 主机 fin-r1(35.198.212.241 · Google Cloud 新加坡)
> 测试时间:2026-09-17 01:30–01:50(上海时间)
> 测试对象:`hunter-opencode:slim-test`(agentpit 本地构建后 `docker save | ssh docker load` 送过来)+ 本仓多阶段 `apps/api/Dockerfile`
> **数据卷 `hunter_opencode_data` 全程未动**,`docker compose down -v` 一次都没执行,旧镜像 `ghcr.io/agentpit-io/hunter-opencode:dev` 保留在机器上直到验证通过。

## 0 · 部署过程

| 步骤 | 实测 |
|---|---|
| fin-r1 工作区起始状态 | `git rev-parse HEAD` = `9a6765802f6db692dd74b647fcf56ae381e5d183`,`git status --porcelain` 空(干净) |
| 磁盘 | 开始 12 GB 可用 → `docker builder prune -f` 回收 9.34 GB + 悬空镜像 18.6 MB → 20 GB 可用 |
| 送镜像 | `docker save \| gzip -1 \| ssh 'gunzip \| docker load'` · **23 秒**(首次)/ **20 秒**(修正后重送) |
| 同步改动文件 | rsync 9 个文件/目录,37 KB |
| `.env` | 备份为 `.env.bak-slim`,`OPENCODE_TAG` 临时改为 `slim-test`,并 `docker tag` 出 `ghcr.io/agentpit-io/hunter-opencode:slim-test` |
| `docker compose build api` | **成功** · 编译阶段 38 秒 + 运行层,全程约 3 分钟 |
| `docker compose up -d opencode api` | 只重建这两个,其余 4 个容器未动 |

## 1 · 中途发现并修掉的一个真问题 · 会话「消失」

第一次起来之后 `GET /session` 返回 **0 条**(基线是 30 条)。**不是卷丢了** —— 卷里的 `opencode-local.db` 6.7 MB 原封不动。

原因在 `packages/core/src/database/database.ts` 的 `path()`:会话库的文件名跟 `InstallationChannel` 走。

- 旧镜像 `bun run packages/opencode/src/index.ts` 跑源码 → channel = `local` → 库叫 **`opencode-local.db`**
- 编译成单文件时把 channel 烘成了 `latest`(因为构建时给了 `OPENCODE_VERSION`)→ 它去开了一个全新的空 **`opencode.db`**

症状和 2026-09-07「卷没挂导致会话全丢」一模一样,原因却完全不同 —— 卷、权限、路径全对,只是文件名差一个后缀。**如果没有把「升级前后会话数量」当成一条硬用例,这个问题会带着上线,而用户看到的是「暂无对话」。**

修法:镜像里钉死 `ENV OPENCODE_DB=opencode-local.db`(`Flag.OPENCODE_DB` 认这个环境变量,相对文件名会落在 `Global.Path.data` 下)。这样新旧镜像读同一个库,升级和回滚都不丢会话。

那个误建出来的空 `opencode.db` 没有删,改名成 `opencode.db.stray-20260917` 留在卷里(万一那十分钟里有人聊过)。

## 2 · 十二个用例

| # | 用例 | 命令 / 做法 | 结果 |
|---|---|---|---|
| 1 | 6 个容器状态 | `docker compose ps` | ✅ postgres / redis / llm-shim / api / web / opencode **全部 healthy**。opencode `restart → healthy` **16 秒**(旧镜像基线 17 秒);`up -d --force-recreate → healthy` **18 秒** |
| 2 | 容器内版本 | `docker exec … opencode --version` / `python3 -c "import mcp,httpx"` | ✅ opencode **1.18.12** · python **3.11.16** · mcp **1.30.0**(1.x)· httpx **0.28.1**。`/opt/opencode-workspace/.git` 不存在 |
| 3 | MCP 连接状态 | `curl http://opencode:3901/mcp` | ✅ `watchlist` / `portfolio` / `uzi` / `hunter_user` / `hunter_cap` / `screener` **6 个全部 connected** |
| 4 | `POST /skill/refresh` | `curl -X POST …/skill/refresh` vs `/api/catalog/skills` | ✅ 返回 **25**,与基线一致;`/api/catalog/skills` summary `{"total":24,"ready":24,"headline":"24/24","user_added":18}`,与基线一致(差的 1 个是 opencode 自带内置 skill) |
| 5 | 对话「601899 现在多少钱」 | 真发消息,读回消息 parts | ✅ 调用 `watchlist_stock_quickview`(completed),回复「紫金矿业(601899)当前股价 **32.17 元**,今日上涨 **1.55%**…」。**冷态首条 75.6 秒**(重启后第一条要付插件 + MCP 冷启动),**热态 8.7 秒**(换 600519 复测,基线旧镜像 13.7 秒) |
| 6 | 深度分析 300750 | 「请对 300750 做一次深度分析」 | ✅ 依次调用 `skill` → **`uzi_stock_deep_analysis`**(completed)→ `watchlist_stock_news`,**26.9 秒**完成(限 300 秒),输出完整五节报告,**没有出现 "no output" / pending** |
| 7 | 全市场扫描 | 「用全市场扫描帮我筛一下最近放量突破的A股」 | ✅ 调用 **`screener_market_screen`**(completed),**18.9 秒**,从 5 237 只标的筛出 15 只并返回带价格/量比的表格 |
| 8 | OCR | 合成一张含 `600519 kweichow` / `000001 pingan` 的图,打 `POST /api/internal/ocr/extract` | ✅ HTTP 200 · engine `tesseract` · 识别出两行、关键数字命中 **2/2**。多阶段改造后 `chi_sim` / `eng` / `osd` 三个语言包都在 |
| 9 | 升级前后会话数量 | `GET /session` + `select count(*) from chat_session_owner` | ✅ 基线 **30** → 修掉 §1 那个问题后 **31**(多的 1 条是我在旧镜像上跑基线对话建的);测试全部跑完后 **35**(本次测试自己建了 5 个会话)。postgres `chat_session_owner` 全程 **93**,未变 |
| 10 | 旧入口脚本 + 新镜像 | 从 `git show HEAD:scripts/opencode/entrypoint.sh` 取旧脚本,临时容器、**不挂数据卷**、端口 3991 | ✅ healthy · `GET /` 200 · 插件全部加载。日志可见 `[boot] mcp SDK 版本可用,跳过安装`,末尾 `exec bun run packages/opencode/src/index.ts serve …` 被镜像里的 `bun` 垫片翻译成 `opencode serve …`。测完已删容器 |
| 10b | 新入口脚本 + 旧镜像(反向) | 新脚本挂进 `ghcr.io/agentpit-io/hunter-opencode:dev`,端口 3992,不挂卷 | ✅ healthy · `GET /` 200。日志:`[boot] opencode 未知(旧镜像 · 源码启动)` → `[boot] 镜像里没有 opencode 二进制(旧镜像),回落到源码启动`。测完已删容器 |
| 11 | 公网可用性 | `curl https://hunter-community.agentpit.io/` 与 `/api/health` | ✅ 首页 **200**(0.066 s)· `/api/health` **200** · body `{"status":"ok","service":"hunter","hunter_api_key":"configured"}` |
| 12 | 单测与静态检查 | 见下 | ✅ 全通过 |

用例 12 明细:

| 子项 | 命令 | 结果 |
|---|---|---|
| llm-shim 单测 | `python3 -m unittest discover -s scripts/llm-shim -p 'test_*.py'` | `Ran 2 tests … OK` |
| SKILL 工具引用检查 | `python3 scripts/check_skill_tools.py --offline` | `检查了 24 个 SKILL 文件` · `[needs_tools] 全部引用合法` · `[prompt_tpl] 全部是自然语言` |
| api 导入冒烟 | `docker exec … python3 -c "import main"` | `import main OK`(加载 24 个 SKILL) |
| 入口脚本有效命令行数 | `grep -vcE '^\s*(#\|$)' scripts/opencode/entrypoint.sh` | **7**(要求 ≤ 10) |

## 3 · 体积与启动(演示站实测)

| 指标 | 瘦身前 | 瘦身后 | 变化 |
|---|---|---|---|
| opencode 镜像 · 解压占盘 | **7.56 GB** | **618 MB** | **−91.8%** |
| opencode 镜像 · 压缩(下载量) | 1 704 397 469 B(1.70 GB) | 152 922 111 B(153 MB) | **−91.0%** |
| api 镜像 · 解压占盘 | 1.32 GB | **909 MB** | **−31%**(−411 MB) |
| opencode `restart → healthy` | 17 秒 | **16 秒** | 基本持平 |
| 对话首条响应(热态 · 行情查询) | 13.7 秒 | 8.7 秒 | 同一条链路、不同时刻的单次采样,**不作为性能结论** |

> 对话耗时只测了各一次,受上游大模型与行情接口波动影响很大,这里只是「没有明显变慢」的旁证,不是基准测试。

## 4 · 没有出现的问题(但检查过)

- **插件加载**:6 个 `plugins/*.ts` 在单文件二进制里照常被扫描到并加载(`/config` 的 `plugin` 数组里 6 个 `file://` 路径齐全),`import type` 被编译期擦除,不需要 node_modules。
- **MCP 子进程**:4 个镜像自带 + 2 个 compose 挂载的,全部 connected,`python3` 与 `mcp` 1.x 都在。
- **`/skill/refresh` 路由**:fork 自己加的接口在编译产物里存在(这正是不用官方预编译二进制的原因)。
- **审计日志**:`HUNTER_AUDIT_PATH` 指向卷内,插件正常写入。
- **旧镜像**:全程保留,回滚随时可用。
