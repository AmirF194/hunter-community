"""涨停后强势整理线(agent_limitup)· 规则用例。

口径是用户 2026-09-17 立项时选的(见引擎文件头):按板块判涨停、三天收盘高于涨停日收盘(严格大于)、
每个信号独立买 1 万(取整股)、次日收盘卖、跌停 / 停牌顺延、A 股手续费从现金里扣。
"""
from datetime import date, timedelta

import pytest

from app.services.quant import agent_limitup as lu
from app.services.quant import agent_vcp as av
from app.services.quant import commission as cm


def bars(closes, lows=None, start=date(2026, 3, 2)):
    """收盘序列 → [(日期, 收, 高, 低, 量)],日期逐日 +1(测试不关心周末)。"""
    lows = lows or closes
    return [(start + timedelta(days=i), c, c, lo, 1e6) for i, (c, lo) in enumerate(zip(closes, lows))]


def ind(closes, lows=None, prev=None):
    """5 根收盘 → 指标。前面补一根 T-5(默认 T-4 收盘的 0.9 倍,让 5 日均线向上),买入类用例不必每条都关心 L-07。"""
    lows = lows or closes
    p5 = closes[0] * 0.9 if prev is None else prev
    return lu.indicators(bars([p5] + list(closes), [p5] + list(lows)))


# ─── 板块门槛 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("code,name,on,lim", [
    ("600519", "贵州茅台", "2026-03-02", 0.098), ("000001", "平安银行", None, 0.098), ("002594", "比亚迪", "2025-01-02", 0.098),
    ("300750", "宁德时代", "2026-03-02", 0.198), ("301236", "软通动力", None, 0.198), ("688981", "中芯国际", "2025-01-02", 0.198),
    ("689009", "九号公司", "2026-03-02", 0.198),
    # 创业板 / 科创板的 ST 也是 20%(立项时写成 5% 是错的,2026-09-17 核对时发现:300044 涨 10.29% 被当成涨停)
    ("300093", "*ST金刚", "2026-03-02", 0.198), ("300044", "*ST赛为", "2025-01-02", 0.198),
    # 主板 ST:2025-07-07 起 10%,之前 5%
    ("600289", "ST信通", "2025-07-04", 0.048), ("600289", "ST信通", "2025-07-07", 0.098),
    ("000004", "st国华", "2026-03-02", 0.098), ("000004", "st国华", None, 0.098),
])
def test_limit_by_board(code, name, on, lim):
    assert lu.limit_of(code, name, on=on)[0] == lim


# ─── 买入三条 ──────────────────────────────────────────────────────

def test_main_board_signal():
    # T-4 10.00 → T-3 11.00(+10%)→ 三天 11.20 / 11.05 / 11.30 都 > 11.00,每天都没涨停
    f = lu.entry_checks(ind([10.0, 11.0, 11.2, 11.05, 11.3]), "600001", "测试")
    assert f["ok"] and f["L-01"] and f["L-02"] and f["L-03"]


def test_rounding_limit_counts():
    # 3.33 元涨停价 3.66,实际涨幅 9.91% —— 9.8% 门槛要算涨停
    assert lu.entry_checks(ind([3.33, 3.66, 3.7, 3.68, 3.72]), "600001", "测试")["L-01"]


def test_main_board_not_limit():
    assert not lu.entry_checks(ind([10.0, 10.9, 11.2, 11.05, 11.3]), "600001", "测试")["L-01"]


def test_growth_board_needs_20pct():
    closes = [10.0, 11.0, 11.2, 11.05, 11.3]           # 创业板涨 10% 不算涨停
    assert not lu.entry_checks(ind(closes), "300001", "测试")["L-01"]
    closes = [10.0, 12.0, 12.2, 12.1, 12.3]            # 涨 20% 才算
    assert lu.entry_checks(ind(closes), "300001", "测试")["ok"]


def test_growth_board_12pct_day_is_not_limit_again():
    # 创业板涨停后第二天涨 12%:不是涨停,L-02 过
    f = lu.entry_checks(ind([10.0, 12.0, 13.44, 13.0, 13.1]), "300001", "测试")
    assert f["L-02"] and f["ok"]


def test_st_main_board_before_and_after_rule_change():
    closes = [10.0, 10.5, 10.6, 10.55, 10.7]           # 涨 5%
    old = lu.indicators(bars([9.0] + closes, start=date(2025, 6, 2)))
    new = lu.indicators(bars([9.0] + closes, start=date(2026, 3, 2)))
    assert lu.entry_checks(old, "600001", "ST测试")["ok"]          # 2025-07-07 前 5% 算涨停
    assert not lu.entry_checks(new, "600001", "ST测试")["L-01"]    # 之后要 10%


def test_st_growth_board_needs_20pct():
    assert not lu.entry_checks(ind([10.0, 11.03, 11.1, 11.05, 11.2]), "300044", "*ST赛为")["L-01"]


def test_impossible_jump_is_data_error():
    # 主板一天涨 19.4% 不可能(600508 拆股修正改错的真实样子),双创 21.6% 同理
    assert not lu.entry_checks(ind([7.424, 8.864, 9.057, 9.007, 9.043]), "600508", "上海能源")["L-01"]
    assert not lu.entry_checks(ind([44.475, 54.101, 54.954, 55.729, 54.864]), "300895", "测试")["L-01"]
    # 边界:主板 10.9%、双创 20.9% 仍算
    assert lu.entry_checks(ind([10.0, 11.09, 11.2, 11.15, 11.3]), "600001", "测试")["L-01"]
    assert lu.entry_checks(ind([10.0, 12.09, 12.2, 12.15, 12.3]), "300001", "测试")["L-01"]


def test_limit_again_rejected():
    # 第二天又涨停
    f = lu.entry_checks(ind([10.0, 11.0, 12.1, 12.0, 12.2]), "600001", "测试")
    assert f["L-01"] and not f["L-02"] and not f["ok"]


def test_close_equal_limit_day_rejected():
    # 用户原话「高于」:等于涨停日收盘不算
    f = lu.entry_checks(ind([10.0, 11.0, 11.2, 11.0, 11.3]), "600001", "测试")
    assert not f["L-03"] and not f["ok"]


def test_close_below_limit_day_rejected():
    f = lu.entry_checks(ind([10.0, 11.0, 11.2, 10.9, 11.3]), "600001", "测试")
    assert not f["L-03"]


def test_uses_limit_day_close_not_open():
    # 三天收盘都在涨停日收盘之上即可,和开盘价无关(用户没选开盘价口径)
    assert lu.entry_checks(ind([10.0, 11.0, 11.01, 11.02, 11.03]), "600001", "测试")["ok"]


# ─── L-07 5 日均线多头(2026-09-17 用户追加:收盘 > MA5 且 MA5 向上)─────────

def test_ma5_up_and_above_passes():
    f = lu.entry_checks(ind([10.0, 11.0, 11.2, 11.05, 11.3], prev=10.5), "600001", "测试")
    assert f["L-07"] and f["ok"]


def test_ma5_not_rising_rejected():
    # T-5 收盘 11.5 > T 收盘 11.3 → MA5 比前一天低
    i = ind([10.0, 11.0, 11.2, 11.05, 11.3], prev=11.5)
    assert i["ma5"] < i["ma5_prev"]
    f = lu.entry_checks(i, "600001", "测试")
    assert f["L-01"] and f["L-02"] and f["L-03"] and not f["L-07"] and not f["ok"]


def test_ma5_flat_rejected():
    # T-5 收盘 = T 收盘 → MA5 持平,不算向上
    f = lu.entry_checks(ind([10.0, 11.0, 11.2, 11.05, 11.3], prev=11.3), "600001", "测试")
    assert not f["L-07"]


def test_close_below_ma5_rejected():
    # 涨停日后三天高位,T 收盘回落到 MA5 下面(仍高于涨停日收盘、MA5 仍向上)
    i = ind([10.0, 12.0, 13.5, 13.6, 12.2], prev=9.0)      # 创业板:T-3 涨 20%,之后每天 < 20%
    assert i["ma5"] > i["ma5_prev"] and 12.2 < i["ma5"]
    f = lu.entry_checks(i, "300001", "测试")
    assert f["L-03"] and not f["L-07"]


def test_ma5_needs_six_bars():
    i = lu.indicators(bars([10.0, 11.0, 11.2, 11.05, 11.3]))
    assert i is not None and i["ma5"] is None
    f = lu.entry_checks(i, "600001", "测试")
    assert not f["L-07"] and f["ma5_na"] and not f["ok"]
    it = lu.watch_item("600001", "测试", i, False, None)
    assert "L-07" in it["fails"] and "算不出" in it["gap"]


def test_ma5_value():
    i = ind([10.0, 11.0, 11.2, 11.05, 11.3], prev=10.5)
    assert i["ma5"] == pytest.approx((10.0 + 11.0 + 11.2 + 11.05 + 11.3) / 5)
    assert i["ma5_prev"] == pytest.approx((10.5 + 10.0 + 11.0 + 11.2 + 11.05) / 5)


def test_short_bars():
    assert lu.indicators(bars([10.0, 11.0, 11.2, 11.3])) is None


# ─── 一天的决策 ────────────────────────────────────────────────────

def run(date_iso, positions, cash, watch, ind_map):
    return lu.run_day(date_iso, positions, cash, None, watch, None, 0, dict(lu.PARAMS), av.GUARDS,
                      ind_of=lambda c: ind_map.get(c))


def test_buy_10k_whole_shares_and_fee():
    i = ind([10.0, 11.0, 11.2, 11.05, 11.4])        # 收盘 11.40 → 10000 // 11.40 = 877 股
    r = run("2026-03-06", [], 1_000_000.0, [("600001", "测试", None)], {"600001": i})
    assert len(r["fills"]) == 1
    f = r["fills"][0]
    assert f["side"] == "buy" and f["shares"] == 877 and f["rule_id"] == "L-01"
    fee = cm.a_share_fee("buy", 877, 11.4)
    assert fee == 5.1                                   # 9997.8 元的万 2.5 不到 5 元,按最低 5 元 + 过户费
    assert r["cash"] == pytest.approx(1_000_000.0 - 877 * 11.4 - fee)
    assert r["equity"] == pytest.approx(1_000_000.0 - fee)


def test_price_above_amount_cannot_buy():
    i = ind([10000.0, 11000.0, 11200.0, 11050.0, 11300.0])
    r = run("2026-03-06", [], 1_000_000.0, [("600001", "测试", None)], {"600001": i})
    assert r["fills"] == [] and r["watch_items"][0].get("blocked")


def _pos(px=13.37, size=747):
    return av.Position(code="600001", name="测试", size=size, initial_size=size, entry_price=px, entry_date="2026-03-06",
                       avg_cost=px, highest=px, level=1, bars_held=0, entry_rule="L-01",
                       extra={"buy_fee": cm.a_share_fee("buy", size, px), "last_close": px})


def test_sell_next_close_with_fee():
    nxt = lu.indicators(bars([11.0, 11.2, 11.05, 13.37, 13.9]))
    r = run("2026-03-09", [_pos()], 0.0, [], {"600001": nxt})
    assert len(r["fills"]) == 1
    f = r["fills"][0]
    assert f["side"] == "sell" and f["rule_id"] == "L-05" and f["shares"] == 747 and f["hold_days"] == 1
    assert f["pnl_abs"] == pytest.approx((13.9 - 13.37) * 747, abs=0.01)     # 成交表的 pnl_abs 是扣费前
    assert r["cash"] == pytest.approx(747 * 13.9 - cm.a_share_fee("sell", 747, 13.9))
    assert r["positions"] == []


def test_limit_down_close_defers():
    # 次日 13.37 → 12.04(-9.95%)且收盘 = 最低:跌停卖不出,顺延
    nxt = lu.indicators(bars([11.0, 11.2, 11.05, 13.37, 12.04], lows=[11.0, 11.2, 11.05, 13.37, 12.04]))
    r = run("2026-03-09", [_pos()], 0.0, [], {"600001": nxt})
    assert r["fills"] == [] and len(r["positions"]) == 1
    assert r["positions"][0].extra["deferred"] == 1
    assert r["equity"] == pytest.approx(747 * 12.04)
    # 再下一天正常收盘 → 卖出,理由里写明顺延
    nxt2 = lu.indicators(bars([11.2, 11.05, 13.37, 12.04, 12.3]))
    r2 = run("2026-03-10", r["positions"], 0.0, [], {"600001": nxt2})
    assert len(r2["fills"]) == 1 and "顺延" in r2["fills"][0]["rationale"] and r2["fills"][0]["hold_days"] == 2


def test_down_big_but_not_sealed_sells():
    # 跌 9.95% 但收盘高于最低(没封住跌停)→ 照卖
    nxt = lu.indicators(bars([11.0, 11.2, 11.05, 13.37, 12.04], lows=[11.0, 11.2, 11.05, 13.37, 11.9]))
    r = run("2026-03-09", [_pos()], 0.0, [], {"600001": nxt})
    assert len(r["fills"]) == 1


def test_suspended_defers_and_marks_last_close():
    r = run("2026-03-09", [_pos()], 0.0, [], {})
    assert r["fills"] == [] and r["positions"][0].extra["deferred"] == 1
    assert r["equity"] == pytest.approx(747 * 13.37)


def test_growth_board_limit_down_threshold():
    # 创业板跌 12% 收在最低:不到 20% 跌停,照卖
    p = _pos(px=20.0, size=500)
    p.code = "300001"
    nxt = lu.indicators(bars([15.0, 18.0, 18.5, 20.0, 17.6], lows=[15.0, 18.0, 18.5, 20.0, 17.6]))
    r = run("2026-03-09", [p], 0.0, [], {"300001": nxt})
    assert len(r["fills"]) == 1


def test_a_share_fee():
    assert cm.a_share_fee("buy", 100, 100) == 5.1          # 1 万:佣金最低 5 + 过户费 0.1
    assert cm.a_share_fee("sell", 100, 100) == 10.1        # + 印花税 5
    assert cm.a_share_fee("sell", 1000, 50) == 38.0        # 5 万:佣金 12.5 + 过户费 0.5 + 印花税 25
    assert cm.a_share_fee("buy", 0, 10) == 0.0
