"""小鹿智能体 · 涨停后强势整理线(A 股 · 2026-09-17 用户要求新建的研究线)。

用户原话:「针对 A 股市场,扫描那些 4 个交易日前涨停,之后连续 3 天没有再涨停,而且这 3 天的收盘都没跌破
当天的开盘价的股。直接在扫描中的当天买入 1 万人民币,后一天收盘时全部卖出,回测一年的数据」。
立项时用 AskUserQuestion 问清的四个口径(都是用户选的,**改之前先问用户**):

1. 「没跌破」= **这 3 天的收盘都高于涨停那天的收盘价**(用户在「每天自己的开盘价 / 涨停日开盘价」之外自己写的)
2. 涨停按板块:主板 10%、创业板 / 科创板 20%、ST 5%。
   **立项当天核对后更正了 ST 的口径**(给用户的选项文案写的是「ST 5%」,那是错的):创业板 / 科创板的 ST 也是 20%;
   沪深主板 ST 从 2025-07-07 起由 5% 改为 10%(交易所修订交易规则)。一年回测全在这之后,实际只有 10% / 20% 两档,
   这里仍按日期区分,回测往 2025-07-07 之前延伸时不会判错
3. **每个信号独立买 1 万**,不限同时持仓(一天最多 66 个信号,本金 100 万永远不会不够)
4. 手续费按 A 股实际扣(commission.a_share_fee),而且**从现金里扣** —— 这条线的净值曲线是扣费后的

## 规则(L-xx)

买入(信号日 T 收盘后判,T 收盘价成交):
- L-01 涨停:T-3 收盘较 T-4 收盘涨幅 ≥ 涨停幅度 − 0.2 个百分点(主板 9.8% / 创业板科创板 19.8% / ST 4.8%)。
       留 0.2 是给涨停价四舍五入到分的误差:3.33 元涨停 3.66,实际涨幅 9.91%。
- L-02 没再涨停:T-2、T-1、T 三天每天涨幅都低于同一门槛
- L-03 守住:T-2、T-1、T 三天收盘都 **高于** T-3 收盘(严格大于,用户原话「高于」)
- L-04 仓位:1 万元 ÷ T 收盘价,**取整股、不按 100 股一手取整** —— 按手取整的话 100 元以上的票买不了,
       或者被抬成一手后金额远超 1 万,每笔金额不一样,总盈亏就被高价股绑架了。这是替用户做的决定,研究口径优先
卖出:
- L-05 T+1 收盘全部卖出。**T+1 收盘跌停(收盘价 = 最低价且跌幅达到跌停门槛)视为卖不出,顺延到下一个交易日收盘**;
       T+1 停牌(没有日线)同样顺延。这是 A 股的交易约束,不是用户规则的一部分,卖出理由里写明
风控:
- L-06 手续费:佣金万 2.5(最低 5 元)+ 过户费 0.001% 买卖各一次,卖出另收印花税 0.05%,从现金里扣
- 不设护栏(单日熔断 / 连亏暂停):信号彼此独立,暂停开仓会让统计不再是「每个信号」

## 数据口径与已知局限

- 候选池 = 筛选器时间回溯跑 POOL_SCRIPT(宽松预筛:涨幅门槛 9.8%、不涨停门槛按 20%),
  **板块门槛由引擎按代码精确判**。脚本里写不出「按代码分板块」,所以不能把严格规则直接写进池子。
- ST 按**今天**的股票简称判断(名称里有 ST),历史上戴帽摘帽的时点拿不到,会有少量误判。
- 筛选器的 A 股股票池是「市值约 5000 万美元以上」且按今天的快照,有幸存者偏差;北交所没有历史日线,不在池里。
- 日线是复权后的,涨跌幅比例不受除权影响;成交按收盘价,没有滑点。
"""
from __future__ import annotations

from app.services.quant import agent_vcp as av
from app.services.quant import commission as cm

MARKET = "a"
CURRENCY = "CNY"
CURRENCY_SYMBOL = "¥"
CURRENCY_UNIT = "元"
BENCH_LABEL = "沪深300"
INITIAL_CAPITAL = 1_000_000.0

PARAMS = {
    "amount": 10_000.0,          # 每个信号买入金额(元)
    "hold_days": 1,              # 持有几个交易日后收盘卖出
    "lu_main": 0.098, "lu_growth": 0.198, "lu_st": 0.048,
    "st_10pct_from": "2025-07-07",   # 沪深主板 ST 涨跌幅从这天起 5% → 10%
    # 涨幅合理性上限 = 名义涨停 + 1 个百分点:超过就是日线有问题,不算涨停(见 entry_checks)
    "lu_cap_slack": 0.012,
    # 面板「护栏」卡要读这两个键;这条线不限持仓、不限单股占比(每笔 1 万 / 本金 100 万 = 1%)
    "max_holdings": 1000, "max_pos_pct": 0.01,
    "watch_pool_days": 1,
}
STOP_KEYS: tuple = ()
MIN_BARS = 5
ENTRY_RULE = "L-01"
WATCH_POOL_DAYS = 1
NO_GUARDS = True                     # 不设单日熔断 / 连亏暂停,面板护栏栏显示「不设」
EXEC_NOTE = "纸上交易 · 日线收盘价成交 · 手续费从现金里扣(净值是扣费后的)"
REBALANCE_SUFFIX = " · 次日收盘卖出(跌停 / 停牌顺延)"

POOL = "limitup"
POOL_LIMIT = 500
POOL_LABEL = "涨停后强势整理预筛池(T-3 涨幅 ≥ 9.8% · 之后三天每天涨幅 < 20% · 三天收盘都高于 T-3 收盘;板块涨停门槛由引擎精确判)"
POOL_SCRIPT = """# ===== 涨停后强势整理 · 宽松预筛(小鹿 · A 股研究线)=====
# 脚本里分不出板块,这里按最宽的门槛圈池:涨停按 9.8%、不涨停按创业板的 20%;
# 主板 10% / 创业板科创板 20% 由引擎按代码精确判。
# ⚠ 2025-07-07 前主板 ST 是 5% 涨停,这个池子圈不到 —— 回测往那之前延伸要先放宽成 0.048。
#   2026-09-17 第一次全年回填用的就是 0.048,结果 4 天命中 548~726 只,超过筛选器单次 500 只上限被截掉,才收紧
def up_t3  = (close[3] - close[4]) / close[4] >= 0.098;
def not_lu = (close[2] - close[3]) / close[3] < 0.198 and (close[1] - close[2]) / close[2] < 0.198 and (close - close[1]) / close[1] < 0.198;
def hold   = close[2] > close[3] and close[1] > close[3] and close > close[3];

plot scan = up_t3 and not_lu and hold;
"""

RULE_NAME = {"L-01": "涨停后强势整理买入", "L-05": "次日收盘卖出"}
RULE_PARAM_KEY: dict = {}          # 规则固定,不进优化器


def limit_of(code: str, name: str | None, p: dict = PARAMS, on: str | None = None) -> tuple[float, str]:
    """→ (涨停判定门槛, 板块说明)。on = 那根 K 线的日期(ISO),决定主板 ST 用 5% 还是 10%;不给按现行规则。
    创业板 / 科创板先判:那边 ST 也是 20%。北交所(4 / 8 / 92 开头)不在池里,这里按主板兜底不会被用到。"""
    if str(code).startswith(("300", "301", "688", "689")):
        return p["lu_growth"], "创业板 / 科创板 20%"
    if "ST" in (name or "").upper():
        if on is not None and str(on) < p["st_10pct_from"]:
            return p["lu_st"], "主板 ST 5%(2025-07-07 前)"
        return p["lu_main"], "主板 ST 10%"
    return p["lu_main"], "主板 10%"


def rules_for(p: dict = PARAMS) -> list[dict]:
    amt = f"{p['amount']:,.0f}"
    return [
        {"id": "L-01", "kind": "buy", "condition": (f"涨停:4 个交易日前(T-3)收盘较前一天涨幅达到涨停 —— 主板 ≥ {p['lu_main'] * 100:.1f}%、"
                                                   f"创业板 / 科创板(含 ST)≥ {p['lu_growth'] * 100:.1f}%;主板 ST {p['st_10pct_from']} 起同主板,"
                                                   f"之前 ≥ {p['lu_st'] * 100:.1f}%")},
        {"id": "L-02", "kind": "buy", "condition": "没再涨停:之后三天(T-2、T-1、T)每天涨幅都没到同一门槛"},
        {"id": "L-03", "kind": "buy", "condition": "守住:这三天的收盘都高于涨停那天(T-3)的收盘价"},
        {"id": "L-04", "kind": "risk", "condition": (f"仓位:每个信号买入 {amt} 元(按 {amt} ÷ 收盘价取整股,不按 100 股一手取整),"
                                                    f"信号当天收盘价成交;不限同时持仓,不设熔断 / 连亏暂停")},
        {"id": "L-05", "kind": "sell", "condition": (f"卖出:买入后第 {p['hold_days']} 个交易日收盘全部卖出;"
                                                    "那天收盘跌停(收盘 = 最低且跌幅到跌停)或停牌卖不出,顺延到下一个交易日收盘")},
        {"id": "L-06", "kind": "risk", "condition": "手续费:佣金万 2.5(最低 5 元)+ 过户费 0.001% 买卖各一次,卖出另收印花税 0.05%;从现金里扣"},
    ]


RULES = rules_for(PARAMS)            # agent_run 的复盘 / 规则手册按 RULES 取规则种类(默认参数的文案)


def summary(p: dict = PARAMS) -> str:
    return (f"A 股涨停后强势整理:4 个交易日前涨停、之后三天没再涨停且收盘都高于涨停日收盘的票,"
            f"信号当天收盘买入 {p['amount']:,.0f} 元,第 {p['hold_days']} 个交易日收盘卖出。"
            "涨停按板块区分(主板 10% / 创业板科创板 20%;主板 ST 2025-07-07 前 5%),手续费按 A 股实际扣。")


# ═══════════════════════════════════════════════════════════════
# 指标
# ═══════════════════════════════════════════════════════════════

def indicators(bars: list[tuple], p: dict = PARAMS, bench: dict | None = None) -> dict | None:
    """bars = [(d, 收, 高, 低, 量)] 升序,最后一根是今天。只要最近 5 根收盘 + 今天的最低价。"""
    if len(bars) < MIN_BARS:
        return None
    c = [b[1] for b in bars[-5:]]            # c[0]=T-4 · c[1]=T-3 · c[2]=T-2 · c[3]=T-1 · c[4]=T
    if any(x is None or x <= 0 for x in c):
        return None
    return {"date": str(bars[-1][0]), "close": c[4], "low": bars[-1][3], "closes": c,
            "chg": [c[i] / c[i - 1] - 1 for i in range(1, 5)]}      # chg[0] = T-3 涨幅 … chg[3] = T 涨幅


def entry_checks(ind: dict, code: str, name: str | None, p: dict = PARAMS) -> dict:
    lim, board = limit_of(code, name, p, ind.get("date"))
    c, chg = ind["closes"], ind["chg"]
    # 上限:主板一天涨不到 11%、双创涨不到 21%。2026-09-17 全年核对发现 screen_asof 的拆股修正会把少数 A 股
    # 前一根收盘改错,造出假涨停(600508 原始 9.43 → 8.86 跌 6%,修正后 7.42 → 8.86「涨 19.4%」被买入)
    cap = lim + p["lu_cap_slack"] + 0.002
    l01 = lim <= chg[0] <= cap
    l02 = all(x < lim for x in chg[1:])
    l03 = all(x > c[1] for x in c[2:])
    return {"L-01": l01, "L-02": l02, "L-03": l03, "ok": l01 and l02 and l03, "limit": lim, "board": board,
            "over_cap": chg[0] > cap, "cap": cap}


def _pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


# ═══════════════════════════════════════════════════════════════
# 观察列表
# ═══════════════════════════════════════════════════════════════

def watch_item(code, name, ind, held, blocked_reason, score=None, p: dict = PARAMS) -> dict:
    it = {"symbol": code, "name": name, "score": score, "rule_id": "L-01", "rule_text": rules_for(p)[0]["condition"]}
    if ind is None:
        it.update({"price": None, "progress_pct": None, "gap": "当天没有日线或不足 5 根,判不了"})
        return it
    f = entry_checks(ind, code, name, p)
    it["price"] = round(ind["close"], 2)
    it["progress_pct"] = int(sum(1 for k in ("L-01", "L-02", "L-03") if f[k]) / 3 * 100)
    it["fails"] = [k for k in ("L-01", "L-02", "L-03") if not f[k]]
    c, chg = ind["closes"], ind["chg"]
    detail = (f"{f['board']}:T-3 涨 {_pct(chg[0])},之后三天 {' / '.join(_pct(x) for x in chg[1:])},"
              f"三天收盘 {' / '.join(f'{x:.2f}' for x in c[2:])} 对涨停日收盘 {c[1]:.2f}")
    if held:
        it["gap"] = "已持仓 · 等卖出"
    elif f["ok"]:
        it["gap"] = "三条全满足 —— 今日收盘买入。" + detail
    else:
        why = []
        if f["over_cap"]:
            why.append(f"L-01 T-3 涨幅超过 {f['cap'] * 100:.1f}%,不是涨停(新股上市头几天没有涨跌幅限制,或日线有误)")
        elif not f["L-01"]:
            why.append(f"L-01 T-3 涨幅没到 {f['limit'] * 100:.1f}%(按{f['board']})")
        if not f["L-02"]:
            why.append("L-02 之后三天里又涨停了")
        if not f["L-03"]:
            why.append("L-03 有一天收盘没高于涨停日收盘")
        it["gap"] = "不买:" + ";".join(why) + "。" + detail
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


def manage_position(pos: av.Position, ind: dict, state: dict, p: dict = PARAMS, want_text: bool = True) -> list[dict]:
    pos.bars_held += 1
    if pos.bars_held < p["hold_days"]:
        return []
    px, ep = ind["close"], pos.entry_price
    lim, _board = limit_of(pos.code, pos.name, p, ind.get("date"))
    # 跌停封板卖不出:收盘就是最低价,且较上一根日线的跌幅达到跌停门槛(停牌复牌也按上一根比)
    if ind.get("low") is not None and px <= ind["low"] and ind["chg"][3] <= -lim:
        pos.extra["last_close"] = px
        pos.extra["deferred"] = int(pos.extra.get("deferred", 0)) + 1
        return []
    fee = cm.a_share_fee("sell", pos.size, px)
    gross = (px - pos.avg_cost) * pos.size
    state["cash"] += pos.size * px - fee
    state["closed_pnl"].append(gross - fee - float(pos.extra.get("buy_fee", 0.0)))
    n_def = int(pos.extra.get("deferred", 0))
    why = ""
    if want_text:
        why = (f"{pos.entry_date} 收盘 ¥{ep:.2f} 买入 {pos.size} 股,持有 {pos.bars_held} 个交易日,今收 ¥{px:.2f}"
               f"({(px / ep - 1) * 100:+.2f}%)—— 按 L-05 收盘卖出。"
               + (f"之前 {n_def} 天收盘跌停(或停牌)卖不出,顺延到今天。" if n_def else "")
               + f"卖出费用 ¥{fee:.2f}(佣金 + 过户费 + 印花税),买入费用 ¥{float(pos.extra.get('buy_fee', 0.0)):.2f}。")
    fill = _fill("sell", pos, pos.size, px, "L-05", why,
                 pnl_abs=round(gross, 2), pnl_pct=round((px / pos.avg_cost - 1) * 100, 2), hold_days=pos.bars_held)
    pos.size = 0
    state["closed"].append(pos)
    return [fill]


def try_entry(code, name, ind, state: dict, p: dict = PARAMS, want_text: bool = True, score=None):
    f = entry_checks(ind, code, name, p)
    if not f["ok"]:
        return None, None
    px = ind["close"]
    size = int(p["amount"] // px)
    if size <= 0:
        return None, f"信号成立,但股价 ¥{px:.2f} 超过每笔金额 {p['amount']:,.0f} 元,买不了 1 股"
    cost = size * px
    fee = cm.a_share_fee("buy", size, px)
    if cost + fee > state["cash"]:
        return None, f"信号成立,但现金只剩 ¥{state['cash']:,.0f},不够买入"
    state["cash"] -= cost + fee
    pos = av.Position(code=code, name=name or code, size=size, initial_size=size, entry_price=px,
                      entry_date=state["date"], avg_cost=px, highest=px, level=1, bars_held=0,
                      entry_rule=ENTRY_RULE, extra={"buy_fee": fee, "last_close": px})
    state["positions"].append(pos)
    extra = {"amount": round(cost, 2), "position_pct": round(cost / state["equity"] * 100, 2) if state["equity"] else None}
    if not want_text:
        return _fill("buy", pos, size, px, ENTRY_RULE, "", **extra), None
    c, chg = ind["closes"], ind["chg"]
    rationale = (f"按{f['board']}判涨停(门槛 {f['limit'] * 100:.1f}%):T-3 收盘 ¥{c[1]:.2f},较前一天 {_pct(chg[0])}(L-01 涨停);"
                 f"之后三天涨幅 {' / '.join(_pct(x) for x in chg[1:])},都没到门槛(L-02);"
                 f"三天收盘 {' / '.join(f'¥{x:.2f}' for x in c[2:])} 都高于涨停日收盘 ¥{c[1]:.2f}(L-03)。"
                 f"今日收盘 ¥{px:.2f} 买入 {size} 股 = ¥{cost:,.2f}(L-04:{p['amount']:,.0f} 元 ÷ 收盘价取整股),"
                 f"买入费用 ¥{fee:.2f}。")
    return _fill("buy", pos, size, px, ENTRY_RULE, rationale, **extra), None


def run_day(date_iso: str, positions, cash: float, bars_of, watch, prev_equity, consec_losses: int,
            p: dict = PARAMS, g: dict = av.GUARDS, ind_of=None, want_text: bool = True) -> dict:
    """接口与 agent_donchian 相同。g(护栏)不用:信号彼此独立,见模块开头。"""
    state = {"date": date_iso, "cash": cash, "positions": list(positions), "closed": [], "closed_pnl": [], "equity": None}
    if ind_of is None:
        def ind_of(code):
            return indicators(bars_of(code) or [], p)
    ind_cache = {pos.code: ind_of(pos.code) for pos in state["positions"]}

    def mark(pos):
        ind = ind_cache.get(pos.code)
        # 当天没日线(停牌)按上一次收盘估值,不按成本 —— 成本会把停牌前的涨跌抹掉
        return ind["close"] if ind else float(pos.extra.get("last_close") or pos.avg_cost)

    state["equity"] = cash + sum(pos.size * mark(pos) for pos in state["positions"])
    fills = []
    for pos in list(state["positions"]):
        ind = ind_cache[pos.code]
        if ind is None:                     # 停牌:当天没有日线,卖不出,顺延
            pos.bars_held += 1
            pos.extra["deferred"] = int(pos.extra.get("deferred", 0)) + 1
            continue
        fills += manage_position(pos, ind, state, p, want_text)
        if pos.size > 0:
            pos.extra["last_close"] = ind["close"]
    state["positions"] = [x for x in state["positions"] if x.size > 0]
    held = {x.code for x in state["positions"]}
    watch_items = []
    for code, name, score in watch:
        ind = ind_cache[code] if code in ind_cache else ind_of(code)
        ind_cache[code] = ind
        blocked = None
        bought = False
        if code not in held and ind is not None:
            f, blocked = try_entry(code, name, ind, state, p, want_text, score)
            if f:
                fills.append(f)
                held.add(code)
                bought = True
        if want_text:
            watch_items.append(watch_item(code, name, ind, code in held and not bought, blocked, score, p))
    for pnl in state["closed_pnl"]:
        consec_losses = consec_losses + 1 if pnl < 0 else 0
    equity = state["cash"] + sum(pos.size * mark(pos) for pos in state["positions"])
    watch_items.sort(key=lambda x: (bool(x.get("blocked")), -(x.get("progress_pct") or 0)))
    return {"fills": fills, "positions": state["positions"], "cash": state["cash"], "equity": equity,
            "watch_items": watch_items, "halt_reason": None, "consec_losses": consec_losses, "closed": state["closed"]}
