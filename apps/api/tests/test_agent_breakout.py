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
check("指标 · 枢轴 = 前一天为止 21 日最高(不含今天 111.1)", abs(ind["pivot"] - 101.0) < 1e-9, str(ind["pivot"]))
check("指标 · Base 低点 = 前一天为止 21 日最低", abs(ind["base_low"] - 99.0) < 1e-9, str(ind["base_low"]))
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
SCREEN_BROKEN = dict(SCREEN_OK, rng1m=0.15, rng5d=0.12)


def good(prev=None, **kw):
    x = {"close": 104.0, "high": 104.5, "low": 101.5, "volume": 2_000_000.0, "prev_high": 102.0,
         "pivot": 102.0, "base_low": 95.0, "av10": 1_100_000.0, "av20": 1_000_000.0, "av50": 1_000_000.0,
         "ema8": 101.0, "ema21": 99.0, "sma50": 95.0, "screen": dict(SCREEN_BROKEN)}
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
      not ab.entry_ok(good(prev={"screen": {"rng1m": 0.15}}, screen=dict(SCREEN_OK)), P, 90, UP))
check("P-06 · 高出枢轴 5% 以上不追", not ab.entry_ok(good(close=107.5, high=108.0), P, 90, UP))
check("P-06 · 量不到 1.5 倍 50 日均量不买", not ab.entry_ok(good(volume=1_400_000.0), P, 90, UP))
check("P-06 · 没站上枢轴不买", not ab.entry_ok(good(close=101.5), P, 90, UP))
check("P-03 · RS 79 不买", not ab.entry_ok(good(), P, 79, UP))
check("P-03 · RS 缺不买", not ab.entry_ok(good(), P, None, UP))
check("P-03 · 前一天均线没排好不买", not ab.entry_ok(good(prev={"sma50": 102.5}), P, 90, UP))
check("P-04 · 前一天 5 日振幅没收紧(0.06 > 0.08 × 0.65)不买", not ab.entry_ok(good(prev={"screen": {"rng5d": 0.06}}), P, 90, UP))
check("P-04 · 前一天 1 月振幅没收缩到 3 月 0.55 倍不买", not ab.entry_ok(good(prev={"screen": {"rng1m": 0.12}}), P, 90, UP))
check("P-04 · 前一天低点没抬高不买", not ab.entry_ok(good(prev={"screen": {"low21": 90.5}}), P, 90, UP))
check("P-05 · 前一天 10 日均量没干燥(≥ 50 日 × 0.9)不买", not ab.entry_ok(good(prev={"av10": 950_000.0}), P, 90, UP))
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
                       avg_cost=ep, highest=ep, level=level, stop=ep * 0.94, risk=ep * 0.06,
                       extra=dict({"unit": unit}, **(extra or {})))


def hold(close, **kw):
    """一份「什么出场条件都不碰」的持仓指标,再按需改几个字段。"""
    x = {"close": close, "high": close * 1.005, "low": close * 0.995, "volume": 1_000_000.0, "prev_high": close * 0.99,
         "pivot": 100.0, "base_low": 90.0, "av10": 1_000_000.0, "av20": 1_000_000.0, "av50": 1_000_000.0,
         "ema8": close * 0.98, "ema21": close * 0.96, "sma50": close * 0.9, "screen": None, "prev": None}
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
r = day(pos(), hold(99.0, ema8=99.5))
check("P-11 · 亏损中收盘 < EMA8 → 止损 C", sold(r) and sold(r)[0]["rule_id"] == "P-11", str(r["fills"]))
r = day(pos(), hold(101.0, ema8=102.0))
check("P-11 · 盈利中跌破 EMA8 不算止损 C", not sold(r), str(r["fills"]))
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
r = day(pos(), hold(99.0, low=87.0, ema8=99.5))
check("出场顺序 · 同时满足 A 和 C 时记止损 A(脚本 full_exit 顺序)", sold(r) and sold(r)[0]["rule_id"] == "P-09")

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
