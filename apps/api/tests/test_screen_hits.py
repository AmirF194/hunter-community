# -*- coding: utf-8 -*-
"""扫描筛选 · 历史命中日(screen_hits)的纯函数用例,不连库。

    cd apps/api && PYTHONPATH=. python tests/test_screen_hits.py

盯两件事:
1. 单只票查名次(rating_of)与全市场排名(screen_rs.rs_ratings)逐位相同 —— 含并列、含覆盖率门槛;
2. raw_at 与 rs_history.rs_raw_exact 浮点逐位一致 —— 不一致的话二分查不到自己,评级整批变 None。
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.quant import screen_hits as sh     # noqa: E402
from app.services.quant import screen_rs              # noqa: E402
from app.services.quant import rs_history as rh       # noqa: E402

fails: list[str] = []
passed = 0


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
    else:
        fails.append(f"{name}  {extra}")


rnd = random.Random(20260913)

# ── 1. 名次与全市场排名一致 ─────────────────────────────────────
for trial in range(40):
    n = rnd.randint(5, 400)
    vals = [round(rnd.uniform(-0.8, 3.0), rnd.choice([1, 2, 6])) for _ in range(n)]   # 保留位数少 → 故意制造并列
    raw = {k: v for k, v in enumerate(vals)}
    pool_n = n + rnd.randint(0, n // 20)
    full, _cov = screen_rs.rs_ratings(raw, pool_n)
    srt = sorted(vals)
    bad = [k for k, v in raw.items() if sh.rating_of(srt, pool_n, v, screen_rs.RS_UNIVERSE_THRESHOLD) != full.get(k)]
    check(f"名次一致 · 第 {trial} 组({n} 只)", not bad, f"不一致 {len(bad)} 只")

vals = [1.0, 2.0, 2.0, 2.0, 3.0]
full, _ = screen_rs.rs_ratings(dict(enumerate(vals)), 5)
check("并列取平均名次", sh.rating_of(sorted(vals), 5, 2.0, 0.9) == full[1], str(full))
check("覆盖率低于门槛整天不给(4/5 = 80% < 90%)", sh.rating_of([1.0, 2.0, 3.0, 4.0], 5, 2.0, 0.9) is None)
check("全市场排名在门槛下同样不给", screen_rs.rs_ratings({0: 1.0, 1: 2.0, 2: 3.0, 3: 4.0, 4: None}, 5)[0] == {})
check("值不在表里 → None(不猜名次)", sh.rating_of([1.0, 2.0, 3.0], 3, 2.5, 0.9) is None)
check("Raw 为 None → None", sh.rating_of([1.0, 2.0], 2, None, 0.9) is None)

# ── 2. raw_at 与 rs_raw_exact 逐位一致 ───────────────────────────
for trial in range(30):
    n = rnd.randint(253, 600)
    px = [rnd.uniform(5, 50)]
    for _ in range(n - 1):
        px.append(max(0.5, px[-1] * (1 + rnd.gauss(0, 0.03))))
    i = rnd.randint(252, n - 1)
    a = sh.raw_at(px, i)
    b = rh.rs_raw_exact(px[:i + 1])
    check(f"Raw 逐位一致 · 第 {trial} 组", a == b, f"{a!r} vs {b!r}")
check("不足 253 根 → None", sh.raw_at([10.0] * 300, 251) is None and rh.rs_raw_exact([10.0] * 252) is None)

print(f"{passed} passed, {len(fails)} failed")
for x in fails:
    print("FAIL", x)
print("ALL OK" if not fails else "SOME FAILED")
sys.exit(1 if fails else 0)
