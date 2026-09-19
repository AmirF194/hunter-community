# 01 · 决策记录 · 为什么走「fork 源码编译单文件」

> 对应执行方案第一、二节。这份文档解释**为什么这么改**,不是改动清单(那个在 CHANGELOG 和各文件注释里)。

## 1 · 先把事实查清楚

原计划里几处「需执行者确认」的,实查结果如下 —— 有三处和原计划写的不一样,**按实查结果办**。

| 项 | 实查结果 | 对方案的影响 |
|---|---|---|
| 镜像构建源 | 私仓 `agentpit-io/huntercode`,默认分支 `dev`,Dockerfile 在 `packages/hunter-server/Dockerfile`,CI 是 `.github/workflows/hunter-community-publish.yml`(原来只推 amd64) | 原计划写的路径 `huntercode/docker/Dockerfile.opencode` **不存在**,改的是上面这个文件 |
| 当前镜像 | 7.56 GB。做法是整个 monorepo `bun install` 之后 `COPY --from=deps /build ./`,再 `bun run packages/opencode/src/index.ts` 跑源码 | 体积来自整仓源码 + 全量 node_modules,再被 `chown -R` 复制一遍 |
| opencode 版本 | `packages/opencode/package.json` = **1.18.12** | 新镜像标签定为 `1.18.12-slim.1` |
| 内核有没有改过 | **有**:提交 `9f840781a5 feat(skill): add POST /skill/refresh`,而 hunter-community 的 `apps/api/app/services/opencode_admin.py` 正在调它 | 决定性的一条,见下节 |
| 插件依赖 | 6 个 `plugins/*.ts` 只有 `import type { Plugin } from "@opencode-ai/plugin"`(编译期擦除)和 Node 内置模块 | 单文件二进制可以直接加载它们,不需要 node_modules |
| 镜像内用户 | `hunter` uid **1001**,会话具名卷挂在 `/home/hunter/.local` | 原计划写的 uid 1000 **不能用** —— 改了会让升级后的容器读不了自己的对话数据 |
| 容器内路径 | `/opt/opencode-workspace/{plugins,mcp,.opencode/opencode.jsonc}`,`OPENCODE_CONFIG_DIR=/opt/opencode-workspace` | compose 往这些路径 bind mount,新镜像必须保持同样布局 |
| 镜像可见性 | GHCR 上 `hunter-opencode` 匿名可拉 | 不用改可见性 |
| Docker Hub / 阿里云 ACR | 没有账号与凭据 | 本次不做,compose 留 `OPENCODE_REGISTRY` 变量,记为待办 |

## 2 · 三条路,为什么选 B

| | A · 换官方预编译二进制 | **B · fork 源码编译单文件** | C · 只装生产依赖 + 删源码 |
|---|---|---|---|
| 做法 | 直接下 `opencode-linux-x64` 发行包 | 用 fork 自己的源码 `bun build --compile` | `bun install --production`,删掉 packages/ 里用不到的包 |
| 体积 | 最小 | 小 | 中(目标 ≤ 3 GB) |
| **能不能保住 `/skill/refresh`** | **不能** | 能 | 能 |
| 风险 | 功能缺失,而且是**静默**缺失 | 编译期风险(动态 import、原生模块) | 删多了会在运行期才炸 |

**A 直接出局**:`POST /skill/refresh` 是这个 fork 自己加的路由,官方二进制里没有。而 api 侧 `opencode_admin.py` 在用户新建 / 编辑 SKILL 之后靠它让 opencode 重扫目录 —— 换成官方二进制,这个调用会 404,表现是「UI 里存了 SKILL,但对话里那个能力压根不存在」,而且没有任何报错。这类静默失效最难查,不接受。

**选 B**。C 作为 B 编不出来时的退路,本次没有用到。

## 3 · B 具体怎么做的

- 编译脚本 `packages/opencode/script/hunter-server-build.ts`,从官方的 `script/build.ts` 派生,defines / bun 插件 / compile 选项逐条对齐,只有三点差异:
  1. 只编 `linux-$TARGETARCH` 一个目标(官方那份编 12 个)。交叉编译靠 bun 自己的 `bun-linux-arm64` target,所以 arm64 镜像也能在 amd64 构建机上编出来,不用 QEMU 模拟整个 `bun install`。
  2. **不内嵌 Web UI**:hunter-community 有自己的前端(`apps/web`),而 `src/server/shared/ui.ts` 那句 `import("opencode-web-ui.gen.ts")` 后面带 `.catch(() => null)`,缺了不会崩。省掉 `packages/app` 的 vite 构建。
  3. 产物固定在 `packages/opencode/dist/opencode`,方便 Dockerfile `COPY`。
- 脚本放在 `packages/opencode/script/` 而不是 `packages/hunter-server/`:后者不是 workspace 成员,从那里 `import @opentui/solid/bun-plugin` 解析不到(bun 按**文件所在目录**往上找 node_modules)。第一次就是这么失败的。
- 版本号用 `OPENCODE_VERSION=1.18.12` 环境变量给死。不给的话 `@opencode-ai/script` 会去读 git 分支、查 npm registry,而构建上下文里没有 `.git`。
- 运行层基底选 `python:3.11-slim` 而不是 alpine:MCP 子进程需要现成的 python3,而 `pydantic-core`(mcp 的依赖)的 musl wheel 供应比 glibc 差。二进制也就相应编成 glibc 目标。
- `pip install --target` 单独一层装 `mcp>=1,<2` 和 `httpx`。**这一层不能跑在构建机架构上** —— `pydantic-core` 是编译过的 wheel,必须是目标架构的。

## 4 · 两个必须保住的兼容性

`scripts/opencode/entrypoint.sh` 是 **bind mount** 进容器的(compose 里 `./scripts/opencode:/opt/hunter-boot:ro`),所以「脚本」和「镜像」是两个独立更新的东西,两种错配都会真实发生:

| 组合 | 怎么兜住 |
|---|---|
| **镜像新 + 脚本旧**(用户 `docker compose pull` 了但没更新代码) | 镜像里放了一个叫 `bun` 的垫片脚本:收到 `bun run packages/opencode/src/index.ts <args...>` 就转成 `exec opencode <args...>`;其他用法一律明确报错说明镜像已改为单文件运行,不做糊弄式兜底 |
| **脚本新 + 镜像旧**(用户更新了代码但 `OPENCODE_TAG` 还钉在老标签) | 新 entrypoint 先 `command -v opencode`,有就用二进制,没有就回落 `exec bun run packages/opencode/src/index.ts serve …` |

两种组合都在演示站实测过,见 `02-e2e-report.md` 用例 10。

## 5 · 顺带修掉的三处「运行时打补丁」

旧 `entrypoint.sh` 里有三段在容器启动时现改文件的代码,每段都对应一个镜像里的缺陷。既然镜像重做了,就在源头修掉:

| 旧做法 | 新做法 |
|---|---|
| 检测到 mcp 是 2.x 就 `pip install --user "mcp<2"` | 镜像构建时就锁 `mcp>=1,<2`,不再需要运行时补装 |
| `sed -i 's/timeout=25.0/timeout=120.0/' uzi_mcp.py` | 改成读环境变量 `UZI_HTTP_TIMEOUT`(默认 170) |
| `sed -i 's/"timeout": 30000/"timeout": 180000/' opencode.jsonc` | huntercode 的 `packages/hunter-server/opencode.jsonc` 源头就写 180000;额外注册的两个 MCP 支持 `HUNTER_MCP_TIMEOUT_MS` 覆盖 |

结果是 entrypoint 从 40 多行有效命令降到 **7 行**。这不只是好看:那三段 sed 依赖「文件可写」和「字符串恰好匹配」,任何一边变了就静默失效,而失效的症状是「深度分析说服务不可用」,根本指不到 entrypoint。

## 6 · 其余决策

- **版本号**:hunter-community 发 `v1.0.1`(v1.0.0 已发布,原计划写的 `v1.0.0-rc2` 不对);opencode 镜像打 git 标签 `hc-v1.18.12-slim.1` → 镜像标签 `1.18.12-slim.1`,compose 默认锁死这个具体版本而不是 `latest`。
- **多仓分发**:只发 GHCR。Docker Hub / 阿里云 ACR 没有凭据,留 `OPENCODE_REGISTRY` 变量和待办。
- **api 镜像**:保持 Python **3.11**(原文件如此,不趁机升级),改多阶段,OCR(tesseract 中英文)保留。
- **冒烟用例**:原计划里的 `uzi_dcf`、对话内「预测茅台走势」在 8/19 撤架后已不存在,换成现存功能,见 `02-e2e-report.md`。
