"""扫描筛选 · 官方示例「最近一次命中是哪天」(用户 2026-09-16 要求)。

普通扫描 0 命中时,结果区提示「距离今日最近一次扫描命中的日子为 X,可以通过时间回溯查看详情」,
点「时间回溯」弹窗自动填好那天。**只做官方示例**:脚本固定、按 key 取,用户脚本不走这条(防止拿它当免费的逐日回测)。

## 口径:逐日跑真正的时间回溯,不做近似

每天调一次 `screen_source.run_script(..., as_of=那天)` —— 和用户点「时间回溯 → 跳转 → 运行扫描」同一条路。
时间序列引擎本来能一次算出整列,拿来预筛会快很多,但递归定义的起算点随窗口变,算出来的「命中日」
可能和用户跳过去看到的对不上 —— 提示说那天有、跳过去却 0 只,比慢更糟。

## 为什么放后台线程

时间序列类(猎杀FOMO做空)回溯一天约 1 秒,横截面类(上升趋势 / VCP 等)约 10~15 秒;
往回找几十天不能卡住扫描请求。所以:扫描返回时带上当前状态(ready / pending / none),
前端 pending 时轮询 `GET /screener/last-hit`。结果按(市场, 示例, 日线最新一天)缓存在进程内 ——
API 是单 worker(Dockerfile 里的 uvicorn 没开 --workers),重启丢了就再算一次。

## 从哪天开始找

- 时间序列类:普通扫描本身就是按日线最新一天算的,从**前一个交易日**开始;
- 横截面类:普通扫描用的是实时快照,日线最新一天是另一套口径,从**日线最新一天**开始。
最多往回 MAX_DAYS 个交易日,或者花满 BUDGET_S 秒就停,返回 none 并说明找到了哪天。
"""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta

import logging

log = logging.getLogger(__name__)

MAX_DAYS = 120
BUDGET_S = 15 * 60

_lock = threading.Lock()
_cache: dict = {}        # (市场, key, 日线最新一天) → 结果
_running: set = set()


def _latest(market: str) -> date | None:
    from app.services.quant import screen_asof
    d = (screen_asof.history_range(market) or {}).get("max_date")
    return date.fromisoformat(str(d)) if d else None


def _search(market: str, key: str, latest: date) -> dict:
    from app.services.quant import screen_source
    p = screen_source.preset(key)
    script = p["script"]
    series = _series(market, script)
    d = latest - timedelta(days=1) if series else latest
    t0 = time.time()
    searched = 0
    oldest = None
    while searched < MAX_DAYS and time.time() - t0 < BUDGET_S:
        try:
            r = screen_source.run_script(script, market, 1, None, True, d, False)
        except screen_source.ScreenError:
            break                                  # 早于日线起点 / 日线没建好 —— 再往前也没有
        actual = date.fromisoformat(str(r.get("as_of")))
        if series and actual >= latest:            # 周末挪回到最新一天:那天普通扫描已经算过
            d = latest - timedelta(days=1)
            continue
        searched += 1
        oldest = actual
        if r.get("matched"):
            return {"status": "ready", "date": str(actual), "matched": r.get("matched"),
                    "searched_days": searched}
        d = actual - timedelta(days=1)
    return {"status": "none", "searched_days": searched, "oldest": str(oldest) if oldest else None}


def _worker(market: str, key: str, latest: date):
    k = (market, key, latest)
    t0 = time.time()
    try:
        res = _search(market, key, latest)
    except Exception as e:                           # noqa: BLE001
        log.warning(f"[last-hit] {market}/{key} 查找失败:{e}")
        res = {"status": "error"}
    res["latest"] = str(latest)
    log.info(f"[last-hit] {market}/{key} 截至 {latest}:{res} · {time.time() - t0:.0f}s")
    with _lock:
        _running.discard(k)
        for old in [x for x in _cache if x[0] == market and x[1] == key and x[2] != latest]:
            _cache.pop(old, None)                    # 日线更新过,前一天算的作废
        if res["status"] != "error":
            _cache[k] = res


def lookup(market: str, key: str, start: bool = True) -> dict:
    """→ {status: ready|pending|none|error|idle, date?, matched?, searched_days?, oldest?}。不阻塞。

    start=False 只查缓存、不起后台任务(轮询接口用,避免有人拿轮询去反复触发)。
    """
    from app.services.quant import screen_source
    p = screen_source.preset(key)
    if p is None or p.get("market") != market:
        return {"status": "error"}
    try:
        latest = _latest(market)
    except Exception:                                # noqa: BLE001
        return {"status": "error"}
    if latest is None:
        return {"status": "error"}
    k = (market, key, latest)
    with _lock:
        if k in _cache:
            return _cache[k]
        if k in _running:
            return {"status": "pending"}
        if not start:
            return {"status": "idle"}
        _running.add(k)
    threading.Thread(target=_worker, args=(market, key, latest), daemon=True,
                     name=f"last-hit-{market}-{key}").start()
    return {"status": "pending"}


def _series(market: str, script: str) -> bool:
    """这份脚本走不走时间序列引擎(和 parse_script / run_script 同一个编译器)。"""
    from app.services.quant import screen_dsl, screen_source
    meta = screen_source.get_meta(market)
    c = screen_dsl.compile_script(script, lambda n: n in meta.names, meta.sma, meta.ema, meta.rsi)
    return c.series is not None


def is_series(market: str, key: str) -> bool:
    from app.services.quant import screen_source
    p = screen_source.preset(key)
    return bool(p) and p.get("market") == market and _series(market, p["script"])
