# -*- coding: utf-8 -*-
"""脚本修错(screen_nl.fix_script / script_changes)回归用例 —— 不联网,不连库,不依赖 pytest。

    cd apps/api && PYTHONPATH=. python tests/test_screen_fix.py

2026-09-13 用户粘了一份 ThinkScript 风格脚本,17 句只有 average_volume_50d_calc 取不到,
界面只给报错、不给 AI 按钮。修法见 screen_nl.py「脚本修错」节。这里盯三件事:
  1. 改了哪几句由程序比对得出,改一个数字也必须被列出来(不采信模型自述)
  2. 模型改动太多 → 判失败,不把重写过的脚本当成「修好了」
  3. 均量周期取不到时报错写清可用值
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_API = os.path.dirname(_HERE)

FAILS = []


def check(name, ok):
    print(("OK   " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


def _load():
    for n in ("app", "app.services", "app.services.quant", "app.services.online_analysis"):
        if n not in sys.modules:
            m = types.ModuleType(n)
            m.__path__ = []
            sys.modules[n] = m
    mods = {}
    for name in ("screen_dsl", "screen_nl"):
        full = f"app.services.quant.{name}"
        path = os.path.join(_API, "app", "services", "quant", f"{name}.py")
        spec = importlib.util.spec_from_file_location(full, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        spec.loader.exec_module(mod)
        mods[name] = mod
    return mods["screen_dsl"], mods["screen_nl"]


dsl, nl = _load()

SMA = [5, 10, 20, 50, 150, 200]
FIELDS = {"SMA5", "SMA10", "SMA20", "SMA50", "SMA150", "SMA200", "rs_rating",
          "high_63d", "low_63d", "high_21d", "low_21d", "price_52_week_high"}
FIELDS |= {f"average_volume_{n}d_calc" for n in (10, 30, 60, 90)}


def compile_(src):
    return dsl.compile_script(src, lambda n: n in FIELDS, SMA, SMA, [14])


ORIG = """# 注释
def c_price = close > 20;   # 价格
def c_rs = rs_rating >= 80;
def rng = (high_63d - low_63d) / high_63d;
def c_depth = rng >= 0.12 and rng <= 0.35;
def c_vdry = average_volume_10d_calc < average_volume_50d_calc * 0.9;
plot scan = c_price and c_rs
    and c_depth and c_vdry;
"""
GOOD = ORIG.replace("average_volume_50d_calc", "average_volume_60d_calc")

# ── 1. 报错信息 ──────────────────────────────────────────────
try:
    compile_(ORIG)
    check("50 天均量应当编译失败", False)
    ERR = ""
except dsl.ScreenError as e:
    ERR = str(e)
    check("报错点名 50 天", "50" in ERR and "average_volume_50d_calc" in ERR)
    check("报错列出可用周期", "10/30/60/90" in ERR and "average_volume_60d_calc" in ERR)
check("改成 60 天能编译", bool(compile_(GOOD)))

# ── 2. looks_like_script(脚本走修错,不走大白话翻译)──────────
check("ThinkScript 脚本判为脚本", nl.looks_like_script(ORIG))
check("大白话不判为脚本", not nl.looks_like_script("成交量大于100万且站上50日线"))

# ── 3. script_changes ─────────────────────────────────────────
ch = nl.script_changes(ORIG, GOOD)
check("只改一句 → 列出一句", len(ch) == 1 and ch[0]["name"] == "def c_vdry")
check("对照里有前后原文", "50d" in ch[0]["before"] and "60d" in ch[0]["after"])
check("注释 / 换行 / 空白差异不算改动",
      nl.script_changes(ORIG, "def c_price = close  >  20;\n" + ORIG.split("\n", 2)[2]) == [])
# 悄悄改数字必须被抓到
sneaky = GOOD.replace("0.12", "0.10")
check("悄悄改了阈值也要列出来", {c["name"] for c in nl.script_changes(ORIG, sneaky)}
      == {"def c_vdry", "def c_depth"})
dropped = GOOD.replace("def c_rs = rs_rating >= 80;\n", "")
check("删掉的句子列成 after=None",
      any(c["name"] == "def c_rs" and c["after"] is None for c in nl.script_changes(ORIG, dropped)))
added = GOOD.replace("plot scan", "def c_x = close > 5;\nplot scan")
check("新增的句子列成 before=None",
      any(c["name"] == "def c_x" and c["before"] is None for c in nl.script_changes(ORIG, added)))


# ── 4. fix_script(假模型)────────────────────────────────────
class _Msg:
    def __init__(self, c): self.message = types.SimpleNamespace(content=c)


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(choices=[_Msg(self.replies.pop(0))], usage=None)


def with_client(client):
    mod = types.ModuleType("app.services.online_analysis.llm_client")
    mod.get_client = lambda: client
    sys.modules["app.services.online_analysis.llm_client"] = mod


fc = FakeClient(["```\n" + GOOD + "```"])
with_client(fc)
r = nl.fix_script(ORIG, ERR, "美股", SMA, SMA, [14], validate=compile_)
check("一轮修好", r["attempts"] == 1 and len(r["changes"]) == 1)
check("报错原文喂给了模型", ERR in fc.calls[0]["messages"][1]["content"])

# 第一轮还错(换成 50 → 45),第二轮对
fc = FakeClient([ORIG.replace("50d", "45d"), GOOD])
with_client(fc)
r = nl.fix_script(ORIG, ERR, "美股", SMA, SMA, [14], validate=compile_)
check("第一轮不合法 → 带报错重试", r["attempts"] == 2 and "45" in fc.calls[1]["messages"][1]["content"])

# 模型把整份脚本重写了(每句都动)→ 三轮都超 → 失败
rewrite = """def a = close > 30;
def b = rs_rating >= 90;
def c = SMA50 > SMA200;
def d = high_63d > low_63d;
def e = average_volume_10d_calc < average_volume_60d_calc;
plot scan = a and b and c and d and e;
"""
fc = FakeClient([rewrite] * 3)
with_client(fc)
try:
    nl.fix_script(ORIG, ERR, "美股", SMA, SMA, [14], validate=compile_)
    check("重写整份脚本应当判失败", False)
except dsl.ScreenError as e:
    check("重写整份脚本判失败,报错里带原始报错", "改动了" in str(e) and "50" in str(e))

fc = FakeClient(["NONE"] * 3)
with_client(fc)
try:
    nl.fix_script(ORIG, ERR, "美股", SMA, SMA, [14], validate=compile_)
    check("模型不产出脚本应当失败", False)
except dsl.ScreenError:
    check("模型不产出脚本 → 失败,不返回半成品", True)

with_client(None)
try:
    nl.fix_script(ORIG, ERR, "美股", SMA, SMA, [14], validate=compile_)
    check("没配 key 应当失败", False)
except dsl.ScreenError as e:
    check("没配 key 明说", "LLM" in str(e))

print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
