'use client'
// 第 3 步 · 填 key 当场测(设计方案 4.5)
//
// 三项检测由 **api 容器**发出(和 opencode 实际调用走同一条网络路径),
// 每项显示真实耗时。三项全过才给 test_token,没有 test_token 保存按钮不可用。
//
// ⚠️ 保存按钮的禁用条件是 `!testToken`,**不是** `!result?.ok` ——
//    token 会过期(10 分钟),过期后 result 还挂在界面上却已经存不进去了。
import { useState } from 'react'
import { Loader2, KeyRound, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react'
import { HUNTER } from '../../lib/hunter-theme'
import { testLlm, saveLlm, isFail, type TestResult } from '../lib/setupClient'
import { Box, Tag, btn } from '../lib/ui'
import { Field, type Draft } from './ModelPick'

export default function ModelTest({
  draft, onChange, testToken, onTested, onSaved, onBack,
}: {
  draft: Draft
  onChange: (d: Draft) => void
  testToken: string
  onTested: (t: string) => void
  onSaved: () => void | Promise<void>
  onBack: () => void
}) {
  const [result, setResult] = useState<TestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const canTest = !!(draft.base_url.trim() && draft.model.trim() && draft.api_key.trim()) && !testing

  const runTest = async () => {
    if (!canTest) return
    setTesting(true); setErr(''); setResult(null); onTested('')
    const r = await testLlm(draft.base_url.trim(), draft.api_key.trim(), draft.model.trim())
    setTesting(false)
    if (isFail(r)) { setErr(r.message); return }
    setResult(r)
    onTested(r.test_token || '')
    // 清洗开关由检测结果决定,不让用户猜(设计方案 4.5)
    if (r.sanitize_suggest) onChange({ ...draft, sanitize: r.sanitize_suggest })
  }

  const save = async () => {
    if (!testToken || saving) return
    setSaving(true); setErr('')
    const r = await saveLlm({
      base_url: draft.base_url.trim(),
      api_key: draft.api_key.trim(),
      model: draft.model.trim(),
      sanitize: draft.sanitize || 'auto',
      test_token: testToken,
    })
    setSaving(false)
    if (isFail(r)) {
      setErr(r.message)
      // 凭证过期 / 配置被改过 —— 让用户重测,而不是让他对着一个存不进去的按钮点
      if (r.data?.reason) onTested('')
      return
    }
    await onSaved()
  }

  return (
    <Box icon={<KeyRound size={16} />} title="第 3 步 · 填 key,当场检测">
      <Field label="接口地址" value={draft.base_url} onChange={(v) => { onChange({ ...draft, base_url: v }); onTested('') }} />
      <Field label="模型名" value={draft.model} onChange={(v) => { onChange({ ...draft, model: v }); onTested('') }} />
      <Field label="API key" type="password" placeholder="粘贴你的 key"
             value={draft.api_key} onChange={(v) => { onChange({ ...draft, api_key: v }); onTested('') }} />
      <div style={{ fontSize: 12.5, color: HUNTER.INK_F, marginTop: 6 }}>
        key 会用 AES-256-GCM 加密后存进这台实例自己的数据库,界面上只回显末 4 位,
        日志里一个字都不打。它只发给你填的这个地址。
      </div>

      <button onClick={() => void runTest()} disabled={!canTest} style={btn('primary', !canTest)}>
        {testing ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <Loader2 size={14} style={{ animation: 'hspin 1s linear infinite' }} /> 检测中…(最长约 85 秒)
        </span> : '开始检测'}
      </button>

      {err && <div style={{ marginTop: 12, color: HUNTER.UP, fontSize: 13.5 }}>{err}</div>}

      {result && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Tag tone={result.ok ? 'ok' : 'fail'}>{result.ok ? '三项全部通过' : '未通过'}</Tag>
            <span style={{ fontSize: 12.5, color: HUNTER.INK_F }}>
              总耗时 {(result.elapsed_ms / 1000).toFixed(2)} 秒
            </span>
          </div>
          <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {result.checks.map((c, i) => (
              <div key={i} style={{
                border: `1px solid ${HUNTER.LINE}`, borderRadius: HUNTER.R_SM,
                padding: '9px 11px', background: c.ok ? HUNTER.PAPER : HUNTER.PAPER3,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
                  {c.ok ? <CheckCircle2 size={15} color={HUNTER.SUCCESS} />
                        : <XCircle size={15} color={HUNTER.UP} />}
                  <strong style={{ fontSize: 13.5, color: HUNTER.INK }}>{i + 1}. {c.name}</strong>
                  <span style={{ fontSize: 12.5, color: HUNTER.INK_F }}>
                    {(c.elapsed_ms / 1000).toFixed(2)} 秒
                  </span>
                </div>
                <div style={{ fontSize: 13, color: HUNTER.INK_S, marginTop: 4 }}>{c.message}</div>
                {c.warn && (
                  <div style={{
                    fontSize: 12.5, color: HUNTER.TAG_WARN_FG, marginTop: 5,
                    display: 'flex', gap: 5, alignItems: 'flex-start',
                  }}>
                    <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 2 }} /> {c.warn}
                  </div>
                )}
              </div>
            ))}
          </div>
          {result.ok && (
            <div style={{ marginTop: 10, fontSize: 13, color: HUNTER.INK_S }}>
              schema 清洗开关将保存为 <strong>{draft.sanitize || 'auto'}</strong>
              {draft.sanitize === '1' && '(这个模型不接受完整 JSON Schema,必须开)'}
              {draft.sanitize === 'auto' && '(未清洗即通过,按模型名自动决定走不走 llm-shim)'}
              。检测结果 {Math.round(result.test_token_ttl / 60)} 分钟内有效,超时要重测。
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 10 }}>
        <button onClick={onBack} style={btn('ghost')}>上一步</button>
        <button onClick={() => void save()} disabled={!testToken || saving}
                style={btn('primary', !testToken || saving)}>
          {saving ? '保存中…' : '保存并继续'}
        </button>
      </div>
      {!testToken && (
        <div style={{ marginTop: 8, fontSize: 12.5, color: HUNTER.INK_F }}>
          三项检测全部通过之后才能保存 —— 存一份没测过的配置,问题会推迟到你发第一条
          消息时才暴露,那时候看到的只是"没有回复"。
        </div>
      )}
    </Box>
  )
}
