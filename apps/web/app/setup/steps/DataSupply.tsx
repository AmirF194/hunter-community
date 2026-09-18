'use client'
// 第 4 步 · 数据供给三选一(设计方案 4.6)
//
// 平台 key 走**现成的** PUT /api/hunter/unlock —— 它本来就是"先校验再保存",
// 不另写一套校验(两套校验对同一把 key 给出不同结论是最难查的一类问题)。
import { useState } from 'react'
import { Database, ExternalLink } from 'lucide-react'
import { HUNTER } from '../../lib/hunter-theme'
import { savePlatformKey, isFail, type SetupStatus } from '../lib/setupClient'
import { Box, Tag, btn } from '../lib/ui'
import { Field } from './ModelPick'

type Choice = 'free' | 'platform' | 'mcp'

export default function DataSupply({
  status, onNext, onBack, onRefresh,
}: {
  status: SetupStatus
  onNext: () => void
  onBack: () => void
  onRefresh: () => Promise<any>
}) {
  const ds = status.data_supply
  const [choice, setChoice] = useState<Choice>(ds?.configured ? 'platform' : 'free')
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [okMsg, setOkMsg] = useState('')

  const saveKey = async () => {
    if (!key.trim() || busy) return
    setBusy(true); setErr(''); setOkMsg('')
    const r = await savePlatformKey(key.trim())
    setBusy(false)
    if (isFail(r)) {
      setErr(r.status === 401
        ? 'key 没保存成功:这台实例开了多用户模式,保存平台 key 需要先有一个账号。'
          + '可以先跳过这一步,在最后一步创建管理员账号之后,到左下角「解锁全部工具」里再填。'
        : r.message)
      return
    }
    setKey('')
    setOkMsg('平台 key 已校验通过并保存。')
    await onRefresh()
  }

  return (
    <Box icon={<Database size={16} />} title="第 4 步 · 数据从哪来">
      <div style={{ color: HUNTER.INK_F, fontSize: 13.5 }}>
        大模型负责思考,行情和财务数据要另外有来源。这一步可以跳过,之后随时能改。
      </div>

      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <Option on={choice === 'free'} onClick={() => setChoice('free')} title="免费开源数据源"
                tag={<Tag tone="ok">不用填任何东西</Tag>}>
          A 股行情、K 线、财务走 AKShare / 腾讯等公开源,装好就能用。
          <div style={{ marginTop: 4, color: HUNTER.INK_F }}>
            局限:容器直连这些站点在部分网络环境下不稳定;港美股与部分高级数据覆盖不全。
          </div>
        </Option>

        <Option on={choice === 'platform'} onClick={() => setChoice('platform')} title="平台数据管道"
                tag={ds?.configured ? <Tag tone="ok">已配置 {ds.masked}</Tag> : <Tag tone="plain">需要一把免费 key</Tag>}>
          一把 key 打开 Kronos 预测、港美股数据、全部工具与 SKILL。
          {ds?.env_locked ? (
            <div style={{ marginTop: 6, color: HUNTER.TAG_WARN_FG }}>
              这台实例的 key 来自 .env(HUNTER_API_KEY),这里改不了。
            </div>
          ) : (
            <>
              <Field label="平台 key" type="password" placeholder="hunt_tools_…"
                     value={key} onChange={setKey} />
              <button onClick={() => void saveKey()} disabled={!key.trim() || busy}
                      style={{ ...btn('primary', !key.trim() || busy), marginTop: 10 }}>
                {busy ? '校验中…' : '校验并保存'}
              </button>
              {ds?.apply_url && (
                <div style={{ marginTop: 8, fontSize: 12.5 }}>
                  <a href={ds.apply_url} target="_blank" rel="noreferrer"
                     onClick={(e) => e.stopPropagation()}
                     style={{ color: HUNTER.THEME, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    免费申请(约 30 秒) <ExternalLink size={12} />
                  </a>
                </div>
              )}
            </>
          )}
        </Option>

        <Option on={choice === 'mcp'} onClick={() => setChoice('mcp')} title="自己接数据源 / MCP"
                tag={<Tag tone="plain">进阶</Tag>}>
          有 Tushare、聚宽这类账号,或者自己写了 MCP 工具,可以直接接进来。
          <div style={{ marginTop: 6, fontSize: 12.5 }}>
            <a href="/mcp-config" style={{ color: HUNTER.THEME }}>去「数据源与 MCP」页配置 →</a>
            <span style={{ color: HUNTER.INK_F }}>（也可以先跳过,配好向导再回来）</span>
          </div>
        </Option>
      </div>

      {err && <div style={{ marginTop: 12, color: HUNTER.UP, fontSize: 13.5 }}>{err}</div>}
      {okMsg && <div style={{ marginTop: 12, color: HUNTER.SUCCESS, fontSize: 13.5 }}>{okMsg}</div>}

      <div style={{ display: 'flex', gap: 10 }}>
        <button onClick={onBack} style={btn('ghost')}>上一步</button>
        <button onClick={onNext} style={btn()}>下一步 · 完成</button>
      </div>
    </Box>
  )
}

function Option({
  on, onClick, title, tag, children,
}: {
  on: boolean
  onClick: () => void
  title: string
  tag?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div onClick={onClick} style={{
      cursor: 'pointer', padding: 13, borderRadius: HUNTER.R_MD,
      background: on ? HUNTER.BRAND_PALE : HUNTER.PAPER,
      border: `1.5px solid ${on ? HUNTER.THEME : HUNTER.LINE}`,
      fontSize: 13, color: HUNTER.INK_S, lineHeight: 1.7,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
        <strong style={{ fontSize: 14.5, color: HUNTER.INK }}>{title}</strong>
        {tag}
      </div>
      {children}
    </div>
  )
}
