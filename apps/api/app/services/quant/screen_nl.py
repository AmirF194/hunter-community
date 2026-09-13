"""自然语言 → 筛选脚本(gemini-3.5-flash)。

用户在生成框里写「成交量大于100万且站上50日线」这种大白话,这里把它翻译成
`def`/`plot` 脚本,再交给 screen_dsl 解析成可视条件行。

## 什么时候才叫 LLM —— 不靠"看起来像不像脚本"的启发式

规则只有一条:**先用真解析器试一遍,失败了才叫 LLM**。
唯一的例外是文本里已经出现 `def ` 或 `plot ` —— 那说明用户明确在写脚本,
解析失败就是他写错了,应该把错误原样告诉他,而不是让 LLM 去"猜他想写什么"
然后悄悄改成别的。用户在调自己的脚本时最不需要的就是一个自作主张的翻译器。

## LLM 的产出**必须**过我们自己的解析器

这是整件事的安全阀。模型完全可能编出 `AverageVolume(close, 37)` 这种
不存在的函数、或者 `pe_ratio` 这种不存在的字段 —— 但 screen_dsl 会拿
扫描源的 metainfo 逐个校验,编造的东西一律报错,不会流到界面上。
所以「LLM 会不会胡说」这个问题在这里不用靠 prompt 解决,靠类型系统解决。

失败时把解析器的报错**喂回给模型重试一次**。报错文本本身写得很具体
(「扫描源没有 SMA37,可用周期:...」),模型据此改对的概率很高。

## 数字来自用户,不来自模型

仓内铁律「LLM 严禁自由生成用户可见的数字」在这里的形态是:
模型只负责把用户说的话映射成字段和运算符,阈值原样搬运。
prompt 里明确要求"不要发明用户没说的阈值",而且最终条件会以
可视条件行的形式摆在用户眼前**让他确认后才能跑扫描** —— 不是直接出结果。

## 不做 mock 兜底

没配 LLM key 就明说没配,不返回一个假的脚本。
"""
from __future__ import annotations

import json
import logging
import re

from app.services.quant import screen_dsl
from app.services.quant.screen_dsl import ScreenError

log = logging.getLogger(__name__)

# 模型锁死 gemini-3.5-flash(仓内铁律)。
# 3.6 / 3.8 对恰好 2 条 [system, user] 的短对话返 400,2026-09-04 上线 20+ 处全砸 500。
# 这里正好就是 2 条消息的短对话,是那个 bug 的高危形态,不要动。
MODEL = "gemini-3.5-flash"

_MAX_INPUT = 500


def _field_hint() -> str:
    """把中文标签表反过来喂给模型 —— 它跟 screen_dsl 是同一份,不会漂。"""
    pairs = []
    for fld, label in screen_dsl._FIELD_LABEL.items():
        pairs.append(f"  {label} = {fld}")
    return "\n".join(pairs)


def _system_prompt(market_label: str, sma: list[int], ema: list[int],
                   rsi: list[int]) -> str:
    return f"""你是一个选股筛选脚本的翻译器。把用户的中文/英文描述翻译成筛选脚本。

# 输出格式(最重要的一条)
**你的回答的第一个字符必须是 `d`(def)或 `p`(plot)。**
不要前言,不要"好的我明白了",不要复述规则,不要解释你的思路,
不要 JSON,不要 markdown 代码块。整个回答就是脚本本身,一行一句。
翻译不了的时候,整个回答就是四个字母:NONE

# 脚本语法
每句 `def 名字 = 表达式;`,最后一句必须是 `plot scan = 条件A and 条件B;`。
名字用英文小写加下划线,见名知意(cond_volume / cond_price)。
运算符:> >= < <= == != + - * / and or not 和括号。

# 内置序列
close 收盘价 · open 开盘价 · high 最高价 · low 最低价 · volume 成交量

# 函数(周期只能取下面列出的值,取不到的值会直接报错)
Average(close, N)     N 取 {', '.join(map(str, sma[:18]))} 等
Average(volume, N)    N 只能是 10 / 30 / 60 / 90
ExpAverage(close, N)  N 取值同 Average(close, N)
Highest(high, N)      N 只能接近 5 / 21 / 63 / 126 / 252
Lowest(low, N)        同上
RSI()                 14 周期;RSI(N) 的 N 只能取 {', '.join(map(str, rsi))}

# 可直接使用的字段(中文名 = 字段名)
{_field_hint()}

# 硬性要求
1. 阈值必须来自用户的原话。**不要发明用户没提到的数字或条件** ——
   用户只说"成交量大于100万",就只出这一条,不要顺手加市值、价格之类的过滤。
2. "100万" = 1000000,"1亿" = 100000000,"5%" 在涨跌幅字段里写 5(不是 0.05)。
3. 用户说"均线多头排列"指 短期均线 > 中期均线 > 长期均线,常见是 20/50/200。
4. 用户说"接近52周新高" 用 (price_52_week_high - close) / price_52_week_high <= 阈值。
5. 看不懂用户在说什么(比如闲聊、和选股无关的话),就只输出一个单词 NONE,
   不要瞎编条件。

当前市场:{market_label}
"""


def _extract_script(raw: str) -> str:
    """从模型返回里取出脚本。

    **不走 JSON。** 第一版让模型返回 {"script": "..."},实测 gemini 会把多行脚本
    里的换行原样塞进 JSON 字符串,产出的根本不是合法 JSON,解析必失败
    (2026-09-10:第一次线上调用就栽在这,报错是「看不懂的字符 '{'」——
    兜底把整个 JSON 当成脚本喂给了解析器)。
    用 JSON 包多行代码本来就脆,直接要纯文本反而稳,反正后面有真解析器把关。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    # markdown 代码块(prompt 说了不要,但模型经常还是加)
    m = re.search(r"```(?:[A-Za-z]*)\s*\n?(.+?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    # 没闭合的围栏 / 零散反引号 —— 实测出现过,漏掉的话解析器会报
    # 「看不懂的字符 '`'」,用户完全不知道发生了什么
    s = s.replace("```", "").replace("`", "").strip()
    # 模型偶尔还是回 JSON —— 认一下,取 script 字段
    if s.startswith("{"):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict) and isinstance(obj.get("script"), str):
                return obj["script"].strip()
        except Exception:                                   # noqa: BLE001
            # JSON 不合法(多半就是换行没转义)—— 退而求其次,把 script 字段的值抠出来
            m2 = re.search(r'"script"\s*:\s*"(.*)"\s*\}?\s*$', s, re.S)
            if m2:
                return m2.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
    # 从第一个 def/plot 开始截 —— 模型很爱先写一段推理再给答案,实测:
    #   ", I understand the instructions. I will translate ... \n\nOutput:\nNONE"
    # 这段前言必须扔掉。
    m3 = re.search(r"(^|\n)\s*(def|plot)\s+[A-Za-z_]", s)
    if m3:
        return s[m3.start():].strip()

    # 没有 def/plot 了。模型说它看不懂时会以 NONE 结尾(前面照样有一段推理)
    if re.search(r"(^|[\s:：\n])NONE[.。\s]*$", s, re.I):
        return "NONE"

    # **返回空,不要把这段推理当脚本。**
    # 早先这里 `return s`,于是整段英文推理被喂给解析器,用户看到的是
    # 「第 1 行:看不懂的字符 "'"」—— 完全指不到真正的原因(2026-09-10 实测)。
    return ""


def looks_like_script(text: str) -> bool:
    """用户是不是在写脚本 —— 只看有没有 def/plot 关键字。

    这个判据要**保守**:判成 True 的代价是"脚本写错时不给 AI 兜底"(用户看到
    真实报错,自己改),判成 False 的代价是"用户在调脚本时被 AI 悄悄改写"。
    后者严重得多。
    """
    t = (text or "")
    return bool(re.search(r"(^|\n)\s*(def|plot)\s+[A-Za-z_]", t))


def translate(text: str, market_label: str, sma: list[int], ema: list[int],
              rsi: list[int], validate) -> dict:
    """自然语言 → 脚本。→ {script, model, tokens, attempts, raw}

    `validate(script)` 由调用方注入:拿真解析器验一遍,不通过就抛 ScreenError。
    翻译器不认识字段,校验必须交给唯一的权威(screen_dsl + metainfo)。
    """
    # 复用在线分析那套客户端的网关/key/超时配置,但**不用 llm_json_call** ——
    # 它强制 response_format=json_object 且会拼 ZH_ONLY_RULE(要求用中文回答),
    # 而这里要的是一段纯代码,两条都帮倒忙。
    from app.services.online_analysis.llm_client import get_client

    text = (text or "").strip()
    if not text:
        raise ScreenError("生成框是空的")
    if len(text) > _MAX_INPUT:
        raise ScreenError(f"描述太长(上限 {_MAX_INPUT} 字),请说得简短一点")

    system = _system_prompt(market_label, sma, ema, rsi)
    user = text
    tokens_in = tokens_out = 0
    last_err = ""

    # 最多两轮:第一轮直译,失败把**解析器的原话**喂回去让它改。
    # 报错文本写得很具体(「没有 SMA37,可用周期:...」),比泛泛说"你错了"有用得多。
    client = get_client()
    if client is None:
        raise ScreenError(
            "这个部署没有配 LLM key,自然语言识别用不了。"
            "可以直接写筛选脚本(点「语法速查」看写法),或在 .env 里配 LLM_API_KEY。")

    for attempt in (1, 2):
        try:
            completion = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=1200,
                temperature=0.1,
            )
        except Exception as e:                              # noqa: BLE001
            raise ScreenError(f"调用模型失败:{type(e).__name__} · {e}") from e
        raw = (completion.choices[0].message.content or "") if completion.choices else ""
        usage = getattr(completion, "usage", None)
        if usage:
            tokens_in += usage.prompt_tokens or 0
            tokens_out += usage.completion_tokens or 0

        script = _extract_script(raw)
        # 模型自己说看不懂 —— 直接告诉用户,不要再让它试第二次编一个出来
        if script.strip().upper().rstrip(".。") == "NONE":
            raise ScreenError(
                "没看懂这段描述想筛什么。换个说法试试,"
                "比如「成交量大于100万,且收盘价站上50日均线」;或者直接写筛选脚本。")
        if not script:
            last_err = "模型没有产出脚本"
            user = (f"{text}\n\n(上一次你没有输出脚本,而是输出了别的文字。"
                    f"请直接以 def 开头输出脚本,不要任何前言和解释。"
                    f"实在翻译不了就只回 NONE)")
            continue

        try:
            validate(script)
        except ScreenError as e:
            last_err = str(e)
            log.info("[screen_nl] 第 %d 轮产出不合法:%s", attempt, last_err)
            user = (f"{text}\n\n上一次你输出的脚本是:\n{script}\n\n"
                    f"但它有错:{last_err}\n请改正后重新输出。")
            continue

        return {
            "script": script,
            "model": MODEL,
            "attempts": attempt,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    # 两轮都不行 —— 把模型最后一次的错误如实说出来,不返回半成品脚本
    raise ScreenError(
        f"没能把这段描述转成筛选条件({last_err})。\n"
        f"把描述写得更具体些通常就好了,比如「成交量大于100万,且收盘价站上50日均线」;"
        f"也可以直接写筛选脚本(点「语法速查」看写法)。")


# ═══════════════════════════════════════════════════════════════
# 脚本修错(2026-09-13 用户要求)
#
# 用户粘了一份 ThinkScript 风格的脚本,17 句里只有 `average_volume_50d_calc` 一处取不到
# (扫描源只有 10/30/60/90 天均量),界面只给了一行报错、没有 AI 按钮 —— 原设计是
# 「写着 def/plot 就是他自己写错了,别让 AI 悄悄改」。
#
# 「悄悄」才是问题,「改」不是。现在:
#   1. 按钮照样要用户点(花 token 的动作必须明示);
#   2. 模型只许改报错涉及的句子,**改了哪几句由我们逐句比对算出来**(script_changes),
#      不采信模型自己的说明 —— 它说「只改了一处」不代表真的只改了一处;
#   3. 改动句数超过门槛直接判失败,不把一份被重写过的脚本当成「修好了」交出去;
#   4. 修出来的东西不进对照表(那张表学的是大白话 → 表达式,不是脚本 → 脚本)。
# ═══════════════════════════════════════════════════════════════

_MAX_FIX_INPUT = 8000
# 改动句数上限:至少允许 3 句(一个错名字常被好几句引用),再多按总句数的 1/3 算
_FIX_MIN_ALLOWED = 3


def _statements(script: str) -> list[tuple[str, str]]:
    """脚本 → [(「def 名字」/「plot 名字」, 规整后的表达式)],按出现顺序。

    去掉 `#` 注释、合并空白后按 `;` 切。只用来**比对改动**,不是解析器 ——
    合法性永远以 screen_dsl 为准。
    """
    lines = [ln.split("#", 1)[0] for ln in (script or "").splitlines()]
    out = []
    for part in " ".join(lines).split(";"):
        s = " ".join(part.split())
        if not s:
            continue
        m = re.match(r"^(def|plot)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", s)
        if m:
            out.append((f"{m.group(1)} {m.group(2)}", m.group(3).strip()))
        else:
            out.append(("?", s))
    return out


def script_changes(before: str, after: str) -> list[dict]:
    """逐句比对两份脚本 → [{name, before, after}]。before/after 为 None 表示新增/删除。

    表达式只做空白规整后逐字比较:`0.9` 改成 `0.90` 也算改动 —— 宁可多报,
    不能让一个被改过的数字从对照里漏掉。
    """
    a = _statements(before)
    b = _statements(after)
    bmap = {}
    for k, v in b:
        bmap.setdefault(k, v)
    amap = {}
    for k, v in a:
        amap.setdefault(k, v)
    changes = []
    for k, v in a:
        if k == "?":
            continue
        nv = bmap.get(k)
        if nv != v:
            changes.append({"name": k, "before": v, "after": nv})
    for k, v in b:
        if k != "?" and k not in amap:
            changes.append({"name": k, "before": None, "after": v})
    return changes


# ── 模型只给「替换指令」,不给整份脚本 ─────────────────────────────
# 第一版让模型输出改好的完整脚本,线上真跑(用户那份 40 行 ThinkScript)三轮全失败:
# gemini-3.5-flash 先吐一大段英文推理,推理里把脚本抄一遍、注释截半句、还怀疑 SMA50 不合法;
# _extract_script 从第一个 def 截,截到的是推理正文(「第 2 行:看不懂的字符 '.'」)。
# 整份重写本来就给了它乱改的空间。现在它只许回 `<<原文>> => <<新写法>>`,由我们在代码里替换:
#   · 原文必须在脚本**代码部分**逐字存在(推理里举的例子自然被滤掉)
#   · 按标识符边界替换(换 SMA5 不会碰到 SMA50),注释原样保留
_REPL_RE = re.compile(r"<<(.+?)>>\s*=>\s*<<(.*?)>>")


def _split_comment(line: str) -> tuple[str, str]:
    i = line.find("#")
    return (line, "") if i < 0 else (line[:i], line[i:])


def _repl_pattern(old: str):
    # 首尾是标识符字符时才加边界 —— 原文可能是 `high_63d - low_63d` 这种带运算符的片段
    pre = r"(?<![A-Za-z0-9_.])" if re.match(r"[A-Za-z0-9_]", old) else ""
    post = r"(?![A-Za-z0-9_])" if re.search(r"[A-Za-z0-9_]$", old) else ""
    return re.compile(pre + re.escape(old) + post)


def parse_replacements(raw: str, script: str) -> list[tuple[str, str]]:
    """从模型回复里取替换指令。只收原文在脚本代码部分存在的;同一原文多次出现取最后一次。"""
    code = "\n".join(_split_comment(ln)[0] for ln in (script or "").splitlines())
    out: dict[str, str] = {}
    for m in _REPL_RE.finditer(raw or ""):
        old, new = m.group(1).strip(), m.group(2).strip()
        if not old or old == new or len(old) > 120 or len(new) > 200 or ";" in new or "#" in new:
            continue
        if not _repl_pattern(old).search(code):
            continue
        out.pop(old, None)
        out[old] = new
    return list(out.items())


def apply_replacements(script: str, pairs: list[tuple[str, str]]) -> str:
    lines = []
    for ln in (script or "").splitlines():
        code, comment = _split_comment(ln)
        for old, new in pairs:
            code = _repl_pattern(old).sub(lambda _m, n=new: n, code)
        lines.append(code + comment)
    return "\n".join(lines)


def _fix_system_prompt(market_label: str, sma: list[int], rsi: list[int]) -> str:
    return f"""你在帮用户修一份选股筛选脚本(可能是 ThinkScript / TradingView 风格)。解析器报了错,你只负责给出替换指令。

# 输出格式(最重要)
不要推理过程,不要解释,不要输出整份脚本。每条替换占一行,格式严格是:
<<脚本里逐字存在的原文>> => <<新写法>>
原文尽量短,通常就是报错点名的那个名字或那个函数调用。修不了就只输出 NONE。

# 规则
1. 只改报错点名的那一处,别的都不许动(数字、条件、名字都不许动)。
2. 字段或周期取不到时,换成可用列表里最接近的那个。
3. SMA50 / SMA150 / SMA200 / EMA20 / high_63d / low_21d / high_5d / rs_rating / vcp_ 开头的名字都是合法字段,不要改。

# 可用写法
Average(close, N) 与 SMA+N 字段:N 取 {', '.join(map(str, sma))}
成交量均线只有 10 / 30 / 60 / 90 天:average_volume_10d_calc / average_volume_30d_calc / average_volume_60d_calc / average_volume_90d_calc
Highest(high, N) / Lowest(low, N):N 只能接近 5 / 21 / 63 / 126 / 252
RSI(N):N 取 {', '.join(map(str, rsi))}

# 可直接使用的字段(中文名 = 字段名)
{_field_hint()}

当前市场:{market_label}
"""


def fix_script(script: str, error: str, market_label: str, sma: list[int], ema: list[int],
               rsi: list[int], validate) -> dict:
    """用户写的脚本编译不过 → 模型给替换指令,我们替换、编译、比对改动。

    → {script, model, attempts, tokens_in, tokens_out, changes}
    一轮修掉一处又露出下一处报错时,下一轮在修过的基础上继续(报错变了才算前进)。
    """
    from app.services.online_analysis.llm_client import get_client

    script = (script or "").strip()
    if not script:
        raise ScreenError("生成框是空的")
    if len(script) > _MAX_FIX_INPUT:
        raise ScreenError(f"脚本太长,AI 修错上限 {_MAX_FIX_INPUT} 字符。请按报错自己改,或删掉注释再试")

    client = get_client()
    if client is None:
        raise ScreenError(
            "这个部署没有配 LLM key,AI 修错用不了。请按上面的报错直接改脚本,"
            "或在 .env 里配 LLM_API_KEY。")

    n_stmt = sum(1 for k, _ in _statements(script) if k != "?")
    allowed = max(_FIX_MIN_ALLOWED, n_stmt // 3)
    system = _fix_system_prompt(market_label, sma, rsi)
    tokens_in = tokens_out = 0
    cur, cur_err = script, error
    last_err = error
    hint = ""

    for attempt in (1, 2, 3):
        user = f"解析器报错:{cur_err}\n\n脚本:\n{cur}{hint}"
        try:
            completion = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=2000,
                temperature=0.1,
            )
        except Exception as e:                              # noqa: BLE001
            raise ScreenError(f"调用模型失败:{type(e).__name__} · {e}") from e
        raw = (completion.choices[0].message.content or "") if completion.choices else ""
        usage = getattr(completion, "usage", None)
        if usage:
            tokens_in += usage.prompt_tokens or 0
            tokens_out += usage.completion_tokens or 0

        pairs = parse_replacements(raw, cur)
        if not pairs:
            last_err = "模型没有给出可用的替换"
            log.info("[screen_nl] 修错第 %d 轮没有可用替换:%r", attempt, raw[:300])
            hint = ("\n\n(上一次你没有给出替换指令,或原文在脚本里找不到。"
                    "只输出形如 <<average_volume_50d_calc>> => <<average_volume_60d_calc>> 的行)")
            continue

        nxt = apply_replacements(cur, pairs)
        changes = script_changes(script, nxt)
        if len(changes) > allowed:
            last_err = f"模型要改 {len(changes)} 句(上限 {allowed} 句),不像是只修报错"
            log.info("[screen_nl] 修错第 %d 轮改动过多:%s", attempt, pairs)
            hint = f"\n\n(上一次你要改 {len(changes)} 句,太多了。只替换报错点名的那一处)"
            continue
        try:
            validate(nxt)
        except ScreenError as e:
            new_err = str(e)
            log.info("[screen_nl] 修错第 %d 轮替换 %s 后仍报错:%s", attempt, pairs, new_err)
            last_err = new_err
            if new_err != cur_err:
                cur, cur_err = nxt, new_err      # 前一处修掉了,露出下一处 —— 在此基础上继续
                hint = ""
            else:
                hint = "\n\n(上一次的替换没有解决这个报错,换一个写法)"
            continue

        return {
            "script": nxt,
            "model": MODEL,
            "attempts": attempt,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "changes": changes,
        }

    raise ScreenError(
        f"AI 没能修好这份脚本({last_err})。\n"
        f"最初的报错是:{error}\n请按这条报错直接改脚本。")
