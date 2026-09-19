/**
 * 把 opencode 记在 assistant 消息 `info.error` 上的失败对象翻成给用户看的中文说明。
 *
 * ## 为什么需要(2026-09-17 本地实测)
 *
 * 模型上游返回 402 Insufficient Balance(DeepSeek 账户余额 0)时,opencode 会把
 * `{name:'APIError', data:{statusCode:402, message:'Insufficient Balance', ...}}`
 * 写进那条 assistant 消息的 `error` 字段,parts 为空。前端原来不读这个字段,
 * 于是界面只剩头像和一句「深度思考完成」,下面空白 —— 用户以为 AI 卡住了,
 * 不知道是额度问题,也不知道该找谁。
 *
 * ## 口径
 *
 * - 用户主动点停止(`MessageAbortedError`)不是故障,返回 null,不画错误卡。
 * - 按状态码归类给出「原因 + 下一步」;认不出的类别如实写「模型调用失败」,
 *   附上游原话(外部原始数据,不翻译不改写),不去猜原因。
 */
export interface ModelErrorView {
  title: string
  hint: string
  /** 上游原话,可能是英文 —— 作为原始数据折叠展示 */
  raw?: string
}

export function describeModelError(err: any): ModelErrorView | null {
  if (!err || typeof err !== 'object') return null
  const name = String(err.name || '')
  if (name === 'MessageAbortedError') return null

  const data = err.data && typeof err.data === 'object' ? err.data : {}
  const status = Number(data.statusCode)
  const raw = String(data.message || err.message || '').trim() || undefined
  const low = (raw || '').toLowerCase()

  if (status === 402 || /insufficient.?balance|quota|余额/.test(low)) {
    return {
      title: '模型账户余额不足,这次没有生成内容',
      hint: '上游模型服务拒绝了请求(额度用完)。请管理员充值,或在部署的 .env 里换一个有余额的 LLM_API_KEY 后重发。',
      raw,
    }
  }
  if (status === 401 || status === 403 || name === 'ProviderAuthError') {
    return {
      title: '模型密钥无效,这次没有生成内容',
      hint: '上游模型服务不认这个 key(可能填错、过期或被撤销)。请管理员检查 LLM_API_KEY 后重发。',
      raw,
    }
  }
  if (status === 429) {
    return {
      title: '模型请求太频繁,被上游限流',
      hint: '稍等一会儿再重发;如果一直这样,说明账户的并发或速率额度不够。',
      raw,
    }
  }
  if (name === 'MessageOutputLengthError') {
    return {
      title: '回答超出长度上限,被截断',
      hint: '可以让它分几次回答,或把问题拆小一点。',
      raw,
    }
  }
  if (Number.isFinite(status) && status >= 500) {
    return {
      title: '模型服务暂时不可用',
      hint: '上游返回了服务端错误,通常过一会儿自己恢复,稍后重发即可。',
      raw,
    }
  }
  return {
    title: '模型调用失败,这次没有生成内容',
    hint: '可以重发一次;反复出现请把下面的原始信息发给管理员。',
    raw,
  }
}
