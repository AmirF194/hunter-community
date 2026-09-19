# M1 · 子任务 A · 镜像自包含与 compose 拆分

> 交付说明 · 2026-09-17 · 分支 `m1/a-images`
> 上游依据:[`design.md`](./design.md) 第 3.1 节与第十节 · [`R0-预研结论.md`](./R0-预研结论.md) 第四、五节

## 零、一句话

四个自家服务全部改成自包含的预构建镜像,`docker-compose.yml` 里**一个 `build:` 都没有、
一处仓库文件 bind mount 都没有**,`git clone` 之后直接 `docker compose up -d` 就能起;
原来的 build 与全部挂载原样搬进新的 `docker-compose.dev.yml` 给开发者用。

---

## 一、改了哪些文件

| 文件 | 动作 | 说明 |
|---|---|---|
| `deploy/opencode.Dockerfile` | 新增 | `FROM hunter-opencode:1.18.12-slim.1`,把原来 9 处 bind mount 的内容 COPY 进来 |
| `deploy/llm-shim.Dockerfile` | 新增 | `FROM python:3.12-alpine` + `COPY scripts/llm-shim /app` + HEALTHCHECK |
| `apps/api/Dockerfile` | 改 | 构建上下文改到仓库根;自带 `skills/` `data/` `db/migrations/`;`CMD` 换成 `/app/boot.sh` |
| `.dockerignore` | 改 | 承接原 `apps/api/.dockerignore` 的排除项(加 `apps/api/` 前缀) |
| `apps/api/.dockerignore` | 改 | 内容换成一段「本文件已失效」的说明 |
| `docker-compose.yml` | 改 | 只用预构建镜像;删掉全部 `build:` 与仓库挂载;新增三个具名卷 |
| `docker-compose.dev.yml` | 新增 | 开发覆盖:`build:` 段 + 全部 bind mount |
| `.env.example` | 改 | 新增 `HUNTER_VERSION` / `HUNTER_REGISTRY`;`JWT_SECRET` 改为留空;大模型三项改为可留空 |
| `README.md` / `README_EN.md` / `docs/01-getting-started.md` | 改 | 启动命令、升级命令、开发者路径、FAQ |
| `.github/workflows/docker-publish.yml` | 改 | 矩阵 4 镜像 × 2 平台,原生 arm64 runner,push-by-digest → merge manifest |
| `scripts/opencode/entrypoint.sh` | 改 | 只加一件事:`/home/hunter/.local` 可写自检 |
| `docs/setup-wizard/M1-A-镜像与compose.md` | 新增 | 本文件 |

**没动**(其他并行子任务的地盘):`scripts/opencode/gen-config.py`、`scripts/llm-shim/shim.py`、
`apps/api/boot.sh`、`apps/api/app/**`、`db/**`、`.github/workflows/ci.yml`、
`.github/workflows/e2e-compose.yml`。

---

## 二、每个决策的理由

### 2.1 api 镜像:为什么「改构建上下文」而不是 additional context

api 镜像要自带 `skills/`、`data/`、`db/migrations/`,而它们都在 `apps/api` 外面,
Dockerfile 不允许 COPY 上下文之外的路径。两条路:

| 做法 | 写法 | 为什么没选 / 选它 |
|---|---|---|
| additional build context | compose 的 `build.additional_contexts` + `COPY --from=skills . …` | 需要 **Compose v2.17+ / BuildKit 较新版本**,而各平台(1Panel、Sealos、老版 Docker Desktop、国内云的内置 compose)版本参差;这是「一键部署」场景,不能要求用户先升级 compose。而且 `docker build` 命令行要写 `--build-context skills=./skills`,四个镜像的构建命令各不相同,CI 与本地容易漂 |
| **改构建上下文到仓库根** ✅ | `docker build -f apps/api/Dockerfile -t … .` | **所有 docker / compose / buildx 版本都支持**,没有任何版本门槛;构建命令与 opencode / llm-shim 完全一致(都是 `-f <path> .`) |

代价是上下文从 5.2 MB 变成 21 MB(整个仓库),以及**生效的忽略文件从 `apps/api/.dockerignore`
变成仓库根的 `.dockerignore`** —— docker 只读 `<构建上下文>/.dockerignore`。
这一点不报错:镜像照样构建成功,只是多装(tests)或少装(被误排的 `skills/`)文件。
所以原排除项按 `apps/api/` 前缀搬到了根,`apps/api/.dockerignore` 留一段说明。

> 为什么不把 `apps/api/.dockerignore` 直接删掉:删了之后,下一个人看到 api 目录没有
> `.dockerignore`,很可能顺手再建一个、再写一遍规则,然后发现「改了没用」。留一行说明最省事。

上下文变大**没有让镜像变大** —— 只 COPY 明确列出的路径(见第三节实测:压缩后 +64 KB)。

### 2.2 为什么默认文件里一个 `build:` 都不留

compose 在同时看到 `image:` 和 `build:` 时,**本地没有该镜像就会去构建而不是拉取**。
这不是配置错误,是 compose 的既定行为(`pull_policy` 的默认值 `missing` 对
buildable service 意味着「构建」)。

后果不是报错,是**云平台和新用户会莫名其妙开始编译 Next.js** —— 十几分钟起、
runner / 小内存机器上常常直接 OOM 或超时,而他们只是想跑起来。
「拉镜像就能跑」这条,只有在默认文件里一个 `build:` 都没有时才成立。

`pull_policy: always` 能改掉这个行为,但那又会让每次 `up` 都去 registry 查一遍;
而且「文件里写着 build 却永远不构建」本身就是个陷阱。所以选择彻底分家:
默认文件只有 `image:`,开发文件才有 `build:`。

**开发文件里 `image:` 被改成 `<名>:dev` 本地标签**:不这么做的话,本地构建出来的东西会
顶着 `ghcr.io/…:1.1.0-rc1` 这个正式标签躺在本机,下次用默认文件启动时 compose 发现
「镜像已存在」就不去拉了 —— 你会在默认模式下跑着自己的半成品构建,而且看不出任何异常。

### 2.3 为什么用原生 arm64 runner 而不是 QEMU

`docker/setup-qemu-action` + `platforms: linux/amd64,linux/arm64` 是最省事的写法,
但 **web 的 Next.js 构建和 api 的 pip 编译在 QEMU 用户态模拟下会慢一个数量级**:
Next 构建本身在 amd64 上就要几分钟,模拟下几十分钟起,常常直接撞上 job 超时;
api 那边 `build-essential` + 就地编译 wheel 同理。

本仓是**公开仓库**,GitHub 免费提供原生 arm64 runner(`ubuntu-24.04-arm`),
所以照官方文档的「Distribute build across multiple runners」模式写:

```
build  (4 镜像 × 2 平台 = 8 个并行 job,runs-on 按平台选)
   └─ outputs: type=image,push-by-digest=true,name-canonical=true,push=true
   └─ digest 以「文件名」形式存成 artifact(digests-<镜像>-<平台>)
merge  (每个镜像一个 job)
   └─ docker buildx imagetools create -t <tag>… <镜像>@sha256:<digest>…
```

⚠️ **build job 不能打 tag**:两个平台同时往同一个 tag 推会互相覆盖,
最后 manifest 里只剩后到的那个架构 —— 而且这不报错,`docker pull` 在另一个架构上
才会说「no matching manifest」。所以只推 blob,tag 统一由 merge job 建。

标签规则保持现状(`type=ref,event=branch` / `type=ref,event=tag` /
`type=sha,prefix=sha-` / `latest` 仅默认分支),**额外加了一条
`type=semver,pattern={{version}}`**:`type=ref,event=tag` 产出的是原样的 `v1.1.0-rc1`,
而 `docker-compose.yml` 里 `HUNTER_VERSION` 的默认值是不带 `v` 的 `1.1.0-rc1`。
少了这条,打完 git tag 之后用户 `docker compose up -d` 会拉不到镜像。两个 tag 都推,指向同一个 manifest。

### 2.4 opencode 包装镜像继续 `FROM hunter-opencode:1.18.12-slim.1`

R0 预研结论第七节:SKILL 同步用 opencode 原生 `skills.urls` 就够,huntercode 无改动,
**不需要发 `hc-v1.18.12-slim.2`**。所以包装层的 FROM 不动。

所有 `COPY` 都带 `--chown=1001:1001`:基础镜像 `USER=hunter`(uid 1001)、
`WORKDIR=/opt/opencode-workspace`。不带的话文件属于 root,容器以 1001 跑,
`gen-config.py` 读 `/opt/hunter-mcp` 会 Permission denied —— 而这个失败发生在启动阶段,
表现是容器反复 `Restarting`,不是一句清楚的报错。

### 2.5 postgres 的 initdb 挂载:两种模式都删掉了

`./db/migrations:/docker-entrypoint-initdb.d:ro` **默认文件与开发文件里都没有**。

默认文件必须删(仓内铁律:那个目录只在数据卷第一次初始化时执行,已有部署里新加的
`.sql` 永远跑不到)。开发文件里也没接回来,是刻意的:只在开发模式接回来的话,
开发环境会走一条线上不存在的路径,而**迁移恰恰是最需要「开发跑的就是线上跑的」那一条**。
迁移统一由 api 启动时做(`boot.sh` → `python -m app.migrate`,子任务 B)。

### 2.6 卷的分工

| 卷 | 谁写 | 为什么不是 bind mount |
|---|---|---|
| `hunter_user_skills` → api `/opt/hunter-user-skills` | api 可写 | 原来是 `./user-skills`;云平台上没有仓库目录 |
| `hunter_packages` → api `/opt/hunter-packages` | api 可写 | 原来是 `./data-packages`;同上 |
| `hunter_secrets` → api rw / opencode **ro** | 子任务 C | 本地 compose 下两个容器共享同一把自动生成密钥的唯一途径(云平台靠模板注入环境变量)。本子任务只把卷与挂载加进 compose,**不写生成逻辑** |

opencode **不再挂 user-skills**(R0 第二节:改由 api 的导出接口 + opencode 原生
`skills.urls` 同步,子任务 D)。开发模式下仍然挂 `./user-skills:/home/hunter/.config/opencode/skills:ro`,
本地开发保持现状,免得一边开发一边还要等同步。

### 2.7 entrypoint 的可写自检

R0 第四节实测:Docker 具名卷首次挂载会把镜像里 `/home/hunter/.local` 的内容与属主
(1001:1001)一起拷进卷,所以 Docker 语义的平台开箱可写;**K8s 的 PVC 不拷贝**,
卷根属主是平台给的(实测 `1000:1003` 或 `0:0`),容器以 1001 跑就写不进去。

原来的失败路径是「插件 mkdir 报 EACCES → 进程退出 → 重启循环」,日志里只有一句
英文 `permission denied`,看不出是卷属主的问题。现在启动前自检,不可写就打印属主与
处理办法后 `exit 1`。**这个文件的其它部分没动**(gen-config 调用、opencode 二进制探测
是子任务 C 的地盘)。

---

## 三、实测(命令与真实输出摘要)

> 本机是共享服务器,所有 `docker build` 前面都加了 `nice -n 10 ionice -c 3`。

### 3.1 构建三个新 / 改的镜像

```bash
nice -n 10 ionice -c 3 docker build -f deploy/llm-shim.Dockerfile -t m1a-shim:test .
nice -n 10 ionice -c 3 docker build -f deploy/opencode.Dockerfile -t m1a-opencode:test .
nice -n 10 ionice -c 3 docker build -f apps/api/Dockerfile      -t m1a-api:test .
```

| 镜像 | 耗时 | DISK USAGE | CONTENT SIZE(压缩后) | 对照 |
|---|---|---|---|---|
| `m1a-shim:test` | **1 秒** | 82.9 MB | 20.6 MB | 基础镜像 `python:3.12-alpine` 83.5 MB / 21.3 MB |
| `m1a-opencode:test` | **2 秒** | 619 MB | 153 MB | 基础镜像 `hunter-opencode:1.18.12-slim.1` 618 MB / 153 MB |
| `m1a-api:test` | **101 秒** | **909 MB** | 218 MB | 改造前 `ghcr.io/agentpit-io/hunter-community-api:latest` **909 MB** / 218 MB |

> 耗时说明:三次构建**都命中了本机的 layer 缓存**(基础镜像已在本地;api 的 builder 阶段
> apt + venv + pip 未改动故整层复用)。api 的 101 秒里 24 秒是 export/unpack。
> 冷构建(无缓存)会明显更久,本次没测 —— 不编数字。

**体积结论:上下文从 5.2 MB 变成 21 MB,镜像没变大。** `docker image inspect … --format '{{.Size}}'`:
api 改造后 `217,709,911` 对改造前 `217,645,518`,**+64 KB**(就是 skills + data + migrations 的压缩量);
opencode `152,990,439` 对基础镜像 `152,923,316`,**+67 KB**。

### 3.2 opencode 镜像内文件与属主

```bash
docker run --rm --entrypoint sh m1a-opencode:test -c \
  'ls -la /opt/hunter-boot /opt/hunter-mcp /opt/opencode-workspace/.opencode/skills; ls -ln /opt/opencode-workspace/mcp/ | head'
```

```
/opt/hunter-boot:          entrypoint.sh(-rwxr-xr-x) · gen-config.py · HUNTER-AGENT.md   全部 hunter hunter
/opt/hunter-mcp:           hunter_capability_mcp.py · hunter_user_mcp.py · screener_mcp.py
                           · uzi_mcp.py · watchlist_mcp.py · plugins/                     全部 hunter hunter
/opt/opencode-workspace/.opencode/skills:
                           deep_analysis · investor_panel · lhb_analyzer · risk_profile
                           · trap_detector · uzi                                          全部 hunter hunter
/opt/opencode-workspace/mcp/(ls -ln,看数字属主):
  -rw-r--r-- 1 1001 1001  5234 Sep 16 17:57 README.md            ← 镜像自带
  -rw-r--r-- 1 1001 1001 10081 Sep 17 16:52 hunter_user_mcp.py   ← 已覆盖(10081 ≠ 镜像的 9233)
  -rw-r--r-- 1 1001 1001  6202 Sep 16 17:57 portfolio_mcp.py     ← 镜像自带
  -rw-r--r-- 1 1001 1001  9964 Sep 16 17:57 screener_mcp.py      ← 镜像自带(与仓库副本逐字节同大小)
  -rw-r--r-- 1 1001 1001 10602 Sep 17 16:52 uzi_mcp.py           ← 已覆盖(10602 ≠ 9694)
  -rw-r--r-- 1 1001 1001 11329 Sep 17 16:52 watchlist_mcp.py     ← 已覆盖
```

属主全部 `1001:1001`;三个覆盖文件按大小与时间戳都能看出确实被换掉了。
插件目录同样核对过:`hunter-lang.ts` 5938(镜像 6235)、`hunter-mcp-context.ts` 8443(镜像 7844)。

### 3.3 api 镜像内容

```bash
docker run --rm --entrypoint sh m1a-api:test -c \
  'ls /opt/hunter-skills /opt/hunter-data /opt/hunter-migrations | head -30; ls -l /app/boot.sh'
```

```
/opt/hunter-data:        hk_master.csv · recommended-skills.json
/opt/hunter-migrations:  0001_local_users.sql … 0021_screen_quota_usage.sql(共 22 个)
/opt/hunter-skills:      deep_analysis · investor_panel · lhb_analyzer · risk_profile · trap_detector · uzi
-rwxr-xr-x 1 root root 1250 Sep 17 16:52 /app/boot.sh          ← 执行位在
```

另核对镜像元数据:`CMD=["/app/boot.sh"]`,HEALTHCHECK 仍是
`curl -fsS http://127.0.0.1:8000/api/health`;`/app/tests` 不存在(`ls` 报
`No such file or directory`),`conftest.py` / `pytest.ini` 也已被根 `.dockerignore` 排除。

### 3.4 compose 解析(不建 `.env` 也能跑)

工作树里**没有 `.env`**,另外显式用 `--env-file /dev/null` 再确认一次:

```bash
docker compose --env-file /dev/null -f docker-compose.yml config                              # 退出码 0
docker compose --env-file /dev/null -f docker-compose.yml -f docker-compose.dev.yml config    # 退出码 0
```

默认组合解析出的镜像:

```
ghcr.io/agentpit-io/hunter-community-api:1.1.0-rc1
ghcr.io/agentpit-io/hunter-community-web:1.1.0-rc1
ghcr.io/agentpit-io/hunter-community-opencode:1.1.0-rc1
ghcr.io/agentpit-io/hunter-community-llm-shim:1.1.0-rc1
postgres:16-alpine · redis:7-alpine
```

dev 组合下 16 处 bind 全部在位,且**同目标路径的具名卷被 bind 正确覆盖、没有重复挂载**
(compose 合并 volumes 时按 target 去重):`api` 的 `/opt/hunter-user-skills` 与
`/opt/hunter-packages` 在 dev 下是 bind,`hunter_secrets` 仍是卷。

### 3.5 默认文件里没有任何仓库 bind mount

```bash
docker compose -f docker-compose.yml config | grep -c "source: /mnt"
# 0
```

### 3.6 workflow 语法自检

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/docker-publish.yml'))"
# 无输出 = 通过;另打印 jobs = ['build', 'merge']、矩阵镜像 4 个、平台 2 个
```

### 3.7 额外做的两条(不在清单里,但值得记)

**入口自检真的会触发**。用一个 root 属主的空目录模拟 K8s PVC:

```bash
mkdir /tmp/m1a-pvc && sudo chown 0:0 /tmp/m1a-pvc
docker run --rm -v /tmp/m1a-pvc:/home/hunter/.local m1a-opencode:test
```
```
[boot] ❌ 会话数据目录 /home/hunter/.local 不可写(当前属主 0:0,容器以 uid 1001 运行)。
[boot]    Docker 具名卷不会出这个问题;K8s / 云平台的 PVC 需要把卷属主设成 1001
[boot]    (securityContext.fsGroup: 1001)或加一个 initContainer 执行 chown。
退出码 1
```

**具名卷场景自检通过**(`docker run --rm -v <新建空卷>:/home/hunter/.local m1a-opencode:test`
直接走到了下一步 `gen-config`,报的是 `LLM_* 未设置` —— 那是子任务 C 要改的地方)。
这也顺带验证了 R0 第四节那条结论:镜像里 `/home/hunter/.local` 存在且属主 1001,
空的具名卷首次挂载会继承它。

---

## 四、遗留问题 / 需要别人接手的

1. **`.github/workflows/e2e-compose.yml` 现在会挂** —— 这是本轮最需要先处理的一条。
   它里面有两步:
   ```
   docker compose pull --ignore-buildable
   docker compose build api web
   ```
   默认 compose 已经没有 `build:` 段,`docker compose build api web` 会失败。
   接手的人(该文件是别的子任务的地盘,我没动)需要改成
   `docker compose -f docker-compose.yml -f docker-compose.dev.yml build api web`
   并在后续所有 `docker compose …` 调用上带同样的 `-f` 组合;
   它写 `.env` 那段里追加 `JWT_SECRET` 的逻辑可以保留(仍然有效),
   但注释里「JWT_SECRET 是 compose 里的必填项(`:?` 语法)」已经不成立了。

2. **`1.1.0-rc1` 这个 tag 在 GHCR 上还不存在。** 默认 compose 现在指向它,
   所以在 `docker-publish.yml` 跑过一次并打出这个 tag 之前,
   `docker compose up -d` 会拉取失败。发 tag 的顺序:先合分支 → 打 `v1.1.0-rc1` →
   等 workflow 的 merge job 绿 → 再对外说「clone 就能跑」。

3. **arm64 分支从未真正构建过。** `ubuntu-24.04-arm` 上 api 的 pip 依赖
   (psycopg2-binary / numpy / pandas 等)是否都有 arm64 wheel、没有的要就地编译多久,
   本地无法验证(本机是 amd64)。第一次 workflow 跑起来要盯一眼 build job 的耗时,
   必要时给 arm64 单独加超时或预编译。

4. **`gen-config.py` 仍然在三个 `LLM_*` 缺一个时拒绝启动**,所以「留空也能起来」
   目前只对 api / web / postgres / redis 成立,opencode 会重启循环、llm-shim 同理。
   这是子任务 C 的范围;`.env.example` 与 README 的措辞已经按「M1 起服务可以不配大模型
   正常启动」写,**在子任务 C 合入之前,那句话还不成立** —— 合分支时注意顺序。

5. **`scripts/opencode/entrypoint.sh` 里有一段过时注释**(「这个脚本是 bind mount 进容器的」),
   现在它是 COPY 进镜像的。没改是因为那一段紧挨着 opencode 二进制探测逻辑,
   属于子任务 C 的改动范围,不想制造冲突。请子任务 C 顺手更正。

6. **没有真的 `up`。** 按分工,起预发栈是统一做的;本子任务只做到 `config` 解析与
   镜像内容核对。六个服务能不能一起健康起来,要等预发栈验证。

7. **`OPENCODE_REGISTRY` / `OPENCODE_TAG` 变成了死变量**(compose 不再读)。
   `.env.example` 里已注释掉并写明原因;老用户 `.env` 里留着它们无害,但改了不会有任何效果。
   要换基础镜像版本,改 `deploy/opencode.Dockerfile` 的 `FROM`。

8. **`NEXT_PUBLIC_API_URL` 在默认部署里是个死变量。** 它是**构建期**烘进前端产物的,
   官方预构建镜像烘的是空值,用户改 `.env` 不会有任何效果。
   查证后确认**这不是缺口**:空值 = 同源相对路径 `/api/*`,而 web 自己有一条
   catch-all BFF(`apps/web/app/api/[...path]/route.ts`)把 `/api/*` 原样转发到 api 容器,
   所有页面的写法都是 `process.env.NEXT_PUBLIC_API_URL || ''`,没有反代也能通。
   已把 `.env.example` 的默认值改成空并写明「要改必须自己重新构建 web」——
   原来那句「直接 docker compose up(没有反代)时必须填成绝对地址」自从加了 BFF
   之后就已经过时了。真正想彻底解决(运行时可配)要改 web 的取值方式,不在本轮范围。
