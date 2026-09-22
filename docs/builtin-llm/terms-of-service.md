# Built-in Model Quota — Terms of Service & Acceptable Use Policy

> Effective: 2026-09-19 (Shanghai time)
> Applies to: self-hosted HunterCode users who use the **built-in model quota**
> Version: v1 （中文版：[服务条款.md](./服务条款.md)）
> This document is versioned with the open-source repo — every wording change is visible in `git log`.

---

## 0. In one sentence

The built-in model quota is a **free starter path we provide to self-hosted
HunterCode users** so you can begin without hunting down an LLM key of your own.
It is not a general-purpose LLM API, it is not guaranteed to exist forever, and
the daily allowance is not guaranteed to stay at today's number.
**We record token counts and model names only — never any conversation content.**

If any of that is unacceptable, use the bring-your-own-key or local-model path.
Those remain first-class citizens and give up no functionality.

---

## 1. What this service is

"Built-in model quota" means: you use a HunterCode platform key (prefix
`hunt_tools_`) against our gateway at
`https://hunter.agentpit.io/api/saas/llm/*`, and we call the upstream model on
your behalf and pay for it. The gateway exposes exactly two model aliases:

| Alias | Purpose |
|---|---|
| `hunter-chat` | Default conversation and tool calling |
| `hunter-deep` | Deep analysis and long-running tasks |

**Provider**: HunterCode / agentpit ("we", "us").

---

## 2. Who may use it

Only **self-hosted users who have requested a HunterCode platform key**, for:

- Research, learning, development and testing inside your own HunterCode instance
- Evaluating whether HunterCode fits you, before switching to your own key or a commercial plan

This is **not** a generative-AI service offered to the general public, and it is
not an API product you may resell. We do not market it to the general public in
mainland China; pending professional advice on the applicable regulatory
requirements, the service stays limited to self-hosted users who actively
requested a key.

---

## 3. Acceptable Use Policy

### 3.1 Allowed

- Normal conversation, tool calls and deep analysis inside your own HunterCode instance
- Reasonable testing for evaluation or development

### 3.2 Explicitly prohibited

1. **Reselling, renting or redistributing** the quota or the key, paid or not.
2. **Using the gateway as a general-purpose API** — wiring it into applications,
   bots, aggregators, proxy services or relays outside HunterCode.
3. **Scripted quota farming**: bulk requests intended to drain the allowance,
   load-test it, or hoard tokens. Normal use is subject to per-minute rate and
   concurrency limits; circumventing them (key rotation, distributed senders,
   etc.) falls under this prohibition.
4. **Sharing one key across many people or instances** on an ongoing basis.
   The allowance is granted per key, not per person.
5. Generating or distributing **illegal content**, or using it for attacks,
   fraud, spam, or to circumvent anyone's security measures.
6. Probing, bypassing or breaking the gateway's or upstream's security controls,
   quota mechanisms, or model allow-list.

### 3.3 Upstream rules apply too

Behind the gateway is a third-party model provider. Their usage policies
(content restrictions, prohibited uses) apply to you as well. We cannot and will
not waive upstream rules on your behalf.

---

## 4. The allowance

- **10,000,000 tokens per key per day** by default (input + output, output
  includes thinking tokens), resetting at 00:00 Asia/Shanghai.
- There are also **per-minute request and concurrency limits**, plus per-request
  input and output length caps.
- **Allowance, rate limits and model mappings may change** without individual
  notice; changes will be reflected in this document and in the gateway's own
  messages. After the pilot we will re-set the tiers based on real usage.
- Running out is **not a service cut-off**: the gateway returns a plain-language
  message telling you when it resets and how to switch to your own key in
  Settings. Your tools, data supply and SKILLs are **unaffected**.
- We also operate a **platform-wide daily circuit breaker**. When it trips, new
  requests are temporarily refused with a message suggesting your own key. This
  protects against runaway cost; it is not aimed at any individual user.

---

## 5. Data and privacy

### 5.1 What we record

The gateway stores **only** these fields:

```
key_id · timestamp · model alias · upstream model · input token count
· output token count · whether estimated · whether streamed · whether aborted
· latency ms · status · error code
```

### 5.2 What we do not record

**No prompts, no responses, no tool arguments, no ticker symbols — not one character.**

This constraint is written into the gateway's source comments and into the table
DDL (`saas_llm_usage`) as a hard internal rule: no column whose name contains
prompt / message / content / text / response may ever be added. The gateway code
lives in our private repo, but its behaviour is verified case-by-case in the test
reports in this open-source repo — including checks like "dump the whole table to
text, grep for the test keywords: 0 hits; count non-ASCII characters: 0".

### 5.3 One thing to understand honestly

**Your prompt text does pass through our servers** on its way to the upstream
model — there is no way to call on your behalf otherwise. We do not retain it,
but it does transit. How the upstream provider handles it is governed by their
own policy.

If even transit is unacceptable to you, use your own key or a local model
(Ollama / vLLM). **That is precisely why the built-in quota is designed as an
optional starter path rather than the only path.**

### 5.4 The rest of your data stays on your machine

Conversation transcripts live in your opencode volume; watchlists, positions and
research records live in your own Postgres. The built-in quota **does not change
that**. The only thing it changes is where inference happens.

---

## 6. How abuse is handled

We record call counts and token counts per key (never content), so we can spot
abnormal usage without looking at a single conversation. When Section 3 is
violated, we respond in proportion:

1. **Lower that key's allowance** — the usual, mildest step; you still see the
   plain-language notice and can switch to your own key.
2. **Disable that key** — note this disables the key entirely: tools, data
   supply and Kronos stop working too.
3. For severe or repeated cases, we stop issuing new keys to that account.

If you were caught by mistake, contact us (Section 9).

---

## 7. Service level (the honest version)

- **There is no SLA.** This is a free add-on. We do not promise availability,
  latency or continuity.
- We **do** run availability monitoring (a probe every 10 minutes; consecutive
  failures page us), but that is so *we* find out quickly — it is not a
  commitment to you.
- The service **may change, be degraded, suspended or shut down**. We will try
  to announce it in the repo's Discussions announcements beforehand, but in an
  emergency we may stop first and explain after.
- If the gateway is turned off entirely, you get a clear plain-language message,
  not a spinner or an English stack trace.
- **Your HunterCode instance keeps working**: switching to your own key is a few
  clicks in Settings, and no session, SKILL or data is lost.

---

## 8. Disclaimer

The built-in quota is provided "as is", without warranty of any kind, express or
implied.

Model output is **not investment advice**. HunterCode is a research tool, not an
advisor; any trading decision and its consequences are yours. This holds
regardless of the built-in quota — but since the quota lowers the barrier to
entry, it bears repeating here.

To the extent permitted by law, we are not liable for any indirect, incidental or
consequential loss arising from use of this service.

---

## 9. Changes and contact

- These terms may be updated. Material changes will be posted in the
  [repo's Discussions announcements](https://github.com/agentpit-io/hunter-community/discussions)
  and the version and date at the top of this file will be updated.
- Continued use constitutes acceptance of the updated terms.
- Questions, requests for a higher allowance, or appeals if you were caught by
  mistake: open a thread in
  [Discussions](https://github.com/agentpit-io/hunter-community/discussions)
  or file an [Issue](https://github.com/agentpit-io/hunter-community/issues).

---

## 10. Related documents

- [Built-in quota user guide (Chinese)](./使用说明.md) — how to use it, where to see your allowance, troubleshooting
- [`docs/01-getting-started.md`](../01-getting-started.md) — from zero to running
- [`docs/02-providers.md`](../02-providers.md) — the bring-your-own-key path
