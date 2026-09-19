# 在 Coolify / Dokploy 上部署 HunterCode

适合谁：手上有一台自己的 VPS，已经装了 Coolify 或 Dokploy 这类自托管 PaaS，
想在面板里点几下就把 HunterCode 跑起来、顺手拿到域名和 HTTPS。

这两家和 Zeabur / Sealos / Railway 最大的区别：**它们直接吃 docker compose**，
不需要把编排翻译成平台专有格式。所以本文给的就是两份**可以整段粘贴**的 compose：

- Coolify → [`deploy/coolify/docker-compose.yml`](../../deploy/coolify/docker-compose.yml)
- Dokploy → [`deploy/dokploy/docker-compose.yml`](../../deploy/dokploy/docker-compose.yml)

两份文件的服务、镜像、环境变量、卷、依赖**完全一致**，
差别只有一处：**随机密钥谁来生成**，以及域名怎么绑。

> ⚠️ **本仓没有 Coolify / Dokploy 的实例，下面每一步都没有在真实面板上点过。**
> 平台行为全部按官方文档核实（每处都给了链接），两份 compose 都在本机用
> 「等价方式」从空卷完整跑过（六服务健康 → 走完向导 → 真实对话 → 深度分析 →
> 重启数据不丢），实测数据见第五节。

---

## 一、为什么这两家可以比云平台简单

Zeabur / Sealos / Railway 上，六个服务跑在不同的机器/Pod 上，**不共享磁盘**，
所以 `JWT_SECRET` 与 `HUNTER_INTERNAL_KEY` 这两把「三家必须同值」的密钥
只能靠模板生成、再分别注入三个服务 —— 填错一处的症状是「服务全绿但一对话就 401」。

Coolify 和 Dokploy 都是**单机 Docker**，三个容器可以共用一个卷。
所以这两份 compose 里**根本没有这两个变量**：api 首次启动时各生成一把 64 位随机串
写进 `hunter_secrets` 卷，web 与 opencode 只读挂同一个卷读回同一把。
少两个能填错的地方，就少两类只能靠猜的故障。

你要准备的只剩两个值：**数据库口令**和**首启向导的初始化口令**。

---

## 二、Coolify

### 2.1 创建

Coolify → 选一个 Project → **+ New Resource** → **Docker Compose** →
把 [`deploy/coolify/docker-compose.yml`](../../deploy/coolify/docker-compose.yml)
**整段粘进去** → **Save** → **Deploy**。

### 2.2 两个随机值：不用你填

compose 里用了 Coolify 的 **magic environment variables**
（[官方文档](https://coolify.io/docs/knowledge-base/docker/compose)）：

| 写法 | Coolify 会做什么 |
|---|---|
| `${SERVICE_PASSWORD_PGPASS}` | 生成 32 位随机口令（不含符号），**同一个名字在全文里是同一个值** |
| `${SERVICE_PASSWORD_SETUPTOKEN}` | 同上，用作首启向导的初始化口令 |
| `SERVICE_FQDN_WEB_3000` | 给 `web` 服务分配域名，并把反代指到容器的 3000 端口 |

生成的值会落进资源的 **Environment Variables** 页，**重新部署不会变**，
在那里可以查看和修改。

> `SERVICE_FQDN_<ID>_<PORT>` 里的 `<ID>` **必须是 compose 里的服务名**
> （连字符和点要换成下划线）。这里服务名就叫 `web`，所以是 `SERVICE_FQDN_WEB_3000`。

### 2.3 域名

默认会用你在 Coolify 里配的泛域名生成一个。想换成自己的：
资源 → **Domains** → 填自己的域名，Coolify 负责签发证书。

### 2.4 初始化口令在哪看

资源 → **Environment Variables** → 找 `SERVICE_PASSWORD_SETUPTOKEN`。
向导第 0 步要填的就是它。

---

## 三、Dokploy

### 3.1 创建

Dokploy → Project → **Create Service** → **Compose** → Provider 选 **Raw** →
把 [`deploy/dokploy/docker-compose.yml`](../../deploy/dokploy/docker-compose.yml)
整段粘进 **Compose File**。

### 3.2 两个随机值：要你自己生成

Dokploy **没有** Coolify 那种自动生成器。在本机先生成两个值：

```bash
echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
echo "HUNTER_SETUP_TOKEN=$(openssl rand -hex 12)"
```

把这两行粘进服务的 **Environment** 页签。

> ⚠️ **别指望 Dokploy 把这些变量注入容器** —— 官方文档原文：
> *Environment variables set in the UI are written to the `.env` file, but are
> **not automatically injected into containers***
> （[Docker Compose | Dokploy](https://docs.dokploy.com/docs/core/docker-compose)）。
> 它写的是同目录的 `.env`，而 compose 的 `${VAR}` 插值**读的正是这个 `.env`**，
> 所以这份文件里的写法是对的，不需要额外的 `env_file`。
>
> ⚠️ **`HUNTER_SETUP_TOKEN` 不要留空。** 空口令 = 公网上谁先打开谁就能配大模型。

### 3.3 域名

服务 → **Domains** 页签 → **Add Domain**：
- Service Name 选 **`web`**
- Container Port 填 **`3000`**
- Host 填你的域名，按需要开 Let's Encrypt

不需要自己写 Traefik 标签、也不需要在 compose 里写 `ports:` ——
官方文档：*At runtime, during the deployment phase, Dokploy automatically adds
Traefik labels internally to your Docker Compose file*，并且会把选中的那个服务
接进 `dokploy-network`（[Domains - Docker Compose](https://docs.dokploy.com/docs/core/docker-compose/domains)）。

### 3.4 部署

**General** → **Deploy**，在 **Deployments** 页签看构建日志，等到 success。

---

## 四、两家都一样的部分

### 4.1 首启向导（五步）

打开域名，会自动进入向导。

| 步 | 做什么 |
|---|---|
| 0 | 输入初始化口令（Coolify 在 Environment Variables 里看；Dokploy 是你自己生成的那个） |
| 1 | 环境自检 —— postgres / redis / opencode / llm-shim / 迁移 / 密钥 / 卷 / 来源判定，各带真实耗时 |
| 2 | 选大模型厂商 —— 内置 5 个常见预设，也可以填任意 OpenAI 兼容网关 |
| 3 | 填 key 当场测 —— 连通 / 对话 / 工具调用三项，由 api 容器发出，**测不通不让保存** |
| 4 | 数据从哪来 —— 可以先跳过 |
| 5 | 完成 —— 热生效，**不重启任何容器** |

- 口令错 5 次锁 15 分钟；重启 api 容器解除锁定（口令本身不变）。
- 向导走完之后**注册第一个账号**（这两份 compose 都是多用户模式
  `HUNTER_SINGLE_USER=0`），第一个注册的账号自动是管理员。
  建好之后建议把 `REGISTRATION_MODE` 改成 `closed` 再重新部署。

### 4.2 数据在哪、怎么备份

六个具名卷，两家平台都交给 docker 自己管
（Coolify 会在 **Configuration → Persistent Storage** 里只读展示它们）：

| 卷 | 装什么 | 要不要备份 |
|---|---|---|
| `hunter_pg` | 账号、自选股、配置、迁移账本 | **必须** |
| `hunter_opencode` | **所有对话正文**（`opencode-local.db`） | **必须** |
| `hunter_user_skills` | 你在界面里装的 SKILL | 建议 |
| `hunter_packages` | 导入的数据包 | 建议 |
| `hunter_secrets` | 两把自动生成的密钥 | **必须**（丢了 = 已保存的大模型 key 全部解不开、登录全部失效） |
| `hunter_redis` | 缓存 | 不用 |

> ⚠️ Dokploy 官方建议：需要备份功能就**用具名卷而不是 bind mount**。这份 compose
> 已经全部是具名卷。

### 4.3 升级

把四个 `ghcr.io/agentpit-io/hunter-community-*` 的镜像标签改成新版本，
重新部署即可。api 启动时自动补跑新增的数据库迁移（日志里逐个列出来），
不需要手工做任何事。

⚠️ **不要删 `hunter_secrets` 卷**，也不要在环境变量里另外塞一个 `JWT_SECRET` ——
它派生了加密已存 key 的密钥，换掉会让所有已保存的 key 解不开、登录全部失效。

### 4.4 资源建议

| 项 | 值 |
|---|---|
| 内存 | 最低 2 GB，**推荐 4 GB**（实测空闲 1.17 GB，深度分析 + 全市场扫描并发峰值 1.27 GB，opencode 一家占七成） |
| 磁盘 | 四个镜像实测合计 **3.3 GB**，加上数据卷留 8 GB 以上 |
| CPU | 2 核起 |

---

## 五、等价验证的实测数据（2026-09-18，本机，非真实面板）

验证方法和其他平台一致：`deploy/tools/template-to-compose.py` 读这两份 compose，
**按平台自己的规则**把变量填上（Coolify：magic 变量生成 32 位口令；
Dokploy：模拟用户 `openssl rand`），别的一个字都不改，然后在本机从空卷跑。

```bash
python3 deploy/tools/template-to-compose.py coolify --out /tmp/cf --web-port 3321
python3 deploy/tools/template-to-compose.py dokploy --out /tmp/dk --web-port 3322
```

| 项 | Coolify | Dokploy |
|---|---|---|
| 从空卷到六服务健康 | **22 秒** | **18 秒** |
| 错误口令 | HTTP 400「还可以再试 4 次」 | 同 |
| 口令长度 | 32（magic 变量） | 24（用户生成） |
| 向导第 1 步 | postgres 10ms · redis 0ms · opencode 373ms · llm-shim 11ms · 迁移 23 个 · 两个卷可写 | postgres 8ms · redis 0ms · opencode 63ms · llm-shim 11ms · 迁移 23 个 · 两个卷可写 |
| 两把密钥的来源 | **本次启动首次生成**（api 写进 `hunter_secrets` 卷，63 / 60 字符） | 同（62 / 61 字符） |
| 第 3 步三项检测 | 端到端 **3123 ms** | **2636 ms** |
| `apply` → `engine-ready` | **764 ms** | **1111 ms** |
| opencode 容器有没有重启 | `StartedAt` 前后完全一致 ✅ | ✅ |
| 注册第一个账号 | 自动 admin ✅ | ✅ |
| **真实对话** | **7.6 秒** | **5.6 秒** |
| **深度分析** | **23.7 秒**（LITE 19.8s · 覆盖率 50%） | **54.9 秒**（LITE 51.1s · 覆盖率 50%） |
| `docker compose restart` 前后快照 | 只差两行：密钥来源 `generated` → `volume` | 同 |

最后那一行正是想要的结果：**第一次启动生成、之后从卷里读回同一把**。
会话数、用户数、`hunter_config`、迁移数、两把密钥的哈希全部不变。

---

## 六、已知待核实（需要真实面板）

| # | 要确认什么 | 不对的话怎么办 |
|---|---|---|
| 1 | Coolify 的 `SERVICE_PASSWORD_*` 生成的字符集里有没有 `$` / `@` | 有的话 `DATABASE_URL` 要做 URL 编码；官方说的是「不含符号」，本轮按此实现 |
| 2 | Coolify 会不会改写 compose 里的 `restart:` / 网络 / 容器名 | 改写不影响本编排（没写 `container_name`，网络也用默认） |
| 3 | Dokploy 的 Isolated Deployments 开关对服务间 DNS 的影响 | 关掉时 `web` 会被接进共享的 `dokploy-network`；服务间通信走的是项目自己的网络，不受影响 |
| 4 | 两家的反代默认读超时会不会掐断 SSE（深度分析实测 20~55 秒） | 把 `proxy_read_timeout` / Traefik 的对应超时放宽到 600 秒 |
| 5 | 面板自带的「应用备份」能不能带上具名卷 | 带不上就用 `docker run --rm -v <卷>:/src -v $PWD:/dst alpine tar czf /dst/x.tgz -C /src .` 自己备 |

---

## 七、排查

| 症状 | 多半是 |
|---|---|
| 打开域名 502 / 503 | 反代指到了错的端口。web 是 **3000** |
| 向导全绿，发消息永远没有回复，日志里什么都没有 | api 的 `LLM_SHIM_URL` 不对。这两份 compose 里服务名就叫 `llm-shim`，一般不会错；改过服务名的话记得一起改 |
| 能进页面，一对话就 401 | `hunter_secrets` 卷没有同时挂给 api / web / opencode 三家 |
| 上传图片没反应 | 同上（web 和 api 的 `HUNTER_INTERNAL_KEY` 对不上） |
| 深度分析跑到一半断掉 | 反代的读超时太短，见第六节第 4 条 |
| 升级后页面 500 | 看 api 日志里的迁移输出；正常情况下它会逐个列出补跑的迁移文件 |
