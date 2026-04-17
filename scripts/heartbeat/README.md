# Aegis Heartbeat

系統層級的健康監控，不依賴 Aegis 排程。即使 Aegis 完全掛掉也能自動偵測並修復。

## 架構

```
systemd timer（不依賴 Aegis）
  L1 (5min)   ─── Python 腳本，零 AI 依賴，自動修復已知問題
  L2 (30min)  ─── AI (Haiku)，日誌分析 + 錯誤模式識別 + 輕量修復

Aegis 內部排程（依賴 Aegis 正常運行）
  L3 (2hr)    ─── CronJob #1，深度分析 + 建卡建議
```

## 安裝

```bash
cd scripts/heartbeat
sudo bash install.sh
```

## 移除

```bash
sudo bash install.sh --uninstall
```

## 設定

編輯 `config.json`：

```json
{
  "zombie_threshold_minutes": 60,
  "ai": {
    "provider": "claude",
    "l2_model": "haiku"
  }
}
```

## 查看狀態

```bash
systemctl list-timers 'aegis-heartbeat-*'

# L1 日誌
journalctl -u aegis-heartbeat-l1 --since '1 hour ago'

# L2 診斷報告
journalctl -u aegis-heartbeat-l2 --since '1 hour ago'
```

## 各層職責

### L1 (`heartbeat.py`)
- 服務存活檢查 (`systemctl is-active`)
- API 回應檢查 (`curl /runner/status`)
- 殭屍任務清理（執行 > 60 分鐘自動 abort）
- venv 完整性（遺失自動重建）
- Worker 錯誤日誌檢查（過多則重啟）
- 冷卻機制（重啟後 10 分鐘內不再重啟）

### L2 (`heartbeat-diagnose.md`)
- 彙整 L1 日誌
- Worker 錯誤模式分析
- 任務成功率統計
- 資源使用檢查
- 輕量修復（重啟、清暫存）

### L3（Aegis CronJob #1）
- 彙整 L1 + L2 報告
- 任務執行分析（成本、token、成功率）
- 失敗任務根因分析
- 可建卡到 Backlog
- 有完整 Aegis 環境（skills、MCP 等）

## 其他 AI Provider

L2 的提示詞在 `heartbeat-diagnose.md`，可替換為其他 CLI：

```bash
# Gemini 範例
ExecStart=gemini -p "read heartbeat-diagnose.md and execute" --model gemini-2.0-flash
```
