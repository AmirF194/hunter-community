# 00 · 瘦身前基线(实测)

> 测量时间:2026-09-17 01:1x–01:2x(上海时间)
> 测量对象:`ghcr.io/agentpit-io/hunter-opencode:dev`(瘦身前的对话引擎镜像)与 `hunter-community-api`
> 这份文档只记**测到的数**,没测的地方写「未测」并说明原因;后续对比一律以此为准。

## 1 · 测量环境

| 主机 | 角色 | 位置 | 规格 | 备注 |
|---|---|---|---|---|
| agentpit(34.133.47.117) | 构建机 | Google Cloud **us-central1-a**(美国中部) | Docker 数据目录在 `/mnt/disk-119`,剩余 109 GB | 只构建,不跑演示站 |
| fin-r1(35.198.212.241) | 演示站 | Google Cloud **asia-southeast1-c**(新加坡) | 4 核 / 15 GB 内存 / 根分区剩 12 GB | https://hunter-community.agentpit.io |

两地都在 Google Cloud 内网出口,拉 GHCR 走的是各自区域的公网线路。**国内网络没有测试机,拉取耗时未测**(见 `03-pull-benchmark.md`)。

## 2 · 镜像体积

Docker 29 默认用 containerd 镜像存储,`docker images` 的 SIZE 与 `docker image inspect .Size` 量的**不是一回事**,两个都记:

| 指标 | 数值 | 含义 |
|---|---|---|
| `docker images` SIZE | **7.56 GB** | 解压后占盘 |
| `docker image inspect .Size` | **1 704 397 469 B ≈ 1.70 GB** | 仓库里的压缩大小,也就是实际要下载的量 |

同机对比:`hunter-community-api` 1.32 GB、`hunter-community-web` 1.67 GB(均为 `docker images` 口径)。

## 3 · 分层 · 体积都花在哪

`docker history ghcr.io/agentpit-io/hunter-opencode:dev` 共 24 层,按大小前 10:

| # | 大小 | 这一层是什么 |
|---|---|---|
| 1 | **2.84 GB** | `RUN addgroup/adduser … && chown -R hunter:hunter /opt/opencode-workspace` |
| 2 | **2.78 GB** | `COPY /build ./`(deps 阶段整个 monorepo) |
| 3 | 128 MB | `RUN apk add python3 py3-pip ripgrep libgcc libstdc++ git curl && pip3 install mcp httpx` |
| 4 | 88.6 MB | `COPY /usr/local/bin/bun`(oven/bun 基础镜像) |
| 5 | 8.99 MB | `ADD alpine-minirootfs-3.22.4-x86_64.tar.gz`(alpine 基底) |
| 6 | 5.67 MB | oven/bun 基础镜像的 `RUN` |
| 7 | 20.5 kB | `COPY packages/hunter-server/opencode.jsonc` |
| 8 | 20.5 kB | `COPY docker-entrypoint.sh`(基础镜像) |
| 9 | 16.4 kB | `WORKDIR /home/bun/app`(基础镜像) |
| 10 | 12.3 kB | `WORKDIR /opt/opencode-workspace` |

**第 1 层是关键**:`chown -R` 改了 2.78 GB 文件的属主,overlayfs 没有「只改元数据」这种说法,整棵树被复制成第二层 —— 一次 chown 等于把镜像翻倍。

## 4 · 容器内目录占用

`docker exec hunter-community-opencode-1 du -sh …`:

| 路径 | 占用 |
|---|---|
| `/opt/opencode-workspace` | 2.7 GB |
| └ `node_modules` | **2.5 GB** |
| └ `packages` | 132.9 MB |
| └ `patches` | 160 KB |
| └ `sdks` | 128 KB |
| `/usr/lib/python3.12` | 97.1 MB |

`packages/` 下前几名:console 50.3 MB、opencode 19.7 MB、web 13.7 MB、ui 11.3 MB、app 10.7 MB、desktop 9.3 MB —— **除了 opencode 和 core,其余在服务端一行都不会执行**。

`/opt/opencode-workspace/.git` 不存在(`.dockerignore` 已排除),这一项不用再省。

## 5 · 运行时基线

| 项 | 实测 | 怎么测的 |
|---|---|---|
| `docker compose restart opencode` → healthy | **17 秒** | 循环查 `docker inspect -f '{{.State.Health.Status}}'`,2 秒一次。注意 healthcheck 本身是 `start-period=15s · interval=30s`,所以这个数的分辨率很粗 |
| opencode 会话数 | **30** | `curl -s http://opencode:3901/session \| python3 -c 'import sys,json;print(len(json.load(sys.stdin)))'`(在 api 容器里跑;演示站没开 Basic Auth) |
| postgres 会话归属记录 | **93** | `docker exec hunter-community-postgres-1 psql -U hunter -d hunter -tAc "select count(*) from chat_session_owner;"` |
| `POST /skill/refresh` | **25** | `curl -s -X POST http://opencode:3901/skill/refresh` |
| `/api/catalog/skills` summary | `{"total": 24, "ready": 24, "headline": "24/24", "user_added": 18}` | `curl -s http://127.0.0.1:8000/api/catalog/skills` |

> 两个会话口径都留着,升级后都要复查:
> · **30** 是对话正文(具名卷 `hunter_opencode_data` 里的 `opencode-local.db`)
> · **93** 是 `session_id ↔ user_id` 的归属映射,在 postgres 里,和卷无关
> 2026-09-07 那次事故正是「93 完好、30 归零」,所以只看一个数会漏。
>
> `/skill/refresh` 的 25 比 `/api/catalog/skills` 的 24 多一个,是 opencode 自带的内置 skill,不是错位。

## 6 · 拉取耗时(瘦身前)

| 从哪拉 | 耗时 | 说明 |
|---|---|---|
| agentpit(美国中部) | **123 秒** | `docker pull ghcr.io/agentpit-io/hunter-opencode:dev`,日志里 5 层全是 `Pull complete`、0 层 `Already exists`,是真冷拉 |
| fin-r1(新加坡) | **未测** | 机器上已有这份镜像;删掉它才能冷测,而红线规定新版本验证通过前不得删除旧镜像(回滚要用) |
| 国内 | **未测** | 没有国内测试机 |

测完已在 agentpit 上 `docker rmi` 掉这份 `:dev`,把空间还回去。
