# Talk STT Provider A/B 測試（Eleven vs Deepgram）

## 前置

1. **Settings 頁設定 `deepgram_api_key`**
   - 到 <https://console.deepgram.com> 註冊免費帳號（有 $200 額度，Nova-3 約可跑數千分鐘音訊）
   - Console → API Keys → Create a New API Key（權限選 `Member` 即可）
   - 填到 Aegis Settings → `deepgram_api_key`
2. **確認 ElevenLabs key 已設定**（`elevenlabs_api_key`，與 TTS 共用）
3. **準備 5–10 條繁中 + 專有名詞測試句**，例如：
   - 「今天天氣如何，幫我看新北市的預報」
   - 「幫我查 Aegis 昨天的 cron job 執行記錄」
   - 「小茵你去把 PostgreSQL 的 N+1 查詢修一下」
   - 「煮個泡麵吃吧，再打電話給小良哥」
   - 「排一個禮拜三下午去彰濱案場做預防性維運」
   - 「Greenshepherd 的 TDEngine 昨天有沒有噴警報」

## 測試流程

### 1. ElevenLabs 基準

- Settings → `stt_provider = elevenlabs`
- 進 `/talk/xiao-liang`（或任一成員）
- 每條測試句**唸 3 次**，記錄：
  - **Partial 首字延遲**：DevTools Performance 錄一段，量從麥克風開始到第一個 `transcript_partial` WS frame 抵達的時間
  - **Final transcript 正確率**：專有名詞對不對？語氣詞有沒有漏？
  - **Final 觸發延遲**：話說完到 `transcript` final frame 抵達的時間

### 2. Deepgram 對比

- Settings → `stt_provider = deepgram`
- 重新整理 Talk 頁（讓 WS 重連讀新設定）
- 同樣 5–10 句各 3 次，記錄同樣三項指標

### 3. 記錄表

| 測試句 | Eleven 首字延遲 | Eleven 準確 | Deepgram 首字延遲 | Deepgram 準確 | 勝者 |
|---|---|---|---|---|---|
| 「今天天氣…」 | 240ms | 正確 | 310ms | 正確 | 平手 |
| 「小茵修 N+1…」 | 260ms | 漏「N+1」 | 280ms | 正確 | Deepgram |
| … | | | | | |

## 判準

- **延遲差 <100ms 視為平手**（雙方都已是 streaming，人耳辨識不出來）
- **準確率計分**：
  - 錯一個普通字：扣 10%
  - 錯專有名詞（人名、技術詞、案場名）：扣 30%
  - 整段不可理解：扣 100%
- **平手時優先選 Eleven**（節省一條上游 provider，降維運面）

## 若 Deepgram 勝

1. Settings → `stt_provider = deepgram` 設為預設
2. 考慮改 `backend/app/database/seed.py` 裡 `stt_provider` 預設值（留給後續 PR，避免影響沒設 key 的部署）
3. 在本檔最末加一段「測試結果」區，記錄日期、測試人、勝者與判斷依據

## 若 Eleven 勝（或平手）

- 維持 `stt_provider = elevenlabs` 不動
- Deepgram 僅作為 Eleven 掛掉時的手動切換備援

## 相關程式碼

- 後端：`backend/app/core/stt_stream.py`（`ElevenLabsStreamingSTT` / `DeepgramStreamingSTT`）
- 後端 WS：`backend/app/api/talk.py`（`_build_streaming_stt` / `_get_deepgram_api_key`）
- 設定 keys：`stt_provider`、`elevenlabs_api_key`、`deepgram_api_key`（SystemSetting 表）
- 計畫：`~/.claude/plans/golden-jingling-galaxy.md` Step 5

## 測試結果（填寫區）

> 小良哥實測完後在此記錄，格式：
> `YYYY-MM-DD 測試人：<name>，勝者：<provider>，判斷依據：<一兩句>`
