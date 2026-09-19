# 在 Railway 上部署 HunterCode

适合谁：海外用户、已经在 Railway 上放了别的服务、想要一个带 HTTPS 域名又不想管服务器的实例。
费用由 Railway 按用量计，和我们无关。

> ⚠️ **本仓没有 Railway 账号，所以下面每一步都没有在真实平台上点过。**
> 字段全部按官方文档核实（每处都给了链接），并在本机用「等价 compose」
> 从空卷完整跑过一遍（六服务健康 → 走完向导 → 真实对话 → 深度分析 → 重启数据不丢），
> 实测数据见第六节。真实平台上仍需核对的点列在第七节。
>
> **Railway 没有「模板文件」这种东西。** 官方流程是：先在控制台里把一个项目
> 跑通，再从那个项目**反向生成**模板（Settings → Generate Template from Project）。
> 所以本文第二节是「要在控制台里敲什么」的逐条清单，机器可读版在
> [`deploy/railway/services.yaml`](../../deploy/railway/services.yaml)
> —— 两者是同一份事实，文档里的表格就是从它来的。

---

## 一、先看三条 Railway 特有的坑

这三条都是**不做就起不来**，而且症状都很难从日志里看出来。写在最前面。

| # | 坑 | 怎么办 |
|---|---|---|
| 1 | **卷的根目录天生带 `lost+found`**（Railway 的卷是 ext4 块设备），而 `initdb` 拒绝在非空目录上建库 → postgres 无限重启，日志里只有 `initdb: error: directory "/var/lib/postgresql/data" exists but is not empty` | postgres 服务加变量 **`PGDATA=/var/lib/postgresql/data/pgdata`**（卷仍挂 `/var/lib/postgresql/data`）。官方镜像自己给的提示就是「Create a subdirectory under the mount point」 |
| 2 | **卷以 root 属主挂载**（[官方文档原文](https://docs.railway.com/reference/volumes)：*Volumes are mounted as the `root` user*），而 postgres / redis / opencode 三个镜像都以非 root 用户跑 → 写不进卷 | 这三个服务各加一个变量 **`RAILWAY_RUN_UID=0`**（官方就是这么说的）。opencode 镜像里 `HOME=/home/hunter` 是写死的 ENV，换成 root 跑之后配置与数据路径**一个字都不变** |
| 3 | **一个服务只能挂一个卷**（官方限制） | api 本来要两份可写数据，合并进同一个卷的两个子目录：卷挂 `/opt/hunter-vol`，再设 `HUNTER_USER_SKILLS_DIR=/opt/hunter-vol/user-skills`、`HUNTER_PACKAGE_DIR=/opt/hunter-vol/packages`。⚠️ **不要挂到 `/opt/hunter-data`** —— 那是镜像自带的静态数据目录（向导的预设清单就在里面），挂上去等于把它遮掉 |

还有一条不致命但值得知道：**2025-10-16 之前创建的环境，私有网络是 IPv6-only**
（[官方文档](https://docs.railway.com/networking/private-networking/how-it-works)），
之后创建的是双栈。本清单把四个自家服务的监听地址统一设成 `::`，两种环境都能用。

---

## 二、在控制台里搭六个服务

### 2.0 建项目

Railway 控制台 → **New Project** → **Empty Project**。
之后每个服务都用 `CMD/CTRL + K` → **New Service** → **Docker Image** 添加。

> 服务名照下面写，**不要带连字符**。原因：引用变量的语法是 `${{ServiceName.VAR}}`，
> 官方文档里的例子都是不带连字符的标识符，带连字符能不能解析官方没写。
> 服务名只影响私有主机名，而所有跨服务地址我们都显式写成变量，改名代价为零。

### 2.1 六个服务一览

| 服务名 | 镜像 | 监听端口 | 对外 | 卷（挂载路径） | 健康检查路径 |
|---|---|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5432 | 否 | `/var/lib/postgresql/data` | —（TCP） |
| `redis` | `redis:7-alpine` | 6379 | 否 | `/data` | —（TCP） |
| `llmshim` | `ghcr.io/agentpit-io/hunter-community-llm-shim:1.1.0` | 3999 | 否 | — | `/health` |
| `api` | `ghcr.io/agentpit-io/hunter-community-api:1.1.0` | 8000 | 否 | `/opt/hunter-vol` | `/api/health` |
| `opencode` | `ghcr.io/agentpit-io/hunter-community-opencode:1.1.0` | 3901 | 否 | `/home/hunter/.local` | —（TCP） |
| `web` | `ghcr.io/agentpit-io/hunter-community-web:1.1.0` | 3000 | **是** | — | `/` |

**只有 `web` 需要公网域名**：点 `web` → Settings → Networking → **Generate Domain**，
目标端口填 `3000`。其余五个一律不要开 Public Networking —— 开了等于把数据库
和内部接口直接挂到公网上。

挂卷：右键服务 → **Attach Volume**，填上表的挂载路径
（[官方说明](https://docs.railway.com/templates/create)）。

健康检查：服务 → Settings → **Healthcheck Path**。TCP 的那三个留空。

### 2.2 每个服务的变量

变量写在服务的 **Variables** 页签。`${{...}}` 是 Railway 的模板语法，
部署时求值：

- `${{secret(N)}}` —— 生成 N 位随机密钥（不给 N 时默认 32 位）。**每处独立求值**
- `${{服务名.变量名}}` —— 引用另一个服务的变量（[Variables Reference](https://docs.railway.com/variables/reference)）
- `${{服务名.RAILWAY_PRIVATE_DOMAIN}}` —— 那个服务的私有主机名。**别写死主机名**，官方最佳实践就是这一条

#### postgres

```
POSTGRES_USER      = hunter
POSTGRES_DB        = hunter
POSTGRES_PASSWORD  = ${{secret(32)}}
PGDATA             = /var/lib/postgresql/data/pgdata      ← 见第一节坑 1
RAILWAY_RUN_UID    = 0                                    ← 见第一节坑 2
```

#### redis

```
RAILWAY_RUN_UID    = 0
```

#### llmshim

```
SHIM_PORT          = 3999
HUNTER_BIND_HOST   = ::
LLM_BASE_URL       =                （留空 · 大模型由首启向导配，入库后热生效）
```

#### api

```
HUNTER_BIND_HOST       = ::
JWT_SECRET             = ${{secret(48)}}
HUNTER_INTERNAL_KEY    = ${{secret(48)}}
HUNTER_SETUP_TOKEN     = ${{secret(24)}}
DATABASE_URL           = postgresql://hunter:${{postgres.POSTGRES_PASSWORD}}@${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/hunter
REDIS_URL              = redis://${{redis.RAILWAY_PRIVATE_DOMAIN}}:6379/0
LLM_SHIM_URL           = http://${{llmshim.RAILWAY_PRIVATE_DOMAIN}}:3999/v1
OPENCODE_URL           = http://opencode.railway.internal:3901
HUNTER_SINGLE_USER     = 0
REGISTRATION_MODE      = open
HUNTER_MINIMAL_BOOT    = 1
JWT_ACCESS_TTL         = 3600
JWT_REFRESH_TTL        = 2592000
HUNTER_UPSTREAM_URL    =
LLM_PROVIDER           = openai_compat
HUNTER_SKILLS_DIR      = /opt/hunter-skills
HUNTER_USER_SKILLS_DIR = /opt/hunter-vol/user-skills
HUNTER_PACKAGE_DIR     = /opt/hunter-vol/packages
HUNTER_API_KEY         =
```

三处需要解释：

- **`HUNTER_SINGLE_USER=0` 是安全底线，不是偏好。** 单用户模式不要账号密码，
  在公网上开着等于任何打开页面的人都拿到 admin。
- **`LLM_SHIM_URL` 必须设**，而且是设在 **api** 上，不是只有 opencode 需要。
  向导保存后由 api 走 `PATCH /global/config` 把 provider 的 `baseURL` 推给 opencode，
  推的就是 api 容器里这个值；不设会回落到硬编码的 `http://llm-shim:3999/v1`，
  而 Railway 上没有这个主机名。这个失败**不报错**：向导五步全绿、`engine-ready`
  也是 `true`，**但发消息永远没有回复，日志里一条都没有**（M3 实测过）。
- **`OPENCODE_URL` 故意写死 `opencode.railway.internal`**，不用引用变量：
  opencode 已经引用了 api 的两把密钥，再反向引用就是两个服务互相引用，
  官方没写这种情况能不能解析。私有主机名的格式是文档里写死的，直接用更稳。

#### opencode

```
RAILWAY_RUN_UID       = 0                                 ← 见第一节坑 2
HUNTER_BIND_HOST      = ::
JWT_SECRET            = ${{api.JWT_SECRET}}
HUNTER_INTERNAL_KEY   = ${{api.HUNTER_INTERNAL_KEY}}
HERMES_API_URL        = http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000
LLM_SHIM_URL          = http://${{llmshim.RAILWAY_PRIVATE_DOMAIN}}:3999/v1
LLM_SCHEMA_SANITIZE   = auto
LLM_PROVIDER          = openai_compat
HUNTER_AUDIT_PATH     = /home/hunter/.local/share/hunter-audit/AUDIT.jsonl
HUNTER_BUDGET_ENABLED = false
```

⚠️ **`JWT_SECRET` 必须和 api 是同一把**（api 签发的 token 由 opencode 的插件验签）。
两边不同的话服务照常启动、健康检查也过，**只是一对话就 401**。
用引用变量就不会填错。

⚠️ opencode 的卷装的是**所有对话正文**（`opencode-local.db`）。
不挂卷 = 一次重建全没，且不可恢复 —— postgres 里只有 `session_id ↔ user_id`
的归属映射，正文一个字都不在里面。

#### web

```
NODE_ENV            = production
PORT                = 3000
HOSTNAME            = ::
HERMES_API_URL      = http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000
OPENCODE_URL        = http://${{opencode.RAILWAY_PRIVATE_DOMAIN}}:3901
HUNTER_INTERNAL_KEY = ${{api.HUNTER_INTERNAL_KEY}}
```

`HERMES_API_URL` / `OPENCODE_URL` 不传的话会回落到 `127.0.0.1` ——
在 web 容器里那是它自己，表现为 503 / 502。

### 2.3 部署

六个服务配完，点 **Deploy**。Railway **不编排启动顺序**，六个服务同时起；
api 要先跑完数据库迁移才开始监听，opencode 会等它（默认最多等 90 秒，
由 `HUNTER_CONFIG_WAIT` 控制），这是正常的。

---

## 三、初始化口令在哪看

Railway 控制台 → **`api` 服务** → **Variables** → 复制 `HUNTER_SETUP_TOKEN` 的值。

这道口令的作用是：**从部署完成到你第一次打开页面之间，防止别人抢先进来
把大模型配置成他自己的**。公网上的实例不设口令，等于谁先打开谁说了算。

- 口令错 5 次锁 15 分钟；重启 `api` 服务解除锁定（口令本身不变）。

## 四、首启向导（五步）

打开 `web` 的域名，会自动进入向导。

| 步 | 做什么 |
|---|---|
| 0 | 输入上一节那个初始化口令 |
| 1 | 环境自检 —— 逐项列出 postgres / redis / opencode / llm-shim / 迁移 / 密钥 / 卷 / 来源判定，各带真实耗时 |
| 2 | 选大模型厂商 —— 内置 5 个常见预设，也可以填任意 OpenAI 兼容网关 |
| 3 | 填 key 当场测 —— 连通 / 对话 / 工具调用三项，由 api 容器发出（和 opencode 走同一条网络路径），**测不通不让保存** |
| 4 | 数据从哪来 —— 可以先跳过 |
| 5 | 完成 —— 热生效，**不重启任何容器** |

向导走完之后**注册第一个账号**（模板是多用户模式），第一个注册的账号自动是管理员。
建好之后建议把 api 的 `REGISTRATION_MODE` 改成 `closed` 再 Redeploy。

## 五、生成模板并发布（维护者用）

这一节是给想把自己跑通的这套项目变成「一键部署按钮」的人看的。
步骤按 [官方文档](https://docs.railway.com/templates/create) 与
[发布说明](https://docs.railway.com/templates/publish-and-share)：

1. **先把项目真的跑通**（第二节做完、向导走完、能对话）。模板是从项目反向生成的，
   项目里是什么样，模板就是什么样。
2. 项目页 → 画布角上的 **Settings** → 下拉到 **Generate Template from Project**
   → **Create Template**。
3. 进入 **template composer**，逐服务确认：
   - **Variables** 页签：确认 `${{secret(N)}}` 与引用变量**原样保留**下来了
     （官方最佳实践：*use template variable functions to generate them,
     avoid hardcoding default credentials at all costs*）。
     顺手给每个变量填上说明 —— 别人部署时看到的就是这行字。
   - **Settings** 页签：确认 Healthcheck Path 与 Public Networking 的开关，
     **只有 web 该是公开的**。
   - 右键服务 → 确认 **Volume** 的挂载路径还在。
4. 图标用 1:1、透明背景（官方最佳实践）。
5. 点 **Publish**，填表单提交到模板市场。
   发布后的部署按钮格式是：

   ```md
   [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template/[TEMPLATE_CODE]?utm_medium=integration&utm_source=button&utm_campaign=huntercode)
   ```

   `[TEMPLATE_CODE]` 换成发布后拿到的模板 ID。
6. 模板被别人部署时维护者可以拿 kickback（官方：开源且有社区支持的模板最高 25%）。

> **上架之前请先按第七节把每一条都核一遍**，并把本文开头那句
> 「没有在真实平台上点过」删掉。README 里的按钮也是上架并实测通过之后才加。

## 六、等价验证的实测数据（2026-09-18，本机，非 Railway）

验证方法和 Zeabur / Sealos / 1Panel 三个平台完全一致：
`deploy/tools/template-to-compose.py` 把
[`deploy/railway/services.yaml`](../../deploy/railway/services.yaml)
**机械翻译**成等价 compose —— 同镜像、同环境变量、用 `secret(N)` 生成的随机密钥、
同卷、同监听地址，**并且刻意模拟了 Railway 的两条卷语义**：卷是空的（不像 Docker
具名卷那样拷贝镜像内容）、根目录带 `lost+found`（ext4）。人不能在中间改。

```bash
python3 deploy/tools/template-to-compose.py railway --out /tmp/rw --web-port 3320
cd /tmp/rw && docker compose up -d
```

| 项 | 实测 |
|---|---|
| 从空卷到六服务健康 | **14 秒**（镜像已在本地） |
| 数据库迁移 | 两阶段 **3.38 秒**，23 个全部执行 |
| 四个服务绑 `::` 之后的连通性 | 容器内 `127.0.0.1` 200 / `[::1]` 200；跨容器 web→api、opencode→api 全 200 |
| 错误口令 | HTTP 400「口令不对，还可以再试 4 次」 |
| 向导第 1 步 | postgres 10ms · redis 1ms · opencode 165ms · llm-shim 15ms · 迁移 23 个 · 两把密钥都是 48 字符「来源：环境变量」· 两个卷可写 |
| 第 3 步三项检测 | 端到端 **2259 ms** |
| `apply` → `engine-ready` | **10736 ms**，opencode 容器 `StartedAt` 前后完全一致（**没有重启**） |
| 注册第一个账号 | 自动 admin |
| 真实对话 | **6.6 秒** |
| 深度分析 | **31.7 秒**（卡片自报 LITE 28.5s · 覆盖率 50%） |
| `docker compose restart` 前后快照 | **逐字节一致**（会话 / 用户 / 配置 / 迁移数 / 两把密钥的哈希全不变） |

这一轮验证**顺手挖出并修掉了四个真问题**，都写在提交
`feat(deploy): Railway 手工搭建清单 + Coolify / Dokploy 可直接粘贴的 compose` 里，
详情见 [`docs/setup-wizard/M4-成果与测试报告.md`](../setup-wizard/M4-成果与测试报告.md)。

### 资源建议

| 项 | 值 |
|---|---|
| 内存 | 最低 2 GB，**推荐 4 GB**（实测空闲 1.17 GB，深度分析 + 全市场扫描并发峰值 1.27 GB，opencode 一家占七成） |
| 磁盘 | 四个镜像实测合计 **3.3 GB**，加上数据卷留 8 GB 以上 |
| CPU | 2 核起 |

## 七、已知待核实（需要 Railway 账号）

| # | 要确认什么 | 不对的话怎么办 |
|---|---|---|
| 1 | `${{服务名.RAILWAY_PRIVATE_DOMAIN}}` 的**实际取值**是不是 `<服务名>.railway.internal` | 不是就把 api 的 `OPENCODE_URL` 改成实际值 |
| 2 | 引用变量 `${{api.JWT_SECRET}}` 能不能引用到**用变量函数生成**的值（而不是拿到字面量 `${{secret(48)}}`） | 拿不到就改成 Shared Variables（项目级共享变量），`${{shared.JWT_SECRET}}` |
| 3 | `RAILWAY_RUN_UID=0` 之后 opencode（Bun 单文件二进制）能不能正常跑 | 本机用 `user: 0:0` 验过可以；平台上若不行，改成加一个 init 容器 chown |
| 4 | Healthcheck 对没有 HTTP 端点的服务（postgres / redis / opencode）怎么配 | 留空即可；平台若强制要求，给 opencode 配 `/` 并放宽失败次数 |
| 5 | web 的 SSE 会不会被平台的反代默认读超时掐断（深度分析实测 20~55 秒） | 被掐断的话找 Railway 的超时设置放宽到 600 秒 |
| 6 | GHCR 镜像在 Railway 的拉取速度 | 慢的话先把镜像同步一份到别的 registry |
| 7 | 模板市场的上架审核要求（图标尺寸、描述、分类） | 按当时的官方表单填 |

## 八、备份与升级

- **备份**：Railway 的卷支持手动与自动备份（服务 → Volume → Backups）。
  **至少要备 postgres 与 opencode 两个卷** —— 前者是账号与配置，后者是所有对话正文。
- **升级**：把四个 `ghcr.io/agentpit-io/hunter-community-*` 的镜像标签改成新版本，
  Redeploy 即可。api 启动时会自动补跑新增的数据库迁移（日志里逐个列出来），
  不需要手工做任何事。**不要改 `JWT_SECRET`** —— 它派生了加密已存 key 的密钥，
  换掉会让所有已保存的 key 解不开、登录全部失效。

## 九、排查

| 症状 | 多半是 |
|---|---|
| postgres 无限重启，日志 `initdb: ... exists but is not empty` | 没设 `PGDATA` 子目录 · 第一节坑 1 |
| opencode 反复重启，日志「会话数据目录不可写」 | 没设 `RAILWAY_RUN_UID=0` · 第一节坑 2 |
| 向导第 2 步没有任何预设可选 | api 的卷挂到了 `/opt/hunter-data`，把镜像自带的静态数据遮掉了 · 第一节坑 3 |
| 打开域名 502 / 503 | web 的 `HERMES_API_URL` / `OPENCODE_URL` 没设，回落到了 127.0.0.1 |
| 向导全绿，发消息永远没有回复，日志里什么都没有 | api 的 `LLM_SHIM_URL` 没设或指向了错误的主机名 · 见 2.2 |
| 能进页面，一对话就 401 | api 与 opencode 的 `JWT_SECRET` 不是同一把 |
| 上传图片没反应 | web 与 api 的 `HUNTER_INTERNAL_KEY` 不是同一把 |
| 重新部署之后模型又变成「尚未配置」 | opencode 等 api 超时了（默认 90 秒）。api 起得更慢的话把 opencode 的 `HUNTER_CONFIG_WAIT` 调大 |
| 服务之间连不上，但每个服务自己日志都正常 | 老环境的私有网络是 IPv6-only。确认四个自家服务的 `HUNTER_BIND_HOST` / `HOSTNAME` 都是 `::` |
