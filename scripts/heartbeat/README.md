# Aegis Heartbeat — 三層心跳監控

系統層級的健康監控，不依賴 Aegis 排程。即使 Aegis 完全掛掉也能自動偵測並修復。

## 架構

```
L1 (5min)   ─── Python 腳本，零 AI 依賴，自動修復已知問題
L2 (30min)  ─── 弱 AI (Haiku)，日誌分析 + 錯誤模式識別 + 輕量修復
L3 (2hr)    ─── 強 AI (Sonnet)，根因分析 + 建卡建議 + 預防性改善
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
    "l2_model": "haiku",
    "l3_model": "sonnet"
  }
}
```

## 查看狀態

```bash
# Timer 狀態
systemctl list-timers 'aegis-heartbeat-*'

# L1 日誌（最頻繁）
journalctl -u aegis-heartbeat-l1 --since '1 hour ago' -f

# L2 診斷報告
journalctl -u aegis-heartbeat-l2 --since '1 hour ago'

# L3 系統分析
journalctl -u aegis-heartbeat-l3 --since '3 hours ago'
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
- Worker 錯誤模式分析（找出重複的錯誤）
- 任務成功率統計
- 資源使用檢查
- 輕量修復（重啟、清暫存）

### L3 (`heartbeat-resolve.md`)
- 彙整 L1 + L2 報告
- 任務執行分析（成本、token、成功率）
- 失敗任務根因分析
- 系統趨勢評估
- 可建卡到 Backlog（不觸發）
- 產出完整報告

## 其他 AI Provider

L2/L3 的提示詞在 `.md` 檔案中，可自行替換為其他 CLI：

```bash
# Gemini 範例（修改 install.sh 或直接改 systemd service）
ExecStart=gemini -p "read heartbeat-diagnose.md and execute" --model gemini-2.0-flash
```
