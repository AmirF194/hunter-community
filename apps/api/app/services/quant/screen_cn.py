"""扫描筛选结果的 A 股中文化 —— 名称、板块两列(2026-09-17 用户要求)。

扫描源(TradingView)给 A 股的 description 是英文公司名(「Guangdong Kingshine Electronic Tec」),
sector 是它自己的 21 个英文大类。A 股用户看不懂,所以只在**展示层**换成中文:
求值早已结束,这里改的是结果行,不影响命中与否。

名称来源两级:
  1. 仓库自带的 data/stocks_catalog_baseline.json(5534 只,随代码分发,零网络)
  2. 后台线程每 24 小时用 akshare 拉一次最新代码-名称表,补清单生成之后才上市的新股
     (线上实测 5565 只 / 12 秒)。**绝不阻塞扫描**:没拉完就先用清单,拉失败只记日志。
两级都查不到的票保留扫描源的英文名 —— 英文名是真的,不能因为缺中文就留空或编一个。

板块是固定的 21 个英文大类,用对照表翻;表里没有的新类别原样显示英文。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import unicodedata
from pathlib import Path

log = logging.getLogger(__name__)

_BASELINE = Path(__file__).resolve().parents[3] / "data" / "stocks_catalog_baseline.json"
_REFRESH_TTL = 24 * 3600
_RETRY_AFTER_FAIL = 30 * 60

# TradingView 的板块(sector)全集,21 个
SECTOR_CN = {
    "Commercial Services": "商业服务",
    "Communications": "通信",
    "Consumer Durables": "耐用消费品",
    "Consumer Non-Durables": "非耐用消费品",
    "Consumer Services": "消费服务",
    "Distribution Services": "分销服务",
    "Electronic Technology": "电子技术",
    "Energy Minerals": "能源矿产",
    "Finance": "金融",
    "Government": "政府机构",
    "Health Services": "医疗服务",
    "Health Technology": "医疗技术",
    "Industrial Services": "工业服务",
    "Miscellaneous": "其他",
    "Non-Energy Minerals": "非能源矿产",
    "Process Industries": "加工工业",
    "Producer Manufacturing": "生产制造",
    "Retail Trade": "零售",
    "Technology Services": "技术服务",
    "Transportation": "交通运输",
    "Utilities": "公用事业",
}

_names: dict[str, str] = {}
_loaded_at = 0.0            # 最近一次 akshare 刷新成功的时刻
_last_try = 0.0
_lock = threading.Lock()
_refreshing = False


def _clean(name: str) -> str:
    # 清单里有「万  科Ａ」这种全角字母 + 中间补空格的写法(交易所简称按 4 字宽对齐),NFKC 再去空白
    return "".join(unicodedata.normalize("NFKC", name or "").split())


def _load_baseline() -> None:
    try:
        d = json.loads(_BASELINE.read_text(encoding="utf-8"))
    except Exception as e:                                        # noqa: BLE001
        log.warning("[screen_cn] 读 A 股名称清单失败: %s", e)
        return
    items = d if isinstance(d, list) else (d.get("items") or [])
    m = {}
    for x in items:
        c, n = str(x.get("code") or "").zfill(6), _clean(str(x.get("name") or ""))
        if n:
            m[c] = n
    with _lock:
        for c, n in m.items():
            _names.setdefault(c, n)


def _refresh_akshare() -> None:
    global _loaded_at, _refreshing
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        m = {str(r["code"]).zfill(6): _clean(str(r["name"])) for _, r in df.iterrows()}
        m = {c: n for c, n in m.items() if n}
        if len(m) > 3000:                     # 半截数据不覆盖
            with _lock:
                _names.update(m)
                _loaded_at = time.time()
            log.info("[screen_cn] akshare 刷新 A 股名称 %d 只", len(m))
        else:
            log.warning("[screen_cn] akshare 只返回 %d 只,不采用", len(m))
    except Exception as e:                                        # noqa: BLE001
        log.warning("[screen_cn] akshare 刷新 A 股名称失败: %s", e)
    finally:
        with _lock:
            _refreshing = False


def _ensure() -> None:
    global _last_try, _refreshing
    if not _names:
        _load_baseline()
    now = time.time()
    with _lock:
        if _refreshing or now - _loaded_at < _REFRESH_TTL or now - _last_try < _RETRY_AFTER_FAIL:
            return
        _refreshing, _last_try = True, now
    threading.Thread(target=_refresh_akshare, name="screen-cn-names", daemon=True).start()


def localize_a_pick(pick: dict) -> dict:
    """A 股结果行:名称、板块换成中文。原地改并返回。查不到的保持原样。"""
    _ensure()
    code = str(pick.get("code") or "")
    with _lock:
        cn = _names.get(code.zfill(6)) if code.isdigit() else None
    if cn:
        pick["name"] = cn
    f = pick.get("fields")
    if isinstance(f, dict):
        if cn:
            if "description" in f:
                f["description"] = cn
            if "name" in f and isinstance(f["name"], str) and not f["name"].isdigit():
                f["name"] = cn
        s = f.get("sector")
        if isinstance(s, str) and s in SECTOR_CN:
            f["sector"] = SECTOR_CN[s]
    return pick
