# Getting started · 入门

> HunterCode · Community Edition

## Prerequisites

- Docker Engine 25+ · Docker Compose v2 (or Docker Desktop on Windows / macOS)
- 2 CPU · 4 GB RAM · 10 GB disk (all six services run from pre-built images since v1.1.0 — nothing is built locally)
- Network access to `ghcr.io` (the chat engine image is pulled from there)
- **A model to talk to.** Recommended: the **built-in quota** — one free
  [`hunt_tools_` platform key](https://hunter.agentpit.io/dev/api-keys) (~30 seconds)
  and you are done; no LLM account of your own, no endpoint to look up. See
  [`docs/builtin-llm/使用说明.md`](./builtin-llm/使用说明.md).
  Advanced path: your own LLM API key (any OpenAI-compatible gateway; DeepSeek is
  the tested default).

## Deploy to a cloud platform instead · 部署到云平台

Don't want to run a server? Every platform below has a step-by-step doc:
不想自己管服务器?下面每个平台都有一篇逐步说明:

| Platform | Doc |
|---|---|
| Zeabur | [`docs/deploy/zeabur.md`](./deploy/zeabur.md) |
| Sealos | [`docs/deploy/sealos.md`](./deploy/sealos.md) |
| Railway | [`docs/deploy/railway.md`](./deploy/railway.md) |
| 1Panel | [`docs/deploy/1panel.md`](./deploy/1panel.md) |
| Coolify / Dokploy | [`docs/deploy/coolify-dokploy.md`](./deploy/coolify-dokploy.md) |

⚠️ None of these has been run on the real platform yet (we have no accounts), and none
is listed in a marketplace — each doc says exactly what was verified and what was not.
A public instance **must** keep `HUNTER_SINGLE_USER=0` and set `HUNTER_SETUP_TOKEN`;
every template already does both.

## Install

```bash
git clone https://github.com/agentpit-io/hunter-community
cd hunter-community
docker compose up -d
```

That is the whole install since v1.1.0 — **`.env` is optional**. Copy it only when
you want to change ports, point at your own LLM, or add a platform key:

```bash
cp .env.example .env
```

## Configure

Edit `.env`:

- **`JWT_SECRET`** · **leave it empty**. On first boot the API generates one and
  stores it in the `hunter_secrets` volume; the opencode container mounts that
  volume read-only and reads the same value (both containers must agree — the
  API signs tokens that opencode's `hunter-auth` plugin verifies).
  ⚠️ **Changing or losing `JWT_SECRET` means every stored key becomes
  undecryptable and has to be entered again.** The generated one lives in a
  Docker volume, so `docker compose down -v` destroys it. If you prefer to pin
  your own, generate it once and never change it:
  ```bash
  openssl rand -base64 48 | tr -d '=/+' | head -c 60
  ```
- **`HUNTER_VERSION` / `HUNTER_REGISTRY`** · which pre-built image tag to pull
  and from where. Pin a concrete version, never `latest`.
- `HUNTER_SINGLE_USER` · `1` (default) means **no login screen at all** — the
  frontend silently obtains a session for one built-in local account. Set it to
  `0` before letting anyone else reach this instance; with it on, any request to
  `/api/auth/local-session` gets an admin token.
- `REGISTRATION_MODE` · only applies when `HUNTER_SINGLE_USER=0` ·
  `open` (anyone can register · first user is admin) ·
  `invite` (needs code from admin · first user still admin) · `closed`
- **`LLM_BASE_URL` / `LLM_DEFAULT_MODEL` / `LLM_API_KEY`** · **leave them empty.**
  Since v1.1.0 the browser wizard configures the model; since v1.2.0 its first card
  is the built-in quota, so the normal path never touches this file at all.
  Setting them here still works and **takes priority** — an instance with all three
  set is *locked* and the wizard can only show them read-only (that is how the demo
  site runs). Fill **all three or none**: a half-filled set makes the upstream return
  401, which gets swallowed into an empty message ("深度思考完成" with no body).
  For DeepSeek also set `LLM_SCHEMA_SANITIZE=1`. Per-provider templates:
  [`docs/env-samples/`](./env-samples/).
  To hard-code the built-in quota (what the one-click deploy templates do):
  ```bash
  LLM_BASE_URL=https://hunter.agentpit.io/api/saas/llm/v1
  LLM_API_KEY=hunt_tools_xxxxxxxxxxxxxxxx   # the platform key — no second key needed
  LLM_DEFAULT_MODEL=hunter-chat
  LLM_SCHEMA_SANITIZE=0                     # sanitizing happens at the gateway
  ```
  ⚠️ Hard-coding it means you must also set the deep-analysis model variables
  yourself — the wizard writes them for you otherwise. See
  [`docs/builtin-llm/使用说明.md` §6](./builtin-llm/使用说明.md).
- `HUNTER_API_KEY` · optional, for the platform data pipeline. Can also be pasted
  in the UI later ("解锁全部工具", bottom-left). On the built-in-quota path the
  wizard stores the same `hunt_tools_` key here for you.
- Everything else has sensible defaults.

## Start

```bash
docker compose up -d
```

The first run only pulls images (~3–5 minutes); later runs take seconds.
Six services should end up running:

```bash
docker compose ps
# NAME                          STATUS
# hunter-community-postgres-1   Up (healthy)
# hunter-community-redis-1      Up (healthy)
# hunter-community-api-1        Up (healthy)
# hunter-community-llm-shim-1   Up (healthy)
# hunter-community-opencode-1   Up
# hunter-community-web-1        Up
```

If `opencode` or `llm-shim` shows `Restarting`, see the error table below.

Open [http://localhost:3100](http://localhost:3100). You land straight in the
app — no registration, no login (see `HUNTER_SINGLE_USER` above).

With no model configured you land in the **first-run wizard**. Step 2's first card,
"使用 HunterCode 内置额度 (recommended)", fills in the endpoint and model name for
you — paste one free `hunt_tools_` platform key in step 3, let the three checks pass,
and you are chatting. It also points deep analysis at `hunter-deep` and unlocks the
data supply with that same key, so step 4 has nothing left to do.
Full walkthrough: [`docs/builtin-llm/使用说明.md`](./builtin-llm/使用说明.md).

With `HUNTER_SINGLE_USER=0` you'll be redirected to `/register?setup=1` instead,
to create the initial admin account.

## Behind a reverse proxy (optional)

For a public deployment put nginx (or caddy · traefik) in front, terminate
TLS, and reverse-proxy to `:3100` for the app and `:8100` for the API.

```nginx
server {
    server_name hunter.example.com;
    listen 443 ssl;
    # ... cert config ...

    location /api/ {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_buffering off;   # SSE-friendly
    }

    location / {
        proxy_pass http://127.0.0.1:3100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 600s;
    }
}
```

## Developing (local builds + source bind mounts)

`docker-compose.yml` intentionally contains **no `build:` section and no bind
mount of repository files** — otherwise a fresh clone (or a cloud platform) would
silently start compiling Next.js instead of pulling. Everything that used to be
mounted now lives in `docker-compose.dev.yml`:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

With that override, `skills/`, `data/`, `user-skills/`, `apps/web/public/`,
`scripts/llm-shim/`, `scripts/opencode/` and `scripts/opencode-mcp/` are mounted
from the working tree again, so edits take effect without rebuilding. The images
it builds are tagged `<name>:dev` so they cannot be mistaken for the released
ones.

## Upgrading

```bash
git pull                 # picks up the new HUNTER_VERSION default
docker compose pull
docker compose up -d
```

Migrations are idempotent — the API applies them on boot (the image ships
`db/migrations/` at `/opt/hunter-migrations`; the old
`/docker-entrypoint-initdb.d` mount on postgres is gone, it only ever ran on a
brand-new data volume).

### Upgrading from v1.0.x · 从 v1.0.x 升级

Two things, both one-off:

1. **Run `bash scripts/migrate-volumes.sh` once.** `user-skills/` and `data-packages/`
   used to be bind mounts; since v1.1.0 they are named volumes owned by the api service.
   Without this, SKILLs you installed through the UI disappear from the list — the files
   are all still there, the container just cannot see them any more.
   Started the stack with `docker compose -p <name>`? Pass it through:
   `bash scripts/migrate-volumes.sh --project <name>`.
2. **Nothing else.** Keep your `.env` as it is. If it has `LLM_BASE_URL` / `LLM_API_KEY` /
   `LLM_DEFAULT_MODEL`, those stay authoritative and are shown as locked in the UI —
   the first-run wizard will **not** appear. Missing tables and columns are filled in
   automatically on the first boot; the api log lists every migration it applies.
   ⚠️ **Do not change `JWT_SECRET`** — it derives the key that encrypts stored API keys,
   so changing it makes every saved key undecryptable and logs everyone out.

To reset the database entirely:

```bash
docker compose down -v   # ⚠ nukes users + all state, including the generated JWT_SECRET
docker compose up -d
```

## Common issues

### 常见报错速查表 · Quick reference

> 先看是哪个容器出的问题：`docker compose ps` 找状态不是 `Up (healthy)` 的服务，再 `docker compose logs <服务名> --tail 50` 看日志。
> 下表的「现象」尽量写成你在命令行或页面上实际看到的文字，可以直接 Ctrl+F 搜。

| # | 现象 | 原因 | 解决 |
|---|---|---|---|
| 1 | `docker compose up` 直接报错 `required variable JWT_SECRET is missing a value` | **v1.1.0 之前**的 `docker-compose.yml` 用 `${JWT_SECRET:?}` 强制要求这一项 | `git pull` 拿新的 `docker-compose.yml`（留空会自动生成）；想自己指定就按下方 ① 生成一把写进 `.env`，之后**不要再改**——换掉它等于已保存的 key 全部解不开 |
| 2 | Windows 上没有 `openssl`，第 1 条的命令跑不了 | Windows 默认不带 openssl | 用下方 ① 的 PowerShell 版本 |
| 3 | `opencode` 一直 `Restarting`，日志里有 `[gen-config] LLM_BASE_URL / LLM_API_KEY / LLM_DEFAULT_MODEL 未设置` | 大模型三项少填了，`gen-config.py` 拒绝生成半残配置 | 在 `.env` 填齐 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_DEFAULT_MODEL`，再 `docker compose up -d` |
| 4 | `llm-shim` 反复重启，日志 `[shim] LLM_BASE_URL 未设置,无法转发`；`opencode` 一直不启动 | 同上，shim 没有上游地址就退出，opencode 要等 shim 健康才会启动 | 同第 3 条 |
| 5 | 能发消息，但回复只有一行「深度思考完成」没有正文；日志里有 `Invalid schema ... type: "null"` | DeepSeek（`deepseek-v4-flash` / `deepseek-v4-pro`）拒绝部分工具的 `parameters: null` | `.env` 加 `LLM_SCHEMA_SANITIZE=1`，然后 `docker compose up -d`（**不能用 restart**，见第 8 条） |
| 6 | 每条消息都失败，日志 `Invalid JSON payload received. Unknown name "$schema"` | Gemini 只认 OpenAPI 子集的工具 schema。默认 `auto` 只在**模型名含 gemini** 时清洗，网关给模型起了别名就识别不到 | `.env` 设 `LLM_SCHEMA_SANITIZE=1` 强制清洗，再 `docker compose up -d` |
| 7 | macOS 开着 Clash / Verge 等 TUN 模式代理，容器里调大模型或拉数据一直超时 | TUN 劫持了容器直连外网的流量 | `.env` 填 `HTTP_PROXY_UPSTREAM` 和 `HTTPS_PROXY_UPSTREAM`（指向宿主机代理，如 `http://host.docker.internal:7890`，端口以你的代理软件为准），`NO_PROXY_UPSTREAM` 保持默认，再 `docker compose up -d`（api 和发大模型请求的 llm-shim 都会走这个代理） |
| 8 | 改了 `.env` 之后 `docker compose restart` 没有任何变化 | `restart` 只重启进程、不重读 `.env` | 改 `.env` 后一律 `docker compose up -d`（compose 会按新环境变量重建受影响的容器） |
| 9 | 登录页或新闻页提示「网络错误」，浏览器请求打到一个奇怪的地址 | `.env` 里填了 `NEXT_PUBLIC_API_URL`，但它是**构建期**写进前端产物的，官方预构建镜像烘的是**空值**（= 同源 `/api/*`，由 web 自己的 BFF 转发给 api，无论有没有反代都通） | 把 `NEXT_PUBLIC_API_URL` 留空即可。真要填绝对地址就得自己重建 web：`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build web` |
| 10 | 端口被占，`Bind for 0.0.0.0:3100 failed: port is already allocated` | 本机已有服务占用 3100 / 8100 / 5442 / 6479 | 改 `.env` 里的 `WEB_HOST_PORT`、`API_HOST_PORT`、`POSTGRES_HOST_PORT`、`REDIS_HOST_PORT`。`NEXT_PUBLIC_API_URL` 留空时浏览器只打 web 那个端口，改 API 端口不影响前端 |
| 11 | 行情、工具、SKILL、走势预测返回 403；深度分析报告全空 | 没配平台 key（`HUNTER_API_KEY`）或 key 已失效。聊天本身不受影响 | 到 [hunter.agentpit.io/dev/api-keys](https://hunter.agentpit.io/dev/api-keys) 免费申请，填进 `.env` 后 `docker compose up -d`；或在页面左下角「解锁全部工具」里粘贴，立即生效。也可以只用免费源，见 README「数据供给三选一」 |
| 12 | 往 `skills/` 或 `user-skills/` 加了 SKILL，界面里看不到 | 默认模式下 `skills/` 已打进镜像、不再挂载，改仓库目录对运行中的容器没有影响；opencode 也只在启动时扫描一次 | 改内置 `skills/` 要重建镜像，或用开发覆盖文件（`-f docker-compose.yml -f docker-compose.dev.yml`）把目录挂回去；改完 `docker compose restart opencode`（约 50 秒），再用 `python scripts/check_skill_sync.py` 核对 |
| 13 | 聊一阵后提示「已达日 token 上限 500000 · 明日再试」 | 旧版 compose / 镜像的预算插件没有关闭。自部署用的是你自己的大模型额度，不该被限 | `git pull` 拿最新 `docker-compose.yml`（默认 `HUNTER_BUDGET_ENABLED=false`），再 `docker compose pull opencode && docker compose up -d` |
| 14 | `opencode` 启动即退出，日志 `[boot] ❌ 会话数据目录 /home/hunter/.local 不可写` | 卷根属主不是 1001。Docker 具名卷不会这样（空卷首次挂载会继承镜像里的属主）；K8s / 云平台的 PVC 不拷贝镜像内容，属主是平台给的 | 平台上给 opencode 的 Pod 设 `securityContext.fsGroup: 1001`，或加一个 initContainer 执行 `chown -R 1001:1001`；本地则恢复仓库里的挂载写法（整个 `/home/hunter/.local` 挂具名卷） |
| 15 | 走 aihubmix 网关时对话一直超时；`docker compose logs llm-shim` 里是 `SSL: UNEXPECTED_EOF_WHILE_READING` | aihubmix 会拦截容器（Alpine）直连的 TLS 指纹 | 宿主机开着代理软件时，`.env` 填 `HTTPS_PROXY_UPSTREAM=http://host.docker.internal:<代理端口>`（llm-shim 与 api 共用这组变量），再 `docker compose up -d`；没有代理软件时，改用宿主机转发脚本，做法见 `docs/model-testing/results/2026-08-16_aihubmix_六家对比.md` |
| 16 | 升级到 v1.0.1 之后打开页面「暂无对话」，但数据卷还在 | 对话引擎换成单文件二进制时，会话库的文件名会跟着 opencode 的 channel 变（源码版叫 `opencode-local.db`，编译版默认叫 `opencode.db`）。**卷、权限、路径全是对的，只是打开了一个空库** | 我们已在镜像里钉死 `OPENCODE_DB=opencode-local.db`，正常升级不会遇到。真遇到了**先别删卷**：`docker exec <opencode 容器> ls -la /home/hunter/.local/share/opencode/`，如果看到新建的空 `opencode.db` 而 `opencode-local.db` 还在，说明是这个问题；确认 `.env` 里没有覆盖 `OPENCODE_DB`，然后 `docker compose up -d opencode` |
| 17 | `docker compose pull opencode` 报 `error from registry: denied` | 镜像是**公开**的，报 denied 通常不是没权限，而是机器上留着一份**过期的 GHCR 登录**——docker 会优先带上它，被拒之后**不会退回匿名** | `docker logout ghcr.io`，再 `docker compose pull opencode` |

> ⚠️ **不要随手 `docker compose down -v`**：`-v` 会删掉所有具名卷，包括数据库和 opencode 的对话正文，删了无法恢复。

**① 生成 `JWT_SECRET`**（可选 —— 留空会自动生成一把存进 `hunter_secrets` 卷）

```bash
# Linux / macOS
echo "JWT_SECRET=$(openssl rand -base64 48 | tr -d '=/+' | head -c 60)" >> .env
```

```powershell
# Windows PowerShell
$b = New-Object byte[] 48
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
Add-Content -Path .env -Encoding ascii -Value ("JWT_SECRET=" + [Convert]::ToBase64String($b))
```

`.env.example` 里的 `JWT_SECRET=` 是空的（v1.1.0 起）。追加新值后请确保文件里只有一行 `JWT_SECRET`——compose 用最后一行、`grep` 取第一行，两边对不上会得到莫名其妙的 401。

### More

- **`docker compose up` hangs on `web` build** · Next.js 15 compile is
  ~2 min on first build · subsequent builds hit the cache.
- **`web` container returns 401 without any UI** · That's your nginx or
  reverse proxy sending basic-auth. Community has none by default.
- **`api` restarts continuously** · Check `docker compose logs api` —
  usually a missing env var. `HUNTER_MINIMAL_BOOT=1` (default) tolerates
  most missing config.
- **Login page keeps appearing** · That means single-user mode is off
  (`HUNTER_SINGLE_USER=0`) or the api container can't be reached — check
  `docker compose logs api`.
- **Register form 400 "该邮箱已注册"** · The email exists. Log in via
  `/login` or reset via `docker compose exec postgres psql -U hunter ...`.
