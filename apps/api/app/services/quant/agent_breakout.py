"""小鹿智能体 · 突破买入线(2026-09-13 用户给的「Patrick Walker Style Complete Strategy」完整合并版脚本)。

用户给的是一份 ThinkScript 风格脚本:市场环境过滤 + 筛选(Clean Simple Base)+ 突破触发 + 两次加仓 +
部分止盈 + 三种止损 + 完全出场。这个引擎逐条移植,规则编号 P-xx(和 VCP 的 R/C/V、唐奇安的 D 不共用)。

## 筛选看前一天收盘,突破看今天(2026-09-13 用户拍板)

脚本字面是筛选和突破在**同一根 K 线**上判断。照字面跑 2025-09-12 ~ 2026-03-10:811 个突破日(P-06 成立)
**没有一个**同一天过得了筛选 —— 突破日本身把筛选破坏掉了:1 月振幅超过 12% 的 767 个(突破把区间撑大)、
10 日均量不再低于 50 日 × 0.9 的 729 个(1.5 倍放量把 10 日均量拉上去)、1 月 ≤ 3 月 × 0.55 的 613 个。
全年 0 笔,回测关会自动淘汰。筛选改看前一天收盘后同一段有 16 次信号。用户选了「筛选看前一天收盘」,
符合脚本「1. 筛选阶段 → 2. 突破触发阶段」的分段意图。**要改回同一天,先把上面这组数字给用户看。**

## 规则

- P-01 市场环境(今天):标普 500 收盘 > 50 日均线 > 200 日均线;不满足不开新仓(持仓按 P-15 退出)。
- P-02 价格与流动性(前一天收盘):收盘 > 20 美元,30 日均量 > 20 万股。
- P-03 趋势(前一天收盘):收盘 > 50 日 > 150 日 > 200 日均线;收盘 > 近 252 日最高价 × 0.80;RS ≥ 80。
        RS 用当天池子里的评级(池子不存前一天的 RS;一天之内评级变化很小)。
- P-04 整理形态(前一天收盘):3 个月振幅 12%~35%、1 个月振幅 3%~12%、1 月振幅 ≤ 3 月振幅 × 0.55、
        5 日振幅 ≤ 1 月振幅 × 0.65、近 21 日最低 > 近 63 日最低 × 1.01(振幅 = (最高 − 最低)÷ 最高)。
- P-05 枢轴与缩量(前一天收盘):距前一天的枢轴 −4% ~ +5%;10 日均量 < 50 日均量 × 0.9。
- P-06 突破触发(今天):枢轴 = 前一天为止的近 21 日最高价(脚本 `highest(high, 21)[1]`);
        收盘 > 枢轴,收盘 < 枢轴 × 1.05(不追高超过 5%),当天成交量 > 50 日均量 × 1.5。
        **脚本里的 `close > open`(阳线)没做:日线没有开盘价**(仓内 CLAUDE.md 小鹿第 1 条),
        不拿「收盘 > 昨收」之类顶替 —— 那是另一个条件。
- P-07 仓位:一个完整仓位 = 总资产 20%;首次买入完整仓位的 50%;最多 5 只。
- P-08 加仓:① 收盘 > 进场价 × 1.02、量 > 20 日均量 × 1.2、收盘 > EMA8、市场向上 → 加完整仓位的 30%;
        ② 收盘 > 进场价 × 1.05、量 > 20 日均量 × 1.1、收盘 > EMA21、市场向上 → 再加 20%。按顺序,一天最多加一次。
- P-09 止损 A:当天最低价 < 前一天为止近 21 日最低价 × 0.98(跌破 Base 低点)。
- P-10 止损 B:收盘 < 进场价 × 0.94(固定 6%)。
- P-11 止损 C:收盘 < EMA8 且收盘 < 进场价。
- P-12 部分止盈:浮盈 ≥ 8%,且收盘 < 前一天最高价、量 < 10 日均量 → 卖出当前持仓约 20%(每个持仓只做一次)。
- P-13 趋势出场:收盘 < EMA21 且浮盈 > 10%。
- P-14 趋势出场:收盘 < 50 日均线且浮盈 > 20%。
- P-15 市场转弱:P-01 不成立 → 清仓。
- P-16 护栏:与其他研究线同一套(单日权益 -3% 当天不开仓、连亏 3 笔停一天)。

## 移植时替用户做的决定(脚本没说清的地方,改之前先问用户)

1. **`entryprice()` = 第一次买入价**,加仓后不变。ThinkScript 里它可以是持仓均价;用首笔价时
   「+2% 加仓、+5% 再加、-6% 止损、浮盈 8%/10%/20%」都相对同一个锚点,和脚本注释的读法一致。
2. **「建议仓位 50% / +30% / +20%」的完整仓位没给大小**,取总资产 20%(和唐奇安线单股上限同一个数),最多 5 只。
3. **部分止盈每个持仓只做一次**。脚本的信号每根 K 线都可能为真,照字面每个「暂停」日都卖 20%,持仓会被切碎。
4. **止损 A 用当天最低价判断、按收盘价成交**。脚本写的是 `low <`;成交价统一收盘(和其他研究线同一口径,
   日线没有盘中路径)。所以止损 A 的实际成交价可能比 Base 低点还低不少,这是口径,不是 bug。
5. 均量窗口含当天(和扫描源 average_volume_Nd_calc 同口径);`[1]` 的两处(枢轴、Base 低点)不含当天。
6. 所有字段由引擎用自家日线精确算(扫描源没有 50 日 / 20 日均量);池子只做宽松预筛。

收盘后决策、信号当天收盘价成交。规则固定,满 30 笔前不优化(tunable 为空)。
"""
from __future__ import annotations

from app.services.quant import agent_vcp as av

MARKET_KEY = "__market__"
SECTORS_KEY = "__sectors__"          # agent_run.ensure_cache 按有 MARKET_KEY 的引擎一起写;本引擎不用板块
MIN_BARS = 60                        # 持仓管理(EMA21 / 50 日线 / 21 日低点)要的最少根数
SCREEN_BARS = 252                    # 筛选要近 252 日最高价

PARAMS = {
    "price_min": 20.0, "liq_min": 200_000.0, "near_high": 0.80, "rs_min": 80,
    "depth_min": 0.12, "depth_max": 0.35, "tight1m_min": 0.03, "tight1m_max": 0.12,
    "shrink": 0.55, "tight5d": 0.65, "higher_low": 1.01,
    "pivot_lo": -4.0, "pivot_hi": 5.0, "vdry": 0.9,
    "extend": 1.05, "vol_surge": 1.5,
    "add1_pct": 1.02, "add1_vol": 1.2, "add2_pct": 1.05, "add2_vol": 1.1,
    "base_stop": 0.98, "fixed_stop": 0.94,
    "partial_profit": 8.0, "partial_frac": 0.20,
    "exit_ema21_profit": 10.0, "exit_sma50_profit": 20.0,
    "unit_pct": 0.20, "initial_frac": 0.50, "add1_frac": 0.30, "add2_frac": 0.20, "max_holdings": 5,
    "watch_pool_days": 1,
}
STOP_KEYS = ("fixed_stop",)
ENTRY_RULE = "P-06"
ADD_RULE = "P-08"
WATCH_POOL_DAYS = 1                  # 突破是当天的事;筛选条件由引擎按前一天收盘重算,池子只要当天的

POOL = "breakout"
POOL_LIMIT = 800
POOL_LABEL = "突破买入预筛池(收盘 > 20 · 30 日均量 > 20 万 · 均线多头 · 距 52 周高点 20% 以内 · RS ≥ 80)"
POOL_SCRIPT = """# ===== 突破买入预筛池(小鹿 · 突破买入线)=====
# 整理形态 / 枢轴 / 50 日均量 / 突破由引擎用日线精确算;这里只圈脚本里扫描源能算的那几条
def c_price = close > 20;
def c_liq   = average_volume_30d_calc > 200000;
def c_trend = close > SMA50 and SMA50 > SMA150 and SMA150 > SMA200;
def c_near  = close > price_52_week_high * 0.80;
def c_rs    = rs_rating >= 80;

plot scan = c_price and c_liq and c_trend and c_near and c_rs;
"""
EXEC_NOTE = "纸上交易 · 日线收盘价成交(筛选看前一天收盘、突破看当天;没有开盘价,阳线条件未实现)"

RULES = [
    {"id": "P-01", "kind": "risk", "condition": "市场环境(当天):标普 500 收盘 > 50 日均线 > 200 日均线;不满足不开新仓"},
    {"id": "P-02", "kind": "buy", "condition": "价格与流动性(前一天收盘):收盘 > $20,30 日均量 > 20 万股"},
    {"id": "P-03", "kind": "buy", "condition": "趋势(前一天收盘):收盘 > 50 日 > 150 日 > 200 日均线;收盘 > 近 252 日最高 × 0.80;RS ≥ 80"},
    {"id": "P-04", "kind": "buy", "condition": "整理形态(前一天收盘):3 月振幅 12%~35%、1 月振幅 3%~12%、1 月 ≤ 3 月 × 0.55、5 日 ≤ 1 月 × 0.65、21 日最低 > 63 日最低 × 1.01"},
    {"id": "P-05", "kind": "buy", "condition": "枢轴与缩量(前一天收盘):距枢轴 −4% ~ +5%;10 日均量 < 50 日均量 × 0.9"},
    {"id": "P-06", "kind": "buy", "condition": "突破触发(当天):收盘 > 枢轴(前一天为止近 21 日最高)、收盘 < 枢轴 × 1.05、成交量 > 50 日均量 × 1.5(阳线条件没做:日线没有开盘价)"},
    {"id": "P-07", "kind": "risk", "condition": "仓位:完整仓位 = 总资产 20%,首次买入 50%;最多 5 只"},
    {"id": "P-08", "kind": "buy", "condition": "加仓:收盘 > 进场价 × 1.02、量 > 20 日均量 × 1.2、收盘 > EMA8、市场向上 → +30%;收盘 > 进场价 × 1.05、量 > 20 日均量 × 1.1、收盘 > EMA21 → 再 +20%"},
    {"id": "P-09", "kind": "sell", "condition": "止损 A:当天最低价 < 前一天为止近 21 日最低 × 0.98(跌破 Base 低点),按收盘价出"},
    {"id": "P-10", "kind": "sell", "condition": "止损 B:收盘 < 进场价 × 0.94(固定 6%)"},
    {"id": "P-11", "kind": "sell", "condition": "止损 C:收盘 < EMA8 且收盘 < 进场价"},
    {"id": "P-12", "kind": "sell", "condition": "部分止盈:浮盈 ≥ 8% 且收盘 < 前一天最高、量 < 10 日均量 → 卖出约 20%(每个持仓一次)"},
    {"id": "P-13", "kind": "sell", "condition": "趋势出场:收盘 < EMA21 且浮盈 > 10%"},
    {"id": "P-14", "kind": "sell", "condition": "趋势出场:收盘 < 50 日均线且浮盈 > 20%"},
    {"id": "P-15", "kind": "sell", "condition": "市场转弱:标普 500 不再满足 收盘 > 50 日 > 200 日 → 清仓"},
    {"id": "P-16", "kind": "risk", "condition": "护栏:单日权益回撤达 -3% 当天停止开仓;连亏 3 笔后下一个交易日不开仓"},
]
RULE_NAME = {"P-06": "枢轴突破买入", "P-08": "加仓", "P-09": "跌破 Base 低点", "P-10": "固定 6% 止损",
             "P-11": "跌破 EMA8 且亏损", "P-12": "部分止盈", "P-13": "跌破 EMA21", "P-14": "跌破 50 日线",
             "P-15": "市场转弱"}
RULE_PARAM_KEY: dict = {}            # 规则固定,不进优化器


def rules_for(p: dict = PARAMS) -> list[dict]:
    return [dict(r) for r in RULES]


def summary(p: dict = PARAMS) -> str:
    return ("Patrick Walker 风格突破:标普在 50 日 > 200 日之上才做;前一天收盘时已是均线多头、离一年高点 20% 以内、RS ≥ 80、"
            "3 个月 → 1 个月 → 5 天振幅逐级收紧、低点抬高、量能干燥的票,今天收盘放量(> 1.5 倍 50 日均量)站上前 21 日最高、"
            "且不超过 5% 时买入完整仓位(总资产 20%)的一半;涨 2% / 5% 且放量站上 EMA8 / EMA21 各加 30% / 20%;"
            "跌破 Base 低点 2%、亏 6%、或亏损中跌破 EMA8 止损;浮盈 8% 后遇暂停卖 20%;"
            "浮盈 10% 跌破 EMA21、浮盈 20% 跌破 50 日线、或大盘转弱时清仓。")


# ═══════════════════════════════════════════════════════════════
# 市场环境 · 指标
# ═══════════════════════════════════════════════════════════════

def market_regime(bars: list[tuple], p: dict = PARAMS) -> dict:
    """基准日线 [(日期, 收, 高, 低, 量)] 截到当天 → {ok, above, text}。算不出时 above = None(不当成转弱)。"""
    if len(bars) < 200:
        return {"ok": False, "above": None, "text": f"基准日线只有 {len(bars)} 根,不足 200,市场环境算不出,不开新仓"}
    c = [b[1] for b in bars]
    s50, s200 = av._sma(c, 50), av._sma(c, 200)
    above = c[-1] > s50 and s50 > s200
    return {"ok": above, "above": above, "close": c[-1], "sma50": s50, "sma200": s200,
            "text": f"标普 {c[-1]:.0f} · 50 日 {s50:.0f} · 200 日 {s200:.0f}" + (" —— 上升趋势" if above else " —— 不在上升趋势")}


def _mean(xs):
    return sum(xs) / len(xs) if xs and all(x is not None for x in xs) else None


def _core(bars: list[tuple]) -> dict | None:
    """一天的字段。持仓管理要的只要 60 根;筛选字段要 252 根且窗口里没有缺值,算不出时 screen = None(不猜)。"""
    n = len(bars)
    if n < MIN_BARS:
        return None
    c = [b[1] for b in bars]
    h = [b[2] for b in bars]
    lo = [b[3] for b in bars]
    v = [b[4] for b in bars]
    if any(x is None for x in h[-23:] + lo[-23:] + v[-50:]):
        return None
    ind = {
        "close": c[-1], "high": h[-1], "low": lo[-1], "volume": v[-1], "prev_high": h[-2],
        "pivot": max(h[-22:-1]), "base_low": min(lo[-22:-1]),
        "av10": _mean(v[-10:]), "av20": _mean(v[-20:]), "av50": _mean(v[-50:]),
        "ema8": av._ema(c[-160:], 8), "ema21": av._ema(c[-160:], 21),
        "sma50": av._sma(c, 50),
        "screen": None,
    }
    if n >= SCREEN_BARS and not any(x is None for x in h[-SCREEN_BARS:] + lo[-63:] + v[-30:]):
        hi63, lo63 = max(h[-63:]), min(lo[-63:])
        hi21, lo21 = max(h[-21:]), min(lo[-21:])
        hi5, lo5 = max(h[-5:]), min(lo[-5:])
        ind["screen"] = {
            "sma150": av._sma(c, 150), "sma200": av._sma(c, 200), "hi252": max(h[-SCREEN_BARS:]),
            "av30": _mean(v[-30:]),
            "rng3m": (hi63 - lo63) / hi63 if hi63 else None,
            "rng1m": (hi21 - lo21) / hi21 if hi21 else None,
            "rng5d": (hi5 - lo5) / hi5 if hi5 else None,
            "low21": lo21, "low63": lo63,
        }
    return ind


def indicators(bars: list[tuple], p: dict = PARAMS, bench: dict | None = None) -> dict | None:
    """bars = [(d, c, h, l, v)] 升序,最后一根是今天。→ 今天的字段 + prev(前一天收盘的字段,筛选用)。"""
    ind = _core(bars)
    if ind is not None:
        prev = _core(bars[:-1])
        if prev is not None:
            prev.pop("prev", None)
        ind["prev"] = prev
    return ind


# ═══════════════════════════════════════════════════════════════
# 买入条件
# ═══════════════════════════════════════════════════════════════

def screen_checks(sp: dict | None, p: dict = PARAMS, score=None) -> list[dict]:
    """P-02 ~ P-05,按 sp(前一天收盘的字段)判断 → [{rule, ok, text}]。"""
    sc = sp.get("screen") if sp else None
    if sc is None:
        t = "前一天的日线不足 252 根或窗口里缺高低量,筛选条件算不出"
        return [{"rule": r, "ok": False, "text": t} for r in ("P-02", "P-03", "P-04", "P-05")]
    px = sp["close"]
    out = []
    ok2 = px > p["price_min"] and sc["av30"] is not None and sc["av30"] > p["liq_min"]
    out.append({"rule": "P-02", "ok": ok2,
                "text": f"昨收 ${px:.2f},30 日均量 {sc['av30'] / 1e4:.0f} 万股" + ("" if ok2 else f"(要 > ${p['price_min']:.0f} 且 > {p['liq_min'] / 1e4:.0f} 万)")})
    s50, s150, s200 = sp["sma50"], sc["sma150"], sc["sma200"]
    stack = s50 is not None and s150 is not None and s200 is not None and px > s50 > s150 > s200
    near = px > sc["hi252"] * p["near_high"]
    rs_ok = score is not None and score >= p["rs_min"]
    bad = []
    if not stack:
        bad.append("昨收时均线没排成 收盘 > 50 > 150 > 200")
    if not near:
        bad.append(f"昨收离一年最高 ${sc['hi252']:.2f} 超过 {(1 - p['near_high']) * 100:.0f}%")
    if not rs_ok:
        bad.append(f"RS {score:.0f} < {p['rs_min']}" if score is not None else "RS 缺")
    out.append({"rule": "P-03", "ok": not bad, "text": "昨收时趋势通过" if not bad else ";".join(bad)})
    r3, r1, r5 = sc["rng3m"], sc["rng1m"], sc["rng5d"]
    bad = []
    if r3 is None or not (p["depth_min"] <= r3 <= p["depth_max"]):
        bad.append(f"3 月振幅 {r3 * 100:.1f}% 不在 {p['depth_min'] * 100:.0f}%~{p['depth_max'] * 100:.0f}%" if r3 is not None else "3 月振幅缺")
    if r1 is None or not (p["tight1m_min"] <= r1 <= p["tight1m_max"]):
        bad.append(f"1 月振幅 {r1 * 100:.1f}% 不在 {p['tight1m_min'] * 100:.0f}%~{p['tight1m_max'] * 100:.0f}%" if r1 is not None else "1 月振幅缺")
    if r1 is not None and r3 is not None and not (r1 <= r3 * p["shrink"]):
        bad.append(f"1 月振幅没收缩到 3 月的 {p['shrink']:.2f} 倍以内")
    if r5 is not None and r1 is not None and not (r5 <= r1 * p["tight5d"]):
        bad.append(f"5 日振幅 {r5 * 100:.1f}% 没收紧到 1 月的 {p['tight5d']:.2f} 倍以内")
    if not (sc["low21"] > sc["low63"] * p["higher_low"]):
        bad.append("近 21 日低点没比 63 日低点高 1% 以上")
    txt = (f"昨收时振幅 3 月 {r3 * 100:.1f}% → 1 月 {r1 * 100:.1f}% → 5 日 {r5 * 100:.1f}%" if None not in (r3, r1, r5) else "振幅算不出")
    out.append({"rule": "P-04", "ok": not bad, "text": txt + ("" if not bad else ";" + ";".join(bad))})
    pv = sp["pivot"]
    dist = (px - pv) / pv * 100
    vdry = sp["av10"] is not None and sp["av50"] is not None and sp["av10"] < sp["av50"] * p["vdry"]
    ok5 = p["pivot_lo"] <= dist <= p["pivot_hi"] and vdry
    ratio = f"{sp['av10'] / sp['av50']:.2f}" if sp["av10"] and sp["av50"] else "—"
    out.append({"rule": "P-05", "ok": ok5,
                "text": f"昨收距当时枢轴 ${pv:.2f} {dist:+.1f}%,10 日均量 ÷ 50 日均量 {ratio}"
                        + ("" if ok5 else f"(要 {p['pivot_lo']:.0f}% ~ +{p['pivot_hi']:.0f}%、量比 < {p['vdry']})")})
    return out


def trigger_check(ind: dict, p: dict = PARAMS) -> dict:
    """P-06:今天的突破。"""
    px, pv = ind["close"], ind["pivot"]
    brk = px > pv
    not_ext = px < pv * p["extend"]
    surge = ind["av50"] is not None and ind["volume"] > ind["av50"] * p["vol_surge"]
    if not brk:
        t6 = f"收盘 ${px:.2f} 还没站上枢轴 ${pv:.2f}"
    elif not not_ext:
        t6 = f"收盘 ${px:.2f} 已高出枢轴 {(px / pv - 1) * 100:.1f}%,超过 {(p['extend'] - 1) * 100:.0f}% 不追"
    else:
        t6 = f"收盘 ${px:.2f} 突破枢轴 ${pv:.2f}(高出 {(px / pv - 1) * 100:.1f}%)"
    t6 += f",成交量 {ind['volume'] / ind['av50']:.2f} × 50 日均量" if ind["av50"] else ",50 日均量算不出"
    if not surge:
        t6 += f"(要 > {p['vol_surge']:.1f} 倍)"
    return {"rule": "P-06", "ok": brk and not_ext and surge, "text": t6}


def entry_checks(ind: dict, p: dict = PARAMS, score=None, market: dict | None = None) -> list[dict]:
    """→ [{rule, ok, text}] 按 P-01 ~ P-06:市场与突破看今天,P-02 ~ P-05 看前一天收盘。"""
    mk_ok = bool(market and market.get("ok"))
    return ([{"rule": "P-01", "ok": mk_ok, "text": market["text"] if market else "没有基准日线"}]
            + screen_checks(ind.get("prev"), p, score) + [trigger_check(ind, p)])


def entry_ok(ind: dict, p: dict = PARAMS, score=None, market: dict | None = None) -> bool:
    return all(c["ok"] for c in entry_checks(ind, p, score, market))


def watch_item(code, name, ind, held, blocked_reason, score=None, p: dict = PARAMS, market=None) -> dict:
    it = {"symbol": code, "name": name, "score": score, "rule_id": ENTRY_RULE, "rule_text": RULES[5]["condition"]}
    if ind is None:
        it.update({"price": None, "progress_pct": None, "gap": f"日线不足 {MIN_BARS} 根或缺高低量,指标算不出"})
        return it
    it["price"] = round(ind["close"], 2)
    checks = entry_checks(ind, p, score, market)
    passed = sum(1 for c in checks if c["ok"])
    it["progress_pct"] = int(passed / len(checks) * 100)
    fails = [c for c in checks if not c["ok"]]
    if held:
        it["gap"] = "已持仓 · 等加仓 / 出场信号"
    elif not fails:
        it["gap"] = "六条全满足 —— 今日收盘触发买入"
    else:
        it["gap"] = f"{passed}/{len(checks)} 满足 · 还差:" + ";".join(f"{c['rule']} {c['text']}" for c in fails)
    if blocked_reason:
        it["blocked"] = True
        it["blocked_reason"] = blocked_reason
    return it


# ═══════════════════════════════════════════════════════════════
# 一天的决策
# ═══════════════════════════════════════════════════════════════

def _fill(side, pos: av.Position, shares, price, rule, rationale, **extra) -> dict:
    d = {"side": side, "symbol": pos.code, "name": pos.name, "shares": int(shares), "price": round(price, 2),
         "rule_id": rule, "rule_name": RULE_NAME.get(rule, rule), "rationale": rationale,
         "entry_date": pos.entry_date, "level": pos.level}
    d.update(extra)
    return d


def _sell(pos: av.Position, qty: int, px: float, rule: str, why: str, state: dict, fills: list, n: int, want_text: bool, base: str):
    qty = max(1, min(int(qty), pos.size))
    pnl = (px - pos.avg_cost) * qty
    state["cash"] += qty * px
    if qty >= pos.size:
        state["closed_pnl"].append(pnl)
    fills.append(_fill("sell", pos, qty, px, rule, (base + why) if want_text else "",
                       pnl_abs=round(pnl, 2), pnl_pct=round((px / pos.avg_cost - 1) * 100, 2), hold_days=n))
    pos.size -= qty


def exit_rule(pos: av.Position, ind: dict, market: dict | None, p: dict = PARAMS) -> tuple[str | None, str]:
    """完全出场(P-09 ~ P-11 止损、P-13 / P-14 趋势、P-15 市场)→ (规则, 说明);不出 → (None, "")。
    按脚本 full_exit 里的顺序取第一个成立的做出场原因。"""
    px, ep = ind["close"], pos.entry_price
    profit = (px - ep) / ep * 100
    if ind["low"] < ind["base_low"] * p["base_stop"]:
        return "P-09", f"最低价 ${ind['low']:.2f} 跌破 Base 低点 ${ind['base_low']:.2f} 的 {p['base_stop']:.2f} 倍 —— 止损 A,按收盘出。"
    if px < ep * p["fixed_stop"]:
        return "P-10", f"收盘 ${px:.2f} 跌破进场价 × {p['fixed_stop']:.2f} = ${ep * p['fixed_stop']:.2f} —— 固定止损。"
    if ind["ema8"] is not None and px < ind["ema8"] and px < ep:
        return "P-11", f"收盘 ${px:.2f} 在 EMA8 ${ind['ema8']:.2f} 下方且低于进场价 —— 止损 C。"
    if ind["ema21"] is not None and px < ind["ema21"] and profit > p["exit_ema21_profit"]:
        return "P-13", f"浮盈 {profit:.1f}% 时收盘跌破 EMA21 ${ind['ema21']:.2f} —— 趋势出场。"
    if ind["sma50"] is not None and px < ind["sma50"] and profit > p["exit_sma50_profit"]:
        return "P-14", f"浮盈 {profit:.1f}% 时收盘跌破 50 日线 ${ind['sma50']:.2f} —— 趋势出场。"
    if market is not None and market.get("above") is False:
        return "P-15", f"大盘转弱({market['text']})—— 清仓。"
    return None, ""


def manage_position(pos: av.Position, ind: dict, state: dict, p: dict = PARAMS, want_text: bool = True) -> list[dict]:
    px, ep = ind["close"], pos.entry_price
    pos.bars_held += 1
    n = pos.bars_held
    ex = pos.extra
    market = state.get("market")
    profit = (px - ep) / ep * 100
    base = (f"进场价 ${ep:.2f},今收 ${px:.2f}({profit:+.1f}%),持有 {n} 个交易日。") if want_text else ""
    fills: list = []
    rule, why = exit_rule(pos, ind, market, p)
    if rule:
        _sell(pos, pos.size, px, rule, why, state, fills, n, want_text, base)
        pos.highest = max(pos.highest, px)
        state["closed"].append(pos)
        return fills
    # 部分止盈(一次)
    if (profit >= p["partial_profit"] and not ex.get("partial_done") and px < ind["prev_high"]
            and ind["av10"] is not None and ind["volume"] < ind["av10"] and pos.size >= 2):
        qty = max(1, int(round(pos.size * p["partial_frac"])))
        _sell(pos, qty, px, "P-12", f"浮盈 {profit:.1f}% ≥ {p['partial_profit']:.0f}%,收盘低于昨天最高 ${ind['prev_high']:.2f}、"
                                     f"量低于 10 日均量 —— 上涨出现暂停,卖出约 {p['partial_frac'] * 100:.0f}%({qty} 股)。",
              state, fills, n, want_text, base)
        ex["partial_done"] = True
    elif market and market.get("ok") and pos.level < 3 and ind["av20"]:
        # 加仓:按顺序,一天最多一次;股数按进场时定下的完整仓位
        unit = int(ex.get("unit") or pos.initial_size)
        add, why = 0, ""
        if (pos.level == 1 and px > ep * p["add1_pct"] and ind["volume"] > ind["av20"] * p["add1_vol"]
                and ind["ema8"] is not None and px > ind["ema8"]):
            add, why = int(unit * p["add1_frac"]), (f"收盘高出进场价 {profit:.1f}%(> {(p['add1_pct'] - 1) * 100:.0f}%),量 "
                                                    f"{ind['volume'] / ind['av20']:.2f} × 20 日均量,站上 EMA8 —— 第一次加仓 {p['add1_frac'] * 100:.0f}%")
        elif (pos.level == 2 and px > ep * p["add2_pct"] and ind["volume"] > ind["av20"] * p["add2_vol"]
                and ind["ema21"] is not None and px > ind["ema21"]):
            add, why = int(unit * p["add2_frac"]), (f"收盘高出进场价 {profit:.1f}%(> {(p['add2_pct'] - 1) * 100:.0f}%),量 "
                                                    f"{ind['volume'] / ind['av20']:.2f} × 20 日均量,站上 EMA21 —— 第二次加仓 {p['add2_frac'] * 100:.0f}%")
        if add > 0 and add * px <= state["cash"]:
            state["cash"] -= add * px
            pos.avg_cost = (pos.avg_cost * pos.size + add * px) / (pos.size + add)
            pos.size += add
            pos.level += 1
            fills.append(_fill("buy", pos, add, px, "P-08", (base + why + f"({add} 股)。") if want_text else "",
                               amount=round(add * px, 2), position_pct=round(add * px / state["equity"] * 100, 2)))
    pos.highest = max(pos.highest, px)
    if pos.size <= 0:
        state["closed"].append(pos)
    return fills


def try_entry(code, name, ind, state: dict, p: dict = PARAMS, want_text: bool = True, score=None):
    market = state.get("market")
    checks = entry_checks(ind, p, score, market)
    if not all(c["ok"] for c in checks[1:]):
        return None, None
    if not checks[0]["ok"]:
        return None, f"突破成立,但市场环境不满足:{checks[0]['text']}(P-01)"
    if state.get("halt_reason"):
        return None, f"突破成立,但护栏挡下:{state['halt_reason']}(P-16)"
    if len(state["positions"]) >= p["max_holdings"]:
        return None, f"突破成立,但已持有 {len(state['positions'])} 只,达到上限 {p['max_holdings']}(P-07)"
    equity, px = state["equity"], ind["close"]
    unit = int(equity * p["unit_pct"] / px)
    size = int(unit * p["initial_frac"])
    if size <= 0:
        return None, "突破成立,但按仓位算出的股数为 0"
    cash_cut = False
    if size * px > state["cash"]:
        size = int(state["cash"] / px)
        cash_cut = True
        if size <= 0:
            return None, f"突破成立,但现金只剩 ${state['cash']:.0f},买不起 1 股"
    cost = size * px
    state["cash"] -= cost
    pos = av.Position(code=code, name=name or code, size=size, initial_size=unit, entry_price=px,
                      entry_date=state["date"], avg_cost=px, highest=px, level=1, bars_held=0,
                      entry_rule=ENTRY_RULE, stop=px * p["fixed_stop"], risk=px * (1 - p["fixed_stop"]),
                      extra={"unit": unit, "pivot": ind["pivot"]})
    state["positions"].append(pos)
    extra = {"amount": round(cost, 2), "position_pct": round(cost / equity * 100, 2)}
    if not want_text:
        return _fill("buy", pos, size, px, ENTRY_RULE, "", **extra), None
    rationale = ("".join(f"{c['rule']} {c['text']};" for c in checks)
                 + f"完整仓位 = 总资产 {p['unit_pct'] * 100:.0f}% ÷ ${px:.2f} = {unit} 股,首次买入 {p['initial_frac'] * 100:.0f}%"
                 + (f",现金只够 {size} 股" if cash_cut else f" = {size} 股")
                 + f",占总资产 {cost / equity * 100:.1f}%。")
    return _fill("buy", pos, size, px, ENTRY_RULE, rationale, **extra), None


def run_day(date_iso: str, positions, cash: float, bars_of, watch, prev_equity, consec_losses: int,
            p: dict = PARAMS, g: dict = av.GUARDS, ind_of=None, want_text: bool = True) -> dict:
    """接口与其他引擎相同。市场环境从 ind_of(MARKET_KEY) 取。"""
    state = {"date": date_iso, "cash": cash, "positions": list(positions), "closed": [], "closed_pnl": [],
             "equity": None, "halt_reason": None, "market": None}
    if ind_of is None:
        def ind_of(code):
            if code in (MARKET_KEY, SECTORS_KEY):
                return None
            return indicators(bars_of(code) or [], p)
    state["market"] = ind_of(MARKET_KEY)
    ind_cache = {pos.code: ind_of(pos.code) for pos in state["positions"]}
    mv = sum(pos.size * (ind_cache[pos.code]["close"] if ind_cache[pos.code] else pos.avg_cost) for pos in state["positions"])
    equity = cash + mv
    state["equity"] = equity
    if prev_equity and (equity / prev_equity - 1) * 100 <= g["daily_loss_halt_pct"]:
        state["halt_reason"] = f"今日权益 {(equity / prev_equity - 1) * 100:+.1f}%,触及单日亏损熔断 {g['daily_loss_halt_pct']:.0f}%,今天不开新仓"
    elif consec_losses >= g["consecutive_loss_pause"]:
        state["halt_reason"] = f"此前连亏 {consec_losses} 笔,按护栏今天不开新仓"
        consec_losses = 0
    fills: list = []
    for pos in list(state["positions"]):
        if pos.extra is None:
            pos.extra = {}
        ind = ind_cache[pos.code]
        if ind is None:
            pos.bars_held += 1
            continue
        fills += manage_position(pos, ind, state, p, want_text)
    state["positions"] = [x for x in state["positions"] if x.size > 0]
    held = {x.code for x in state["positions"]}
    watch_items = []
    for code, name, score in watch:
        ind = ind_cache[code] if code in ind_cache else ind_of(code)
        ind_cache[code] = ind
        blocked = None
        if code not in held and ind is not None:
            f, blocked = try_entry(code, name, ind, state, p, want_text, score)
            if f:
                fills.append(f)
                held.add(code)
        if want_text:
            watch_items.append(watch_item(code, name, ind, code in held and not any(
                x["symbol"] == code and x["side"] == "buy" and x["rule_id"] == ENTRY_RULE for x in fills),
                blocked, score, p, state["market"]))
    for pnl in state["closed_pnl"]:
        consec_losses = consec_losses + 1 if pnl < 0 else 0
    mv = sum(pos.size * (ind_cache.get(pos.code) or ind_of(pos.code) or {"close": pos.avg_cost})["close"]
             for pos in state["positions"])
    watch_items.sort(key=lambda x: (bool(x.get("blocked")), -(x.get("progress_pct") or 0)))
    return {"fills": fills, "positions": state["positions"], "cash": state["cash"],
            "equity": state["cash"] + mv, "watch_items": watch_items, "halt_reason": state["halt_reason"],
            "consec_losses": consec_losses, "closed": state["closed"], "market": state["market"]}
