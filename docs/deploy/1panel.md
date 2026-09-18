# 在 1Panel 上部署 HunterCode

适合谁：手里有自己的 VPS / 云主机、已经在用 1Panel 管面板、希望在面板里点一下安装。

> ⚠️ **本应用包尚未在真实 1Panel 面板上装过**（做的时候没有面板环境）。
> 格式按 `1Panel-dev/appstore` 的真实应用与官方打包规范仓库
> `1Panel-dev/1Panel-appstore-skills` 编写，**过了官方 `validate_app_package.py`
> 校验（零 error 零 warning）**，并在本机把它的 `docker-compose.yml` 从空目录
> 完整跑过一遍（向导 + 真实对话 + 深度分析 + 重启）。
> 真实面板上的差异见文末「已知待核实」。

## 一、安装

应用包还没提交到 1Panel 应用商店（上架步骤见文末）。在上架之前可以手工安装：

```bash
# 1. 准备目录（面板一般在 /opt/1panel/apps 下）
mkdir -p ~/hunter-community && cd ~/hunter-community
cp -r <仓库>/deploy/1panel/hunter-community/1.1.0-rc2/* .

# 2. 填 .env（表单里那几项，手工装就自己写）
cat > .env <<'EOF'
CONTAINER_NAME=hunter
PANEL_APP_PORT_HTTP=3180
HUNTER_SETUP_TOKEN=<换成一串随机值，openssl rand -hex 16>
POSTGRES_PASSWORD=<换成一串随机值，只用字母数字>
REGISTRATION_MODE=open
HUNTER_API_KEY=
HUNTER_ADMIN_EMAILS=
EOF

# 3. 建目录、改属主（面板安装时由 scripts/init.sh 自动做）
mkdir -p data/{postgres,redis,opencode,secrets,user-skills,packages}
sudo bash scripts/init.sh

# 4. 起
docker network create 1panel-network 2>/dev/null
docker compose up -d
```

> ⚠️ `POSTGRES_PASSWORD` 里**不要用 `@ / # :`** —— 它会被拼进 `DATABASE_URL`，
> 这几个字符会让连接串解析错位。表单里那项的 `rule: paramCommon` 就是为此。

## 二、初始化口令在哪看

面板安装：**应用 → HunterCode → 参数**，找 `HUNTER_SETUP_TOKEN`。
手工安装：就是你写进 `.env` 的那个值。

首启向导第 0 步要用它。错 5 次锁 15 分钟；重启 api 容器可解除锁定（口令不变）。

## 三、首启向导（五步）

浏览器打开 `http://<服务器IP>:3180`（或你在面板「网站」里配的反代域名），
会自动进入向导。步骤与含义同 [Zeabur 那篇](./zeabur.md#三首启向导五步)。

向导之后注册第一个账号，它自动成为管理员。建好之后建议把表单里的「注册策略」
改成 `closed` 再重建容器。

全程**不需要编辑任何文件**。

## 四、资源建议

来自 R0 实测（六个容器整栈）：

| 场景 | 实测内存 |
|---|---|
| 空闲 60 秒 | 1171 MB |
| **深度分析 + 全市场扫描并发（峰值）** | **1271 MB** |

| | |
|---|---|
| 最低 | 2 核 2 GB |
| 推荐 | 2 核 4 GB |
| 磁盘 | ≥ 10 GB（镜像约 3.8 GB + 数据） |

> 面板本身、你已经装的别的应用都要另算。2 GB 的机器上如果 1Panel 里还跑着
> 数据库或建站应用，多半不够。

## 五、数据放在哪 · 怎么备份

**全部在应用安装目录的 `data/` 下**，这是这个包和云平台模板最大的不同 ——
1Panel 的「应用备份」只打包安装目录，用具名卷的话对话正文会被漏掉。

| 目录 | 内容 |
|---|---|
| `data/postgres` | 自选股、组合、研究台、配置、**大模型 key 密文** |
| `data/opencode` | **对话正文与会话**（属主必须是 1001） |
| `data/secrets` | api 自动生成的 `JWT_SECRET` / `HUNTER_INTERNAL_KEY`，web 与 opencode 只读挂同一个目录 |
| `data/user-skills` | 你装的 SKILL |
| `data/packages` | 导入的数据包 |

备份：直接用面板的**应用备份**。手工装的话 `tar` 整个安装目录即可
（先 `docker compose stop` 保证 sqlite 一致性）。

> ⚠️ **`data/secrets` 不能丢**。`JWT_SECRET` 派生了加密已存 key 的密钥 ——
> 丢了之后已保存的大模型 key 全部解不开，所有人要重新登录、重新填 key。

## 六、升级

面板里选新版本升级即可。`data/secrets` 会被保留，所以已保存的 key 仍然解得开。

api 启动时会自动补跑数据库迁移（两阶段 + advisory lock + 记账表），
**不需要手工执行任何 SQL**。

**不要单独升级其中一两个容器** —— 四个镜像一起发版，混版本没有测过。

## 七、这个包里几个不能随手改的地方

- **服务间一律用 `${CONTAINER_NAME}-<服务>`，不用裸服务名**。`1panel-network`
  是全面板共用的外部网络，`api` / `postgres` 这种名字会和别的应用撞网络别名，
  症状是随机 502 / 连错数据库，而且完全查不出规律。
- **`data/opencode` 的属主必须是 1001**（`scripts/init.sh` 负责）。容器以 uid 1001
  运行，属主不对时入口脚本会打印「会话数据目录不可写」并退出 —— 本机实测复现过：
  不 chown 时 opencode 反复重启，chown 之后六个服务立刻全部 healthy。
- **api 上的 `LLM_SHIM_URL`**。向导保存后 api 把 provider 的 baseURL 推给
  opencode，那个值取自 api 容器的这个变量；不设就回落到硬编码的 `llm-shim`，
  而这里的容器叫 `${CONTAINER_NAME}-llm-shim`，解析不了。症状是**向导五步全绿、
  发消息却永远没有回复，日志里一条报错都没有**。
- **`HUNTER_SINGLE_USER: "0"` 写死在 compose 里，没做成表单项**。面板部署面向
  公网，做成可改项等于给用户留一个「谁都能拿 admin token」的开关。
- **web 排在 compose 的第一个服务**。appstore 的 Renovate 会拿第一个服务的镜像
  标签去重命名版本目录 —— postgres 排第一会把目录名改成 `16-alpine`。

## 八、已知待核实（拿到面板后要确认）

1. **表单 `random: true` 生成值的字符集**。如果生成的值含 `$` / `@`，
   `HUNTER_SETUP_TOKEN` 会被 compose 插值、`DATABASE_URL` 会解析错位。
   装一次看 `.env` 就知道。这是唯一可能需要改 compose 的一条。
2. **`scripts/init.sh` 需要 1Panel ≥ v2.2.5**。更老的面板不 dispatch `init`，
   `data/opencode` 属主还是 root，opencode 会反复重启。
3. 反向代理下 SSE 流式（深度分析实测单次 20～54 秒）会不会被面板的 nginx
   默认读超时掐断 —— 需要在「网站 → 配置」里把 `proxy_read_timeout` 放宽到 600。
4. 安装 / 启停 / 卸载 / 升级 / 表单渲染在真实面板上的表现。

完整 12 条待核实清单见
[`docs/setup-wizard/M3-E-1Panel应用包.md`](../setup-wizard/M3-E-1Panel应用包.md) 第 6 节。

## 九、上架步骤（需要你来做）

1. Fork <https://github.com/1Panel-dev/appstore>
2. 把 `deploy/1panel/hunter-community/` 整个目录放到仓库的 `apps/` 下
3. **先在自己的面板上装一次**，确认安装 / 启停 / 卸载 / 升级都正常
4. 跑一遍官方校验：
   `python3 scripts/validate_app_package.py apps/hunter-community`
   （脚本在 <https://github.com/1Panel-dev/1Panel-appstore-skills>）
5. 提 PR

⚠️ **PR 描述里要先说明「为什么自带 postgres / redis」**：仓库主流做法是用
`type: service` 引用面板已装的中间件。我们自带是为了让「装完就能用、不要求用户
先装数据库」。如果被驳回，改成 4 个 `PANEL_DB_*` / `PANEL_REDIS_*` 表单字段即可。
