# 一键部署模板 + 首启向导 · 总进度

目标：从 `git clone` 到第一次对话，**需要编辑的文件 = 0**；云平台点一个按钮就能部署。

- 权威设计方案：[`design.md`](./design.md)（第十节已按 R0 实测回填）
- 预研原始数据：[`R0-预研结论.md`](./R0-预研结论.md)

## 里程碑

| 里程碑 | 状态 | 完成日期 | 成果文档 | 主要提交 |
|---|---|---|---|---|
| **R0 · 预研** | ✅ 完成 | 2026-09-18 | [R0-预研结论.md](./R0-预研结论.md) | 见下方「R0」 |
| **M1 · 镜像自包含与配置入库** | ✅ 完成 | 2026-09-18 | [M1-成果与测试报告.md](./M1-成果与测试报告.md) | `faa3891`（合并）· 子任务 [A](./M1-A-镜像与compose.md) [B](./M1-B-自动迁移.md) [C](./M1-C-配置与密钥.md) [D](./M1-D-SKILL同步.md) |
| **M2 · 首启向导** | ⏳ 未开始 | — | — | — |
| **M3 · 第一批模板（Zeabur / Sealos）** | ⏳ 未开始 | — | — | — |
| **M4 · 第二批模板与发布（Railway / 1Panel）** | ⏳ 未开始 | — | — | — |

## R0 关键结论速查

| 问题 | 结论 |
|---|---|
| 向导保存后怎么让 opencode 生效 | `PATCH /global/config`（**不是** `PATCH /config`，后者写的文件没人读）。端到端 7.4～7.9 秒 |
| 用户装的 SKILL 怎么让模型看见 | opencode 原生 `skills.urls` + `POST /skill/refresh`，0.07 秒。**不需要写 huntercode 插件** |
| 需要多大内存 | 空闲 1.17 GB，深度分析 + 全市场扫描并发峰值 1.27 GB。最低 2 GB、推荐 4 GB |
| 云平台新卷 opencode 写得进去吗 | Docker 卷可以；K8s PVC 不行，Sealos 模板必须 `fsGroup: 1001` |
| GHCR 能匿名拉吗 | agentpit / fin-r1 都可以。api 与 web 目前**只有 amd64**，M1 补 arm64。国内平台未测 |

## M1 关键结论速查

| 问题 | 结论 |
|---|---|
| 从零到 6 服务健康要改几个文件 | **0 个**（`git clone` → `docker compose up -d`）。大模型仍需配置，图形化向导是 M2 |
| 默认 compose 里还有仓库挂载吗 | 一处都没有；`build:` 段也全部移到 `docker-compose.dev.yml` |
| 大模型换配置要重启吗 | 不用。`apply_llm()` 走 `PATCH /global/config`，实测端到端 **9.2 秒** |
| 老部署升级会不会缺表 | 不会。api 启动时两阶段迁移（`init_db()` → 增量），演示站实测 23/23 补齐 |
| 老用户升级要做什么 | 跑一次 `bash scripts/migrate-volumes.sh`（把 `user-skills/` `data-packages/` 搬进新卷），否则装过的 SKILL 会从界面消失 |
| 未配置大模型时会发生什么 | opencode 照常启动、**绝不回落 OpenCode Zen**；发消息 5 秒内收到中文的「大模型尚未配置」 |

### M1 顺带修掉的三个线上隐患

1. **`db/migrations` 里 7 个文件一直在静默失败** —— 它们依赖的基础表由 `init_db()` 建，而 postgres 的 initdb 在 api 之前就跑了它们。
2. **`0010` 会让「手工补跑过迁移」的库升级后起不来** —— 演示站正是这种库，实测反证：修复前退出码 3、修复后 0。
3. **18 处硬编码把开源用户的数据发到我们自己的演示站网关** —— `LLM_BASE_URL` 8 处 + `ONE_API_BASE_URL` 10 处，全部清掉。
