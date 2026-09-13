"""扫描筛选 · 一只票在过去一年里「哪些天会被当前脚本命中」(用户 2026-09-13 要求)。

筛选器结果表悬停日K 上的淡蓝色竖带就是它:把**这次运行的脚本**放回过去 250 个交易日,每天按那天收盘重算
这只票的字段、求值一次。口径与「时间回溯」(`screen_asof.build_rows`)逐条相同 —— 同一份日线、同一份拆股修正、
同一套字段算法、同一个 RS 排名池 —— 只是只算一只票,所以一只票一年大约 1~3 秒,而不是 250 次全市场回溯。

## 为什么 RS 评级要单独建一张表

RS 评级是**全市场排名**:算某天这只票的评级,要知道那天排名池里所有票的 RS Raw。逐日跑 build_rows 太重,
这里按市场建一张「日期 → 当天排名池里全部 RS Raw(升序)」的表,和整窗日线一起按缓存周期复用;
单只票的评级用二分查名次,并列取平均名次 —— 与 `screen_rs.rs_ratings` 逐位相同(tests/test_screen_hits.py 盯着)。
算术顺序照抄 `rs_history.rs_raw_exact`,浮点结果逐位一致,二分才查得到自己。

## 算不出的天

脚本用到**没有历史**的字段(市值 / 财务,`screen_asof.reconstructable` 为假)时,那些条件每天都是「算不出」,
不算命中也不算没命中,计进 `unknown` 并在 `note` 里点名 —— 不许当成「那天没命中」,
否则图上一条蓝线都没有,用户会以为这只票过去一年从没满足过条件。
"""
from __future__ import annotations

import hashlib
import threading
import time
from bisect import bisect_left, bisect_right
from datetime import date

DAYS = 250
_TTL = 20 * 60
_lock = threading.Lock()
_snap_cache: dict = {}      # 市场 → (时间, 快照行, {code: 行})
_rs_cache: dict = {}        # 市场 → (整窗日线 loaded_at, {日期: (升序 RS Raw, 排名池只数)})
_hit_cache: dict = {}       # (市场, 脚本哈希, 代码, 截止日, 天数) → (loaded_at, 结果)
_RS_WEIGHTS = ((63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2))


def rating_of(sorted_raws: list[float], pool_n: int, value: float | None, threshold: float) -> int | None:
    """某天排名池全部 RS Raw(升序、不含 None)里,value 的 RS 评级(1–99)。

    与 screen_rs.rs_ratings 同一口径:覆盖率 = 有 Raw 的只数 ÷ 排名池只数,低于门槛整天不给;
    并列取平均名次,round(pct × 98 + 1)。value 不在表里 → None(不猜名次)。
    """
    n = len(sorted_raws)
    if value is None or n == 0 or pool_n <= 0 or n / pool_n < threshold:
        return None
    i = bisect_left(sorted_raws, value)
    j = bisect_right(sorted_raws, value) - 1
    if j < i:
        return None
    pct = ((i + 1) + (j + 1)) / 2.0 / n
    return int(round(pct * 98 + 1))


def raw_at(closes, i: int) -> float | None:
    """收盘序列第 i 根的精确 RS Raw。算术顺序照抄 rs_history.rs_raw_exact(浮点逐位一致)。"""
    if i < 252:
        return None
    last = float(closes[i])
    if last <= 0:
        return None
    tot = 0.0
    for days, w in _RS_WEIGHTS:
        base = float(closes[i - days])
        if base <= 0:
            return None
        tot += w * (last / base - 1.0)
    return tot


def _snapshot(market_raw: str, market_key: str, has_field):
    """今天的快照,只用静态列 + 拆股锚点 + 排名池两列(与 run_script 的回溯分支同一份列)。"""
    from app.services.quant import screen_source, screen_asof, rs_history
    now = time.time()
    with _lock:
        hit = _snap_cache.get(market_key)
    if hit and now - hit[0] < _TTL:
        return hit[1], hit[2]
    cols = [x for x in screen_asof.STATIC_COLS if x not in screen_source.ALWAYS_COLS and has_field(x)]
    cols += list(rs_history._PERF_COLS) + ["exchange", "market_cap_basic"]
    rows, _ = screen_source.fetch_rows(market_raw, cols)
    perf = {r["_code"]: r for r in rows}
    with _lock:
        _snap_cache[market_key] = (now, rows, perf)
    return rows, perf


def _rs_table(market_key: str, store: dict, snap: dict) -> dict:
    """{日期: (那天排名池里全部 RS Raw 升序, 排名池只数)},只建最近 DAYS+5 个交易日。

    排名池口径同 build_rows:在排名池里(交易所上市 + 市值门槛)、那天有收盘、且已有 253 根以上日线
    (次新股不进分母)。Raw 算不出(收盘非正)的票在分母里、不在列表里。
    """
    from app.services.quant import screen_rs
    with _lock:
        hit = _rs_cache.get(market_key)
    if hit and hit[0] == store["loaded_at"]:
        return hit[1]
    window = sorted(store["bench"])[-(DAYS + 5):]
    want = set(window)
    raws: dict = {d: [] for d in window}
    pool: dict = {d: 0 for d in window}
    first = window[0] if window else None
    for code, (dates, arr) in store["codes"].items():
        s = snap.get(code)
        if not s or not screen_rs.in_population(s, market_key) or len(dates) <= 252:
            continue
        closes = arr[:, 0]
        for i in range(max(bisect_left(dates, first), 252), len(dates)):
            d = dates[i]
            if d not in want:
                continue
            pool[d] += 1
            v = raw_at(closes, i)
            if v is not None:
                raws[d].append(v)
    table = {d: (sorted(v), pool[d]) for d, v in raws.items()}
    with _lock:
        _rs_cache[market_key] = (store["loaded_at"], table)
    return table


def hit_days(script: str, market: str, code: str, as_of: date | None = None, days: int = DAYS) -> dict:
    """→ {code, market, from, to, evaluated, hits: [YYYY-MM-DD], unknown, unavailable: [字段], note}"""
    from app.services.quant import screen_source, screen_dsl, screen_asof, screen_rs, rs_history as rh, vcp

    if not (script or "").strip():
        raise screen_source.ScreenError("没有脚本")
    md = screen_source._market(market)
    meta = screen_source.get_meta(market)

    def has_field(n: str) -> bool:
        return n in meta.names

    c = screen_dsl.compile_script(script, has_field, meta.sma, meta.ema, meta.rsi)
    rcache = screen_dsl.build_resolver_cache(c, has_field, meta.sma, meta.ema, meta.rsi)
    fields = list(c.fields)
    _rows, perf = _snapshot(market, md.key, has_field)
    store = screen_asof.get_store(md.key, perf)
    item = store["codes"].get(code)
    days = max(1, min(int(days or DAYS), DAYS))
    base = {"code": code, "market": md.key, "hits": [], "evaluated": 0, "unknown": 0, "unavailable": []}
    if not item:
        return dict(base, **{"from": None, "to": None,
                             "note": "自家全市场日线里没有这只票(不在日线池里,或者还没拉到),算不出过去哪些天会被命中"})
    dates, arr = item
    end = min(as_of, store["last"]) if as_of else store["last"]
    k_end = bisect_right(dates, end)
    if k_end == 0:
        return dict(base, **{"from": None, "to": None, "note": f"这只票在 {end} 之前没有日线"})
    key = (md.key, hashlib.sha1(script.encode("utf-8")).hexdigest(), code, str(end), days)
    with _lock:
        hit = _hit_cache.get(key)
    if hit and hit[0] == store["loaded_at"]:
        return hit[1]

    unavailable = sorted({f for f in fields if not screen_asof.reconstructable(f)})
    plain = [f for f in fields if f not in screen_asof.STATIC_COLS and screen_asof.need_bars(f) is not None
             and f not in screen_rs.RS_FIELDS and f not in vcp.FIELDS and f != vcp.DISPLAY]
    uses_rating = any(f in ("rs_rating", "rs_raw") for f in fields)
    uses_line = "rs_line_up_days" in fields
    vcp_used = [f for f in fields if f in vcp.FIELDS or f == vcp.DISPLAY]
    uses_vcp_core = any(f.startswith("vcp_") for f in vcp_used)
    uses_pv = any(f in ("up_days_20d", "down_days_20d", "ud_vol_ratio_20d") for f in vcp_used)
    uses_win = any(f in vcp.WINDOW_FIELDS for f in vcp_used)
    s = perf.get(code) or {}
    in_pool = bool(s) and screen_rs.in_population(s, md.key)
    table = _rs_table(md.key, store, perf) if uses_rating else None

    hits: list[str] = []
    unknown = 0
    idxs = range(max(0, k_end - days), k_end)
    for i in idxs:
        d = dates[i]
        bars = screen_asof._tuples(dates, arr, i + 1)
        row = {"_code": code}
        for col in screen_asof.STATIC_COLS:
            if col in fields:
                row[col] = s.get(col)
        row.update(screen_asof.compute_fields(bars, plain, d.year))
        for f in unavailable:
            row[f] = None
        if uses_line:
            st = rh.rs_line_stats([(b[0], b[1]) for b in bars], store["bench"])    # 股票日线已截到 d,基准多出来的日子对不上,不影响
            row["rs_line_up_days"] = st["up_days"] if st else None
        if uses_vcp_core:
            vs = vcp.vcp_stats(bars) or {}
            for f in vcp.FIELDS:
                if f.startswith("vcp_"):
                    row[f] = vs.get(f[4:])
        if uses_pv:
            pv = vcp.pv_stats(bars)
            row["up_days_20d"], row["down_days_20d"] = pv["up_days"], pv["down_days"]
            row["ud_vol_ratio_20d"] = pv["ud_vol_ratio"]
        if uses_win:
            row.update(vcp.window_stats(bars))
        if uses_rating:
            raw = rh.rs_raw_exact([b[1] for b in bars]) if (in_pool and len(bars) > 252) else None
            sr, pn = table.get(d, ([], 0))
            row["rs_raw"] = raw
            row["rs_rating"] = rating_of(sr, pn, raw, screen_rs.RS_UNIVERSE_THRESHOLD)
        env: dict = {}
        for stmt in c.stmts:
            env[stmt.name] = screen_dsl._eval(stmt.node, row, env, rcache)
        v = screen_dsl._truthy(env.get(c.plot_name))
        if v is None:
            unknown += 1
        elif v:
            hits.append(str(d))

    notes = []
    if unavailable:
        names = "、".join(screen_dsl.field_label_cn(f) or f for f in unavailable)
        notes.append(f"脚本用到没有历史的字段({names}),用到它们的条件每天都算不出")
    if unknown:
        notes.append(f"{unknown} 天字段算不出(日线不够长 / 缺高低量 / RS 排名池覆盖不足),不算命中也不算没命中")
    out = dict(base, **{"from": str(dates[idxs[0]]) if len(idxs) else None, "to": str(end),
                        "evaluated": len(idxs), "hits": hits, "unknown": unknown, "unavailable": unavailable,
                        "note": ";".join(notes) or None})
    with _lock:
        if len(_hit_cache) > 2000:
            _hit_cache.clear()
        _hit_cache[key] = (store["loaded_at"], out)
    return out
