# M1 · 子任务 C 交付说明 · 配置与密钥

> 分支 `m1/c-config`(本地,未 push)· 完成于 2026-09-17
> 对应设计方案 [`design.md`](./design.md) 3.2 / 3.3,以及 [`R0-预研结论.md`](./R0-预研结论.md) 第一节
> 目标:**不建 `.env` 也能起来,配置存数据库,环境变量非空时优先且锁定**
>
> 全文不含任何密钥明文。示例一律写成 `sk-****`。

---

## 一、做了什么

| 文件 | 改动 |
|---|---|
| `apps/api/boot.sh` | 填上「① 密钥」段:环境变量非空 → `hunter_secrets` 卷 → 本次生成;弱密钥告警;写不进卷时降级继续 |
| `scripts/opencode/load-secrets.sh`(新增) | opencode 侧读同一份 `secrets.env`,供 `entrypoint.sh` `.`(source) |
| `apps/api/app/services/runtime_config.py`(新增) | 大模型配置的唯一读取入口:环境变量非空 → 数据库(30 秒缓存、api_key 加密) |
| `apps/api/app/routers/internal_runtime.py`(新增) | `GET /api/internal/runtime/llm`,给 opencode 容器拉配置 |
| `apps/api/main.py` | 只加注册这一处 |
| 10 个读 `LLM_*` 的文件 | 一律改走 `runtime_config.llm()`;**删掉硬编码的演示站网关与模型名**(见第二节) |
| `scripts/opencode/gen-config.py` | 三种来源都能启动;按 R0 结论分两处写配置;写 `skills.urls` |
| `scripts/opencode/entrypoint.sh` | 取子任务 A 的版本 + 两处小改(见交接事项) |
| `scripts/llm-shim/shim.py` | 免配置启动;上游取请求头;地址白名单;未配置立刻回中文错(含流式) |
| `scripts/llm-shim/schema_clean.py`(新增) | schema 清洗规则抽出来,shim 与(M2 的)api 共用一份 |
| `scripts/llm-shim/test_shim.py` | 8 → 23 条 |
| `apps/api/app/services/opencode_admin.py` | 新增 `apply_llm()`(`PATCH /global/config`),没动 `refresh_skills()` |
| `apps/api/tests/test_runtime_config.py`(新增) | 16 条,monkeypatch 打桩数据库 |

### 1.1 密钥(设计方案 3.2)

优先级 **环境变量非空 → `/opt/hunter-secrets/secrets.env` → 本次生成**。
判断一律用「非空」——— compose 的 `${X:-}` 会把「用户没设」注入成空字符串。

- 生成:`openssl rand -base64 48 | tr -d '\n=+/'`(**实测确认** api 镜像
  `python:3.11-slim` 自带 `/usr/bin/openssl`),没有 openssl 时退回
  `python3 -c 'import secrets;print(secrets.token_urlsafe(48))'`。
  去掉 `+/=` 是为了让值能被 `sh` 的 `.` 直接读。实测长度 61~64(要求 ≥48)。
- `secrets.env` 格式就是 `KEY=value` 每行一个,没有引号、没有注释,可 `source`。
- **属主 `1001:1001` + 权限 `640`**(不是 600):api 以 root 跑、opencode(hunter)
  与 web(nextjs)都是 uid 1001。600+root 会让后两者读不到,表现是「对话莫名 401」
  「上传图片没反应」。`chown` 失败(只读挂载 / K8s 限制)降级成 644 并告警。
- **弱密钥**(等于 `.env.example` 的 `change-me-in-production-please`,或长度 < 32):
  打 `ERROR` 说清风险(它派生了加密已存 key 的 AES 密钥)与处理办法,
  **不自动轮换、不退出** —— 轮换会让已加密的 key 全部解不开、登录全部失效。
- 卷写不进:报清楚原因后**继续启动**(用内存里的值),并警告重启后密钥会变。
  另外用 `df` 认出「目录其实在容器可写层上」(压根没挂卷)这种更隐蔽的情况。
- 日志只打**来源与长度**,绝不打印密钥本身。

### 1.2 `runtime_config`(设计方案 3.3)

```python
llm() -> LLMConfig(base_url, api_key, model, sanitize, configured, source)
source(key) -> "env" | "db" | "none"     # key: base_url / api_key / model / sanitize
save_llm(cfg, tested_token=None) -> None
invalidate() -> None
env_locked() -> bool
```

- 键:`llm.base_url` · `llm.api_key`(`crypto.encrypt`)· `llm.model` ·
  `llm.sanitize` · `llm.tested_at` · `setup.completed_at`。表沿用 `hunter_config`。
- **每一项独立判断**,支持「地址来自环境变量 + 模型来自数据库」的混合。
  整体 `source` 只有在三项**全部**来自环境变量时才是 `env`(这决定 gen-config
  把 provider 写到哪,见 1.4)。
- 三项都在环境变量里时**压根不查库** —— 老用户(含演示站)零行为变化、零新依赖。
- 数据库不可用、或 api_key 解密失败(`JWT_SECRET` 变过)→ 打 warning、按未配置处理,
  **不抛异常**(照抄 `hunter_key.resolve()`)。
- `save_llm` 的 `tested_token` **留了参数但不校验**,注释写明 M2 的
  `PUT /api/setup/llm` 会补上。M1 不造半成品 HMAC —— 那会给人「已经验过了」的错觉。

### 1.3 `GET /api/internal/runtime/llm`

鉴权照抄 `internal_tools._auth`(`HUNTER_INTERNAL_KEY`)。返回
`{configured, source, base_url, api_key, model, sanitize}`,**api_key 是明文**:
opencode 拿它去调网关,打码等于这个接口白做。暴露面与改造前一致(三个容器都不
对外映射端口;改造前这把 key 本来就明文写在 `opencode.json` 里、`GET /config`
也明文回显,见 R0 §1.5)。**向导前端不要代理这个接口**,M2 用 `/api/setup/status`
给打码值。

### 1.4 `gen-config.py`

取配置:环境变量三项非空 → `GET /api/internal/runtime/llm`(10 秒超时、最多 3 次、
401 立即放弃)→ 都没有则占位。**三种情况都写 provider**:不写时 opencode 会回落到
内置 OpenCode Zen,把用户的问题发给第三方免费模型。未配置时 provider 指向
llm-shim、模型名 `hunter-unconfigured`。

| 内容 | 写到哪 |
|---|---|
| `mcp` · `instructions` | 项目 `/opt/opencode-workspace/opencode.json` |
| `provider`/`model`,来源 **env** | 项目文件(优先级最高 = 环境变量锁定) |
| `provider`/`model`,来源 **db / none** | 全局 `/home/hunter/.config/opencode/opencode.jsonc` |
| `skills.urls` | 全局文件(`HUNTER_INTERNAL_KEY` 为空时不写) |

全局文件**每次启动整份重写**:既清掉来源切回 env 时的残留,也清掉
`PATCH /global/config`(mergeDeep)累积下来的旧模型名。
全局路径取 `$XDG_CONFIG_HOME/opencode/opencode.jsonc`、回落 `~/.config/...`;
**实测**容器内 `XDG_CONFIG_HOME` 为空、真实路径就是
`/home/hunter/.config/opencode/opencode.jsonc`,且对 uid 1001 可写。

### 1.5 llm-shim

- 启动不再要求 `LLM_BASE_URL`(否则健康检查过不去 → opencode 因 `depends_on` 起不来
  → 用户连首页都打不开)。
- 上游:请求头 `X-Hunter-Upstream` → 环境变量 `LLM_BASE_URL`。
- **地址白名单**(安全关键):只允许 `http/https`;拒绝内部服务名
  (`api`/`web`/`postgres`/`redis`/`opencode`/`llm-shim`)、回环(`127/8`、`::1`、
  `localhost`)、链路本地(`169.254/16`,含云元数据 `169.254.169.254`)、私有网段
  (`10/8`、`172.16/12`、`192.168/16`、IPv6 ULA)、保留与组播地址。
  **解析一次 DNS 再判断 IP** —— 只看字符串挡不住「公网域名解析到 127.0.0.1」。
  一组解析结果里只要有一条命中就拒绝。
- **`LLM_SHIM_ALLOW_PRIVATE=1`**(默认关)放行回环与内网上游,给自建内网网关用。
  它**不放行**内部服务名与链路本地地址 —— 前者没有一个是大模型网关,后者能吐出
  云实例凭证。
- 未配置(模型名是 `hunter-unconfigured`,或没有可用上游)→ **立刻**回
  OpenAI 兼容错误,不等上游超时(R0 §1.5:上游不可达时对话挂住 100 秒以上)。
  非流式 400 + `{"error":{"message":...}}`;流式 200 + 合法 SSE(一条正文帧带中文、
  一条 `finish_reason:stop`、`[DONE]`)。用正文帧是因为任何 OpenAI 兼容客户端都会把
  它渲染成回答文字,用户直接看得见;只发 `error` 帧的话不同 SDK 处理不一,最坏是
  前端一片空白 —— 而「一片空白」正是要消灭的症状。

**文案(以不撒谎为准)**:M1 还没有向导页面,所以不写「打开首页完成初始化向导」:

> 大模型尚未配置:这套部署还没有可用的大模型地址。请在部署环境里填好
> `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_DEFAULT_MODEL` 后重启,或等初始化向导
> 上线后在首页完成配置。

M2 向导上线后把后半句换成「请打开首页完成初始化向导」。

### 1.6 `opencode_admin.apply_llm()`

见第三节(偏离项)与代码注释。M1 只给服务函数,**不暴露 HTTP 接口**。

---

## 二、⚠️ 删掉硬编码的演示站网关地址(单独一节)

改造前,这 10 个文件里有 **8 处**把 `LLM_BASE_URL` 的默认值写成了

```
http://104.197.139.51:3000/v1
```

**那是我们自己演示站的网关地址。** 开源用户没有配 `LLM_BASE_URL` 时,他的股票
代码、持仓、对话内容会被发到我们的服务器上 —— 用户完全无从知晓,日志里也只会显示
一个「connection refused」或「401」。

出现位置(全部已删):

| 文件 | 处数 |
|---|---|
| `app/services/online_analysis/llm_client.py` | 1 |
| `agents/sentinel/llm_client.py` | 1 |
| `agents/sentinel/thesis_gen.py` | 1 |
| `agents/bull_researcher.py` | 1 |
| `agents/bear_researcher.py` | 1 |
| `agents/risk_perspectives.py` | 1 |
| `agents/translation.py` | 2(`ensure_chinese` / `translate_desc`) |

同时删掉的模型名硬编码默认:`gemini-3.5-flash`(6 处)、`gpt-4o-mini`(1 处,
`app/providers/llm/__init__.py`)。猜一个模型名只会让配了 DeepSeek 的用户收到一个
看不懂的 404,比「尚未配置」更难排查。

**现在的规则:没配就是没配**(`configured=False`),各调用方走自己原有的
「暂不可用 / 503 / 返回 None」分支,文案统一成「大模型尚未配置 · 请填
`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_DEFAULT_MODEL`,或在首页完成初始化向导」。

> **本次范围之外、但同样有问题**:`apps/api` 里还有 **11 处** `ONE_API_BASE_URL`
> 的默认值也是这个地址(逐条核对过):
> `app/services/attribution.py:251` · `app/services/signal_monitor.py:466,526` ·
> `app/services/online_analysis/thesis_gen.py:15` ·
> `app/routers/research_assistant.py:197,231` · `app/routers/gm/research.py:35` ·
> `app/routers/gm/assistant.py:83` · `app/routers/gm/recap.py:159` ·
> `app/routers/gm/guardian.py:27` · `scripts/test_oneapi_gateway.py:34`。
> 它们只读 `ONE_API_*`、不在本子任务的 10 个文件里,**没有改**。
> 复现命令:`grep -rn "104\.197\.139\.51" --include=*.py apps/api`。
> 建议单独开一个清理任务,见第七节遗留问题。

---

## 三、偏离设计方案的地方与原因

### 3.1 热生效改用 `PATCH /global/config`(设计方案 3.3 写的是 `PATCH /config`)

R0 实测:`PATCH /config` 返回 200、也确实写出了 `<实例目录>/config.json`,但**那个
文件根本不在配置加载路径上**,内容永不生效。`PATCH /global/config` 走
`Config.updateGlobal`:写全局文件 + `invalidate()` 清缓存 + 销毁全部实例,才真的生效
(端到端 7.42 / 7.87 秒,6/6 MCP 重连)。`apply_llm()` 按后者实现,R0 的实测数字写进
了函数注释。

### 3.2 gen-config 分两处写(设计方案只说写 `opencode.json`)

同样出自 R0:配置合并顺序是「全局 < `OPENCODE_CONFIG` < 项目 `opencode.json(c)` <
`.opencode/opencode.json(c)`」,而 `PATCH /global/config` 只改**全局**文件。
所以只有把 `provider`/`model` 写进全局文件,向导才改得动;而「环境变量锁定」正好
靠把它写进**项目**文件来实现 —— 项目文件优先级更高,向导即使误调也盖不住。
代价是多一个文件要维护,好处是锁定语义不需要任何额外代码。

### 3.3 `apply_llm()` 保持同步函数

与既有 `refresh_skills()` 风格一致。代价:**async 调用方必须
`await run_in_threadpool(apply_llm, cfg)`**,直接在 `async def` 里调会把单 worker 的
uvicorn 事件循环整个堵住(子任务 D 已在 `/skill/refresh` 上踩过一次:卡满 30 秒超时,
而文件其实早写好了)。这一条写进了函数 docstring,也列在下面的交接事项里。

### 3.4 `screen_nl.py` 的模型锁按「是不是 gemini」分流

仓内铁律要求这里锁死 `gemini-3.5-flash`(3.6/3.8 对恰好 2 条消息的短对话返 400)。
但对配了 DeepSeek / OpenAI 的开源用户,这个锁等于把一个这套部署根本没有的模型名发
出去,「AI 识别」永远 404。现在:**当前生效的模型名含 `gemini` 时仍然锁
`gemini-3.5-flash`(演示站与内部部署逐位不变)**,否则用用户自己配的模型;
需要强制指定时设 `SCREEN_NL_MODEL`。铁律本身没有被去掉。

### 3.5 `providers/llm` 的单例改成「按配置内容缓存」

原来是进程级单例,配置在运行时被向导改掉之后必须重启容器才生效 —— 而「不用重启」
正是向导的卖点。现在缓存键是 `(provider, base_url, api_key, model)`,内容一变就重建。

### 3.6 `LLM_PROVIDER=anthropic` 的 `claude-sonnet-4-6` 默认保留

它不是「猜一个网关地址/模型名」:走 anthropic 直连时模型命名空间是确定的,而且这是
文档里写明的可选默认。其余所有默认值都删了。

---

## 四、测试:真实命令与输出

全部在容器里真跑过,下面是命令原文与输出摘要(未编造)。

### 4.1 llm-shim 单测(8 → 23 条)

```
$ docker run --rm -v "$PWD/scripts/llm-shim:/t" -w /t python:3.12-alpine \
      python3 -m unittest discover -p 'test_*.py' -v
...
Ran 23 tests in 0.693s

OK
```

新增覆盖:上游白名单的放行/拒绝(协议、内部服务名、回环、链路本地+云元数据、
私有网段、IPv6 `::1` 与 ULA、DNS 解析不了、多条 A 记录里有一条落内网、
`allow_private` 开关)、未配置时的错误体(非流式 + 流式 SSE)、占位模型名即使有上游
也拒发、`X-Hunter-Upstream` 覆盖环境变量且同样要过白名单、schema 清洗抽出后行为不变。

> 已有的两条流式用例现在要显式 `patch.object(shim, "ALLOW_PRIVATE", True)` ——
> 它们的上游是 `127.0.0.1`,正好证明默认拦得住。
> 踩到一个坑写进了用例注释:`patch socket.getaddrinfo` 会连测试自己的 HTTP 客户端
> 一起改道,有一条用例因此真的把请求发到了公网(已改)。

### 4.2 `runtime_config` 单测(16 条)

```
$ docker run --rm -v "$PWD/apps/api:/src" -w /src -e JWT_SECRET=ci-test-secret \
    -e DATABASE_URL=postgresql://placeholder@localhost/placeholder \
    --entrypoint sh ghcr.io/agentpit-io/hunter-community-api:latest \
    -c 'pip install -q pytest pytest-asyncio; python -m pytest tests/test_runtime_config.py -q'
................                                                         [100%]
```

覆盖:环境变量优先 / 空串与纯空白不算配置 / 数据库来源 / 都无 / 单项混合来源 /
部分配置不算 configured / 缓存命中与 `invalidate` / 三项全在环境变量时**不查库** /
数据库抛异常时不炸 / sanitize 默认与大小写 / `save_llm` 加密入库并失效缓存。

> ⚠️ 只跑这一个文件,别跑整个 `tests/` —— `tests/test_screen_fix.py` 在 import 阶段
> 就 `sys.exit()`,会把整个 pytest 搞崩。那是既有问题,不是本次引入的。

### 4.3 既有回归(改了 `screen_nl.py`,按仓内铁律必须跑)

```
$ ... --entrypoint sh <api 镜像> -c 'PYTHONPATH=. python tests/test_screen_fix.py; \
                                     PYTHONPATH=. python tests/test_screen_kw.py'
ALL OK
ALL OK
```

### 4.4 `python -m compileall`

```
$ docker run --rm -v "$PWD/apps/api:/src" -w /src --entrypoint sh <api 镜像> \
      -c 'python -m compileall -q app main.py agents && echo "compileall OK"'
compileall OK
```

### 4.5 `boot.sh` 密钥段 · 7 个用例(api 镜像里真跑)

做法:`sed` 掉 migrate / uvicorn 两行,只跑密钥段,再 `ls -l` 与打指纹(不打印明文)。

| 用例 | 结果(日志原文节选) |
|---|---|
| 空卷、无环境变量 | `来源=本次生成 长度=61 · 密钥卷可写(… · 属主 1001:1001 · 权限 640)`;`-rw-r----- 1 1001 1001` |
| 再跑一次 | `来源=密钥卷 长度=61`,值不变(指纹一致) |
| 环境变量非空 | `来源=环境变量 长度=45`,并写回卷 |
| `JWT_SECRET=change-me-in-production-please` | 5 行 `ERROR`(风险 + 后果 + 处理),**继续启动** |
| `JWT_SECRET=short` | `ERROR JWT_SECRET 只有 5 个字符(建议 ≥48,至少 32)`,继续启动 |
| 密钥卷只读挂载 | `⚠ 写不进 …` + 4 行 ERROR(重启后密钥会变、已存 key 解不开),继续启动 |
| 没挂卷 | `WARN … 在容器可写层上,没有挂 hunter_secrets 卷`,继续启动 |

opencode 镜像里 `. load-secrets.sh` 实测:`uid=1001(hunter)` 读得到 640 的文件,
输出 `[load-secrets] JWT_SECRET 来源=密钥卷 长度=… · HUNTER_INTERNAL_KEY 来源=密钥卷 长度=…`。

### 4.6 `gen-config.py` 三种来源(opencode 镜像里真跑,两个文件都 cat 出来核对)

```
$ docker run --rm -v "$PWD/scripts/opencode:/opt/hunter-boot:ro" \
    -v "$PWD/scripts/opencode-mcp:/opt/hunter-mcp:ro" [环境变量…] \
    --entrypoint sh ghcr.io/agentpit-io/hunter-opencode:1.18.12-slim.1 \
    -c 'python3 /opt/hunter-boot/gen-config.py; cat /opt/opencode-workspace/opencode.json; \
        cat $HOME/.config/opencode/opencode.jsonc'
```

| 用例 | 日志 | 项目文件 | 全局文件 |
|---|---|---|---|
| A · 三项环境变量 | `配置来源:环境变量` · `provider/model 写在项目文件(环境变量锁定,向导改不动)` | 有 provider/model + instructions + mcp | 只有 `$schema` + `skills.urls` |
| B · 假 api 返回 db 配置 | `配置来源:数据库(初始化向导)` | instructions + mcp,**没有** provider | provider/model(kimi-k2)+ skills.urls |
| C · 一项都没配、api 也连不上 | 三次重试日志 + `配置来源:尚未配置` + 一段中文提示 | instructions + mcp | provider → `http://llm-shim:3999/v1`,`model: hunter-llm/hunter-unconfigured` |
| D · 来源 env,但全局文件里预置了残留 `hunter-llm/stale-model` | `配置来源:环境变量` | 有 provider/model | **被整份清成 `{"$schema": ...}`** |
| E · 密钥全链路(`load-secrets.sh` + 空环境变量 + 密钥卷) | `[load-secrets] … 来源=密钥卷` → gen-config 用卷里的 key 拼出 `skills.urls` | — | `skills.urls` 里带的是卷里的 internal key |

### 4.7 `GET /api/internal/runtime/llm`(真起 FastAPI app)

```
无口令: 401
带口令: 200 {'configured': False, 'source': 'none', 'base_url': '', 'api_key': '', 'model': '', 'sanitize': 'auto'}
配好后: 200 {'configured': True, 'source': 'env', 'base_url': 'https://api.deepseek.com/v1',
             'api_key': 'sk-****', 'model': 'deepseek-chat', 'sanitize': 'auto'}
```

### 4.8 llm-shim 免配置启动 + 健康检查(compose 用的那条命令)

```
[shim] listening 0.0.0.0:3999/v1 -> (环境变量未配上游 · 等请求头 X-Hunter-Upstream)
healthcheck → b'{"ok":true}'
非流式 → 400 {"error": {"message": "大模型尚未配置:…", "type": "invalid_request_error",
                        "code": "hunter_unconfigured", "param": null}}
流式   → 200 · data:{…delta.content="大模型尚未配置:…"} / data:{…finish_reason:"stop"} / data:[DONE]
```

### 4.9 `apply_llm()`(假 opencode 桩)

`PATCH 路径: /global/config`;body 结构与设计方案一致;
`sanitize=auto` + gemini → `baseURL: http://llm-shim:3999/v1` 且带
`X-Hunter-Upstream`;`sanitize=0` → 直连用户地址、不带头;非 gemini + auto → 直连;
没有模型名 → `{'ok': False, 'reason': '大模型尚未配置(没有模型名),不推送'}`;
200 + HTML → `{'ok': False, 'reason': '当前 opencode 镜像不支持热更新配置(未知路由被 SPA 接管)'}`;
opencode 连不上 → `{'ok': False, 'reason': '连不上 opencode(ConnectError)'}`,不抛异常。

### 4.10 10 个文件的解析结果(探针脚本)

在 api 镜像里逐个 import 并调用,确认:配了三项时 10 处都拿到
`(https://api.deepseek.com/v1, sk-****, deepseek-chat)`;清空后
`get_client()` 返回 `None`、`_resolve_llm()` 返回 `('', '', '')`、
`providers.llm.get_llm()` 抛「大模型尚未配置:缺 base_url…」;
`screen_nl.model_name()` 在 gemini 下给 `gemini-3.5-flash`、在 deepseek 下给
`deepseek-chat`。**没有任何一处再指向 104.197.139.51。**

### 4.11 没做到 / 没测到的

- **没有跑起完整的 6 容器 compose 冷启动**:`docker-compose.yml`、`Dockerfile`、
  `app/migrate.py` 都在别的子任务手里,本分支上的 compose 仍是旧的(`JWT_SECRET`
  用 `:?` 强制、api 的 `CMD` 还是 uvicorn、没有 `hunter_secrets` 卷)。
  所有验证都是**单容器 + 挂载本分支文件**的方式做的。端到端冷启动要等合并后。
- **没有对真实网关发过一次请求**:`apply_llm` 与 gen-config 的 db 分支都是打桩验证。
  R0 已经在预发栈上实测过 `PATCH /global/config` 的真实耗时,本次没有重复。
- **没有测过 `LLM_SHIM_ALLOW_PRIVATE=1` 连真实内网网关**(手头没有)。
  逻辑由单测覆盖。

---

## 五、给合并者的交接事项

1. **`scripts/opencode/entrypoint.sh` 我已经改了,注意与子任务 A 的版本合并。**
   我是**以 A 分支的版本为基础**改的(含 A 加的 `/home/hunter/.local` 可写自检),
   加了两处:
   - 开头 `. /opt/hunter-boot/load-secrets.sh`(**必须 source,不能直接执行** ——
     直接执行的话 export 只作用于子进程,opencode 本体拿不到 `JWT_SECRET`,
     hunter-auth 插件验不了签,表现是对话莫名 401);
   - 修掉「本脚本是 bind mount 进容器的」那句过时注释(A 已改成 COPY 进镜像)。
   合并时**不要重复再加一次 source 那行**(重复其实无害,第二次读到的环境变量已非空,
   只会多打一行日志,但没必要)。

2. **web 容器也需要同一个 `HUNTER_INTERNAL_KEY`。**
   `apps/web/app/api/opencode/[...path]/route.ts` 里是
   `process.env.HUNTER_INTERNAL_KEY || 'hunter-internal-local'`,它调 api 的
   `/api/internal/ocr/extract`。api 自动生成随机 key 之后,web 还用默认值就会 401,
   表现是「上传图片没反应」。web 的 Dockerfile 不在任何子任务范围内,需要你补:
   - compose 给 web 挂 `hunter_secrets:/opt/hunter-secrets:ro`;
   - web 入口脚本里 `. /opt/hunter-boot/load-secrets.sh`(或等价的几行 sh)。
   `secrets.env` 的契约:路径 `/opt/hunter-secrets/secrets.env`,属主 `1001:1001`,
   权限 `640`,内容是两行 `JWT_SECRET=…` / `HUNTER_INTERNAL_KEY=…`,
   值只含 `[A-Za-z0-9]`,可以直接 `.`(source)。web 镜像的 `nextjs` 也是 uid 1001,读得到。

3. **compose 里 `LLM_DEFAULT_MODEL` 的默认值要改掉。**
   现在是 `${LLM_DEFAULT_MODEL:-gpt-4o-mini}`(api 与 opencode 两处)。留着的话,
   容器里这个环境变量**永远非空**,`runtime_config` 会认为「模型来自环境变量、已锁定」,
   数据库里向导填的模型永远轮不到生效。必须改成 `${LLM_DEFAULT_MODEL:-}`。
   (`LLM_BASE_URL` / `LLM_API_KEY` 已经是 `:-`,没问题。)

4. **api 的 `boot.sh` 要真的被当成入口**(A 说 `CMD` 已经是 `/app/boot.sh`,确认一下),
   并且 api 对 `hunter_secrets` 卷要有**写**权限(不是 `:ro`),opencode / web 只读。

5. **`/api/internal/skills/<key>/` 这个 URL 是我写进全局配置的**(子任务 D 提供接口)。
   如果 D 最终的路径形状不是这个,改 `scripts/opencode/gen-config.py` 的
   `_global_config()` 一处即可。**末尾那个 `/` 不能少** —— `Discovery.pull` 用
   `new URL("index.json", base)` 拼地址,少一个斜杠会把最后一段路径吃掉。

6. **`GET /api/internal/runtime/llm` 返回明文 api_key**,这是故意的(opencode 要用)。
   合并时确认三件事仍然成立:api / opencode / llm-shim 都不映射宿主端口;
   web 不代理 `/api/internal/*`;向导前端不直接读这个接口。

---

## 六、给 M2 的交接事项

1. **`apply_llm()` 是同步函数,`async def` 里必须
   `await run_in_threadpool(apply_llm, cfg)`。** api 是单 worker uvicorn,
   直接调会把事件循环堵死。
2. **「保存后轮询就绪」同样必须 `run_in_threadpool`。**
   `PATCH /global/config` 的实例销毁发生在响应之后,PATCH 这一下是安全的;但**下一个**
   打到 opencode 的请求会触发实例重建,重建时要走完整的 SKILL 发现流程,而
   `skills.urls` 会**回头来拉 api**。api 这边如果正被同步调用堵着,就是死锁:
   opencode 拉不到清单,api 等到超时,最后给用户一句「请重启 opencode」——
   而两边其实都好好的。子任务 D 已经在 `/skill/refresh` 上踩过一次(30.07 秒 → 0.164 秒)。
3. **就绪判定用「当前 `model` 等于新模型」**,不要用「models 列表只有一个」——
   `updateGlobal` 是 mergeDeep,旧模型名删不掉(R0 §1.5)。
4. **`save_llm(cfg, tested_token)` 的校验还没做。** M2 的 `PUT /api/setup/llm` 要补上
   「HMAC(地址 + 模型 + key 摘要),10 分钟有效」,并在 `env_locked()` 为真时返回 409。
5. **向导的「工具调用」检测请 `from schema_clean import clean_tools`**
   (`scripts/llm-shim/schema_clean.py`),不要再抄一份清洗规则。
6. **llm-shim 的未配置文案要跟着改**:M2 上线后把「或等初始化向导上线后在首页完成配置」
   换成「请打开首页完成初始化向导」(`shim.py` 的 `UNCONFIGURED_MSG` 一处)。

---

## 七、遗留问题

1. **11 处 `ONE_API_BASE_URL` 的演示站默认地址没清**(见第二节末尾的清单)。
   它们不在本子任务的 10 个文件里,但性质完全一样:开源用户没配 `ONE_API_BASE_URL`
   时,归因分析 / 信号监控 / 研究助手 / gm 系列接口会把数据发到我们的服务器。
   **建议尽快单独开一个任务清理**,改法与本次一致(改走 `runtime_config`)。
2. **`LLM_DEEP_MODEL` 等其余模型类环境变量没有入库**。它们仍然只读环境变量(保持原状),
   向导也不管它们 —— 与设计方案 2.2「不做模型切换以外的高级配置 UI」一致。
3. **`secrets.env` 里的值是明文落盘的**(权限 640 / 属主 1001)。这与 `.env` 明文躺在
   宿主机上是同一个量级的暴露面,但如果将来要支持「平台托管密钥」,这里要重新设计。
4. **环境变量提供的密钥也会被写回卷**。好处是用户以后从 `.env` 里删掉它们,值不会变、
   已加密的 key 仍解得开;代价是「我明明改了 `.env`」时要知道环境变量仍然优先(改了就生效),
   而删掉环境变量后用的是卷里的旧值。文档与日志都写了来源,排查时先看那一行。
5. **弱密钥只在启动时告警一次**。向导第 1 步的黄色警告(设计方案 4.3)属于 M2。
6. **没有跑通完整冷启动**(见 4.11),合并后需要按 M1 的验收标准再走一遍:
   不建 `.env` → `docker compose up -d` → 6 服务健康 → 首页可打开 → 发一条消息看到
   「大模型尚未配置」而不是空白或转圈。
