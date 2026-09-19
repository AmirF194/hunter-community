# M3 · 子任务 E · 1Panel 应用商店应用包

| 项 | 值 |
|---|---|
| 分支 | `m3/e-1panel`（基于 `feat/oneclick-m3`，起点 `a34257a`） |
| 产物目录 | `deploy/1panel/hunter-community/` |
| 应用版本 | `1.1.0-rc2`（四个自家镜像同版本） |
| 完成日期 | 2026-09-18 |
| **本轮没有真实 1Panel 面板** | 只做了静态校验（见第 5 节），装机验证留给有面板的人，待核实清单见第 6 节 |

---

## 一、核实到的官方规范要点

### 1.1 查了哪些一手材料

| 材料 | 地址 | 查阅日期 | 用法 |
|---|---|---|---|
| 1Panel 应用商店官方仓库 | https://github.com/1Panel-dev/appstore （clone 到 `/tmp/1panel-appstore`，HEAD `1ba7b2a` · 2026-09-18） | 2026-09-18 | **格式的最终依据**：263 个现存应用的真实写法 |
| 官方打包 SKILL 仓库 | https://github.com/1Panel-dev/1Panel-appstore-skills （HEAD `fd702ea` · 2026-09-09） | 2026-09-18 | 唯一一份把规范写成文字的官方材料：`references/appstore-format.md`、`references/appspec.md`、`references/review-checklist.md`，外加可执行的 `scripts/validate_app_package.py` |
| 仓库 README（中文） | https://github.com/1Panel-dev/appstore/blob/dev/README_zh.md | 2026-09-18 | 上架标准与提交入口 |
| 提交自己想要的应用（Wiki） | https://github.com/1Panel-dev/appstore/wiki/%E5%A6%82%E4%BD%95%E6%8F%90%E4%BA%A4%E8%87%AA%E5%B7%B1%E6%83%B3%E8%A6%81%E7%9A%84%E5%BA%94%E7%94%A8 | 2026-09-18 | README_zh 里给出的上架入口链接（未逐字读，Wiki 页在 clone 里不含） |
| 生命周期脚本的调用点 | `appstore-format.md` 里引用的 1Panel 主仓源码行号（v2.2.5 `agent/app/service/app_utils.go#L992-L1017`、dev-v2 `5ad12c6` 同文件 `#L998-L1033`） | 2026-09-18 | `init.sh` / `upgrade.sh` 的执行时机与超时 |

> 设计方案 5.1 表格里写的「1Panel 表单字段 `random`」这一条**需要更正**：1Panel 没有 `type: random`，
> 随机值是 `random: true` 这个**属性**，配在 `type: password`（或 `text`）字段上。见 1.3。

### 1.2 目录规范（`references/appstore-format.md` 原文结构）

```
apps/<app-key>/
  logo.png
  README.md
  README_en.md
  data.yml
  <version>/
    data.yml
    docker-compose.yml
    <持久化目录>/.gitkeep
    scripts/init.sh | upgrade.sh | uninstall.sh
```

- **根 `data.yml` 与版本 `data.yml` 都要**，不是二选一：根的是应用元信息，版本的是表单字段。
- 版本目录名**不能以 `v` 开头**（校验脚本会报 error）。带预发布后缀是允许的，仓库里有先例：`apps/deepseek-harness/0.1.5-rc.1`。所以本包用 `1.1.0-rc2`。
- 根 `data.yml` 必填：`name` / `tags` / `title` / `description` / `additionalProperties.{key,name,tags,shortDescZh,shortDescEn,description,type,crossVersionUpdate,limit,architectures}`；`additionalProperties.key` 必须等于目录名。
- `additionalProperties.description` 必须覆盖语言集 `en, es-es, ja, ms, pt-br, ru, ko, zh-Hant, zh, tr`（校验脚本逐个检查）。
- **每个表单字段的 `label` 也要覆盖同一套语言集**，且校验脚本只看 `label:` 之后 16 行，所以语言块要紧挨着写。
- compose 硬性要求：主服务 `container_name: ${CONTAINER_NAME}`、次要服务 `${CONTAINER_NAME}-<服务>`、所有服务加入 `1panel-network`（`external: true`）、每个服务带 `labels.createdBy: "Apps"`、对外端口用 `PANEL_APP_PORT_*`、持久化用相对路径挂载（`./data:/...`）。
- compose 里出现的每个 `${...}` **都必须在版本 `data.yml` 里声明 `envKey`**，只有 `CONTAINER_NAME` / `HOST_IP` / `HOST_ADDRESS`（以及声明了 `PANEL_DB_HOST` 时的 `PANEL_DB_PORT`）是面板内置的。
- README 风格：中文 `## 产品介绍`（可选 `## 主要功能`）、英文 `## Introduction` / `## Features`；**不许**写生成过程、本地测试路径、source evidence。

### 1.3 表单字段的真实写法（从 263 个应用里统计出来的）

| 属性 | 取值与出现次数 |
|---|---|
| `type` | `text` 452 · `number` 354 · `password` 154 · `select` 53 · `apps` 30 · `service` 24 |
| `rule` | `paramPort` 443 · `paramCommon` 163 · `paramComplexity` 56 · `paramExtUrl` 24 · `paramHttp` 9 · `paramPortRange` 1 |
| 随机值 | **`random: true` 属性**，配 `type: password` 或 `type: text`；`rule` 用 `paramCommon` 或 `paramComplexity` 都有先例 |

`type: password` + `rule: paramCommon` + `random: true` 的组合在仓库里有 5 处先例：
`hermes-agent/2026.9.14`（`HERMES_DASHBOARD_PASSWORD`）、`zitadel/4.17.0`、`archivebox/0.7.4`、`emqx/6.3.1`、`copaw/2.2.1`。本包两处随机密钥照这个写法。

### 1.4 logo 尺寸

`appstore-format.md` 与 `review-checklist.md` **都没有规定尺寸**，只要求文件名是 `logo.png`。
实测仓库里 263 个 logo 的尺寸分布（`struct.unpack` 读 PNG IHDR）：

```
180×180 : 88   300×300 : 44   200×200 : 23   256×256 : 13
512×512 :  8   320×320 :  5   120×120 :  5   225×225 :  4 …
最大文件 29,805 B，中位 3,752 B
```

本包取 **256×256 / 18,566 B**（在实测分布内，且比 180 更清晰）。

### 1.5 参照了仓库里哪几个现有应用

| 应用 | 为什么参照 |
|---|---|
| `apps/docmost/0.96.0` | **多服务 + postgres + redis** 的标准写法；表单字段的完整语言块、`random: true`、`paramPort` 写法都抄自它；另外它有 `scripts/init.sh` + `upgrade.sh` 的真实样例 |
| `apps/twenty/2.41.0` | 同一应用两个容器（server / worker）互相 `depends_on: condition: service_healthy` + healthcheck 的写法；根 `data.yml` 的 `type: website` / `crossVersionUpdate` / `recommend` 字段取值 |
| `apps/sub2api/0.2.5` | 单主服务 + 大量业务表单字段（含 `JWT_SECRET` 的 `random: true`、`select` 字段、`required: false` 可选字段）的完整样例 |
| `apps/rocketmq/5.5.0`、`apps/zabbix-xinchuang-edition/7.0.27` | 仓库里仅有的「一个应用自带 4~7 个容器」的样例，确认**多容器是被接受的**，以及次要容器一律 `${CONTAINER_NAME}-<服务>` 的命名 |
| `apps/postgresql/16.15-alpine`、`apps/redis/7.4.11` | 官方数据库应用怎么挂数据目录（都是 `./data:/var/lib/postgresql/data`、`./data:/data`），本包的 postgres / redis 挂载照抄 |

> **本包与主流写法的一处不同**：docmost / twenty / sub2api 用 `type: service` 字段引用面板里**另外装好的** PostgreSQL / Redis 应用。
> 本包按任务要求**自带 postgres + redis**（`POSTGRES_PASSWORD` 是 `random` 表单字段）。理由：hunter-community 的库是自己的私有 schema，
> 让用户先装两个中间件再装本应用，"一键"就名存实亡。代价与风险记在第 6 节。

---

## 二、目录结构与每个文件的作用

```
deploy/1panel/hunter-community/
├── data.yml                     根 · 应用元信息(名称/分类/多语言简介/架构/仓库链接)
├── README.md                    中文说明 · 产品介绍 + 主要功能 + 安装说明
├── README_en.md                 英文说明 · Introduction + Features + Notes
├── logo.png                     256×256 应用图标(本地 PIL 生成,无外部素材)
└── 1.1.0-rc2/
    ├── data.yml                 版本 · 安装表单(6 个字段,见第 3 节)
    ├── docker-compose.yml       六服务编排 · 1Panel 版
    ├── scripts/
    │   └── init.sh              容器启动前把 data/opencode 属主改成 1001:1001
    └── data/                    持久化目录(随包分发,各带 .gitkeep)
        ├── postgres/            PostgreSQL 数据目录
        ├── redis/               Redis AOF/RDB
        ├── opencode/            ⚠ 会话正文(所有对话内容)
        ├── secrets/             api 自动生成的 JWT_SECRET / HUNTER_INTERNAL_KEY
        ├── user-skills/         用户在界面里新建/安装的 SKILL
        └── packages/            数据包(用户导入 / 我们打包)
```

上架时把 `hunter-community/` 整个目录放到 appstore 仓库的 `apps/hunter-community/`（见第 7 节）。

---

## 三、data.yml 字段表

### 3.1 根 `data.yml`

| 字段 | 值 | 为什么 |
|---|---|---|
| `additionalProperties.key` | `hunter-community` | 必须等于目录名，校验脚本会比对 |
| `tags` / `additionalProperties.tags` | `AI` | `data.yaml` 根里的合法 tag key 只有 17 个（AI / Website / Database / Server / Runtime / Tool / Storage / BI / CRM / Security / DevTool / DevOps / Middleware / Media / Email / Game / Local）；同类应用 ai-gateway / ai-portal / astrbot 都用 `AI` |
| `type` | `website` | 同上三个 AI 应用都是 `website`（有 Web 界面的应用一律这个值，`tool` 是命令行类） |
| `crossVersionUpdate` | `true` | 允许跨版本升级；镜像自带迁移（api 启动跑 `python -m app.migrate`，带 advisory lock 与 `schema_migrations` 记账），跨版本升级是安全的 |
| `limit` | `0` | 不限制同一面板安装几个实例 |
| `recommend` | `0` | 不自荐排序（官方决定），twenty 也是 0 |
| `architectures` | `amd64` + `arm64` | **实测**，见 5.4 |
| `description` | 10 种语言 + `fa` | 校验脚本硬性要求 |

### 3.2 版本 `1.1.0-rc2/data.yml` 表单字段

| # | envKey | type | rule | 默认值 | random | 必填 | 中文 label | 为什么这么定 |
|---|---|---|---|---|---|---|---|---|
| 1 | `PANEL_APP_PORT_HTTP` | `number` | `paramPort` | `3180` | — | 是 | Web 访问端口 | 只有 web（容器内 3000）需要对外。默认 **3180**：避开面板上最常见的 3000 / 8080，也避开本项目本机 compose 的 3100（同机同时跑两套时不撞）。规范要求端口字段必须 `type: number` + `rule: paramPort` |
| 2 | `HUNTER_SETUP_TOKEN` | `password` | `paramCommon` | `change-me-on-install` | **是** | 是 | 首启向导初始化口令 | M2 语义：**非空 = 一律要口令**，不管来源看起来是不是本机（来源判断靠 HTTP 转发头，访问者可伪造；"有没有口令"伪造不了）。面板部署基本都会反代到公网，所以必填 + 随机生成。装完在「应用 → 参数」里看得到明文，向导第 0 步要填它。用 `paramCommon`（字母数字 + `. - _`）而不是 `paramComplexity`：值会写进 `.env`，含 `$` 会被 compose 当变量插值 |
| 3 | `POSTGRES_PASSWORD` | `password` | `paramCommon` | `change-me-on-install` | **是** | 是 | 数据库密码 | **必须 `paramCommon`**：这个值被拼进 `DATABASE_URL=postgresql://hunter:<pw>@host:5432/hunter`，含 `@ / # : ?` 会让连接串解析错位（`paramComplexity` 允许特殊字符，用它就是埋雷） |
| 4 | `REGISTRATION_MODE` | `select` | — | `open` | — | 是 | 注册策略 | 取值来自 `apps/api/app/routers/auth.py:55`：`open` / `invite` / `closed`（未知值回落 `closed`）。本应用强制多用户模式，走完向导要注册管理员，所以默认 `open`；建好管理员后建议改 `closed` 再重建容器 |
| 5 | `HUNTER_API_KEY` | `password` | `paramCommon` | 空 | — | 否 | HunterCode 平台 Key（可选） | 留空也能跑（聊天用用户自己的大模型 key），填了解锁行情数据 / 工具 / 预测。用 `password` 而不是 `text`：它是凭证，不该在面板表单里明文回显 |
| 6 | `HUNTER_ADMIN_EMAILS` | `text` | — | 空 | — | 否 | 管理员邮箱（可选，逗号分隔） | 这些邮箱注册即管理员；留空则第一个注册的账号是管理员 |

**故意没有做成表单项的三个值，以及原因：**

| 值 | 处理 | 原因 |
|---|---|---|
| `JWT_SECRET` | compose 里**根本不出现** | 留空（不注入）时 api 首启生成 64 位随机串写进 `./data/secrets/secrets.env`（属主 1001:1001 · 权限 640），web 与 opencode 只读挂同一个目录读回来。做成三个表单项只会多出「三处填不一致 → 对话莫名 401」的坑；而且 `JWT_SECRET` 派生了加密已存 key 的 AES 密钥，用户手滑改一次，所有已保存的 key 全部解不开 |
| `HUNTER_INTERNAL_KEY` | 同上 | 同上（web 的 BFF 调 `/api/internal/ocr/extract` 要和 api 同值，不一致的症状只是「上传图片没反应」，极难往密钥上想） |
| `HUNTER_SINGLE_USER` | compose 里**写死 `"0"`** | 面板部署面向公网，单用户免登录模式等于任何打开页面的人都能拿 admin token。这不是偏好，是安全底线，做成可改项就是给用户留一个自毁开关 |

---

## 四、与仓库默认 `docker-compose.yml` 的逐项差异

事实来源：仓库根 `docker-compose.yml`（六服务：postgres / redis / api / web / llm-shim / opencode）。

| # | 差异 | 默认 compose | 1Panel 包 | 原因 |
|---|---|---|---|---|
| 1 | **对外端口** | postgres 5442、redis 6479、api 8100、opencode 3921、web 3100 全部映射 | **只有 web** `${PANEL_APP_PORT_HTTP}:3000` | 面板机器多半在公网，把库和内部服务暴露到宿主没有任何理由。要连库调试用面板的「容器 → 终端」 |
| 2 | **`HUNTER_SINGLE_USER`** | `${…:-1}`（本机自用免登录） | 写死 `"0"` | 见 3.2 末表。设计方案 4.2 与 M2 报告遗留问题 #1 都点名了这一条 |
| 3 | **`HUNTER_SETUP_TOKEN`** | `${…:-}`（本机可留空直接进向导） | 表单 `random` 必填 | 同上：公网上不设口令 = 谁先打开谁能配置大模型 |
| 4 | **镜像版本** | `${HUNTER_VERSION:-1.1.0-rc2}`，可换 registry | **写死 `1.1.0-rc2`、写死 GHCR 地址** | 1Panel 升级是「换版本目录」，版本号由目录名表达；留 `${}` 会让每个变量都得进表单（规范要求），凭空多出两个没人会改的字段 |
| 5 | **容器名与服务发现** | 服务名直连（`postgres:5432`、`http://api:8000`） | 一律 `${CONTAINER_NAME}-<服务>` | `1panel-network` 是**全面板共用**的外部网络，compose 会把 `api` / `web` / `postgres` 这类服务名注册成网络别名。面板里再装一个同样有 `api` 服务的应用，DNS 就在两者之间随机解析 —— 症状是「时好时坏的 502 / 连错数据库」，查不出规律 |
| 6 | **网络** | 默认 bridge（compose 自建） | `1panel-network`，`external: true` | 规范硬性要求（校验脚本会检查） |
| 7 | **`restart`** | `unless-stopped` | `always` | `review-checklist.md` 写的是 `restart: always`；面板重启宿主后要能自己起来 |
| 8 | **卷** | 6 个具名卷（`hunter_pg_data` / `hunter_redis_data` / `hunter_opencode_data` / `hunter_user_skills` / `hunter_packages` / `hunter_secrets`） | 6 个相对路径 `./data/<名>` | 规范要求相对挂载；更重要的是 1Panel 的「应用备份」备份的是安装目录，具名卷**不会**被带上 —— 而 `data/opencode` 里是所有对话正文（2026-09-07 丢过一次的那份数据） |
| 9 | **`scripts/init.sh`** | 无 | 新增，`chown -R 1001:1001 data/opencode` | 具名卷首次挂载会把镜像里 `/home/hunter/.local` 的内容与属主一起拷进卷，**宿主目录 bind mount 不会** —— 目录由 docker 以 root 建出来，容器里的 uid 1001 写不进去，症状是 opencode 反复重启。这是差异 8 的必要配套 |
| 10 | **代理变量** | `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`（Mac Docker Desktop + TUN 场景） | 全部删掉 | 面板跑在 Linux 服务器上，没有宿主机 TUN 代理这回事；留着就得进表单，徒增三个字段 |
| 11 | **`LLM_*` / `AGENT_*` / `ASSISTANT_*` 等 20 多个透传变量** | 全部 `${…:-}` 透传 | 只保留 `LLM_PROVIDER: openai_compat` | 大模型配置在 M2 之后是**入库 + 热生效**，全部交给首启向导。这些变量留空时代码自己会决定，写成表单反而让用户以为必须填 |
| 12 | **`OPENCODE_USER` / `OPENCODE_PASS`** | `${…:-}` | web 里显式写 `""`，opencode 里不写 | 默认 compose 传的就是空串，行为一致；opencode 的真正门禁是 hunter-auth 插件 |
| 13 | **`SCREEN_SCAN_GAP_S`** | `${…:-5}` | 不写（用镜像/代码默认 5） | 面板部署可能多人共用，保持 5 秒对上游的保护 |
| 14 | **`FINDATA_DB_URL` / `DATA_SOURCE_PROVIDER` / `FORECAST_PROVIDER` 等** | 透传空值 | 不写 | compose 的 `:-` 对「未设」和「设为空」一视同仁，写进去等于把空串塞进容器，代码层默认值永远轮不到生效 |
| 15 | **服务顺序** | postgres 在最前 | **web 在最前** | appstore 的 Renovate 工作流（`.github/workflows/renovate-app-version.sh`）取 `.services \| keys \| .[0]` 的镜像标签**去重命名版本目录**。postgres 排第一的话，某次自动升级会把目录改成 `16-alpine` |
| 16 | **`db/migrations` 挂载** | 默认 compose 里已经删掉了 | 同样没有 | 保持一致（迁移由 api 启动时执行） |

**没有变的（刻意保留）**：六个服务、镜像清单、`depends_on` + `condition: service_healthy` 的依赖链、postgres/redis 的 healthcheck、
`HUNTER_MINIMAL_BOOT=1`、`HUNTER_AUDIT_PATH` 指向持久化目录、`LLM_SCHEMA_SANITIZE=auto`、预算三个变量、
`hunter_secrets` 目录 api 可写 / web 与 opencode 只读的读写方向。

---

## 五、静态校验（真实命令与真实输出）

### 5.1 YAML 语法

```
$ cd /mnt/disk-119/hunter-oneclick/wt-e-1panel/deploy/1panel
$ for f in hunter-community/data.yml hunter-community/1.1.0-rc2/data.yml hunter-community/1.1.0-rc2/docker-compose.yml; do
    python3 -c "import yaml,sys;yaml.safe_load(open('$f'));print('OK  $f')"; done
OK  hunter-community/data.yml
OK  hunter-community/1.1.0-rc2/data.yml
OK  hunter-community/1.1.0-rc2/docker-compose.yml
```

### 5.2 官方校验脚本（`1Panel-dev/1Panel-appstore-skills`）

```
$ python3 /tmp/1panel-skills/scripts/validate_app_package.py \
      /mnt/disk-119/hunter-oneclick/wt-e-1panel/deploy/1panel/hunter-community
OK: /mnt/disk-119/hunter-oneclick/wt-e-1panel/deploy/1panel/hunter-community
（退出码 0 · 零 error、零 warning）
```

它检查了：必需文件齐全、README 风格、根 `data.yml` 的 key 与目录名一致、description 十语言、
版本目录名不以 `v` 开头、`formFields` 存在、每个 `label` 的十语言、compose 的 `services` /
`1panel-network` / `external: true` / `createdBy` / `${CONTAINER_NAME}`、
**compose 里每个 `${...}` 都在 data.yml 里声明**、端口字段的 `paramPort` + `number`、
风险模式（privileged / host 网络 / docker.sock / `/` `/etc` 挂载）、镜像是否浮动标签、
`scripts/init.sh` 是否带来源证据标记。

> appstore 仓库本身的 GitHub Actions（`.github/workflows/`）只有四个：openresty 模块自检、
> LLM code review、Renovate 与 Renovate 版本改名脚本。**没有通用的应用包校验 Action**，
> 所以上面这个脚本就是能跑的全部官方校验。

### 5.3 `docker compose config -q`

1Panel 会在安装目录写一个 `.env`，compose 从那里取变量。这里用一份**替换过变量的临时副本**校验
（`.env` 里全是占位符，不含任何真实密钥）：

```
$ TMP=/tmp/hunter-1panel-cfgcheck; mkdir -p $TMP
$ cp deploy/1panel/hunter-community/1.1.0-rc2/docker-compose.yml $TMP/
$ cat > $TMP/.env <<'EOF'
CONTAINER_NAME=hunter-community-CHECK
PANEL_APP_PORT_HTTP=3180
HUNTER_SETUP_TOKEN=PLACEHOLDER-NOT-A-REAL-TOKEN
POSTGRES_PASSWORD=PLACEHOLDER-NOT-A-REAL-PASSWORD
REGISTRATION_MODE=open
HUNTER_API_KEY=
HUNTER_ADMIN_EMAILS=
EOF
$ cd $TMP && docker compose -f docker-compose.yml config -q
（无输出 · 退出码 0 = 合法）
```

解析结果抽查（确认容器名前缀、端口只开一个、网络与 label 都对）：

```
web      | container_name= hunter-community-CHECK          | ports= [3180->3000/tcp] | networks= ['1panel-network'] | labels= {'createdBy': 'Apps'}
api      | container_name= hunter-community-CHECK-api      | ports= None | networks= ['1panel-network'] | labels= {'createdBy': 'Apps'}
opencode | container_name= hunter-community-CHECK-opencode | ports= None | networks= ['1panel-network'] | labels= {'createdBy': 'Apps'}
llm-shim | container_name= hunter-community-CHECK-llm-shim | ports= None | networks= ['1panel-network'] | labels= {'createdBy': 'Apps'}
postgres | container_name= hunter-community-CHECK-postgres | ports= None | networks= ['1panel-network'] | labels= {'createdBy': 'Apps'}
redis    | container_name= hunter-community-CHECK-redis    | ports= None | networks= ['1panel-network'] | labels= {'createdBy': 'Apps'}
外部网络: {'1panel-network': {'name': '1panel-network', 'external': True}}
api DATABASE_URL = postgresql://hunter:***@hunter-community-CHECK-postgres:5432/hunter
web OPENCODE_URL = http://hunter-community-CHECK-opencode:3901
```

### 5.4 镜像实测（GHCR 匿名 · 架构核实）

```
$ for img in api web opencode llm-shim; do
    t=$(curl -s "https://ghcr.io/token?scope=repository:agentpit-io/hunter-community-$img:pull&service=ghcr.io" | jq -r .token)
    curl -s -H "Authorization: Bearer $t" \
         -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json" \
         "https://ghcr.io/v2/agentpit-io/hunter-community-$img/manifests/1.1.0-rc2" | …
  done
api      : [{'architecture': 'arm64', 'os': 'linux'}, {'architecture': 'amd64', 'os': 'linux'}]
web      : [{'architecture': 'arm64', 'os': 'linux'}, {'architecture': 'amd64', 'os': 'linux'}]
opencode : [{'architecture': 'amd64', 'os': 'linux'}, {'architecture': 'arm64', 'os': 'linux'}]
llm-shim : [{'architecture': 'arm64', 'os': 'linux'}, {'architecture': 'amd64', 'os': 'linux'}]
```

四个镜像 `1.1.0-rc2` 标签**都存在、都是 amd64 + arm64、匿名可拉**（请求没带任何凭证）。
根 `data.yml` 的 `architectures` 就是照这个填的。

### 5.5 挂载点属主实测（决定 bind mount 能不能用）

```
$ docker run --rm --network none --entrypoint sh \
      ghcr.io/agentpit-io/hunter-community-opencode:1.1.0-rc1 \
      -c 'ls -laR /home/hunter/.local; id'
/home/hunter/.local:
drwxr-xr-x 4 hunter hunter 4096 … share
drwxr-xr-x 4 hunter hunter 4096 … state
（share/ 与 state/ 都是空目录）
uid=1001(hunter) gid=1001(hunter) groups=1001(hunter)

$ docker run --rm --network none --entrypoint sh \
      ghcr.io/agentpit-io/hunter-community-api:1.1.0-rc1 \
      -c 'id; ls -la /opt/hunter-user-skills /opt/hunter-packages /opt/hunter-secrets'
uid=0(root) gid=0(root) groups=0(root)
ls: cannot access '/opt/hunter-user-skills': No such file or directory
ls: cannot access '/opt/hunter-packages': No such file or directory
ls: cannot access '/opt/hunter-secrets': No such file or directory

$ docker run --rm --network none --entrypoint sh \
      ghcr.io/agentpit-io/hunter-community-web:1.1.0-rc1 -c 'id'
uid=1001(nextjs) gid=65533(nogroup) groups=65533(nogroup)
```

结论（这三条是「具名卷 → 相对挂载」改法能成立的依据）：

1. opencode 的 `/home/hunter/.local` 在镜像里**只有两个空目录**，bind mount 不会遮盖任何有用内容，只需要把宿主目录属主改成 1001 → `scripts/init.sh` 做这一件事就够。
2. api 以 **root** 运行，且三个挂载点在镜像里**不存在**，所以 `user-skills` / `packages` / `secrets` 用 bind mount 既不遮盖也不会写不进去。
3. web 的 uid 是 1001 但 **gid 是 65533（nogroup）**，不是 1001。`secrets.env` 是属主 1001:1001 + 权限 640，web 靠**属主位**（不是组位）读到它 —— 这条成立，但也说明 `boot.sh` 注释里「组内可读正好覆盖另外两个容器」的说法对 web 并不准确（对 opencode 才准确）。行为没问题，只是原因和注释写的不同。

> 用的是 `1.1.0-rc1`（本机已有的镜像），rc2 是同一套 Dockerfile 出的，运行用户与挂载点结构不会变。
> 只跑了 `ls` / `id`，**没有启动任何服务**，没碰预发栈。

### 5.6 shell 语法与密钥体检

```
$ bash -n deploy/1panel/hunter-community/1.1.0-rc2/scripts/init.sh
bash -n OK
$ grep -rnE "sk-[A-Za-z0-9]{8,}|ghp_|-----BEGIN" deploy/1panel/
未发现疑似密钥
```

### 5.7 没做的校验

| 没做 | 原因 |
|---|---|
| 真实 1Panel 面板上「刷新本地应用 → 安装 → 启停 → 卸载 → 重装 → 升级」 | **没有面板环境**，这是 `review-checklist.md` 的 Local Test 一整节 |
| `docker compose up -d` 起这套编排 | 主控明确保留预发环境；本包的编排差异（端口、网络、挂载）由主控用「等价 compose」实测 |
| 表单在面板里的渲染效果、`random: true` 生成的字符集与长度 | 需要面板，见第 6 节 |

---

## 六、存疑 / 待核实清单

| # | 事项 | 现状与影响 | 建议怎么确认 |
|---|---|---|---|
| 1 | **`random: true` 生成值的字符集与长度** | 官方文档没写；本包给两个随机字段都用了 `rule: paramCommon`，假设生成器会遵守该 rule。如果它无视 rule 生成含 `$` 的值，`.env` 里会被 compose 当变量插值（`HUNTER_SETUP_TOKEN` 变成空或被截断）；含 `@ / #` 则会打断 `DATABASE_URL` | 在面板上装一次，看安装目录的 `.env` 里这两个值长什么样。若含特殊字符：`DATABASE_URL` 改用分离的 `PGHOST/PGUSER/PGPASSWORD` 写法，或在 `init.sh` 里做一次 URL 编码 |
| 2 | **自带 postgres / redis 会不会被审核驳回** | 仓库里主流做法是 `type: service` 引用面板已装的中间件；自带多容器有 rocketmq / zabbix 先例但都不带数据库 | 提 PR 时在描述里说明理由（私有 schema + 一键目标）。若审核要求改：改成 `PANEL_DB_*` / `PANEL_REDIS_*` 字段，本包第 3 节的字段 3 换成 4 个 service 字段，compose 去掉两个服务 |
| 3 | **版本目录 `1.1.0-rc2` 的排序** | 仓库有 `deepseek-harness/0.1.5-rc.1` 先例，但没查到 1Panel 对预发布后缀的排序规则；同时存在 `1.1.0` 和 `1.1.0-rc2` 时哪个被当成"最新"未知 | 正式版发布后直接建 `1.1.0/` 目录并删掉 rc2；上架建议等正式版 |
| 4 | **Renovate 会不会自动改我们的镜像标签** | `renovate.json` 是全仓 `apps/**` 生效的。它可能把 `postgres:16-alpine` 升到 17、或把我们的 `1.1.0-rc2` 升到新 tag 并**重命名版本目录**（已把 web 排到第一个服务来保证改名后目录仍等于我们的版本号） | 上架后关注 renovate PR；必要时在 `renovate.json` 的 `ignorePaths` 里加 `apps/hunter-community/**`（需要 1Panel 维护者合作） |
| 5 | **`init.sh` 的执行时机与 1Panel 版本** | 官方文档说 v2.2.5 起 dispatch `init` / `upgrade` / `uninstall`；更老的面板可能不执行 `init.sh` → `data/opencode` 属主还是 root → opencode 起不来 | README 或应用描述里注明要求 1Panel ≥ v2.2.5；或在 opencode 入口脚本里加一句更明确的中文报错（镜像侧改动，不在本子任务范围） |
| 6 | **`upgrade.sh` 要不要写** | 本包没写。升级时 `data/opencode` 属主已经是 1001，不需要再 chown；但如果 1Panel 升级时**重建了 data 目录**就需要 | 面板上真做一次升级，看 `data/` 属主有没有被动过 |
| 7 | **`description` 多语言只给了 zh / zh-Hant / en** | 表单字段的 `label` 给了全量十语言（校验脚本要求），但字段的 `description`（说明文字）只有三种。官方 SKILL 明确说「没有可靠翻译来源时用英文兜底，不要编」，所以其余语言留空由面板回落 | 如需补全，找母语者或官方翻译；不要机翻长句 |
| 8 | **`recommend: 0` / `limit: 0` 的确切语义** | 照抄 twenty 与 docmost，没查到字段说明文档 | 无影响（都是最宽松的值）；有面板可对照界面确认 |
| 9 | **`type: password` 的可选字段（`HUNTER_API_KEY`）留空会不会被当必填** | `required: false` + 空默认值，理论上可留空；但面板对 password 类型是否强制非空未验证 | 面板上装一次，不填直接下一步 |
| 10 | **面板反代 / HTTPS** | 本包只暴露宿主端口，反代由用户在面板「网站」里自己配。WebSocket（聊天流式）需要反代放行 SSE/长连接 | 面板上配一次反代，确认 `/chat` 的流式回答不被缓冲截断 |
| 11 | **资源建议是上一轮实测，不是本包实测** | 「空闲 1171 MB / 峰值 1271 MB → 最低 2 核 2 GB、推荐 2 核 4 GB、磁盘 ≥ 10 GB」来自 R0 预研，跑的是具名卷版编排。本包改成 bind mount，内存占用不会变，磁盘占用一样 | 主控用等价 compose 实测时顺带复核一次 |
| 12 | **`boot.sh` 注释里关于 web 的一句话不准确** | 注释说「属主 1001 + 组内可读(640) 正好覆盖另外两个容器」，实测 web 是 `uid=1001 gid=65533(nogroup)`，它靠**属主位**读到而不是组位（见 5.5）。行为正确，只是解释不对 | 顺手改注释即可，不影响本包 |

---

## 七、用户上架步骤

### 7.1 提交到官方应用商店

1. **Fork** https://github.com/1Panel-dev/appstore （默认分支是 `dev`，不是 `main`）。
2. 把本仓的 `deploy/1panel/hunter-community/` **整个目录**复制到 fork 的 `apps/hunter-community/`：
   ```bash
   cp -r hunter-community/deploy/1panel/hunter-community appstore/apps/hunter-community
   ```
   目录名必须是 `hunter-community`（要和根 `data.yml` 的 `additionalProperties.key` 一致）。
3. 本地跑一遍官方校验（可选但强烈建议）：
   ```bash
   git clone --depth 1 https://github.com/1Panel-dev/1Panel-appstore-skills /tmp/1panel-skills
   python3 /tmp/1panel-skills/scripts/validate_app_package.py apps/hunter-community
   # 期望输出:OK: apps/hunter-community
   ```
4. 提 PR 到 `1Panel-dev/appstore` 的 **`dev`** 分支。PR 描述里建议写清楚：
   - 应用是什么、官网 / GitHub 链接；
   - **为什么自带 postgres + redis**（见第 6 节 #2），免得审核来回；
   - 镜像是 GHCR 上的官方预构建镜像、支持 amd64 + arm64、匿名可拉；
   - 已做的静态校验与还没做的装机验证。
5. PR 会跑两个 Action：`LLM Code Review`（qwen2.5-coder 的英文评论，非阻塞）和 Renovate 相关的（只在 `renovate/*` 分支触发）。**没有**通用的应用包校验 Action。
6. 上架标准（README_zh 原文）：知名且活跃的开源项目 · 有一定安装基础 · 提供官方 Docker 镜像 · 其他审核通过的项目。

### 7.2 不上架、自己用（本地应用）

不想等审核的话，1Panel 支持本地应用，**不需要 PR**：

```bash
# 在装了 1Panel 的服务器上
scp -r hunter-community/deploy/1panel/hunter-community \
    root@<服务器>:/opt/1panel/resource/apps/local/hunter-community
```

然后面板里「应用商店 → 本地应用 → 同步/刷新」，就能看到并安装。
（路径 `/opt/1panel/resource/apps/local/<app-key>` 来自官方 SKILL 的 Output Contract 一节。）

### 7.3 装完之后

1. 「应用 → 参数」里抄下 **首启向导初始化口令**（`HUNTER_SETUP_TOKEN`）。
2. 打开 `http://<服务器IP>:3180`（或你在表单里改的端口），向导第 0 步填那个口令。
3. 走完五步（环境自检 → 选大模型 → 填 key 当场测试 → 数据供给），最后一步按提示**注册管理员账号**（第一个注册的就是管理员）。
4. 建好管理员后，回「应用 → 参数」把 `REGISTRATION_MODE` 改成 `closed`，**重建容器**生效。
5. 建议再用面板的「网站」功能给 3180 端口配反代 + HTTPS。
6. 备份：面板的「应用备份」会带上安装目录下的整个 `data/`（数据库、对话正文、密钥、SKILL、数据包都在里面）。

---

## 八、给主控的话

- 本包的 compose 可以直接 `docker compose -f <版本目录>/docker-compose.yml up -d` 跑，前提是先 `docker network create 1panel-network` 并提供一份含 `CONTAINER_NAME` / `PANEL_APP_PORT_HTTP` / `HUNTER_SETUP_TOKEN` / `POSTGRES_PASSWORD` / `REGISTRATION_MODE` / `HUNTER_API_KEY` / `HUNTER_ADMIN_EMAILS` 的 `.env`，并先 `bash scripts/init.sh`（它要在版本目录下跑，会建 `data/*` 并把 `data/opencode` 的属主改成 1001）。
- 做等价 compose 实测时，最值得盯的三件事：① `data/opencode` 属主对不对（不对 opencode 会反复重启）；② `data/secrets/secrets.env` 生成后 web 与 opencode 读不读得到（读不到的症状是「上传图片没反应」和「对话 401」，不是崩溃）；③ `HUNTER_SINGLE_USER=0` 下向导第 5 步有没有出现「创建管理员账号」。
- 第 6 节 #1（`random` 生成值的字符集）是唯一可能需要改 compose 的存疑项，其余都不影响文件内容。
