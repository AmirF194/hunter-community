"""首启向导 · `/api/setup/*`（设计方案 4.8 接口清单）。

`/api/internal/runtime/llm` 与 `/api/internal/skills/export` 是清单里的另外两条，
M1 已经实现（`routers/internal_runtime.py` / `routers/internal_skills.py`），
这里不重复。

## 鉴权

这个前缀走**自己的一套**，不走 `middleware/auth.py` 的 JWT：向导要在
「还没有任何账号、也还没配大模型」的状态下用。规则（`_guard`）：

  · 管理员 JWT（`request.state.user_role == "admin"`）→ 放行
  · 单用户模式下任何已登录用户 → 放行（那台机器上只有他一个人）
  · 初始化会话 token（`X-Hunter-Setup-Session`）→ 放行
  · 口令没配置 **且** 来源判为本机/内网 → 放行（`git clone && up -d` 的主路径）
  · 其余 → 401，前端跳第 0 步

**`/api/setup/` 必须加进 `middleware/auth.py` 的 `_PUBLIC_PREFIXES`**，
否则 JWT 中间件会在到这里之前就把请求拒掉。
加进公开前缀的同时，这里每个写接口都自己调 `_guard` —— 公开前缀下的写接口
如果不自己鉴权，就是"谁都能改"（仓内铁律：`/api/catalog/*` 那条）。

## 这个路由**绝不**做的两件事

1. **不回显 api key**。`/status` 只给打码值，`/llm-presets` 里没有 key。
2. **不代理 opencode 的 `/config`** —— 它会把 apiKey 明文回显（M1 遗留问题 #4）。
   要看当前模型就读 `runtime_config`。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from loguru import logger
from pydantic import BaseModel

from app.services import llm_probe, opencode_admin, runtime_config, setup_guard, setup_probe
from app.utils.crypto import mask

router = APIRouter(prefix="/setup", tags=["setup-wizard"])

SESSION_HEADER = "X-Hunter-Setup-Session"

# 预设清单随镜像走（Dockerfile: COPY data /opt/hunter-data）
PRESETS_PATH = Path(os.getenv("HUNTER_DATA_DIR", "/opt/hunter-data")) / "llm-presets.json"
# 仓库里直接跑时的回落路径。⚠️ 不写死层数:容器里模块路径只有 3 级父目录,
# 写死 parents[4] 会在**模块加载期** IndexError,整个 api 起不来。
PRESETS_FALLBACK = [p / "data" / "llm-presets.json"
                    for p in Path(__file__).resolve().parents]


def _single_user() -> bool:
    return (os.getenv("HUNTER_SINGLE_USER", "1") or "1").strip() not in ("0", "false", "no")


# ── 鉴权 ────────────────────────────────────────────────────────────
def _guard(request: Request) -> dict:
    """返回 {"via": ..., "source": Source}。不通过就抛 401（body 里带 need_unlock）。"""
    src = setup_guard.source_of(request)

    role = getattr(request.state, "user_role", None)
    uid = getattr(request.state, "user_id", None)
    if role == "admin":
        return {"via": "admin", "source": src}
    if uid and _single_user():
        return {"via": "single_user", "source": src}

    sess = request.headers.get(SESSION_HEADER, "")
    if setup_guard.session_valid(sess):
        return {"via": "setup_session", "source": src}

    if setup_guard.token_configured():
        raise HTTPException(401, {
            "need_unlock": True,
            "reason": "token_required",
            "message": "这台实例设置了初始化口令，请先输入口令",
        })
    if src.is_trusted_zone:
        return {"via": "local", "source": src}
    raise HTTPException(401, {
        "need_unlock": True,
        "reason": "no_token_public",
        "message": "检测到来自公网的访问，而这台实例没有设置初始化口令。"
                   "请在部署平台的环境变量里设置 HUNTER_SETUP_TOKEN，然后重启 api 容器。",
    })


# ── 1. 口令 ─────────────────────────────────────────────────────────
class UnlockIn(BaseModel):
    token: str = ""


@router.post("/unlock")
async def unlock(body: UnlockIn, request: Request):
    """校验初始化口令，签发 30 分钟的初始化会话。公开 + 限流 + 锁定。"""
    src = setup_guard.source_of(request)
    res = setup_guard.verify_token(body.token or "")
    if not res["ok"]:
        code = 423 if res["reason"] == "locked" else 400
        if res["reason"] == "not_configured":
            code = 409
        logger.warning("[setup] unlock 失败 · reason={} · 来源={}({})",
                       res["reason"], src.ip or "?", src.kind)
        raise HTTPException(code, {
            "reason": res["reason"],
            "message": res["message"],
            "locked_for": res["locked_for"],
        })
    token, ttl = setup_guard.issue_session()
    logger.info("[setup] unlock 成功 · 来源={}({}) · 会话 {} 秒", src.ip or "?", src.kind, ttl)
    return {"ok": True, "session": token, "expires_in": ttl}


# ── 2. 状态 ─────────────────────────────────────────────────────────
@router.get("/status")
async def status(request: Request):
    """向导与对话页共用的一张状态表。**不含任何 key 明文。**

    `/chat` 靠 `llm.source == "none" && !setup.completed_at` 决定要不要跳向导。
    """
    src = setup_guard.source_of(request)
    token_cfg = setup_guard.token_configured()

    # 未鉴权也要能回答「要不要进向导 / 要不要先输口令」—— 否则前端无从判断。
    # 这一段**只暴露布尔量**，不含地址、不含 key。
    try:
        gate = _guard(request)
        authed, via = True, gate["via"]
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, dict) else {}
        cfg_min = runtime_config.llm()
        return {
            "authed": False,
            "need_unlock": True,
            "unlock_reason": detail.get("reason", "token_required"),
            "message": detail.get("message", ""),
            "token_configured": token_cfg,
            "locked_for": setup_guard.lock_remaining(),
            "llm": {"source": cfg_min.source, "configured": cfg_min.configured},
            "setup": {"completed_at": runtime_config.get_str(runtime_config.K_SETUP_DONE)},
            "single_user": _single_user(),
        }

    cfg = runtime_config.llm()
    done_at = runtime_config.get_str(runtime_config.K_SETUP_DONE)
    hunter_key_state = _hunter_key_state()

    return {
        "authed": authed,
        "via": via,
        "need_unlock": False,
        "token_configured": token_cfg,
        "locked_for": 0,
        "single_user": _single_user(),
        "source": src.to_dict(),
        "llm": {
            "configured": cfg.configured,
            "source": cfg.source,                 # env / db / none
            "base_url": cfg.base_url,
            "model": cfg.model,
            "sanitize": cfg.sanitize,
            "api_key_masked": mask(cfg.api_key) if cfg.api_key else "",
            "env_locked": runtime_config.env_locked(),
            "locked_items": {k: runtime_config.source(k)
                             for k in ("base_url", "api_key", "model")},
            "tested_at": runtime_config.get_str(runtime_config.K_TESTED_AT),
        },
        "data_supply": hunter_key_state,
        "setup": {
            "completed_at": done_at,
            # 该不该自动进向导：没配大模型、也没人说过「稍后配置」
            "should_run": (not cfg.configured) and (not done_at),
        },
    }


def _hunter_key_state() -> dict:
    """平台 key 的配置状态（第 4 步用）。**不校验、不打网络** —— status 要快。"""
    try:
        from app.services import hunter_key
        k = hunter_key.resolve()
        return {"configured": bool(k), "masked": hunter_key.masked(k),
                "env_locked": hunter_key.env_locked(),
                "apply_url": hunter_key.APPLY_URL}
    except Exception as e:  # noqa: BLE001
        logger.warning("[setup] 读平台 key 状态失败: {}", e)
        return {"configured": False, "masked": "", "env_locked": False, "apply_url": ""}


# ── 3. 环境自检 ─────────────────────────────────────────────────────
@router.get("/env-check")
async def env_check(request: Request):
    """第 1 步。探测里有同步 socket / httpx，放线程池，别堵事件循环。"""
    gate = _guard(request)
    return await run_in_threadpool(setup_probe.run, gate["source"],
                                   setup_guard.token_configured())


# ── 4. 预设 ─────────────────────────────────────────────────────────
@router.get("/llm-presets")
async def llm_presets(request: Request):
    _guard(request)
    for p in (PRESETS_PATH, *PRESETS_FALLBACK):
        try:
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("[setup] 读预设 {} 失败: {}", p, e)
    # 读不到就如实说没有，**不要在代码里内置一份**（两处数值迟早会不一致）
    return {"updated_at": "", "source_doc": "", "presets": [],
            "error": f"读不到预设文件（镜像里应在 {PRESETS_PATH}）"}


# ── 5. 三项检测 ─────────────────────────────────────────────────────
class TestIn(BaseModel):
    base_url: str
    api_key: str = ""
    model: str


@router.post("/llm/test")
async def llm_test(body: TestIn, request: Request):
    _guard(request)
    slot = setup_guard.take_test_slot()
    if not slot["ok"]:
        raise HTTPException(429, {"message": slot["message"], "retry_after": slot["retry_after"]})

    base_url = (body.base_url or "").strip().rstrip("/")
    model = (body.model or "").strip()
    api_key = (body.api_key or "").strip()

    if not base_url or not model:
        raise HTTPException(400, {"message": "地址和模型名都要填"})
    if not base_url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, {"message": "地址要以 http:// 或 https:// 开头"})

    # ⚠️ 已保存的 key 不回显给前端，所以「只改模型名、不重填 key」时前端会送空 key。
    # 空 key 时取库里那把（环境变量优先），让用户不必重新粘贴。
    if not api_key:
        cur = runtime_config.llm()
        api_key = cur.api_key
        if not api_key:
            raise HTTPException(400, {"message": "请填写 API key"})

    res = await run_in_threadpool(llm_probe.run_all, base_url, api_key, model)
    res["test_token"] = (setup_guard.issue_test_token(
        base_url, model, api_key, res.get("sanitize_suggest") or "") if res["ok"] else "")
    res["test_token_ttl"] = setup_guard.TEST_TOKEN_SECONDS if res["ok"] else 0
    logger.info("[setup] 检测完成 · ok={} · 共 {} ms · base={} model={}",
                res["ok"], res["elapsed_ms"], base_url, model)
    return res


# ── 6. 保存 ─────────────────────────────────────────────────────────
class SaveIn(BaseModel):
    base_url: str
    api_key: str = ""
    model: str
    sanitize: str = ""
    test_token: str = ""


@router.put("/llm")
async def llm_save(body: SaveIn, request: Request):
    _guard(request)
    if runtime_config.env_locked():
        locked = [k for k in ("base_url", "api_key", "model")
                  if runtime_config.source(k) == "env"]
        raise HTTPException(409, {
            "message": "这台实例的大模型配置写在环境变量里（"
                       + "、".join({"base_url": "LLM_BASE_URL", "api_key": "LLM_API_KEY",
                                    "model": "LLM_DEFAULT_MODEL"}[k] for k in locked)
                       + "），向导改不了它。要换模型请改 .env 后 docker compose up -d。",
            "locked_items": locked,
        })

    base_url = (body.base_url or "").strip().rstrip("/")
    model = (body.model or "").strip()
    api_key = (body.api_key or "").strip() or runtime_config.llm().api_key

    chk = setup_guard.verify_test_token(body.test_token or "", base_url, model, api_key)
    if not chk["ok"]:
        raise HTTPException(400, {"message": chk["message"], "reason": chk["reason"]})

    # 优先级:调用方明确指定 > 检测得出的建议(签在凭证里) > 默认。
    # 中间这一层是给「直接调接口」的人兜底的 —— 检测报文承诺「保存时会自动设为开」,
    # 网页端靠前端回传做到了,接口调用方不该因为少传一个字段就拿到相反的结果。
    sanitize = ((body.sanitize or "").strip().lower()
                or chk.get("sanitize_suggest") or runtime_config.SANITIZE_DEFAULT)
    if sanitize not in ("0", "1", "auto"):
        raise HTTPException(400, {"message": "schema 清洗开关只能是 0 / 1 / auto"})

    class _Cfg:
        pass
    cfg = _Cfg()
    cfg.base_url, cfg.api_key, cfg.model, cfg.sanitize = base_url, api_key, model, sanitize
    await run_in_threadpool(runtime_config.save_llm, cfg, body.test_token)
    return {"ok": True, "saved": {"base_url": base_url, "model": model,
                                  "sanitize": sanitize, "api_key_masked": mask(api_key)}}


# ── 7. 热生效 ───────────────────────────────────────────────────────
@router.post("/apply")
async def apply(request: Request):
    """把配置热推给 opencode。**必须 run_in_threadpool**（M1 交接第 1 条）。"""
    _guard(request)
    cfg = runtime_config.llm()
    if not cfg.configured:
        raise HTTPException(400, {"message": "大模型还没配置好，没有可以生效的内容"})
    res = await run_in_threadpool(opencode_admin.apply_llm, cfg)
    return {"ok": bool(res.get("ok")), "reason": res.get("reason", ""),
            "model": cfg.model,
            # R0 实测端到端 7.4~7.9 秒；这里只告诉前端"别急着判失败"
            "expect_ready_seconds": 10}


# ── 8. 就绪探测 ─────────────────────────────────────────────────────
def _probe_ready(model: str) -> dict:
    """问 opencode 当前生效的模型是不是我们刚推的那个。

    **判据是「当前 model 等于新模型」，不是「models 列表里有它」**（M1 交接第 3 条）：
    `updateGlobal` 是 mergeDeep，旧模型名会一直累积在列表里。

    同步 httpx，调用方负责丢线程池 —— 这个请求会触发 opencode 实例重建，
    重建时 SKILL 发现要回头拉 api，在事件循环里同步等就是死锁（M1 3.3）。
    """
    import base64

    import httpx
    url = os.getenv("OPENCODE_URL", "http://opencode:3901").rstrip("/")
    u, p = os.getenv("OPENCODE_SERVER_USERNAME", ""), os.getenv("OPENCODE_SERVER_PASSWORD", "")
    headers = {}
    if u or p:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()
    try:
        r = httpx.get(f"{url}/config", headers=headers, timeout=20.0)
    except Exception as e:  # noqa: BLE001
        return {"ready": False, "reason": f"连不上 opencode（{type(e).__name__}）"}
    if r.status_code != 200:
        return {"ready": False, "reason": f"opencode 返回 HTTP {r.status_code}"}
    try:
        d = r.json()
    except Exception:  # noqa: BLE001
        return {"ready": False, "reason": "opencode 返回的不是 JSON"}
    cur = d.get("model") if isinstance(d, dict) else None
    if isinstance(cur, str) and cur.endswith(f"/{model}"):
        return {"ready": True, "reason": "", "current": cur}
    return {"ready": False, "reason": "配置还在重新加载", "current": cur or ""}


@router.get("/engine-ready")
async def engine_ready(request: Request):
    _guard(request)
    cfg = runtime_config.llm()
    if not cfg.model:
        return {"ready": False, "reason": "大模型还没配置"}
    return await run_in_threadpool(_probe_ready, cfg.model)


# ── 9. 标记完成 ─────────────────────────────────────────────────────
class CompleteIn(BaseModel):
    skipped: bool = False


@router.post("/complete")
async def complete(body: CompleteIn, request: Request):
    """写 `setup.completed_at`。`skipped=True` 是「稍后配置」——
    同样写时间戳（否则每次打开对话页都会被弹回向导），但记明是跳过的。"""
    _guard(request)
    ts = str(int(time.time()))
    await run_in_threadpool(runtime_config.set_str, runtime_config.K_SETUP_DONE, ts)
    if body.skipped:
        await run_in_threadpool(runtime_config.set_str, "setup.skipped", "1")
    logger.info("[setup] 向导完成（skipped={}）", body.skipped)
    return {"ok": True, "completed_at": ts}


# ── 10. 重新运行 ────────────────────────────────────────────────────
@router.post("/reopen")
async def reopen(request: Request):
    """设置页的「重新运行初始化向导」。只清完成标记，**不动已保存的配置** ——
    用户可能只是想换个模型，清掉配置会让他在向导里连当前值都看不到。"""
    _guard(request)
    await run_in_threadpool(runtime_config.set_str, runtime_config.K_SETUP_DONE, "")
    await run_in_threadpool(runtime_config.set_str, "setup.skipped", "")
    return {"ok": True}
