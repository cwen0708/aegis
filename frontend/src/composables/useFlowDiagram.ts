import { computed, type Ref } from 'vue'
import { parseLine, type ParsedLine } from './useStreamParser'

/**
 * 將 taskLogs（raw string[]）轉成 Mermaid sequence diagram 語法
 */
export function useFlowDiagram(rawLogs: Ref<string[]>, memberName?: string) {
  const MAX_EVENTS = 60

  const parsed = computed<ParsedLine[]>(() => {
    return rawLogs.value
      .map(parseLine)
      .filter(l => l.content && l.type !== 'system')
  })

  const mermaidCode = computed(() => {
    const lines = parsed.value
    if (lines.length === 0) return ''

    const agentName = memberName || 'Agent'
    const participants = new Map<string, string>()
    participants.set('Agent', agentName)

    const events: string[] = []
    let lastToolName = ''

    // 取最近 MAX_EVENTS 筆
    const recent = lines.slice(-MAX_EVENTS)

    for (const line of recent) {
      switch (line.type) {
        case 'assistant': {
          const text = sanitize(truncate(line.content, 60))
          events.push(`    Agent->>Agent: ${text}`)
          // 如果有 detail（工具呼叫提示），記錄
          if (line.detail) {
            const tools = line.detail.replace('→ ', '').split(', ')
            for (const tool of tools) {
              const toolId = toolParticipantId(tool)
              if (!participants.has(toolId)) {
                participants.set(toolId, tool)
              }
              lastToolName = toolId
            }
          }
          break
        }
        case 'tool_call': {
          const tools = line.content.split(', ')
          for (const tool of tools) {
            const toolId = toolParticipantId(tool)
            if (!participants.has(toolId)) {
              participants.set(toolId, tool)
            }
            events.push(`    Agent->>${toolId}: call`)
            lastToolName = toolId
          }
          break
        }
        case 'tool_result': {
          const target = lastToolName || 'Tool'
          if (!participants.has(target)) {
            participants.set(target, target)
          }
          const text = sanitize(truncate(line.content, 50))
          events.push(`    ${target}-->>Agent: ${text}`)
          break
        }
        case 'error': {
          const text = sanitize(truncate(line.content, 50))
          events.push(`    Note over Agent: ⚠️ ${text}`)
          break
        }
        case 'text': {
          // 純文字通常是系統輸出，跳過大部分
          if (line.content.length > 10) {
            const text = sanitize(truncate(line.content, 40))
            events.push(`    Note right of Agent: ${text}`)
          }
          break
        }
      }
    }

    if (events.length === 0) return ''

    // 組合 Mermaid 語法
    const header = 'sequenceDiagram'
    const participantLines = Array.from(participants.entries())
      .map(([id, label]) => {
        if (id === 'Agent') return `    participant Agent as ${label}`
        return `    participant ${id} as ${label}`
      })

    return [header, ...participantLines, '', ...events].join('\n')
  })

  const hasData = computed(() => parsed.value.length > 0)

  return { mermaidCode, parsed, hasData }
}

// =============================================
// Helpers
// =============================================

/** 工具名稱 → 合法的 participant ID（移除空格和特殊字元） */
function toolParticipantId(name: string): string {
  return name.replace(/[^a-zA-Z0-9_]/g, '_')
}

/** 截斷文字 */
function truncate(text: string, maxLen: number): string {
  const oneLine = text.replace(/\n/g, ' ').trim()
  if (oneLine.length <= maxLen) return oneLine
  return oneLine.slice(0, maxLen - 3) + '...'
}

/** 跳脫 Mermaid 特殊字元 */
function sanitize(text: string): string {
  return text
    .replace(/;/g, '；')
    .replace(/#/g, '＃')
    .replace(/-->/g, '→')
    .replace(/->>/, '→')
    .replace(/:/g, '：')
    .replace(/\{/g, '(')
    .replace(/\}/g, ')')
}
