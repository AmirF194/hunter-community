# M1 · 子任务 D · 用户 SKILL 同步(api → opencode)

> 实施时间：2026-09-17（上海时间）
> 分支：`m1/d-skills`
> 依据：`docs/setup-wizard/design.md` §3.5 + **`R0-预研结论.md` 第二节（3.5 的原做法已被预研推翻，以 R0 为准）**
> 验证环境：本机预发栈 `hunter-staging`（opencode `127.0.0.1:3931`）+ 一个只跑本分支代码的临时 api 容器

---

## 一、一句话

用户在界面里装的 SKILL 原来靠「api 和 opencode bind mount 同一个宿主目录」被模型看到，
云平台上两个服务不能共用卷，于是模型看不到。
本次改为 **api 把用户 SKILL 目录导出成一个静态清单接口，opencode 用它原生的 `skills.urls` 自己来拉**。
不写 huntercode 插件，不加数据库表。

实测：走真实的「界面新建 SKILL」接口，**0.16 秒**后模型侧已能读到正文。

---

## 二、做了什么

| 文件 | 改动 |
|---|---|
| `apps/api/app/routers/internal_skills.py` | **新增** · 导出接口 `GET /api/internal/skills/{key}/index.json` 与 `/{key}/{name}/{path}` |
| `apps/api/main.py` | 注册上面这个路由（只加了 import + 一行 `include_router`） |
| `apps/api/app/services/skill_files.py` | **新增导出函数**（见下表），原有逻辑一行未动 |
| `apps/api/app/routers/chat_skill.py` | ① 补全 `_after_write()` 的说明 ② **修一个本次架构引入的自锁 bug**（第六节） |
| `apps/api/tests/test_internal_skills.py` | **新增** · 24 条用例 |
| `docs/setup-wizard/M1-D-SKILL同步.md` | 本文 |

`skill_files.py` 新增的函数（放在这里而不是路由里，因为「怎么算一个用户 SKILL」本来就属于这个模块）：

| 函数 | 作用 |
|---|---|
| `user_skill_dir(name)` | name → 用户目录下**可导出**的 SKILL 目录；非法/越界/无 `SKILL.md` 返回 None |
| `list_user_skill_names()` | 所有可导出的 SKILL 目录名 |
| `iter_user_skill_files(name)` | `[(相对路径, 字节), ...]`，按路径排序 |
| `user_skill_version(files)` | 全部文件内容的 sha256 |
| `resolve_user_skill_file(name, rel)` | `(name, 相对路径)` → 真实文件；**唯一的路径穿越防线** |
| `export_index()` | 直接喂给 `index.json` 的清单 |

### 不改 `docker-compose.yml` / `deploy/**` / `scripts/**`

本子任务只交付 api 这一侧。opencode 侧写 `skills.urls` 配置那一行由**子任务 C**（`scripts/opencode/gen-config.py`）负责，契约见第三节。

---

## 三、接口契约（给子任务 C 与 M2）

opencode 的配置里应当是：

```json
"skills": { "urls": ["http://api:8000/api/internal/skills/<HUNTER_INTERNAL_KEY>/"] }
```

> 结尾那个 `/` **不能省**。opencode 的 `Discovery.pull` 里 `const base = url.endsWith("/") ? url : url + "/"` 会补上，
> 但 `host = base.slice(0, -1)` 之后拼文件 URL 用的是 `${host}/${skill.name}/`，写不写都能跑通，
> 写上更贴近它文档里的形态，也少一层心智负担。

### `GET <base>index.json`

```json
{"skills":[{"name":"my_dcf_check","files":["SKILL.md","refs/data-sources.md"],"version":"<64 位 sha256 hex>"}]}
```

- **schema 必须逐字如此**。opencode 侧用 effect `Schema` 严校验，多包一层（比如 `{"ok":true,"data":{...}}`）
  会让它整份解析失败，日志里只留一条 `failed to fetch index`，然后**当作一个 SKILL 都没有**——不报错，只是空。
- `files` **必须包含 `SKILL.md`**，否则 opencode 跳过该条目并打 warning。所以没有 `SKILL.md` 的目录压根不进清单。
- `version` = 该 SKILL 全部文件内容的 sha256。

### `GET <base><name>/<相对路径>`

文件原始字节。`SKILL.md` → `text/markdown; charset=utf-8`；其余按扩展名猜，猜不出 `application/octet-stream`，二进制原样返回。

### 调用方需要知道的 opencode 行为（源码 `packages/opencode/src/skill/discovery.ts`，已实测）

| 行为 | 说明 |
|---|---|
| `version` **不变** | 只补本地缺失的文件，已存在的不重下 → 所以 version 必须对内容敏感 |
| `version` **变了** | 下到 staging 目录，全部就位且确认有 `SKILL.md` 后**原子 rename** 换版；换版中途模型读到的始终是完整旧版 |
| `pull` 的返回值 | **只包含本次清单里的目录**。删掉的 SKILL 下次 refresh 就不再被扫到（缓存盘上的残留目录不参与扫描）——**删除也靠这条生效** |
| `POST /skill/refresh` | 重跑整个发现流程，URL 拉取在里面。api 写完 SKILL 后照旧调它（`opencode_admin.refresh_skills()`，已有代码） |
| 请求形式 | **裸 GET**，`HttpClientRequest.get` + `acceptJson`，**带不了任何自定义头** → 鉴权只能放 URL 路径段 |
| 缓存落点 | `~/.cache/opencode/skills/<name>/`，容器内实测 `/home/hunter/.cache/opencode/skills/` |

### 导出的是**用户 SKILL**，内置 SKILL 不导出

- 导出：`HUNTER_USER_SKILLS_DIR`，默认 `/opt/hunter-user-skills`
- **不导出**：`HUNTER_SKILLS_DIR`，默认 `/opt/hunter-skills`

内置 SKILL 已经由**子任务 A** 打进 opencode 镜像的 `/opt/opencode-workspace/.opencode/skills/`。
再从 URL 导一份，同一个 SKILL 会在模型那里**出现两次**（一次本地目录、一次 URL 缓存），
而且两份可能还不是同一个版本（镜像里的随发版走，api 里的随代码走）。
单测 `test_builtin_skills_not_exported` 盯着这一条。

---

## 四、偏离设计方案：**不引入 `user_skill_files` 数据库表**

设计方案 §3.5 写的是「**数据库为准**：新表 `user_skill_files(skill_name, path, content bytea, sha256, updated_at)`；api 写库（本地若挂了目录，同时写目录，保持向后兼容）」，并计划新增迁移 `db/migrations/0022_user_skill_files.sql`。

**本次不做。** 三条理由：

1. **它要解决的问题已经解决了。** §3.5 的真正目标是「opencode 看不到 api 写的 SKILL」。
   R0 证明导出接口 + opencode 原生 `skills.urls` 已经完整解决了它，而且是 0.07～0.16 秒级。
   数据库表在这条链路上**不提供任何额外能力**——导出接口无论从磁盘读还是从库读，对 opencode 完全一样。

2. **api 在每个部署形态下都有自己的卷。** 设计方案 §5.3 给 api 列了 `/opt/hunter-user-skills` 和 `/opt/hunter-packages` 两个卷，
   Zeabur / Sealos / Railway / 1Panel 的模板都会照着给。文件系统本来就是持久的，
   「api 重启后用户 SKILL 丢了」这个假想风险不存在。

3. **再存一份到数据库就有了两个事实来源，而写入路径有十几个分支。**
   `skill_files.py` 的写入面有 `save()` / `save_raw()` / `save_assets()` / `set_hunter_field()` / `delete()`，
   上游调用点覆盖「表单新建 / 编辑 / 安装推荐仓库 / 从 GitHub 装 / 暂存区落盘 / 翻译回写 hunter 字段 / 删除」。
   每一个都要双写。**任何一处漏掉，就是「界面显示 A、模型看到 B」**——
   这类 bug 不报错、不告警，只有用户觉得「我明明改了啊」，而我们在两个地方看到的都是「对的」。
   为了一个已经不需要的能力去背这个风险，不划算。

**将来什么情况下补回来**：遇到**不能给 api 挂卷**的平台（例如只给无状态容器的 serverless 形态）。
那时把 `skill_files.iter_user_skill_files()` / `list_user_skill_names()` 的实现换成读库即可，
**导出接口的契约（第三节）一个字都不用变**，opencode 侧和子任务 C 的配置也不用动。
这正是把遍历函数放进 `skill_files.py`、而不是直接写在路由里的原因。

---

## 五、安全设计

| 风险 | 措施 | 单测 |
|---|---|---|
| **口令泄露给扫描者** | 不匹配返回 **404 而不是 401**。401 等于告诉对方「这个路径存在，只是口令不对」；404 和「压根没这个接口」无法区分。所有失败原因（口令错 / SKILL 不存在 / 路径越界 / 超上限）的响应体统一是 `{"detail":"not found"}` | `test_wrong_key_is_404_not_401` |
| **计时侧信道** | `secrets.compare_digest` 常数时间比较。按**字节**比而不是按 str——`compare_digest` 对 str 要求纯 ASCII，口令里有非 ASCII 会抛 `TypeError`（那会变成 500，反而暴露信息） | `test_wrong_key_*` |
| **没配口令就人人可读** | `HUNTER_INTERNAL_KEY` 为空时整个接口直接 404，**绝不退化成「不校验」**。一个「没配置就开放」的接口比没有这个接口危险得多 | `test_empty_internal_key_closes_endpoint` |
| **路径穿越** | `resolve_user_skill_file()` 是唯一防线：先按 `/` 拆段拒绝 `.` `..` 和隐藏名，再 `Path.resolve()` 后 `relative_to(skill 目录)`。只查字符串里有没有 `..` **挡不住软链**，必须 resolve | `test_traversal_rejected_at_unit_level`、`test_traversal_rejected_over_http` |
| **软链指向容器内任意文件** | 文件软链、目录软链、以及**软链形式的 SKILL 目录**一律不导出、不可下载。`os.walk(followlinks=False)` + 逐项 `is_symlink()` | `test_symlink_pointing_outside_rejected`、`test_symlinked_skill_dir_not_exported` |
| **口令写进日志** | 日志里**不打 `request.url.path`**——那里面带着口令。只打 `name` / 相对路径，且截断 | — |
| **撑爆 opencode 缓存盘** | 单文件 `EXPORT_MAX_FILE_BYTES = 5 MB`、单 SKILL `EXPORT_MAX_FILES = 200`，超了跳过并 warning，不让整个 SKILL 失败 | `test_oversized_file_skipped`、`test_file_count_capped` |
| **把 `.env` / `.git` 喂给模型** | 隐藏文件与隐藏目录、`__pycache__` / `.git` / `.github` / `node_modules` / `.venv` 一律不导出，也不可单独下载（「清单里没有却下得到」同样是泄露） | `test_hidden_and_junk_files_excluded` |
| **「清单里没有却下得到」** | 没有 `SKILL.md` 的目录整体不可访问。user-skills 下可能躺着安装失败的半截目录、用户手拷进来的杂物，那些不该是一个对外可读的文件服务 | `test_skill_without_skill_md_is_skipped` |

> **口令为什么只能放 URL 路径段**：opencode 的 `Discovery.pull` 用裸 GET，
> 带不了 `X-Hunter-Internal-Key` 这种自定义头。配合「api 在 compose / 平台内网里、不对外暴露端口」
> 这个前提，风险与其它 `/api/internal/*` 接口一致。

### 关于缓存

导出接口**一律直读磁盘，不走 `skill_files._cache`**。
那个缓存是给 UI 列表用的（只存解析后的字段，不存文件字节），失效时机由写入路径控制。
导出接口要的是「**此刻磁盘上到底是什么**」——缓存晚一拍，表现就是「用户刚存完、模型拉到的还是上一版」，
正是这次要根除的那类 bug。单测 `test_export_reads_disk_not_cache` 故意把 `_cache` 清空成「什么都没有」，导出仍然正确。

---

## 六、实测发现并修掉的一个 bug：SKILL 保存自锁

**这条不是预想中的工作，是端到端验证当场撞出来的，而且会 100% 出现在生产上。**

改成 URL 拉取之后，`api → opencode` 的 refresh 调用**变成了一个闭环**：

```
api  ──POST /skill/refresh──►  opencode
api  ◄──GET /api/internal/skills/.../index.json──  opencode
```

而 `opencode_admin.refresh_skills()` 用的是**同步** httpx，`chat_skill._after_write()` 在 `async def` 里直接调它，
会把 uvicorn 的事件循环整个堵住（镜像入口是 `uvicorn main:app`，**单 worker**）。
于是 opencode 拉不到清单、api 等满 30 秒超时。

第一次跑真实写入路径的输出：

```
$ curl -X POST http://127.0.0.1:8299/api/chat/skills -H 'authorization: Bearer …' -d '{…"slug":"d_probe2"…}'
{"ok":true,"key":"d_probe2","synced":false,"needs_restart":true,
 "message":"新能力已保存，但当前 opencode 需要重启才能识别 …… docker compose restart opencode（约 50 秒）",
 "reason":"连不上 opencode(ReadTimeout)"}
real    0m30.073s
```

**文件其实写好了、opencode 其实也活着**——纯粹是自己把自己锁死，
然后给用户弹一句「去重启 opencode，大概 50 秒」。api 日志把因果关系钉得很死：

```
17:08:27.498 | WARNING | opencode_admin:refresh_skills - [opencode_admin] refresh 请求失败: timed out
17:08:27.502 | INFO    | internal_skills:skills_index   - [internal.skills] 导出清单 · 2 个用户 SKILL
17:08:27.504 | INFO    | "GET /api/internal/skills/…/index.json HTTP/1.1" 200 OK
```

opencode 的请求是 **17:08:27.502** 才被处理的——阻塞调用一放弃，事件循环一空，它立刻就服务了。

**改法**：`chat_skill._after_write()` 改成 `async`，用 `starlette.concurrency.run_in_threadpool` 调 `refresh_skills()`，
5 个调用点加 `await`。**没有动 `opencode_admin.py`**（那是子任务 C 的地盘）。

改后同一条命令：

```
{"ok":true,"key":"d_probe2","synced":true,"skill_count":10}
real    0m0.164s
```

> **给其它子任务的提醒**：任何「api 同步调 opencode、而 opencode 会回头调 api」的地方都有这个坑。
> 子任务 C 的 `opencode_admin.apply_llm()`（`PATCH /global/config`）如果也从 `async def` 里同步调，
> 而 opencode 重建实例时会去拉 `/api/internal/runtime/llm`，就是同一个死锁。

---

## 七、验证

### 7.1 单测

```
$ docker run --rm -v "$PWD/apps/api:/src" -w /src \
    -e JWT_SECRET=ci-test-secret -e HUNTER_INTERNAL_KEY=testkey123 \
    -e DATABASE_URL=postgresql://placeholder@localhost/placeholder \
    --entrypoint sh ghcr.io/agentpit-io/hunter-community-api:latest \
    -c 'pip install -q pytest pytest-asyncio httpx; python -m pytest tests/test_internal_skills.py -q'

24 passed, 2 warnings in 1.05s
```

> ⚠️ **不要跑整个 `tests/` 目录**——`test_screen_fix.py` 在 import 阶段就 `sys.exit()`，
> 会把整个 pytest 进程带走。那是既有问题，不是本次引入的。

第一版跑出来有 1 条失败，是**测试抓到的真 bug**（不是用例写错）：

```
FAILED tests/test_internal_skills.py::test_skill_without_skill_md_is_skipped
    assert client.get(f"{BASE}/broken/readme.md").status_code == 404
E   AssertionError: assert 200 == 404
```

没有 `SKILL.md` 的目录不在清单里，但它底下的文件仍然能被逐个下走——「清单里没有、却下得到」。
已在 `user_skill_dir()` 里补上。

### 7.2 端到端（**通过**）

做法：本机起一个**只跑本分支代码**的临时 api 容器 `m1d-api`（挂工作树进官方镜像、接 `hunter-staging_default` 网络、
指向预发栈的 postgres、`HUNTER_MINIMAL_BOOT=1`），让预发栈里**已经在跑的** opencode 去拉它。

```
docker run -d --name m1d-api --network hunter-staging_default -p 127.0.0.1:8299:8000 \
  -v .../wt-d-skills/apps/api:/app \
  -v .../wt-d-skills/skills:/opt/hunter-skills:ro \
  -v /tmp/m1d-user-skills:/opt/hunter-user-skills \
  -e HUNTER_INTERNAL_KEY=<测试口令> -e HUNTER_MINIMAL_BOOT=1 -e HUNTER_SINGLE_USER=1 \
  -e JWT_SECRET=<测试值> -e DATABASE_URL=postgresql://hunter:<预发栈密码>@postgres:5432/hunter \
  -e REDIS_URL=redis://redis:6379/0 \
  -e HUNTER_SKILLS_DIR=/opt/hunter-skills -e HUNTER_USER_SKILLS_DIR=/opt/hunter-user-skills \
  ghcr.io/agentpit-io/hunter-community-api:latest
```

探针 SKILL：`/tmp/m1d-user-skills/d_probe/`，含 `SKILL.md`（正文埋 `D-SKILL-777`）、`refs/detail.md`，
外加**故意放进去的**不该导出的东西：`.env`、`__pycache__/x.pyc`、以及一个没有 `SKILL.md` 的目录 `no_skill_md/`。

#### ① 导出接口本身

```
$ curl -s <临时api>/api/internal/skills/<口令>/index.json          # 0.043 秒
{"skills":[{"name":"d_probe","files":["SKILL.md","refs/detail.md"],
            "version":"bd5a0362798c75b8d486822177097a03d566563b1515095bb8e3340adfdc1818"}]}
```

`.env`、`__pycache__/x.pyc`、`no_skill_md` 都**不在** `files` 里，符合预期。

```
$ curl -sD- <base>/d_probe/SKILL.md | head -5
HTTP/1.1 200 OK
content-length: 312
content-type: text/markdown; charset=utf-8
（正文正确，含 D-SKILL-777）

$ curl -s <base>/d_probe/refs/detail.md
附属文件 · 第一版 · ALPHA          [HTTP 200]
```

#### ② 鉴权与路径穿越（容器内放了一个 `/opt/m1d-secret.txt` 当靶子）

```
错误 key /wrongkey/index.json                          → HTTP 404
短一位  /testkey12/index.json                          → HTTP 404
长一位  /testkey1234/index.json                        → HTTP 404
大小写  /TESTKEY123/index.json                         → HTTP 404
错误 key 取文件                                        → HTTP 404
../../m1d-secret.txt          (%2e%2e%2f…)             → HTTP 404
../m1d-secret.txt                                      → HTTP 404
refs/../../../m1d-secret.txt                           → HTTP 404
/etc/passwd                   (%2fetc%2fpasswd)        → HTTP 404
../../../../etc/passwd                                 → HTTP 404
隐藏文件 .env                                          → HTTP 404
__pycache__/x.pyc                                      → HTTP 404
无 SKILL.md 的目录 no_skill_md/readme.md               → HTTP 404
内置 SKILL quote/SKILL.md（不该被导出）                → HTTP 404
不存在的 SKILL                                          → HTTP 404

所有 404 的响应体都是：{"detail":"not found"}
靶子文件内容一次都没出现在任何响应里。
```

#### ③ 预发栈 opencode 真的拉到了

```
$ curl -s -X PATCH http://127.0.0.1:3931/global/config -H 'content-type: application/json' \
    -d '{"skills":{"urls":["http://m1d-api:8000/api/internal/skills/<口令>/"]}}'
HTTP 200                                                          # 0.042 秒

$ curl -s -X POST http://127.0.0.1:3931/skill/refresh
9                                                                 # 0.680 秒

$ curl -s http://127.0.0.1:3931/skill | …
{
  "name": "d_probe",
  "description": "M1 子任务 D 的端到端探针 · 用来验证 opencode 能从 api 拉到用户 SKILL",
  "location": "/home/hunter/.cache/opencode/skills/d_probe/SKILL.md",
  "content": "…**探针口令是 `D-SKILL-777`。**…"
}
```

opencode 容器内：

```
$ docker exec hunter-staging-opencode-1 ls -la /home/hunter/.cache/opencode/skills/d_probe/
.opencode-version   64 B
SKILL.md           312 B
refs/              （detail.md 35 B）

$ docker exec … cat .../d_probe/.opencode-version
bd5a0362798c75b8d486822177097a03d566563b1515095bb8e3340adfdc1818   ← 与 api 导出的 version 逐字相同
```

#### ④ 换版：改内容 → version 自动 bump → refresh → 缓存真的更新了

```
不改内容再 refresh 一次：version bd5a0362… → bd5a0362…      ✅ 不变（opencode 不会重下）
改 SKILL.md（777→999）+ 改 refs/detail.md（ALPHA→BETA）：
   version bd5a0362… → c6205e11…                            ✅ 已变
POST /skill/refresh + 读回：0.109 秒
   opencode 返回的 content：**探针口令是 `D-SKILL-999`。**
$ docker exec hunter-staging-opencode-1 …
   D-SKILL-999
   附属文件 · 第二版 · BETA
   version: c6205e1120452115d35dd6c21ba89eec780348b7eeef7e53666a91ee5961acfc
```

#### ⑤ 删除也生效

```
把 d_probe 从用户目录移走 → index.json 返回 {"skills":[]}
POST /skill/refresh → 8
GET /skill          → d_probe 还在吗: False
$ docker exec … ls ~/.cache/opencode/skills/  → d_probe r0-demo r0-second
   （缓存文件残留，但不在本次 pull 的返回里，所以不被扫描 —— 模型看不到）
移回来 + refresh → 9，d_probe 回来了
```

#### ⑥ 走**真实的界面写入接口**跑完整闭环（最有说服力的一条）

```
$ curl -X POST <临时api>/api/chat/skills -H 'authorization: Bearer <自签 JWT>' \
    -d '{"name":"端到端探针二号","slug":"d_probe2",…,"body":"探针二号口令是 `D-SKILL-888`。"}'
{"ok":true,"key":"d_probe2","synced":true,"skill_count":10}
real    0m0.164s

$ curl -s http://127.0.0.1:3931/skill          # 没有再手动 refresh，api 已经替我们刷过了
10 个，含 d_probe2 · location=/home/hunter/.cache/opencode/skills/d_probe2/SKILL.md
content: 探针二号口令是 `D-SKILL-888`。

$ curl -X DELETE <临时api>/api/chat/skills/d_probe2 -H 'authorization: Bearer …'
{"ok":true,"synced":true,"skill_count":9}
real    0m0.047s
删除后 d_probe2 还在吗: False · 共 9 个
```

**这一条就是判定线**（「api 装 SKILL 后模型 60 秒内可见」）：实测 **0.164 秒**，余量三个数量级。
第一次跑这条时是 30.07 秒且报 `synced:false` —— 见第六节的自锁 bug。

#### ⑦ 顺带测了「api 不可达时会怎样」

```
docker stop m1d-api
POST /skill/refresh   → 39.49 秒（内部重试），返回 8
GET  /skill           → d_probe 不在列表里（缓存文件仍在盘上，只是没被扫）
docker start m1d-api；POST /skill/refresh → 9，d_probe 自动回来
```

结论：api 挂掉期间，**用户 SKILL 会临时从模型的能力列表里消失**（内置 SKILL 不受影响，它们在本地目录里），
api 恢复后一次 refresh 就自愈。不会丢数据，但 refresh 会慢到 40 秒。见第八节遗留问题。

#### ⑧ 收尾（预发栈已还原，未动其它任何东西）

```
$ curl -s -X PATCH http://127.0.0.1:3931/global/config -d '{"skills":{"urls":[]}}'   → 200
$ curl -s -X POST http://127.0.0.1:3931/skill/refresh                                 → 8
$ curl -s http://127.0.0.1:3931/global/config | …  → skills = {"urls": []}
$ docker rm -f m1d-api                                                                → m1d-api
$ docker ps | grep hunter-staging
  opencode / web / api / postgres / redis / llm-shim  全部 Up 40 minutes (healthy)
$ curl -so/dev/null -w '%{http_code}' http://127.0.0.1:8200/api/health                → 200
```

> 注：验证前预发栈的 `skills.urls` 是 R0 留下的 `["http://r0skills:8080/"]`，
> 而那个静态文件服务容器早已不存在（所以 R0 的 `r0-demo` / `r0-second` 本来就拉不到了）。
> 按任务要求还原成 `[]`。

---

## 八、遗留问题

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| 1 | **opencode 缓存盘会积累已删除 SKILL 的残留目录**。`~/.cache/opencode/skills/` 下删掉的 SKILL 目录不会被清理（`Discovery.pull` 只管下载与换版，不做清理） | 只占磁盘，**不影响正确性**（不在 pull 返回值里就不被扫描）。按单 SKILL 上限 200 文件 × 5 MB 估，残留量与用户装过的 SKILL 总量同阶 | 不在 M1 修。要修得改 huntercode（清理不在清单里的目录），或在 opencode 入口脚本里启动时清空缓存目录——后者代价是每次重启全量重下 |
| 2 | **api 不可达时 `POST /skill/refresh` 要 39 秒**（opencode 内部对 HTTP 有重试退避），且期间用户 SKILL 从能力列表消失 | 只在 api 真的挂了时出现，而那时用户本来也用不了别的功能 | 不修。但 M2 的向导「环境自检」把 api↔opencode 双向连通性列进去是值得的 |
| 3 | `HUNTER_INTERNAL_KEY` 会明文出现在 opencode 的全局配置文件 `~/.config/opencode/opencode.jsonc` 里 | 与现状一致（`GET /config` 本来就明文回显 `apiKey`，见 R0 §1.5）。该文件在容器可写层，recreate 即消失 | 与 R0 的结论一致：**向导前端不要直接代理 opencode 的 `/config`** |
| 4 | 导出接口没有做速率限制 | 它在内网、且需要口令；`/api/internal/*` 其它接口也都没做 | 与其它 internal 接口保持一致，不单独加 |
| 5 | **子任务 C 需要注意**：`opencode_admin.apply_llm()` 若也从 `async def` 里同步调 `PATCH /global/config`，而 opencode 重建实例时会回头拉 api 的 `/api/internal/runtime/llm`，就是第六节同一个死锁 | 向导「保存大模型配置」会挂 30 秒然后报失败 | 同样用 `run_in_threadpool`（或把 `opencode_admin` 改成 async httpx） |
| 6 | 本次未验证「opencode 容器**冷启动**时从 URL 拉取」 | 实测走的都是 `POST /skill/refresh` 热路径。冷启动路径走的是同一个 `Discovery.pull`（`skill/index.ts` 的 `state` 首次求值），但确实没有实跑 | 子任务 C 把 `skills.urls` 写进 gen-config 之后，用完整 compose 冷启动跑一次确认 |

---

## 九、给评审的自查清单

- [x] `version` = 全部文件内容 sha256，内容不变则不变（含「只改 mtime」）
- [x] `files` 必含 `SKILL.md`，无 `SKILL.md` 的目录既不进清单、也不可访问
- [x] `secrets.compare_digest` 常数时间比较；空口令 → 接口整体 404；不匹配 → 404 而非 401
- [x] `Path.resolve()` 后确认仍在 SKILL 目录内；`..` / 绝对路径 / 软链外指 一律 404（有单测）
- [x] 只导出用户 SKILL，内置 SKILL 不导出（有单测）
- [x] 单文件 5 MB、单 SKILL 200 文件上限，超了跳过 + warning
- [x] 跳过 `__pycache__` / `.git` / 隐藏文件 / 符号链接
- [x] 导出直读磁盘，不走 `_cache`
- [x] 所有写用户 SKILL 的路径都调了 `refresh_skills()`（核对了新建 / 编辑 / 删除 / 装仓库 / 暂存区落盘 5 条，无遗漏）
- [x] 文档、注释、日志、提交信息里没有任何密钥明文
- [x] 未改 `docker-compose*.yml` / `Dockerfile` / `deploy/**` / `db/**` / `boot.sh` / `migrate.py` / `runtime_config.py` / `opencode_admin.py` / `scripts/**` / `.github/**`
