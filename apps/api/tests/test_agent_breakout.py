# -*- coding: utf-8 -*-
"""小鹿智能体 · 突破买入线引擎用例(纯计算,不连库)。

    cd apps/api && PYTHONPATH=. python tests/test_agent_breakout.py

每条买卖规则至少一例;替用户做的几个决定(entryprice = 首笔价、部分止盈只做一次、
加仓按顺序、市场算不出不当成转弱)各有一例盯着。
「筛选看前一天收盘、突破看当天」(2026-09-13 用户拍板)有正反两例:突破日当天的振幅 / 量能被突破撑坏也照买;
前一天不满足、今天才满足的不买。
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.quant import agent_breakout as ab   # noqa: E402
from app.services.quant import agent_vcp as av        # noqa: E402

fails: list[str] = []
passed = 0


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
    else:
        fails.append(f"{name}  {extra}")


def mk(closes, rng=0.01, vol=1_000_000.0, start=date(2025, 1, 6)):
    out, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append((d, c, c * (1 + rng), c * (1 - rng), vol))
        d += timedelta(days=1)
    return out


G = av.GUARDS
P = ab.PARAMS
UP = {"ok": True, "above": True, "text": "标普上升趋势"}
DOWN = {"ok": False, "above": False, "text": "标普不在上升趋势"}
NA = {"ok": False, "above": None, "text": "基准日线不足"}

# ── 指标:[1] 的两处不含今天;prev = 前一天收盘的字段 ─────────────────
bars = mk([100.0] * 79 + [110.0])
ind = ab.indicators(bars)
check("指标 · Base 低点 = 前一天为止 21 日最低", abs(ind["base_low"] - 99.0) < 1e-9, str(ind["base_low"]))

# ── v2 枢轴:浪高点下方的密集成交区上沿 ──────────────────────────────
zb = mk([100.0] * 80)
zb[50] = (zb[50][0], 104.0, 106.0, 103.5, 100_000.0)          # 一根冲高回落、几乎没成交的「浪高点」
z = ab.pivot_zone(zb)
check("枢轴 · 浪高 = 窗口最高价 106(不含今天)", z is not None and abs(z["wave_high"] - 106.0) < 1e-9, str(z))
check("枢轴 · 取的是 99~101 的密集成交区,不是 106 那根长上影", z is not None and 100.5 < z["high"] < 102.0 and z["low"] < 99.6, str(z))
check("枢轴 · indicators 的 pivot = 密集区上沿", ab.indicators(zb)["pivot"] == z["high"])
zb2 = mk([100.0] * 80)
zb2[60] = (zb2[60][0], 115.0, 116.0, 114.0, 1_000_000.0)     # 浪高 116,下方 10% 内几乎没有成交
z2 = ab.pivot_zone(zb2)
check("枢轴 · 浪高下方 10% 内成交不到 10% → 没有枢轴(不退回单根最高价)", z2 is None, str(z2))
check("枢轴 · 日线不足 63 根 → 没有枢轴", ab.pivot_zone(mk([100.0] * 40)) is None)
noz = ab.indicators(zb2)
check("枢轴为空 → P-06 不成立并写明", noz["pivot"] is None and not ab.trigger_check(noz)["ok"]
      and "密集成交区" in ab.trigger_check(noz)["text"])
check("枢轴为空 → P-05 不成立", not ab.screen_checks(dict(noz, screen={"sma150": 1, "sma200": 1, "hi252": 1, "av30": 1e6,
                                                                "rng3m": 0.2, "rng1m": 0.08, "rng5d": 0.04, "low21": 2, "low63": 1}),
                                                     P, 90)[3]["ok"])
check("指标 · prev 是前一天收盘的字段", ind["prev"] is not None and ind["prev"]["close"] == 100.0)
check("指标 · 不足 252 根 → 筛选字段为空(不猜)", ind["screen"] is None and ind["prev"]["screen"] is None)
check("指标 · 不足 60 根 → None", ab.indicators(bars[:50]) is None)
long_ = ab.indicators(mk([100.0] * 300))
check("指标 · 252 根以上 → 今天和前一天的筛选字段都算得出", long_["screen"] is not None and long_["prev"]["screen"] is not None)

mr = ab.market_regime(mk([100.0 + i * 0.1 for i in range(260)]))
check("P-01 · 标普一路向上 → 上升趋势", mr["ok"] and mr["above"] is True)
mr2 = ab.market_regime(mk([100.0] * 150))
check("P-01 · 不足 200 根 → 算不出(above = None,不当成转弱)", not mr2["ok"] and mr2["above"] is None)


# ── 买入:构造一份全满足的指标 ───────────────────────────────────
SCREEN_OK = {"sma150": 90.0, "sma200": 85.0, "hi252": 110.0, "av30": 900_000.0,
             "rng3m": 0.20, "rng1m": 0.08, "rng5d": 0.04, "low21": 96.0, "low63": 90.0}
# 突破日当天的筛选字段被突破撑坏(1 月振幅 15%、5 日振幅大),照字面同一天判断就过不了
SCREEN_BROKEN = dict(SCREEN_OK, rng1m=0.18, rng5d=0.12)       # 18%:v4 把 4b 上限放到 15% 之后仍算撑坏


def good(prev=None, **kw):
    x = {"close": 104.0, "high": 104.5, "low": 101.5, "volume": 2_000_000.0, "prev_high": 102.0,
         "pivot": 102.0, "base_low": 95.0, "av10": 1_100_000.0, "av20": 1_000_000.0, "av50": 1_000_000.0,
         "ema8": 101.0, "ema21": 99.0, "sma50": 95.0, "screen": dict(SCREEN_BROKEN),
         "ema10": 101.5, "ema20": 99.5, "atr20": 3.0}
    pv = {"close": 101.8, "pivot": 102.0, "av10": 800_000.0, "av50": 1_000_000.0, "sma50": 95.0,
          "screen": dict(SCREEN_OK)}
    prev = dict(prev or {})
    if "screen" in prev:
        sc = prev.pop("screen")
        pv["screen"] = None if sc is None else dict(SCREEN_OK, **sc)
    pv.update(prev)
    x["prev"] = pv
    x.update(kw)
    return x


chk = {c["rule"]: c["ok"] for c in ab.entry_checks(good(), P, 90, UP)}
check("买入 · 构造的指标六条全满足", all(chk.values()), str(chk))
check("前一天筛选 · 突破日当天振幅 / 10 日量被撑坏也照买(用户拍板)",
      ab.entry_ok(good(), P, 90, UP) and good()["screen"]["rng1m"] > P["tight1m_max"] and good()["av10"] > good()["av50"] * P["vdry"])
check("前一天筛选 · 前一天 1 月振幅不满足、只有今天满足 → 不买",
      not ab.entry_ok(good(prev={"screen": {"rng1m": 0.18}}, screen=dict(SCREEN_OK)), P, 90, UP))
check("P-06 · 高出枢轴 5% 以上不追", not ab.entry_ok(good(close=107.5, high=108.0), P, 90, UP))
check("P-06 · 量不到 1.5 倍 50 日均量不买", not ab.entry_ok(good(volume=1_400_000.0), P, 90, UP))
check("P-06 · 没站上枢轴不买", not ab.entry_ok(good(close=101.5), P, 90, UP))
check("P-03 · RS 69 不买(v2 门槛 70)", not ab.entry_ok(good(), P, 69, UP))
check("P-03 · RS 70 买(v2 从 80 降到 70)", ab.entry_ok(good(), P, 70, UP))
check("P-03 · RS 缺不买", not ab.entry_ok(good(), P, None, UP))
check("P-03 · 前一天均线没排好不买", not ab.entry_ok(good(prev={"sma50": 102.5}), P, 90, UP))
check("P-04 · 前一天 5 日振幅没收紧(0.06 > 0.08 × 0.65)不买", not ab.entry_ok(good(prev={"screen": {"rng5d": 0.06}}), P, 90, UP))
check("P-04 · 前一天 1 月振幅没收缩到 3 月 0.55 倍不买", not ab.entry_ok(good(prev={"screen": {"rng1m": 0.12}}), P, 90, UP))
check("P-04 · 前一天低点没抬高不买", not ab.entry_ok(good(prev={"screen": {"low21": 90.5}}), P, 90, UP))
# v4:4b 上限 15%。1 月振幅 14%(3 月 30%,收缩比 0.47 仍 ≤ 0.55;5 日 8% ≤ 14% × 0.65)→ 过;16% → 不过
check("P-04 · v4 1 月振幅 14% 算过(上限 15%)",
      ab.entry_ok(good(prev={"screen": {"rng1m": 0.14, "rng3m": 0.30, "rng5d": 0.08}}), P, 90, UP))
check("P-04 · v4 1 月振幅 16% 超过上限不买",
      not ab.entry_ok(good(prev={"screen": {"rng1m": 0.16, "rng3m": 0.34, "rng5d": 0.08}}), P, 90, UP))
check("P-05 · 前一天 10 日均量放大(≥ 50 日均量)不买", not ab.entry_ok(good(prev={"av10": 1_050_000.0}), P, 90, UP))
check("P-05 · v3 缩量门槛 1.0:10 日均量 0.95 倍也算过", ab.entry_ok(good(prev={"av10": 950_000.0}), P, 90, UP))
check("P-05 · 前一天离枢轴超过 −4% 不买", not ab.entry_ok(good(prev={"close": 97.0}), P, 90, UP))
check("P-02 · 前一天收盘 ≤ 20 不买", not ab.entry_ok(good(prev={"close": 19.0}), P, 90, UP))
check("前一天筛选算不出 → 不买", not ab.entry_ok(good(prev={"screen": None}), P, 90, UP))
g0 = good()
g0["prev"] = None
check("前一天字段整个缺 → 不买", not ab.entry_ok(g0, P, 90, UP))
check("接口 · 规则文案写明看前一天收盘", "前一天收盘" in ab.RULES[3]["condition"] and "当天" in ab.RULES[5]["condition"])

r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, P, G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else good())
buys = [f for f in r["fills"] if f["side"] == "buy"]
check("进场 · 全满足当天买入", len(buys) == 1, str(r["fills"]))
if buys:
    unit = int(100_000 * 0.20 / 104.0)
    check("P-07 · 首次买入 = 完整仓位(总资产 20%)的一半", buys[0]["shares"] == int(unit * 0.5), f"{buys[0]['shares']} vs {unit}")
    check("进场 · 理由里逐条写了 P-01 ~ P-06 与股数算法", all(k in buys[0]["rationale"] for k in ("P-01", "P-04", "P-06", "完整仓位", "昨收")))
    check("进场 · 完整仓位记在 extra 里(加仓按它算)", r["positions"][0].extra.get("unit") == unit)
    check("P-11 · 初始止损 = 进场价 − 1 ATR(104 − 3 = 101)", abs(r["positions"][0].stop - 101.0) < 1e-9, str(r["positions"][0].stop))
    check("P-11 · 买入理由写了初始止损算法", "初始止损" in buys[0]["rationale"])

r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, P, G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else good(atr20=12.0))
check("P-11 · ATR 12 超过 8% → 止损被截在 进场价 × 0.92",
      r["positions"] and abs(r["positions"][0].stop - 104.0 * 0.92) < 1e-9, str([x.stop for x in r["positions"]]))
r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, P, G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else good(atr20=None))
check("P-11 · ATR 算不出 → 不买并写明(不拿 8% 顶替)", not r["fills"] and "ATR" in (r["watch_items"][0].get("blocked_reason") or ""))

r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, P, G,
               ind_of=lambda c: DOWN if c == ab.MARKET_KEY else good())
check("P-01 · 大盘不在上升趋势 → 不买并写明", not r["fills"] and r["watch_items"][0].get("blocked")
      and "P-01" in r["watch_items"][0]["blocked_reason"])
r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 3, P, G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else good())
check("P-16 · 连亏 3 笔 → 今天不开仓", not r["fills"] and r["halt_reason"])


# ── 持仓管理 ─────────────────────────────────────────────────
def pos(ep=100.0, size=100, unit=200, level=1, extra=None):
    return av.Position(code="AAA", name="AAA", size=size, initial_size=unit, entry_price=ep, entry_date="2026-01-02",
                       avg_cost=ep, highest=ep, level=level, stop=ep * 0.90, risk=ep * 0.10,
                       extra=dict({"unit": unit}, **(extra or {})))


def hold(close, **kw):
    """一份「什么出场条件都不碰」的持仓指标,再按需改几个字段。"""
    x = {"close": close, "high": close * 1.005, "low": close * 0.995, "volume": 1_000_000.0, "prev_high": close * 0.99,
         "pivot": 100.0, "base_low": 90.0, "av10": 1_000_000.0, "av20": 1_000_000.0, "av50": 1_000_000.0,
         "ema8": close * 0.98, "ema21": close * 0.96, "sma50": close * 0.9, "screen": None, "prev": None,
         "ema10": close * 0.97, "ema20": close * 0.95, "atr20": 2.0}
    x.update(kw)
    return x


def day(p_, ind_, market=UP, cash=100_000.0):
    return ab.run_day("2026-03-02", [p_], cash, lambda c: [], [], None, 0, P, G,
                      ind_of=lambda c: market if c == ab.MARKET_KEY else ind_)


def sold(r_):
    return [f for f in r_["fills"] if f["side"] == "sell"]


r = day(pos(), hold(101.0, low=87.0))
check("P-09 · 最低价跌破 Base 低点 × 0.98 → 清仓按收盘价", sold(r) and sold(r)[0]["rule_id"] == "P-09"
      and sold(r)[0]["price"] == 101.0 and sold(r)[0]["shares"] == 100, str(r["fills"]))
r = day(pos(), hold(93.9, ema8=90.0, low=93.5))
check("P-10 · 收盘 < 进场价 × 0.94 → 固定止损", sold(r) and sold(r)[0]["rule_id"] == "P-10", str(r["fills"]))
p11 = pos()
p11.stop = 97.0
r = day(p11, hold(96.5, low=96.0))
check("P-11 · 收盘跌破初始止损 97 → 出场", sold(r) and sold(r)[0]["rule_id"] == "P-11" and "初始止损" in sold(r)[0]["rationale"], str(r["fills"]))
p11 = pos()
p11.stop = 97.0
r = day(p11, hold(98.0, ema8=99.5))
check("P-11 · v5 不再有 EMA8 止损:亏损中跌破 EMA8 但没破止损 → 不卖", not sold(r), str(r["fills"]))
pbe = pos()
pbe.stop = 97.0
r = day(pbe, hold(105.5))
check("保本 · 最高收盘到过 +5% → 止损上移到持仓均价 100", not sold(r) and abs(r["positions"][0].stop - 100.0) < 1e-9,
      str([x.stop for x in r["positions"]]))
r = day(r["positions"][0], hold(99.5))
check("保本 · 之后跌回均价下方 → 按保本止损出场", sold(r) and sold(r)[0]["rule_id"] == "P-11" and "保本" in sold(r)[0]["rationale"], str(r["fills"]))
pbe2 = pos()
pbe2.stop = 97.0
r = day(pbe2, hold(104.5))
check("保本 · 最高只到 +4.5% → 止损不动", abs(r["positions"][0].stop - 97.0) < 1e-9)

# +20% 减半 → EMA10 再减半 → EMA20 清仓
r = day(pos(), hold(121.0, sma50=100.0))
s = sold(r)
check("P-17 · 收盘到 +21% → 卖出一半", s and s[0]["rule_id"] == "P-17" and s[0]["shares"] == 50, str(r["fills"]))
check("P-17 · 标记已减半,余 50 股", r["positions"] and r["positions"][0].size == 50 and r["positions"][0].extra.get("half20_done"))
r = day(pos(size=50, extra={"half20_done": True}), hold(125.0, sma50=100.0))
check("P-17 · 只减一次", not sold(r), str(r["fills"]))
r = day(pos(size=50, extra={"half20_done": True}), hold(115.0, ema10=116.0, ema20=110.0, sma50=100.0))
s = sold(r)
check("P-18 · 减半后跌破 EMA10 → 再卖余仓一半", s and s[0]["rule_id"] == "P-18" and s[0]["shares"] == 25, str(r["fills"]))
r = day(pos(size=25, extra={"half20_done": True, "ema10_done": True}), hold(115.0, ema10=116.0, ema20=110.0, sma50=100.0))
check("P-18 · 只减一次", not sold(r), str(r["fills"]))
r = day(pos(size=25, extra={"half20_done": True, "ema10_done": True}), hold(109.0, ema10=112.0, ema20=110.0, ema21=110.5, sma50=100.0))
s = sold(r)
check("P-19 · 减半后跌破 EMA20 → 清仓", s and s[0]["rule_id"] == "P-19" and s[0]["shares"] == 25, str(r["fills"]))
r = day(pos(size=25, extra={"half20_done": True}), hold(111.0, ema20=112.0, ema21=112.0, sma50=100.0))
check("P-19 · 与 P-13(浮盈 11% 破 EMA21)同时成立时记 P-19", sold(r) and sold(r)[0]["rule_id"] == "P-19", str(r["fills"]))
r = day(pos(), hold(111.0, ema20=112.0, ema21=100.0, sma50=100.0))
check("P-19 · 没减过半时跌破 EMA20 不清仓", not any(f["rule_id"] == "P-19" for f in r["fills"]), str(r["fills"]))
r = day(pos(), hold(111.0, ema8=110.0, ema21=112.0))
check("P-13 · 浮盈 11% 跌破 EMA21 → 清仓", sold(r) and sold(r)[0]["rule_id"] == "P-13", str(r["fills"]))
r = day(pos(), hold(109.0, ema8=108.0, ema21=110.0))
check("P-13 · 浮盈 9% 跌破 EMA21 不出", not any(f["rule_id"] == "P-13" for f in sold(r)), str(r["fills"]))
r = day(pos(), hold(121.0, ema21=118.0, sma50=122.0))
check("P-14 · 浮盈 21% 跌破 50 日线 → 清仓", sold(r) and sold(r)[0]["rule_id"] == "P-14", str(r["fills"]))
r = day(pos(), hold(103.0), market=DOWN)
check("P-15 · 大盘转弱 → 清仓", sold(r) and sold(r)[0]["rule_id"] == "P-15", str(r["fills"]))
r = day(pos(), hold(103.0), market=NA)
check("P-15 · 大盘算不出不当成转弱", not sold(r), str(r["fills"]))
p_ord = pos()
p_ord.stop = 97.0
r = day(p_ord, hold(96.5, low=87.0))
check("出场顺序 · 同时满足 Base 低点(P-09)和初始止损(P-11)时记 P-09", sold(r) and sold(r)[0]["rule_id"] == "P-09")

# 部分止盈:只做一次
p1 = pos()
r = day(p1, hold(109.0, prev_high=110.0, volume=800_000.0, av10=900_000.0))
s = sold(r)
check("P-12 · 浮盈 9% 且收盘低于昨高、量低于 10 日均量 → 卖 20%", s and s[0]["rule_id"] == "P-12" and s[0]["shares"] == 20, str(r["fills"]))
check("P-12 · 部分止盈后还持有 80 股", r["positions"] and r["positions"][0].size == 80)
r = day(r["positions"][0], hold(109.0, prev_high=110.0, volume=800_000.0, av10=900_000.0))
check("P-12 · 同一个持仓第二次暂停不再卖(决定 3)", not sold(r), str(r["fills"]))

# 加仓:按顺序,相对首笔价
r = day(pos(), hold(102.5, volume=1_300_000.0, ema8=102.0))
adds = [f for f in r["fills"] if f["rule_id"] == "P-08"]
check("P-08 · +2.5%、量 1.3 倍、站上 EMA8 → 第一次加仓 30% 完整仓位", adds and adds[0]["shares"] == 60, str(r["fills"]))
check("P-08 · 加仓后 level = 2、均价上移", r["positions"][0].level == 2 and r["positions"][0].avg_cost > 100.0)
check("P-08 · entryprice 仍是首笔价(决定 1)", r["positions"][0].entry_price == 100.0)
r = day(pos(), hold(106.0, volume=1_300_000.0))
adds = [f for f in r["fills"] if f["rule_id"] == "P-08"]
check("P-08 · 没加过第一次时,+6% 也只加第一次(30%)", adds and adds[0]["shares"] == 60 and r["positions"][0].level == 2, str(r["fills"]))
r = day(pos(level=2), hold(106.0, volume=1_150_000.0, ema21=104.0))
adds = [f for f in r["fills"] if f["rule_id"] == "P-08"]
check("P-08 · 第二次:+6%、量 1.15 倍、站上 EMA21 → 加 20%", adds and adds[0]["shares"] == 40, str(r["fills"]))
r = day(pos(level=3), hold(110.0, volume=2_000_000.0))
check("P-08 · 加满两次不再加", not [f for f in r["fills"] if f["side"] == "buy"])
r = day(pos(), hold(102.5, volume=1_300_000.0, ema8=102.0), market=NA)
check("P-08 · 大盘算不出不加仓", not [f for f in r["fills"] if f["side"] == "buy"])
r = day(pos(), hold(102.5, volume=1_300_000.0, ema8=102.0), cash=10.0)
check("P-08 · 现金不够不加仓", not [f for f in r["fills"] if f["side"] == "buy"])

check("接口 · 规则固定,不进优化器", ab.RULE_PARAM_KEY == {})
check("接口 · 规则编号 P- 开头,与其他线不冲突", all(x["id"].startswith("P-") for x in ab.RULES))
check("接口 · 阳线条件没做要写在规则里", "开盘价" in ab.RULES[5]["condition"])

print(f"{passed} passed, {len(fails)} failed")
for x in fails:
    print("FAIL", x)
print("ALL OK" if not fails else "SOME FAILED")
sys.exit(1 if fails else 0)
