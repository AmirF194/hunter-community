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


VPS_S = {"acc21": 4, "dist21": 0, "ad21": 4, "acc63": 6, "dist63": 1, "ad63": 5, "udv63": 1.4, "udv21": 1.5}


def vps(ad21, ad63=5, udv63=1.4):
    return dict(VPS_S, ad21=ad21, acc21=max(ad21, 0), dist21=max(-ad21, 0), ad63=ad63, udv63=udv63)


GF_S = {"stop": 101.0, "sup": {"count": 4, "items": [], "text": "4 类"}, "vp": 6, "vps": VPS_S, "def": (16, 30),
        "macd_d": True, "macd_w": True, "res": None}              # 五项全 S(500 分)


def good(prev=None, gf=None, **kw):
    x = {"close": 104.0, "high": 104.5, "low": 101.5, "volume": 2_000_000.0, "prev_high": 102.0,
         "pivot": 102.0, "base_low": 95.0, "av10": 1_100_000.0, "av20": 1_000_000.0, "av50": 1_000_000.0,
         "ema8": 101.0, "ema21": 99.0, "sma50": 95.0, "screen": dict(SCREEN_BROKEN),
         "ema10": 101.5, "ema20": 99.5, "atr20": 3.0, "gf": dict(GF_S, **(gf or {}))}
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
UNIT = int(100_000 * 0.20 / 104.0)
UNIFORM = int(UNIT * 0.5)
if buys:
    check("P-07 · v8 统一仓位:首次买入 完整仓位(总资产 20%)的一半", buys[0]["shares"] == UNIFORM, f"{buys[0]['shares']} vs {UNIFORM}")
    check("进场 · 理由里写了 P-01 ~ P-06、走廊、评分与统一仓位", all(k in buys[0]["rationale"] for k in ("P-01", "P-04", "P-06", "P-21", "P-20", "统一仓位", "昨收")))
    check("进场 · 加仓基数 = 完整仓位(extra.unit)", r["positions"][0].extra.get("unit") == UNIT)
    check("进场 · 成交记录照写档位与分数(追高 1.96% → A,其余 S → 480)", buys[0].get("grade") == "S" and buys[0].get("points") == 480,
          str((buys[0].get("grade"), buys[0].get("points"))))
    check("P-11 · v7 回到 v5:初始止损 = 进场价 − 1 ATR(104 − 3 = 101)", abs(r["positions"][0].stop - 101.0) < 1e-9,
          str(r["positions"][0].stop))

r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, P, G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else good(atr20=12.0))
check("P-11 · ATR 12 超过 8% → 止损被截在 进场价 × 0.92",
      r["positions"] and abs(r["positions"][0].stop - 104.0 * 0.92) < 1e-9, str([x.stop for x in r["positions"]]))

# ── v7 评分定仓 ──────────────────────────────────────────────
def entry_with(gf, score=90):
    return ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", score)], None, 0, P, G,
                      ind_of=lambda c: UP if c == ab.MARKET_KEY else good(gf=gf))


# v8:第 4 项换成追高幅度。good() 收盘 104、枢轴 102 → 高出 1.96% → A
g0_ = ab.grade(good(), 101.0, 90)
check("P-20 · v8 第 4 项叫「追高幅度」,不再是走廊", g0_["factors"][3][0] == "追高幅度", str(g0_["factors"][3]))
check("P-20 · 四项 S + 追高 A = 480", g0_["points"] == 480, g0_["text"])
check("追高 · 高出 0.5% → S", ab.grade(good(close=102.5), 101.0, 90)["factors"][3][1] == "S")
check("追高 · 高出 1.99%(A 档上沿内)→ A", ab.grade(good(close=104.03), 101.0, 90)["factors"][3][1] == "A")
check("追高 · 高出 2.9% → B", ab.grade(good(close=105.0), 101.0, 90)["factors"][3][1] == "B")
check("追高 · 高出 3.9% → C", ab.grade(good(close=106.0), 101.0, 90)["factors"][3][1] == "C")
check("追高 · 高出 4.4% → D", ab.grade(good(close=106.5), 101.0, 90)["factors"][3][1] == "D")
check("追高 · 枢轴缺 → D", ab.grade(dict(good(), pivot=None), 101.0, 90)["factors"][3][1] == "D")
# A 级:支撑 2 类 B60 + 量价 3 C40 + 抗跌 3 次 C40 + 追高 A80 + 只有周线金叉 A80 = 300
gf_a = {"sup": {"count": 2, "items": [], "text": "2 类"}, "vps": vps(1), "def": (3, 30), "macd_d": False, "macd_w": True}
g_a = ab.grade(good(gf=gf_a), 101.0, 90)
check("P-20 · 60 + 40 + 40 + 80 + 80 = 300 → A", g_a["grade"] == "A" and g_a["points"] == 300, g_a["text"])
r = entry_with(gf_a)
b = [f for f in r["fills"] if f["side"] == "buy"]
check("P-07 · v8 统一仓位:A 级也买完整仓位一半,档位照记", b and b[0]["shares"] == UNIFORM and b[0]["grade"] == "A", str(r["fills"]))
# D 级:支撑 0 + 量价 2 + 抗跌 2 + 追高 A80 + 周线 A80 = 160
gf_d = {"sup": {"count": 0, "items": [], "text": "0 类"}, "vps": vps(0), "def": (2, 30), "macd_d": False, "macd_w": True}
check("P-20 · 0 + 0 + 0 + 80 + 80 = 160 → D", ab.grade(good(gf=gf_d), 101.0, 90)["grade"] == "D")
r = entry_with(gf_d)
b = [f for f in r["fills"] if f["side"] == "buy"]
check("P-20 · v9 D 级不再拦人:照买、档位记 D", b and b[0]["grade"] == "D" and b[0]["shares"] == UNIFORM, str(r["fills"]))
r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, dict(P, block_d=True), G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else good(gf=gf_d))
check("P-20 · 开关 block_d 打开 → D 级不买(v8 口径留成开关)", not r["fills"]
      and "D 级不买" in (r["watch_items"][0].get("blocked_reason") or ""), str(r["watch_items"][0]))
# v9 唯一硬条件:追高超过 4% 不买。枢轴 102:收盘 106.5 → 4.4% 挡;106.0 → 3.9% 放行
r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, P, G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else good(close=106.5))
check("P-20 · 追高 4.4% > 4% → 不买并写明", not r["fills"] and "追高不买" in (r["watch_items"][0].get("blocked_reason") or ""),
      str(r["watch_items"][0]))
r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, P, G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else good(close=106.0))
check("P-20 · 追高 3.9% → 照买", any(f["side"] == "buy" for f in r["fills"]), str(r["watch_items"][0]))
gf_c = dict(gf_d, sup={"count": 2, "items": [], "text": "2 类"})
g_c = ab.grade(good(gf=gf_c), 101.0, 90)
check("P-20 · 60 + 0 + 0 + 80 + 80 = 220 → C", g_c["grade"] == "C" and g_c["points"] == 220, g_c["text"])
r = entry_with(gf_c)
b = [f for f in r["fills"] if f["side"] == "buy"]
check("P-07 · v8 统一仓位:C 级同样买完整仓位一半", b and b[0]["shares"] == UNIFORM and b[0]["grade"] == "C", str(r["fills"]))
r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, dict(P, size_by_grade=True), G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else good(gf=gf_c))
b = [f for f in r["fills"] if f["side"] == "buy"]
check("P-07 · 开关 size_by_grade 打开 → 回到 v7 按档定仓(C 级 5%)", b and b[0]["shares"] == int(100_000 * 0.05 / 104.0), str(r["fills"]))
# ── v10 量价配合定档 ─────────────────────────────────────────
check("量价 v10 · 近 21 天净放量上涨 4 → S", ab.vp_tier(vps(4))[0] == "S")
check("量价 v10 · 3 → A · 2 → B · 1 → C", [ab.vp_tier(vps(x))[0] for x in (3, 2, 1)] == ["A", "B", "C"])
check("量价 v10 · 0 或负数 → D", ab.vp_tier(vps(0))[0] == "D" and ab.vp_tier(vps(-2))[0] == "D")
check("量价 v10 · 3 个月上涨量 ÷ 下跌量 1.8 过热 → S 降成 A", ab.vp_tier(vps(4, udv63=1.8))[0] == "A")
check("量价 v10 · 3 个月净放量 8 过热 → B 降成 C", ab.vp_tier(vps(2, ad63=8))[0] == "C")
check("量价 v10 · 比值 1.7 正好不算过热", ab.vp_tier(vps(4, udv63=1.7))[0] == "S")
check("量价 v10 · D 不再往下降", ab.vp_tier(vps(0, udv63=2.5))[0] == "D")
check("量价 v10 · 说明里写了放量天数、比值和降档", all(k in ab.vp_tier(vps(4, udv63=1.8))[1] for k in ("放量上涨", "上涨量 ÷ 下跌量", "过热降一档")))
check("量价 v10 · 算不出 → None(评分按 D 计 0 分)", ab.vp_tier(None)[0] is None)
check("量价 v10 · 评分里第 2 项用新口径(原 vp=6 不再决定档位)",
      ab.grade(good(gf={"vp": 6, "vps": vps(0)}), 101.0, 90)["factors"][1][1] == "D")
# vp_stats:造 140 根日线,量 1M 平稳,最后 21 天里 3 天放量上涨、1 天放量下跌
vb = [(date(2025, 1, 1) + timedelta(days=i), 100.0 + (i % 2) * 0.1, 101.0, 99.0, 1_000_000.0) for i in range(140)]
for i, (c_, v_) in {125: (101.0, 1_500_000.0), 130: (102.0, 1_500_000.0), 135: (103.0, 1_500_000.0), 137: (99.0, 1_500_000.0)}.items():
    vb[i] = (vb[i][0], c_, 104.0, 98.0, v_)
st = ab.vp_stats(vb)
check("vp_stats · 近 21 天放量上涨 3、放量下跌 1、净 2", st and (st["acc21"], st["dist21"], st["ad21"]) == (3, 1, 2), str(st))
check("vp_stats · 日线不足 113 根 → None", ab.vp_stats(vb[-100:]) is None)

g_na = ab.grade(good(gf={"sup": None, "vp": None, "vps": None, "def": None, "macd_d": None, "macd_w": None}), 101.0, 90)
check("P-20 · 算不出的项按 D 计 0 分、MACD 算不出记 C", [f[1] for f in g_na["factors"]] == ["D", "D", "D", "A", "C"], str(g_na["factors"]))

# 走廊:R = 104 − 101 = 3。阻力 116 → 4R A;阻力 108.5 → 1.5R 空间受限
check("走廊 · 阻力 116 → 4.0R → A", ab.c3._tier(ab.corridor(good(gf={"res": (116.0, "前高")}), 101.0)[0], ab.c3.RR_MIN) == "A")
r = entry_with({"res": (108.5, "底部左侧前高")})
check("P-21 · v9 门槛 1R:走廊 1.5R → 照买", any(f["side"] == "buy" for f in r["fills"]), str(r["watch_items"][0]))
r = entry_with({"res": (106.4, "底部左侧前高")})
check("P-21 · 走廊 0.8R 不足 1R → 空间受限不买(不是记 0 分)", not r["fills"]
      and "空间受限" in (r["watch_items"][0].get("blocked_reason") or ""), str(r["watch_items"][0]))
r = ab.run_day("2026-03-02", [], 100_000.0, lambda c: [], [("AAA", "AAA", 90)], None, 0, P, G,
               ind_of=lambda c: UP if c == ab.MARKET_KEY else dict(good(), gf=None))
check("P-20 · 评分字段没算出来 → 不买", not r["fills"])

# 第 1 项支撑结构:造一段 100 → 106 平台 → 108 平台 的日线,止损 105、今天收 110
def bar(i, c, h, l, v=1_000_000.0):
    return (date(2025, 1, 1) + timedelta(days=i), c, h, l, v)


sb = [bar(i, 100.0, 100.5, 99.5) for i in range(100)]
sb += [bar(100 + i, 106.0, 106.3, 105.7) for i in range(10)]                   # 平台 A
for i in range(30):                                                             # 平台 B:缺口下沿 106.3 未回补
    sb.append(bar(110 + i, 108.0, 108.3, 107.7))
sb[115] = bar(115, 108.0, 108.9, 107.7)                                         # 前浪顶 108.9
sb[122] = bar(122, 108.2, 108.6, 106.6)                                         # 拒绝块:振幅 2.0、收盘在 80% 处,低点 106.6
sb[130] = bar(130, 108.25, 108.3, 107.7, 3_000_000.0)                           # 关键 K 线:3 倍量、收在上 1/3、高于前一天
sb.append(bar(140, 110.0, 110.5, 109.5, 2_000_000.0))                           # 今天
sp = ab.supports(sb, 105.0)
kinds = {x[0] for x in sp["items"]} if sp else set()
check("支撑 · 均线 / 前浪顶 / 拒绝块 / 缺口 / 关键 K 线五类都认出来", kinds == {"均线", "前浪顶", "拒绝块", "缺口", "关键 K 线"}, str(sp))
check("支撑 · 五类 → S", sp and ab.c3._tier(sp["count"], ab.SUP_MIN) == "S")
check("支撑 · 止损 109.6(区间里什么都没有)→ 0 类", ab.supports(sb, 109.6)["count"] == 0, ab.supports(sb, 109.6)["text"])
sb_fill = list(sb)
sb_fill[135] = bar(135, 108.0, 108.3, 106.0)                                     # 回补到 106 → 缺口没了
check("支撑 · 缺口被回补就不算", "缺口" not in {x[0] for x in ab.supports(sb_fill, 105.0)["items"]})
check("支撑 · 突破当天那根放量阳线不算关键 K 线(只看今天之前)",
      "关键 K 线" not in {x[0] for x in ab.supports(sb[:130] + [bar(130, 108.0, 108.3, 107.7)] + sb[131:], 105.0)["items"]})
check("支撑 · 日线不够 → None", ab.supports(sb[-80:], 105.0) is None)
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
check("P-09 · v7 加回:最低价跌破 Base 低点 × 0.98 → 清仓按收盘价", sold(r) and sold(r)[0]["rule_id"] == "P-09"
      and sold(r)[0]["price"] == 101.0 and sold(r)[0]["shares"] == 100, str(r["fills"]))
r = day(pos(), hold(93.9, ema8=90.0, low=93.5))
check("P-10 · v7 加回:收盘 < 进场价 × 0.94 → 固定止损", sold(r) and sold(r)[0]["rule_id"] == "P-10", str(r["fills"]))
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
