/**
 * useDateFormat — 統一日期格式化 composable
 *
 * 提供兩種格式化函數：
 * - formatDate: 相對時間（幾分鐘前、幾小時前）+ 超過一天則顯示月日
 * - formatDateFull: 完整日期（僅顯示 zh-TW 本地日期）
 * - formatTime: 顯示時間（時:分）
 */
export function useDateFormat() {
  /**
   * 相對時間格式化（源自 GitPanel.vue）
   * - < 1 小時：X m ago
   * - < 24 小時：X h ago
   * - 其他：M月D日
   */
  function formatDate(iso: string): string {
    if (!iso) return ''
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    const diffSec = Math.floor((Date.now() - d.getTime()) / 1000)
    if (diffSec < 3600) return `${Math.max(0, Math.floor(diffSec / 60))}m ago`
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
    return d.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' })
  }

  /**
   * 完整日期格式化（源自 SettingsProjects.vue）
   * 輸出如「2026/3/30」
   */
  function formatDateFull(dateStr: string): string {
    if (!dateStr) return ''
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr
    return d.toLocaleDateString('zh-TW')
  }

  /**
   * 時間格式化，輸出如「14:30」
   */
  function formatTime(dateStr: string): string {
    if (!dateStr) return ''
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr
    return d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
  }

  return { formatDate, formatDateFull, formatTime }
}
