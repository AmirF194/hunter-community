# Getting started · 入门

> HunterCode · Community Edition

## Prerequisites

- Docker Engine 25+ · Docker Compose v2 (or Docker Desktop on Windows / macOS)
- 2 CPU · 4 GB RAM · 20 GB disk (the opencode chat-engine image is ~7.5 GB)
- Network access to `ghcr.io` (the chat engine image is pulled from there)
- An LLM API key (any OpenAI-compatible gateway; DeepSeek is the tested default)

## Install

```bash
git clone https://github.com/agentpit-io/hunter-community
cd hunter-community
cp .env.example .env
```

## Configure

Edit `.env`:

- **`JWT_SECRET`** · rotate it before you expose the instance to the
  internet. Generate one:
  ```bash
  openssl rand -base64 48 | tr -d '=/+' | head -c 60
  ```
- `HUNTER_SINGLE_USER` · `1` (default) means **no login screen at all** — the
  frontend silently obtains a session for one built-in local account. Set it to
  `0` before letting anyone else reach this instance; with it on, any request to
  `/api/auth/local-session` gets an admin token.
- `REGISTRATION_MODE` · only applies when `HUNTER_SINGLE_USER=0` ·
  `open` (anyone can register · first user is admin) ·
  `invite` (needs code from admin · first user still admin) · `closed`
- **`LLM_BASE_URL` / `LLM_DEFAULT_MODEL` / `LLM_API_KEY`** · required. If any is
  missing, the `opencode` container refuses to start and keeps restarting. For
  DeepSeek also set `LLM_SCHEMA_SANITIZE=1`. Per-provider templates:
  [`docs/env-samples/`](./env-samples/).
- `HUNTER_API_KEY` · optional, for the platform data pipeline. Can also be pasted
  in the UI later ("解锁全部工具", bottom-left).
- Everything else has sensible defaults.

## Start

```bash
docker compose up -d
```

The first run builds `api` and `web` locally and pulls the opencode image
(~10–15 minutes depending on your network; ~5 minutes once images are cached).
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

## Upgrading

```bash
git pull
docker compose up -d --build
```

Migrations are idempotent — the API applies them on boot. To reset the
database entirely:

```bash
docker compose down -v   # ⚠ nukes users + all state
docker compose up -d --build
```

## Common issues

### 常见报错速查表 · Quick reference

> 先看是哪个容器出的问题：`docker compose ps` 找状态不是 `Up (healthy)` 的服务，再 `docker compose logs <服务名> --tail 50` 看日志。
> 下表的「现象」尽量写成你在命令行或页面上实际看到的文字，可以直接 Ctrl+F 搜。

| # | 现象 | 原因 | 解决 |
|---|---|---|---|
| 1 | `docker compose up` 直接报错 `required variable JWT_SECRET is missing a value: 请在 .env 里设置 JWT_SECRET` | `docker-compose.yml` 强制要求 `JWT_SECRET`（api 签发 token、opencode 验签必须同一把，不允许留空） | 生成一把写进 `.env`，命令见下方 ① ；然后重新 `docker compose up -d` |
| 2 | Windows 上没有 `openssl`，第 1 条的命令跑不了 | Windows 默认不带 openssl | 用下方 ① 的 PowerShell 版本 |
| 3 | `opencode` 一直 `Restarting`，日志里有 `[gen-config] LLM_BASE_URL / LLM_API_KEY / LLM_DEFAULT_MODEL 未设置` | 大模型三项少填了，`gen-config.py` 拒绝生成半残配置 | 在 `.env` 填齐 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_DEFAULT_MODEL`，再 `docker compose up -d` |
| 4 | `llm-shim` 反复重启，日志 `[shim] LLM_BASE_URL 未设置,无法转发`；`opencode` 一直不启动 | 同上，shim 没有上游地址就退出，opencode 要等 shim 健康才会启动 | 同第 3 条 |
| 5 | 能发消息，但回复只有一行「深度思考完成」没有正文；日志里有 `Invalid schema ... type: "null"` | DeepSeek（`deepseek-v4-flash` / `deepseek-v4-pro`）拒绝部分工具的 `parameters: null` | `.env` 加 `LLM_SCHEMA_SANITIZE=1`，然后 `docker compose up -d`（**不能用 restart**，见第 8 条） |
| 6 | 每条消息都失败，日志 `Invalid JSON payload received. Unknown name "$schema"` | Gemini 只认 OpenAPI 子集的工具 schema。默认 `auto` 只在**模型名含 gemini** 时清洗，网关给模型起了别名就识别不到 | `.env` 设 `LLM_SCHEMA_SANITIZE=1` 强制清洗，再 `docker compose up -d` |
| 7 | macOS 开着 Clash / Verge 等 TUN 模式代理，容器里调大模型或拉数据一直超时 | TUN 劫持了容器直连外网的流量 | `.env` 填 `HTTP_PROXY_UPSTREAM` 和 `HTTPS_PROXY_UPSTREAM`（指向宿主机代理，如 `http://host.docker.internal:7890`，端口以你的代理软件为准），`NO_PROXY_UPSTREAM` 保持默认，再 `docker compose up -d` |
| 8 | 改了 `.env` 之后 `docker compose restart` 没有任何变化 | `restart` 只重启进程、不重读 `.env` | 改 `.env` 后一律 `docker compose up -d`（compose 会按新环境变量重建受影响的容器） |
| 9 | 改了端口后，登录页或新闻页提示「网络错误」，浏览器请求还打到旧端口 | `NEXT_PUBLIC_API_URL` 是**构建期**写进前端产物的，改 `.env` 不会自动生效 | 同步改 `NEXT_PUBLIC_API_URL`（如 `http://localhost:8101`），然后 `docker compose up -d --build web` |
| 10 | 端口被占，`Bind for 0.0.0.0:3100 failed: port is already allocated` | 本机已有服务占用 3100 / 8100 / 5442 / 6479 | 改 `.env` 里的 `WEB_HOST_PORT`、`API_HOST_PORT`、`POSTGRES_HOST_PORT`、`REDIS_HOST_PORT`；改了 API 端口要同时做第 9 条 |
| 11 | 行情、工具、SKILL、走势预测返回 403；深度分析报告全空 | 没配平台 key（`HUNTER_API_KEY`）或 key 已失效。聊天本身不受影响 | 到 [hunter.agentpit.io/dev/api-keys](https://hunter.agentpit.io/dev/api-keys) 免费申请，填进 `.env` 后 `docker compose up -d`；或在页面左下角「解锁全部工具」里粘贴，立即生效。也可以只用免费源，见 README「数据供给三选一」 |
| 12 | 往 `skills/` 或 `user-skills/` 加了 SKILL，界面里看不到 | opencode 只在启动时扫描一次 SKILL 目录 | `docker compose restart opencode`（约 50 秒），再用 `python scripts/check_skill_sync.py` 核对 |
| 13 | 聊一阵后提示「已达日 token 上限 500000 · 明日再试」 | 旧版 compose / 镜像的预算插件没有关闭。自部署用的是你自己的大模型额度，不该被限 | `git pull` 拿最新 `docker-compose.yml`（默认 `HUNTER_BUDGET_ENABLED=false`），再 `docker compose pull opencode && docker compose up -d` |
| 14 | `opencode` 重启循环，日志 `EACCES: permission denied, mkdir '/home/hunter/.local/state'` | 自己改过挂载，只挂了 `.local/share/opencode`；docker 以 root 补建父目录，容器用户 1001 写不进去 | 恢复仓库里的挂载写法（整个 `/home/hunter/.local` 挂具名卷），再 `docker compose up -d opencode` |
| 15 | 走 aihubmix 网关时连通性不稳、TLS 握手失败 | aihubmix 会拦截容器（Alpine）的 TLS 指纹 | 在宿主机起一个转发代理，让容器走 `http://host.docker.internal:<端口>/v1`，做法见 `docs/model-testing/results/2026-08-16_aihubmix_六家对比.md` |

> ⚠️ **不要随手 `docker compose down -v`**：`-v` 会删掉所有具名卷，包括数据库和 opencode 的对话正文，删了无法恢复。

**① 生成 `JWT_SECRET`**

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

`.env.example` 里自带一行示例值 `JWT_SECRET=change-me-in-production-please`（公开值，不安全）。追加新值后请**把示例那一行删掉**，确保文件里只有一行 `JWT_SECRET`。

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
