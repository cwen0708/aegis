# Ralph Loop 多輪迭代（Harness P4）

## 目標
讓 AI 在同一張卡片內多輪自我修正 —— 第一輪產出草稿，後續輪次檢視上一輪結果繼續精修，直到 AI 主動宣告 `<!-- loop:done -->` 或達到 `max_rounds` 上限。適用於 review-and-fix、漸進式重構、難一次到位的大型任務。

## 流程
```
worker.process_pending_cards → _execute_card_task → run_task (Round 1)
  └─ success? → parse_loop_signal(output)
         ├─ CONTINUE 且 round < max_rounds → build_next_round_prompt → run_task (Round N)
         └─ DONE / NONE / round == max_rounds → 合併 Round 1..N 輸出 → _handle_regular_result
```
單輪 prompt 由 `backend/app/core/ralph_loop.py::build_next_round_prompt` 組裝（含前一輪摘要，截斷至 2000 字），避免 prompt 無限膨脹。Chat 模式與 cron 卡片不進 Ralph Loop。

## 關鍵欄位
`Card.max_rounds`（`backend/app/models/core.py`）：整數，預設 `1`（單輪）。值 >1 才啟用 Ralph Loop，由 `CardResponse` 暴露到前端（Backlog #13062）。無硬上限，但實務建議 ≤ 5，避免單卡長時間占用工作台。

## failover
Round 1 跑過「主帳號 → 備用帳號 → provider failover」鏈（`worker.py` 中 `accounts_list` 與 `get_failover_chain`）。一旦某組 `(provider, model, auth)` 成功，以 `used_provider/used_model/used_auth` 記住，後續輪次只用該組合執行（見 #12898）—— 避免 Round 2 又退回已知失敗的主帳號。

## 如何停用／退回單輪
把卡片 `max_rounds` 設回 `1`（前端卡片編輯器或 `UPDATE cards SET max_rounds=1 WHERE id=?`）。`max_rounds <= 1` 時 worker 完全跳過 Ralph Loop 區塊，行為等同傳統單輪任務。核心邏輯仍在 `backend/app/core/ralph_loop.py`，未來可再調高恢復多輪。
