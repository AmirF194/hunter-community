# M1 子任务 B · api 启动时自动迁移

> 实测于 2026-09-17，本机 docker（postgres:16-alpine，临时容器端口 5462/5464），
> python 环境用 `ghcr.io/agentpit-io/hunter-community-api:latest` 镜像（只当运行环境，
> 代码从仓库挂进去）。权威设计见 [`design.md`](./design.md) 3.4。

## 一、这轮改了什么

| 文件 | 改动 |
|---|---|
| 新增 `apps/api/app/migrate.py` | 迁移执行器。`boot.sh` 里已有的 `python -m app.migrate` 从此有了实现 |
| 新增 `db/migrations/0022_schema_migrations.sql` | 账本表，让 `db/migrations/` 仍是一份完整 schema |
| 新增 `apps/api/tests/test_migrate.py` | 15 个测试（7 个纯函数 + 8 个真库） |
| 新增 `apps/api/tests/manual_migrate_check.sh` | 手工验收脚本，自己起 postgres，四种情况真跑 |
| `.github/workflows/ci.yml` | 新增 `migrations` job（现有 job 未改动） |

**没有**改 `docker-compose.yml`、`apps/api/Dockerfile`、`boot.sh`、`scripts/**`，也没有改
`app/` 下除 `migrate.py` 以外的任何文件、没有改任何历史迁移文件。

## 二、为什么要做

改造前，迁移靠 postgres 的 `docker-entrypoint-initdb.d` 挂载执行，而那个目录
**只在数据卷第一次创建时执行一次**。于是迁移跟着**数据卷**走，不跟着镜像版本走：
老用户 `git pull` 升级后，新增的迁移一个都不会跑。

本机踩过的真实例子：8 月建的数据卷，升级后 `compliance-status` 接口 500，原因是
`users` 表缺 `compliance_ack_at` 列（0006 没跑过），手工补跑迁移才恢复。

改成 api 启动时执行后，迁移跟着**镜像版本**走：拉新镜像 = 补齐迁移。
失败时**故意**让容器起不来（`boot.sh` 里 `set -e` + 本模块非 0 退出）——
缺表的实例「看着是健康的、一点就 500」比直接起不来难排查得多。

## 三、设计

### 3.1 两个阶段，顺序不能反

```
① 基础表 DDL      app.services.database.init_db()
② 增量迁移        db/migrations/*.sql 里没跑过的
```

**这是本轮发现并修掉的一个真实缺陷，不是顺手加的细节。**

`db/migrations/*.sql` 里有 7 个文件，它们 ALTER / 建视图的目标表**不是迁移文件建的**，
而是 `app/services/database.py::init_db()` 建的，而 `init_db()` 挂在 FastAPI 的 lifespan 上
—— 也就是在迁移**之后**才跑。在全新空库上只灌迁移，实测报错：

```
$ for f in db/migrations/*.sql; do psql -v ON_ERROR_STOP=1 -q < "$f"; done
ok   0001_local_users.sql
...
FAIL 0007_watchlist_shares.sql        ERROR:  relation "stocks" does not exist
FAIL 0008_klines_etl.sql              ERROR:  relation "klines" does not exist
ok   0009_compliance_violation.sql
FAIL 0010_daily_close_view.sql        ERROR:  relation "klines" does not exist
ok   0011_backtest_config.sql
ok   0012_company_master.sql
FAIL 0013_backtest_trade.sql          ERROR:  relation "backtest_result" does not exist
FAIL 0014_daily_close_v2.sql          ERROR:  relation "klines" does not exist
FAIL 0015_stocks_avg_cost.sql         ERROR:  relation "stocks" does not exist
FAIL 0016_backtest_positions_hist.sql ERROR:  relation "backtest_result" does not exist
```

**这说明改造之前线上其实一直是坏的**：compose 把 `./db/migrations` 挂成 postgres 的
`docker-entrypoint-initdb.d`，initdb 跑在 api 第一次启动**之前**，那时基础表还不存在，
这 7 个迁移当场就失败了 —— 而 initdb 的 psql 默认不带 `ON_ERROR_STOP`，失败被静默吞掉。
这正是「老库缺列」那类问题的根源之一。

所以 `migrate.py` 先跑 `init_db()`，再跑增量迁移。验证：

```
① 基础表 DDL（app.services.database.init_db）开始
app.services.database:init_db:827 - Database initialized
① 基础表 DDL 完成，耗时 0.83 秒
② 增量迁移（db/migrations）：共 23 个迁移文件，已应用 0 个，本次待执行 23 个
  [1/23] 0001_local_users.sql 完成，耗时 0.065 秒
  ...（23 个全部 ok）
② 增量迁移完成：本次执行 23 个；两阶段总耗时 1.28 秒
```

两个实现细节：

- **每次启动都跑 `init_db()`**，不做「缺表才跑」的条件判断。它幂等、约 0.3～1 秒；
  而条件判断只能盯住固定几张表，基础表清单以后还会长，漏了就又是一次线上事故。
- **必须自己复查关键表**。`init_db()` 内部 `try/except` 吞异常、只打 ERROR 日志不抛
  （`database.py:828`），而且它整个是**一个大事务**（`conn.commit()` 在 825 行），
  中间任何一步失败会全部回滚。所以 `migrate.py` 跑完后查 `to_regclass('stocks' / 'klines' /
  'backtest_result')`，有缺就报清楚的错并非 0 退出。

### 3.2 advisory lock 常量怎么来的

```python
ADVISORY_LOCK_NAMESPACE = "hunter-community.schema_migrations"
ADVISORY_LOCK_ID = 8700181780438093709
```

取 `sha256(b"hunter-community.schema_migrations").digest()[:8]` 的大端 int，再与
`(1<<63)-1` 按位与。掐到 63 位是因为 pg 的 advisory lock 参数是**有符号 bigint**，
保证为正数，免得不同语言/不同实现算出来的符号不一致。复算：

```bash
python -c "import hashlib;d=hashlib.sha256(b'hunter-community.schema_migrations').digest();print(int.from_bytes(d[:8],'big')&((1<<63)-1))"
# 8700181780438093709
```

**不要改这个值。** advisory lock 只按数值排斥：改了之后，新旧版本的 api 同时启动时会
各自拿到不同的锁、互相不排斥，等于没加锁 —— 而滚动更新正是最需要它的时刻。
`test_migrate.py::test_advisory_lock_id_可复现` 就是拿来防这件事的。

用的是**会话级** `pg_advisory_lock`（不是事务级 `pg_advisory_xact_lock`），因为每个迁移
文件要各自开事务提交，锁必须跨事务存活。跑完显式 `pg_advisory_unlock` 并关连接
（关连接本身也会释放会话级锁，unlock 只是让意图明确）。

### 3.3 为什么每个文件一个独立事务

整批一个事务的话，第 20 个文件失败会把前 19 个一起回滚 —— 修好之后还得从头重跑一遍，
白等；更糟的是「已经成功的那部分到底算不算数」会变得说不清。

一个文件一个事务：失败点**之前**的全部已提交并记账，修完只需要跑剩下的。
失败信息里也明确写了这件事：

```
迁移 0010_daily_close_view.sql 执行失败
  位置：（报错位置未知）
  错误：cannot drop columns from view
  说明：本文件已整体回滚，它**之前**的迁移都已提交并记账，修好这个文件后重启 api 会从它开始继续跑。
```

（「位置」能算出行号时会打成 `第 N 行：<该行内容>`，用 psycopg2 的
`diag.statement_position` 换算；上面这个错误 pg 没给字符偏移，所以显示「报错位置未知」。）

### 3.4 checksum 变了为什么不重跑

已记录意味着这条 DDL 在**这个库**上已经生效过了。重跑最好的情况是白跑一遍，
最坏的情况是把线上数据改坏（比如 0006 里带 `UPDATE users`）。
迁移文件一旦发出去就该当成不可变的，所以只打 WARNING：

```
迁移文件被改过：0021_screen_quota_usage.sql（记录 8a3f…… → 现在 c1d0……）。**不会重跑**，
因为它在本库上已经生效过，重跑可能改坏已有数据。如果确实需要让这次改动生效，
请新增一个迁移文件（例如 00XX_fix_xxx.sql），不要改老文件。
```

这也是**不要去改历史迁移文件内容**的原因：改了 checksum 就变了，所有已部署的库启动时
都会刷这条 WARNING。

### 3.5 其它

| 点 | 做法 |
|---|---|
| 连接 | 与 `database.py::get_conn()` 一致（`psycopg2.connect(DATABASE_URL)`，无连接池）。不 import 它是为了让启动路径的 import 链尽量短 |
| 重试 | 连不上每 2 秒重试一次，最多 60 秒。compose 有 `depends_on: service_healthy`，但云平台不保证，postgres 慢起来是常态 |
| 迁移目录 | `HUNTER_MIGRATIONS_DIR` > `/opt/hunter-migrations`（镜像内，与子任务 A 约定）> 仓库内 `db/migrations`。都找不到报清楚的错 |
| 顺序 | 纯文件名字典序。有两个 `0020_`，字典序下 `rs_history` 在前，确定且可复现 |
| `--dry-run` | 只打印待执行清单：不建表、不加锁、不动任何东西。加锁反而可能卡在正在跑迁移的另一个副本后面 |
| 退出码 | 全部成功 0，任何失败非 0 |

## 四、既有迁移文件可重复执行核实（逐个）

核实方式有两道，**两道都真跑过**：

1. **写法**（grep）：`CREATE TABLE` / `CREATE INDEX` / `ADD COLUMN` 必须带 `IF NOT EXISTS`，
   `CREATE VIEW` 必须是 `CREATE OR REPLACE VIEW`（去掉 `--` 行注释后再匹配）。
2. **实效**：在**已经完整迁移过的库**上，把每个文件单独再跑一遍（`ON_ERROR_STOP=1`）。

| # | 文件 | 写法 | 重跑实测 | 备注 |
|---|---|:--:|:--:|---|
| 1 | 0001_local_users.sql | ✅ | ✅ | 3 张表 + 2 索引，全 IF NOT EXISTS |
| 2 | 0002_user_saas_config.sql | ✅ | ✅ | |
| 3 | 0003_hunter_config.sql | ✅ | ✅ | |
| 4 | 0004_pred_backtest.sql | ✅ | ✅ | 3 表 6 索引 |
| 5 | 0005_backtest_share.sql | ✅ | ✅ | `ADD COLUMN IF NOT EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS` |
| 6 | 0006_compliance.sql | ✅ | ✅ | **含数据写入**：`UPDATE users … SET x = COALESCE(x, …) WHERE email_lower='judge-2026@…'`。用 COALESCE 保证幂等，且只命中一个演示账号 |
| 7 | 0007_watchlist_shares.sql | ✅ | ✅ | 目标表 `stocks` 由 `init_db()` 建（见 3.1） |
| 8 | 0008_klines_etl.sql | ✅ | ✅ | 目标表 `klines` 由 `init_db()` 建 |
| 9 | 0009_compliance_violation.sql | ✅ | ✅ | |
| 10 | 0010_daily_close_view.sql | ✅ | **❌** | **唯一一个不可重复执行的文件**，详见 4.1 |
| 11 | 0011_backtest_config.sql | ✅ | ✅ | **含数据写入**：`INSERT … ON CONFLICT (id) DO NOTHING`，幂等 |
| 12 | 0012_company_master.sql | ✅ | ✅ | |
| 13 | 0013_backtest_trade.sql | ✅ | ✅ | 目标表 `backtest_result` 由 `init_db()` 建；文件头写着「apply(用户手动 · 别自动跑)」——这句话现在过时了，它会被自动跑 |
| 14 | 0014_daily_close_v2.sql | ✅ | ✅ | 同上，文件头也写着「用户手动」 |
| 15 | 0015_stocks_avg_cost.sql | ✅ | ✅ | |
| 16 | 0016_backtest_positions_hist.sql | ✅ | ✅ | |
| 17 | 0017_user_cap_group_name.sql | ✅ | ✅ | |
| 18 | 0018_user_cap_item_group.sql | ✅ | ✅ | |
| 19 | 0019_user_screen_preset.sql | ✅ | ✅ | |
| 20 | 0020_rs_history.sql | ✅ | ✅ | 24 个 `ADD COLUMN IF NOT EXISTS` |
| 21 | 0020_screen_learned_phrase.sql | ✅ | ✅ | 与上一行同号，字典序在后 |
| 22 | 0021_screen_quota_usage.sql | ✅ | ✅ | |
| 23 | 0022_schema_migrations.sql | ✅ | ✅ | 本次新增 |

> 任务书里写的是「现有 21 个迁移文件」，**实际是 22 个**（0001～0019 共 19 个 + 两个
> `0020_` + 一个 `0021_`）。加上本次新增的 0022 共 23 个。

### 4.1 ❌ 0010_daily_close_view.sql 不可重复执行（如实报告）

写法上它是 `CREATE OR REPLACE VIEW`，grep 规则通过；但在**已经跑过 0014 的库上**单独
重跑会失败：

```
失败 ❌ 0010_daily_close_view.sql :: ERROR:  cannot drop columns from view
```

原因：0010 和 0014 定义的是**同一个视图 `daily_close`**，0014 多一列 `adv_20d`。
`CREATE OR REPLACE VIEW` 不允许减列，所以「在 0014 之后重跑 0010」等于降级，pg 拒绝。

**正常路径不受影响**：按文件名顺序执行时 0010 永远在 0014 之前；账本也保证不会重跑。
四种测试情况全部通过，就是因为走的都是正常顺序。

**但有一条会咬人的路径**，而且正是这次改造要救的那批用户：

> 库里已经有 0014 的视图（比如运维照着 0013/0014 文件头写的「apply(用户手动)」手工
> 补跑过，或者像本机这样手工补跑过全部迁移），而账本是空的（账本本来就是这轮才有的）。
> 升级后 migrate 从 0001 重跑 → 撞上 0010 → **api 起不来**。

实测复现（`init_db` + 手工跑 0010、0014 + 无账本）：

```
② 增量迁移（db/migrations）：共 23 个迁移文件，已应用 9 个，本次待执行 14 个
ERROR | 迁移失败，api 不会启动。原因如下：
迁移 0010_daily_close_view.sql 执行失败
  错误：cannot drop columns from view
  可能原因：这个视图在库里已经是**更新的版本**（列更多），而 CREATE OR REPLACE VIEW 不允许减列。
           多半是有人手工补跑过后面的迁移。
  两种修法（任选一种，都要在确认库里的视图定义确实更新之后再做）：
    a) 让它重建一遍：psql 里执行 DROP VIEW IF EXISTS <视图名> CASCADE; 然后重启 api
    b) 直接跳过：给 api 加环境变量 HUNTER_MIGRATIONS_SKIP=0010_daily_close_view.sql 后重启
退出码 1
```

两种修法都**真跑验证过**：

```
# a) DROP VIEW 后重跑
$ psql -c "DROP VIEW IF EXISTS daily_close CASCADE"
$ python -m app.migrate
  [14/14] 0022_schema_migrations.sql 完成，耗时 0.003 秒
  ② 增量迁移完成：本次执行 14 个；两阶段总耗时 0.64 秒     → 退出码 0，账本 23 行，视图 9 列（0014 版）

# b) 跳过
$ HUNTER_MIGRATIONS_SKIP=0010_daily_close_view.sql python -m app.migrate
  WARNING | [1/14] 0010_daily_close_view.sql 按 HUNTER_MIGRATIONS_SKIP 跳过：只记账、不执行。
  ② 增量迁移完成：本次执行 14 个                          → 退出码 0，账本 23 行
```

`HUNTER_MIGRATIONS_SKIP` 是本模块提供的逃生舱：把列出的文件**标记为已应用但不执行**，
写错文件名会当场报错。它是排障手段，不是日常配置。
回归测试见 `test_migrate.py::test_手工补跑过的库_0010_会失败_并给出可照做的建议`。

**推荐的根治办法（需要 `db/migrations` 的 owner 拍板，不在本子任务改动范围内）**：
给 0010 开头加一行 `DROP VIEW IF EXISTS daily_close CASCADE;`。
现在做这件事**代价为零** —— 账本是这轮才引入的，世上还没有任何一个库记录过 0010 的
checksum，所以不会产生 3.4 说的那种 WARNING。**过了这个版本再改就有代价了。**
详见第七节遗留问题 ①。

## 五、四种测试情况（真实命令与输出）

一条命令全跑（自己起 postgres、跑完删容器）：

```bash
bash apps/api/tests/manual_migrate_check.sh 5462
```

完整输出见下（已去掉 ANSI 颜色码；每段迁移明细省略为 `...`）。

### 情况 1 · 空库

```
═══ 情况 1 · 空库:跑一遍应全部执行并记录
迁移目录：/opt/hunter-migrations
① 基础表 DDL（app.services.database.init_db）开始
app.services.database:init_db:827 - Database initialized
① 基础表 DDL 完成，耗时 0.83 秒
② 增量迁移（db/migrations）：共 23 个迁移文件，已应用 0 个，本次待执行 23 个
  [1/23] 0001_local_users.sql 完成，耗时 0.065 秒
  ...
  [23/23] 0022_schema_migrations.sql 完成，耗时 0.003 秒
② 增量迁移完成：本次执行 23 个；两阶段总耗时 1.28 秒
schema_migrations 行数: 23(应为 23)
public 表数量:          61
users.compliance_ack_at:1(应为 1)
stocks.avg_cost:        1(应为 1)
daily_close 视图:       1(应为 1)
```

### 情况 2 · 老库（8 月状态）

构造方式：先复刻 initdb 的行为灌 0001～0014（psql 不带 `ON_ERROR_STOP`，失败继续 ——
当年就是这样），再跑一次 `init_db()`（老版本 api 启动）。这比「纯灌迁移」更接近真实老库。

```
═══ 情况 2 · 老库(8 月状态:initdb 灌过 0001~0014 + 老 api 跑过 init_db)
-- 复刻 initdb 行为(psql 不带 ON_ERROR_STOP,失败继续)--
  0001_local_users.sql  ok
  ...
  0007_watchlist_shares.sql  ← 当年就失败了 · ERROR:  relation "stocks" does not exist
  0008_klines_etl.sql  ← 当年就失败了 · ERROR:  relation "klines" does not exist
  0009_compliance_violation.sql  ok
  0010_daily_close_view.sql  ← 当年就失败了 · ERROR:  relation "klines" does not exist
  0011_backtest_config.sql  ok
  0012_company_master.sql  ok
  0013_backtest_trade.sql  ← 当年就失败了 · ERROR:  relation "backtest_result" does not exist
  0014_daily_close_v2.sql  ← 当年就失败了 · ERROR:  relation "klines" does not exist
-- 老版本 api 起来,跑 init_db() --
app.services.database:init_db:827 - Database initialized
升级前 stocks.avg_cost: 0(应为 0 · 0015 没跑过)
-- 升级到新版本 api --
① 基础表 DDL 完成，耗时 0.50 秒
② 增量迁移（db/migrations）：共 23 个迁移文件，已应用 0 个，本次待执行 23 个
  ...（23 个全部成功，含当年失败的 0007/0008/0010/0013/0014）
② 增量迁移完成：本次执行 23 个；两阶段总耗时 0.50 秒
schema_migrations 行数: 23(应为 23)
升级后 stocks.avg_cost: 1(应为 1)
升级后 screen_quota_usage: 1(应为 1)
```

老库没有账本，所以 23 个文件会全部再跑一遍 —— 这正是「可重复执行」这条要求存在的理由。

### 情况 3 · 重复启动

```
═══ 情况 3 · 重复启动:第二遍应 0 个待执行、账本行数不变
① 基础表 DDL 完成，耗时 0.26 秒
② 增量迁移（db/migrations）：共 23 个迁移文件，已应用 23 个，本次待执行 0 个
② 增量迁移完成：本次执行 0 个；两阶段总耗时 0.27 秒
账本行数 23 → 23(应相等)
最后应用时间 2026-09-17 17:12:33.775615+00 → 2026-09-17 17:12:33.775615+00(应相等,说明确实没重跑)
```

`applied_at` 不变是关键断言：只比行数的话，「删掉再插一遍」也能过。

### 情况 4 · 并发

```
═══ 情况 4 · 并发:两个进程同时跑空库,advisory lock 应串行化
进程 A 退出码 0 · 进程 B 退出码 0(都应为 0)
A: 本次待执行 23 个
B: 本次待执行 0 个
schema_migrations 行数: 23(应为 23,没有重复)
```

两个进程同时对空库跑：先拿到 advisory lock 的那个跑完全部 23 个，另一个等锁，
拿到后发现 0 个待执行。两个都 0 退出，账本 23 行无重复。
（哪个进程先拿到锁是不确定的，两次运行分别出现过 A 先和 B 先，都符合预期。）

### 附加 · `--dry-run` 不改数据库

```
② 增量迁移：共 23 个迁移文件，已应用 0 个，本次待执行 23 个（--dry-run，不执行）
  待执行：0001_local_users.sql
  ...
  待执行：0022_schema_migrations.sql
schema_migrations 是否存在: 不存在(应为「不存在」)
```

### 附加 · pytest

```
$ docker run --rm --network host -v "$PWD/apps/api:/src" -v "$PWD/db/migrations:/opt/hunter-migrations:ro" \
    -w /src -e HUNTER_MIGRATIONS_DIR=/opt/hunter-migrations \
    -e TEST_DATABASE_URL="postgresql://hunter:<临时口令>@127.0.0.1:5462/postgres" \
    ghcr.io/agentpit-io/hunter-community-api:latest \
    sh -c 'pip install -q pytest && python -m pytest tests/test_migrate.py -p no:cacheprovider -q'
...............                                                          [100%]
```

15 passed（7 个纯函数 + 8 个真库）。运行镜像里没装 pytest，脚本会现装一个；
装不上（没网）时这一步跳过，不影响上面四种情况的结论。

## 六、CI

新增 job `migrations`（`.github/workflows/ci.yml`），**现有 job 一行未改**。五步：

1. **迁移文件可重复执行规则**（grep）：四条规则，去掉 `--` 行注释后匹配。
   现有 23 个文件**全部通过，不需要白名单**。
2. **规则自检**：拿一个故意写错的 SQL 喂给四条规则，必须四条都报错 ——
   否则哪天 grep 写坏了，这个 job 就成了永远绿的摆设。
3. **空库连跑两遍**：第一遍断言「本次待执行 = 文件总数」，第二遍断言「本次待执行 0 个」
   且无 WARNING，两遍都必须 0 退出；再查账本行数、`users.compliance_ack_at`、
   以及 `stocks`/`klines`/`backtest_result` 三张基础表（后者证明阶段 ① 确实跑在阶段 ② 之前）。
4. **已迁移库上逐个文件重跑**（真·幂等检查）：比 grep 强，正是它抓到了 4.1 的 0010。
   白名单里只有 `0010_daily_close_view.sql`，理由写在 yml 注释里。
5. **`pytest tests/test_migrate.py`**：只跑这一个文件。仓库里另外 32 个测试文件的通过状态
   未知，贸然给整个 `tests/` 加 pytest 会把 CI 搞红，那不是这个 job 该背的锅。

## 七、遗留问题

1. **（需要决策，建议在本版本内解决）0010 的根治**。见 4.1。
   建议给 `db/migrations/0010_daily_close_view.sql` 开头加
   `DROP VIEW IF EXISTS daily_close CASCADE;`，然后把 CI 白名单去掉。
   现在改代价为零（还没有任何库记录过它的 checksum），过了这个版本再改就要刷 WARNING。
   本子任务的改动范围不含历史迁移文件，所以没有自行动手。

2. **`init_db()` 该拆成 `0000_baseline.sql`**。现在「基础表在 python 里、增量表在 SQL 里」
   是两套东西，靠 `migrate.py` 里的调用顺序粘在一起。彻底的做法是把 `database.py` 的
   `CREATE_TABLES` 与 `init_db()` 里那些 `cur.execute(DDL)` 抽成一个 `0000_` 迁移文件，
   `init_db()` 只保留数据 seed。这要动 `database.py`，属于别的子任务的地盘。

3. **0013 / 0014 文件头的「apply(用户手动 · 别自动跑)」已经过时**，它们现在会被自动跑。
   不改，因为改文件内容会变 checksum（见 3.4）；等哪天有别的理由动这两个文件时顺手修。

4. **`migrate.py` 目前对「同一个 DDL 分散在多个文件里改同一个对象」没有防护**。
   0010/0014 这种「后一个文件覆盖前一个文件的视图定义」的写法，靠的是顺序执行 + 账本。
   如果以后再出现这种写法，CI 第 4 步会抓到（只要不加白名单）。

5. **`--dry-run` 不加 advisory lock**，所以它看到的「待执行清单」可能在另一个副本正在跑
   迁移时是过时的。这是故意的（加锁会让排障命令卡住），排障时注意。

6. **老库升级的端到端验证（用 8 月版本的真实数据卷快照）还没做** —— 那是 design.md
   第七节「老库升级」那一栏的事，需要真实快照，不在本子任务范围。本文第五节情况 2 是
   按迁移文件构造的等价老库。
