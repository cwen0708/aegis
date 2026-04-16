# GC 技術債掃描排程（Harness P3）

## 目標
每晚 `0 2 * * *` 自動掃描專案技術債（長函式、TODO 堆積、過期文件、大檔案等），把結果寫成 Backlog 卡片，讓技術債進入例行審查流程。

## 流程
```
cron_poller → _execute_gc_action → gc_scheduler.schedule_gc_scan
  → gc_scanner.scan(project.path) → dedupe → card_factory.create_card
```
`cron_poller` 每分鐘挑出到期任務，若 `api_url == "gc"` 即交給 `_execute_gc_action` 呼叫 `schedule_gc_scan`，產生的 findings 經去重後建立帶 `gc-scan` tag 的 Backlog 卡。

## 手動觸發
```bash
# 走 CronJob（會寫 CronLog）
curl -X POST http://127.0.0.1:8899/api/v1/cron-jobs/{ID}/gc
# 直接呼叫掃描端點
curl -X POST http://127.0.0.1:8899/api/v1/gc/scan -H 'content-type: application/json' -d '{"project_id": 1}'
```
回傳 `{"ok": true, "action": "gc", "cards_created": N}`。`N=0` 代表本輪全部去重，屬正常。

## 去重規則
以 `rule_id + file`（檔案相對路徑）為鍵，比對 Backlog 內未封存的卡片；同檔同規則只產一張卡。

## 如何停用
把 seed 建立的「GC 技術債掃描」CronJob 設成 `is_enabled=False`（UI 切換或 `UPDATE cron_jobs SET is_enabled=0 WHERE name='GC 技術債掃描'`）。主邏輯仍保留在 `backend/app/core/gc_scheduler.py`，未來可重新啟用。
