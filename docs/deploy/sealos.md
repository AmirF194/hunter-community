# 在 Sealos 上部署 HunterCode

适合谁：国内用户、希望按量付费、不想自己维护 K8s。

> ⚠️ **本模板尚未在 Sealos 上实测过**（写模板时没有账号）。字段按
> `labring-actions/templates` 仓库的规范与官方 `example.md` 编写，
> 15 个标准 K8s 资源已过 `kubeconform -strict`（K8s 1.30 官方 schema），
> 并在本机用「等价 compose」从空卷完整跑过一遍（向导 + 真实对话 + 深度分析 + 重启）。
> 真实平台上的差异见文末「已知待核实」。

## 一、部署

模板还没上架到 Sealos 应用商店（上架步骤见文末）。在上架之前，可以：

1. 打开 Sealos 的「应用管理 / 模板市场」，选择**从 YAML 部署**；
2. 粘贴 [`deploy/sealos/index.yaml`](../../deploy/sealos/index.yaml) 的内容。

表单上有三项：

| 字段 | 说明 |
|---|---|
| **Setup token** | 首启向导第 0 步要填的初始化口令。**已自动生成，提交前先复制下来** |
| **Session volume size** | 对话与会话的磁盘（GiB），默认 5 |
| **Data volume size** | 你装的 SKILL 与导入的数据包（GiB），默认 3 |

**不需要**在部署前准备大模型配置。

## 二、初始化口令在哪看

**部署表单里那个自动填好的 Setup token 就是**，提交前复制下来。

如果已经提交了：Sealos 控制台 → 应用详情 → `<应用名>-api` 这个工作负载 →
环境变量 → `HUNTER_SETUP_TOKEN`。

这道口令防的是：从部署完成到你第一次打开页面之间，别人抢先进来把大模型
配置成他自己的。错 5 次锁 15 分钟；重启 api 工作负载可解除锁定（口令不变）。

## 三、首启向导（五步）

打开 `https://<应用域名>`，会自动进入向导。步骤与耗时含义同
[Zeabur 那篇](./zeabur.md#三首启向导五步)，不再重复。要点：

- 第 3 步的三项检测**由 api 容器发起**，走的是和 opencode 同一条网络路径，
  所以测得通就是真的通；**测不通不让保存**。
- 第 5 步配置写进数据库并**热生效，不重启 Pod**。
- 向导之后注册第一个账号，它自动成为管理员。

全程**不需要编辑任何文件**。

## 四、资源建议

来自 R0 实测（六个容器整栈）：

| 场景 | 实测内存 |
|---|---|
| 空闲 60 秒 | 1171 MB |
| **深度分析 + 全市场扫描并发（峰值）** | **1271 MB** |

模板里已按实测写好每个工作负载的 requests / limits：

| 工作负载 | requests | limits | 实测占用 |
|---|---|---|---|
| opencode | 200m / 768Mi | 2000m / 1536Mi | 869 MB（常驻，几乎与负载无关） |
| web | 100m / 192Mi | 1000m / 512Mi | 139 MB |
| api | 100m / 256Mi | 1000m / 1024Mi | 105 → 203 MB（随负载涨） |
| llm-shim | 10m / 32Mi | 500m / 256Mi | 15.6 MB |
| pg / redis（KubeBlocks） | 100m / 102Mi | 1000m / 1024Mi | 34 / 10 MB |

整体最低 2 核 2 GB、推荐 2 核 4 GB；磁盘 ≥ 10 GB。

## 五、数据放在哪 · 怎么备份

| 内容 | 位置 |
|---|---|
| 自选股、组合、研究台、配置、**大模型 key 密文** | `<应用名>-pg` 的 KubeBlocks 集群 |
| 对话正文与会话 | `<应用名>-opencode` 的 PVC，挂在 `/home/hunter/.local` |
| 你装的 SKILL、导入的数据包 | `<应用名>-api` 的两个 PVC |

> ⚠️ postgres 里的 `chat_session_owner` 表**不是对话备份** —— 它只存
> session_id ↔ user_id 的归属映射，对话正文一个字都不在里面。

备份做法：

- **数据库**：用 Sealos 数据库面板自带的备份（KubeBlocks 原生支持）。
- **对话正文**：opencode 的 sqlite 是 WAL 模式，直接拷主库文件可能读不到最新数据。
  进 Pod 终端取一致性快照后 `kubectl cp` 出来：

  ```bash
  bun -e "new (require('bun:sqlite').Database)(process.env.HOME+'/.local/share/opencode/opencode-local.db',{readonly:true}).exec(\"VACUUM INTO '/tmp/bk.db'\")"
  ```

## 六、升级

把四个 `ghcr.io/agentpit-io/hunter-community-*` 工作负载的镜像标签**一起**改成新版本。
api 启动时会自动补跑数据库迁移（两阶段 + advisory lock + 记账表），
**不需要手工执行任何 SQL**。

**不要单独升级其中一两个** —— 四个镜像一起发版，混版本没有测过。

## 七、这份模板里几个不能随手改的地方

- **`securityContext.fsGroup: 1001`（opencode）**。K8s 的新 PVC 是空目录、属主由
  平台决定（R0 实测是 `1000:1003` 或 `0:0`），而容器以 uid 1001 运行 —— 不设它
  入口脚本会打印「会话数据目录不可写」并退出，Pod 进 CrashLoopBackOff。
  本机用「清空卷 + chown 到 GID 1001」模拟了这一条，实测 opencode 能正常建
  `share/` 与 `state/` 并保持健康。
- **api 上的 `LLM_SHIM_URL`**。向导保存后 api 把 provider 的 baseURL 推给
  opencode，那个值取自 api 容器的这个变量；不设就回落到硬编码的 `llm-shim`
  主机名，在这里解析不了。实测症状是**向导五步全绿、发消息却永远没有回复，
  日志里一条报错都没有**。
- **`HUNTER_SINGLE_USER: "0"`**。挂了 Ingress 就是公网，开着单用户模式等于
  谁都能拿 admin token。
- **Ingress 上的 `proxy-read-timeout: 600` 与 `proxy-buffering: off`**。
  深度分析走 SSE 流式返回，实测单次 20～54 秒，默认 60 秒读超时 + 响应缓冲会
  把它掐断，表现是「报告生成到一半白屏」。

## 八、已知待核实（拿到账号后要确认）

1. KubeBlocks 的 `clusterVersionRef: postgresql-16.4.0` / `redis-7.2.7` 在目标
   Sealos 集群上是否可用（不同集群装的 addon 版本可能不同）。
2. `storageClassName: openebs-backup` 是否存在。
3. 连接凭据 Secret 名 `<应用名>-pg-conn-credential` 与
   `<应用名>-redis-redis-account-default`（按仓库里 100+ 个现有模板的一致写法取的）。
4. GHCR 镜像在国内 Sealos 集群上的拉取速度 —— 慢的话要先做 Docker Hub /
   阿里云 ACR 同步（设计方案 5.3 列的前置项，本轮未做）。

## 九、上架步骤（需要你来做）

1. Fork <https://github.com/labring-actions/templates>
2. 把 `deploy/sealos/` 下的四个文件放到 `template/hunter-community/`：
   `index.yaml`、`README.md`、`README_zh.md`、`logo.png`、`website-screenshot.webp`
3. **先在 Sealos 上用你 fork 里的 YAML 部署一次**，确认能跑（仓库 CONTRIBUTING
   的前置条件里明写「You have tested the template on Sealos」）
4. 提 PR，标题 `Add template for HunterCode`，描述里写应用信息与测试结果
5. 合并后按钮地址是
   `[![](https://sealos.io/Deploy-on-Sealos.svg)](https://sealos.io/products/app-store/hunter-community)`

参考：仓库 [CONTRIBUTING.md](https://github.com/labring-actions/templates/blob/main/CONTRIBUTING.md)
与 [example.md](https://github.com/labring-actions/templates/blob/main/example.md)（2026-09-18 查）。
