# 在 Zeabur 上部署 HunterCode

适合谁：不想自己管服务器、希望点几下就有一个带 HTTPS 域名的实例。
费用由 Zeabur 按用量计，和我们无关。

> ⚠️ **本模板尚未在 Zeabur 上实测过**（写模板时没有账号）。字段全部按官方文档与
> 官方 JSON Schema 校验通过，并在本机用「等价 compose」从空卷完整跑过一遍
> （向导 + 真实对话 + 深度分析 + 重启）。真实平台上的差异见文末「已知待核实」。

## 一、部署

```bash
npx zeabur@latest auth login
npx zeabur@latest template deploy -f deploy/zeabur/template.yaml
```

部署表单里**只有一项**要填：**访问域名**。Zeabur 会引导你生成一个
`xxx.zeabur.app` 或绑定自有域名。

**不需要**在部署前准备大模型配置 —— 那是下一步的事。

## 二、初始化口令在哪看

打开 Zeabur 控制台 → **`api` 服务** → **变量** → 复制 `HUNTER_SETUP_TOKEN` 的值。

这道口令是模板随机生成的，作用是：**从部署完成到你第一次打开页面之间，防止别人
抢先进来把大模型配置成他自己的**。公网上的实例不设口令，等于谁先打开谁说了算。

- 口令错 5 次会锁 15 分钟。
- 重启 `api` 服务可以解除锁定（口令本身不变）。

## 三、首启向导（五步）

打开你绑定的域名，会自动进入向导。

| 步 | 做什么 | 说明 |
|---|---|---|
| 0 | 输入初始化口令 | 上一节那个值 |
| 1 | 环境自检 | 逐项列出 postgres / redis / opencode / llm-shim / 迁移 / 密钥 / 卷 / 来源判定，各带真实耗时 |
| 2 | 选大模型厂商 | 内置 5 个常见预设，也可以填任意 OpenAI 兼容网关 |
| 3 | 填你自己的 API key | **由 api 容器当场发起三项检测**：连通 / 真实对话 / 真实工具调用，各显示真实耗时。**测不通不让保存**。工具调用被拒时会自动用 schema 清洗重试，通过就把清洗开关设为开 |
| 4 | 数据供给三选一 | 可以先跳过 |
| 5 | 完成 | 配置写进数据库并**热生效，不重启容器** |

全程**不需要编辑任何文件**。

向导之后注册第一个账号，它自动成为管理员。

### 你需要自备什么

一把 OpenAI 兼容的大模型 API key（DeepSeek / 通义 / Moonshot / OpenAI /
Anthropic / 自建网关都行）。

可选：去 <https://hunter.agentpit.io/dev/api-keys> 免费申请一把 HunterCode 平台
key，解锁实时行情和全部工具。**不填也能用** —— 没有它时助手会如实说
「暂未配置 Hunter Key，无法获取实时行情」，而不是编一个价格出来。

## 四、资源建议

来自 R0 实测（六个容器整栈，`docs/setup-wizard/R0-预研结论.md` 第三节）：

| 场景 | 实测内存 |
|---|---|
| 空闲 60 秒 | 1171 MB |
| 全市场扫描 | 1250 MB |
| 深度分析 | 1245 MB |
| **两者并发（峰值）** | **1271 MB** |

| | |
|---|---|
| 最低 | 2 核 2 GB（2 GB 机器留给系统约 700 MB，紧但可跑） |
| 推荐 | 2 核 4 GB |
| 磁盘 | ≥ 10 GB（镜像约 3.8 GB + 数据） |

内存大头是 `opencode`（869 MB，占 68%），而且**几乎与负载无关** —— 那是常驻占用，
不是峰值风险；真正随负载涨的是 api（+99 MB）。

## 五、数据放在哪 · 怎么备份

| 内容 | 位置 |
|---|---|
| 自选股、组合、研究台、配置、**大模型 key 密文** | `postgres` 服务的卷 |
| 对话正文与会话 | `opencode` 服务的卷 `/home/hunter/.local` |
| 你装的 SKILL、导入的数据包 | `api` 服务的两个卷 |

> ⚠️ postgres 里的 `chat_session_owner` 表**不是对话备份** —— 它只存
> session_id ↔ user_id 的归属映射，对话正文一个字都不在里面。
> 只备份数据库 ≠ 备份了对话。

备份做法：

- **数据库**：用 Zeabur 控制台上 postgres 服务自带的备份功能，或
  `pg_dump` 到你自己的存储。
- **对话正文**：opencode 的 `opencode-local.db` 是 WAL 模式的 sqlite，
  **直接复制主库文件可能读不到最新数据**。取一致性快照：

  ```bash
  # 在 opencode 服务的终端里
  bun -e "new (require('bun:sqlite').Database)(process.env.HOME+'/.local/share/opencode/opencode-local.db',{readonly:true}).exec(\"VACUUM INTO '/tmp/bk.db'\")"
  ```

  然后把 `/tmp/bk.db` 取走。

## 六、升级

把四个 `ghcr.io/agentpit-io/hunter-community-*` 服务的镜像标签**一起**换成新版本，
重新部署即可。

api 启动时会自动补跑数据库迁移（两阶段：基础表 DDL → 增量迁移，带 advisory lock
与 `schema_migrations` 记账表），**不需要手工执行任何 SQL**。

本机实测（rc1 → rc2，从空卷装好 rc1、建账号、再整栈升级）：

- `docker compose up -d` 到六服务健康 25 秒
- 迁移日志：`共 23 个迁移文件，已应用 23 个，本次待执行 0 个`
- 升级前建的账号照常登录，角色仍是 admin
- 六个服务全部 healthy

**不要单独升级其中一两个服务** —— 四个镜像是一起发版的，混版本没有测过。

## 七、已知待核实（拿到账号后要确认）

1. `${PASSWORD}` 的实际长度。api 启动时对 `JWT_SECRET < 32 字符` 会打 ERROR。
   官方没公开长度，模板按 32 实现。
2. 一个服务里引用两次 `${PASSWORD}` 是不是同一个值（模板按「是」设计，因此把四把
   密钥借位定义在四个不同的服务上）。
3. `instructions` 里的口令能不能在控制台正常显示。
4. 模板市场的上架路径与审核要求。

详见 [`deploy/zeabur/README.md`](../../deploy/zeabur/README.md)。

## 八、排查

| 症状 | 先看哪 |
|---|---|
| 向导五步全绿，但发消息永远没有回复 | `api` 服务的 `LLM_SHIM_URL` 是不是指到了真实的 shim 主机名。这个失败**日志里没有任何报错** |
| 对话莫名 401 | api 与 opencode 的 `JWT_SECRET` 是不是同一个值 |
| 上传图片没反应 | api / web / opencode 的 `HUNTER_INTERNAL_KEY` 是不是同一个值 |
| opencode 反复重启，日志写「会话数据目录不可写」 | 卷的属主不是 1001。模板里的 `init` 规则负责改，被删掉或没跑就会这样 |
| 一发消息就收到「大模型尚未配置」 | 向导没走完，或 `apply` 没成功。重走一遍向导第 5 步 |
