export interface ParsedLine {
  type: 'text' | 'assistant' | 'tool_call' | 'tool_result' | 'system' | 'error'
  content: string
  detail?: string
}

export function parseLine(raw: string): ParsedLine {
  // 嘗試解析 JSON
  try {
    const obj = JSON.parse(raw)

    // system init
    if (obj.type === 'system' && obj.subtype === 'init') {
      return { type: 'system', content: `Session 啟動 (${obj.model || 'unknown'})` }
    }

    // assistant text
    if (obj.type === 'assistant' && obj.message?.content) {
      const parts = obj.message.content
      const texts: string[] = []
      const tools: string[] = []

      for (const part of parts) {
        if (part.type === 'text' && part.text) {
          texts.push(part.text)
        }
        if (part.type === 'tool_use') {
          tools.push(`${part.name}`)
        }
      }

      if (texts.length > 0) {
        return { type: 'assistant', content: texts.join('\n'), detail: tools.length ? `→ ${tools.join(', ')}` : undefined }
      }
      if (tools.length > 0) {
        return { type: 'tool_call', content: tools.join(', ') }
      }
    }

    // tool result
    if (obj.type === 'user' && obj.message?.content) {
      const parts = obj.message.content
      for (const part of parts) {
        if (part.type === 'tool_result') {
          const content = typeof part.content === 'string' ? part.content : ''
          if (part.is_error) {
            return { type: 'error', content: content.slice(0, 200) }
          }
          // 截斷過長的結果
          if (content.length > 300) {
            return { type: 'tool_result', content: content.slice(0, 200) + '...' }
          }
          return { type: 'tool_result', content: content || '(ok)' }
        }
      }
      if (obj.tool_use_result === 'Error') {
        return { type: 'error', content: obj.tool_use_result }
      }
    }

    // 處理中提示
    if (typeof obj === 'string' && obj.includes('處理中')) {
      return { type: 'system', content: obj }
    }

    // 其他 JSON — 不顯示
    return { type: 'system', content: '' }
  } catch {
    // 非 JSON — 純文字
    const trimmed = raw.trim()
    if (!trimmed) return { type: 'text', content: '' }
    // 處理中提示
    if (trimmed.startsWith('⏳')) {
      return { type: 'system', content: trimmed }
    }
    return { type: 'text', content: trimmed }
  }
}

export function parseOutput(raw: string): ParsedLine[] {
  return raw.split('\n').map(parseLine).filter(l => l.content)
}
