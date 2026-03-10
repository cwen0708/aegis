/**
 * Aegis 前端配置
 * 透過環境變數配置 API 和 WebSocket URL
 */

export const config = {
  // API URL（空字串 = 同源）
  apiUrl: import.meta.env.VITE_API_URL || '',

  // WebSocket URL（自動偵測協議）
  wsUrl: import.meta.env.VITE_WS_URL ||
    `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}`,

  // OneStack 連接（可選）
  onestack: {
    enabled: import.meta.env.VITE_ONESTACK_ENABLED === 'true',
    url: import.meta.env.VITE_ONESTACK_URL || '',
  },
}
