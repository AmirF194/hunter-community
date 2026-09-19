'use client'
// 第 2 步 · 选大模型(设计方案 4.4)
//
// 预设来自 `data/llm-presets.json`(随 api 镜像分发)。卡片上的命中率与耗时
// **全是实测值**,抄自 docs/model-testing/model-compat-matrix.md ——
// 读不到预设文件时如实显示"读不到",不在前端内置一份兜底(两处数值迟早不一致)。
import { useEffect, useState } from 'react'
import { Loader2, Cpu, ExternalLink } from 'lucide-react'
import { HUNTER } from '../../lib/hunter-theme'
import { getPresets, isFail, type Preset, type PresetDoc, type LlmStatus } from '../lib/setupClient'
import { Box, Tag, btn } from '../lib/ui'

export interface Draft {
  base_url: string
  api_key: string
  model: string
  sanitize: string
  preset?: Preset
}

export default function ModelPick({
  llm, draft, onChange, onNext, onBack,
}: {
  llm: LlmStatus
  draft: Draft
  onChange: (d: Draft) => void
  onNext: () => void
  onBack: () => void
}) {
  const [doc, setDoc] = useState<PresetDoc | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    void (async () => {
      const r = await getPresets()
      if (isFail(r)) { setErr(r.message); return }
      setDoc(r)
      // 已经配过的话,默认停在当前配置上(换模型的场景),不强迫重选
      if (!draft.base_url && llm.configured) {
        onChange({ ...draft, base_url: llm.base_url, model: llm.model, sanitize: llm.sanitize })
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const pick = (p: Preset) => {
    onChange({
      base_url: p.base_url,
      model: p.model,
      sanitize: p.sanitize,
      api_key: draft.api_key,
      preset: p,
    })
  }

  const chosen = draft.preset?.id
  const canNext = !!(draft.base_url.trim() && draft.model.trim()) || chosen === 'custom'

  return (
    <Box icon={<Cpu size={16} />} title="第 2 步 · 选大模型">
      <div style={{ color: HUNTER.INK_F, fontSize: 13.5 }}>
        猎鹿人自己不训练模型,对话和分析都靠你自己的大模型账号。
        下面的命中率和耗时是我们实测出来的
        {doc?.updated_at ? `(${doc.updated_at},7 个 golden case)` : ''},
        不是厂商宣传值。
      </div>

      {err && <div style={{ marginTop: 12, color: HUNTER.UP, fontSize: 13.5 }}>{err}</div>}
      {doc?.error && <div style={{ marginTop: 12, color: HUNTER.UP, fontSize: 13.5 }}>{doc.error}</div>}

      {!doc && !err && (
        <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 8, color: HUNTER.INK_F }}>
          <Loader2 size={15} style={{ animation: 'hspin 1s linear infinite' }} /> 正在读取预设…
        </div>
      )}

      {llm.configured && (
        <div style={{
          marginTop: 12, padding: '9px 11px', borderRadius: HUNTER.R_SM,
          background: HUNTER.BRAND_PALE, fontSize: 13, color: HUNTER.COPPER3,
        }}>
          当前在用:<strong>{llm.model}</strong> @ {llm.base_url}
          （key {llm.api_key_masked || '未配置'}）
        </div>
      )}

      <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {(doc?.presets || []).map((p) => {
          const on = chosen === p.id
          return (
            <button key={p.id} onClick={() => pick(p)} style={{
              textAlign: 'left', cursor: 'pointer', padding: 13,
              borderRadius: HUNTER.R_MD, background: on ? HUNTER.BRAND_PALE : HUNTER.PAPER,
              border: `1.5px solid ${on ? HUNTER.THEME : HUNTER.LINE}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <strong style={{ fontSize: 14.5, color: HUNTER.INK }}>{p.title}</strong>
                {p.tags.map((t) => <Tag key={t} tone={t === '不推荐' ? 'fail' : 'ok'}>{t}</Tag>)}
              </div>
              <div style={{ fontSize: 12.5, color: HUNTER.INK_F, marginTop: 3 }}>{p.vendor}</div>
              {(p.tool_hit || p.avg_latency_s != null) && (
                <div style={{ fontSize: 12.5, color: HUNTER.INK_S, marginTop: 6 }}>
                  工具调用命中 <strong>{p.tool_hit || '—'}</strong>
                  {p.avg_latency_s != null && <> · 单次平均 <strong>{p.avg_latency_s} 秒</strong></>}
                  {p.tested_at && <> · 实测于 {p.tested_at}</>}
                </div>
              )}
              {p.notes?.length > 0 && (
                <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12.5, color: HUNTER.INK_F }}>
                  {p.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              )}
              {p.apply_url && (
                <div style={{ marginTop: 6, fontSize: 12.5 }}>
                  <a href={p.apply_url} target="_blank" rel="noreferrer"
                     onClick={(e) => e.stopPropagation()}
                     style={{ color: HUNTER.THEME, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    去申请 key <ExternalLink size={12} />
                  </a>
                  {p.key_hint && <span style={{ color: HUNTER.INK_F }}> · {p.key_hint}</span>}
                </div>
              )}
            </button>
          )
        })}
      </div>

      {chosen && (
        <div style={{ marginTop: 14 }}>
          <Field label="接口地址(OpenAI 兼容)" value={draft.base_url}
                 placeholder="https://your-gateway/v1"
                 onChange={(v) => onChange({ ...draft, base_url: v })} />
          <Field label="模型名" value={draft.model}
                 placeholder="例如 deepseek-v4-pro"
                 onChange={(v) => onChange({ ...draft, model: v })} />
          <div style={{ fontSize: 12.5, color: HUNTER.INK_F, marginTop: 6 }}>
            这两项可以在这里改。key 在下一步填,填完当场检测三项。
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 10 }}>
        <button onClick={onBack} style={btn('ghost')}>上一步</button>
        <button onClick={onNext} disabled={!canNext} style={btn('primary', !canNext)}>
          下一步 · 填 key 当场测
        </button>
      </div>
    </Box>
  )
}

export function Field({
  label, value, onChange, placeholder, type, disabled,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  disabled?: boolean
}) {
  return (
    <label style={{ display: 'block', marginTop: 10 }}>
      <div style={{ fontSize: 12.5, color: HUNTER.INK_S, marginBottom: 4 }}>{label}</div>
      <input
        type={type || 'text'}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: '100%', padding: '10px 11px', fontSize: 14,
          borderRadius: HUNTER.R_MD, border: `1px solid ${HUNTER.LINE}`,
          background: disabled ? HUNTER.PAPER2 : '#fff', color: HUNTER.INK,
        }}
      />
    </label>
  )
}
