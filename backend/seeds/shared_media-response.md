---
description: 媒體回傳格式：圖片生成（Gemini）與檔案回傳的標準格式。傳送檔案、圖片給用戶時必讀。
globs:
alwaysApply: true
---

# 媒體回傳

當用戶要求圖表、圖片或檔案時，按以下方式處理。

## ⚠️ 安全規範（必讀）

- **禁止直接存取 Bot Token**：不要從資料庫、環境變數或設定檔讀取 Telegram/LINE Bot Token
- **禁止直接呼叫 Telegram/LINE API**：不要用 curl、Python requests 等直接呼叫平台 API
- **一律使用 send_file 標記**：系統會自動解析標記並透過正確的頻道發送

## 發送檔案標記格式

在回應中插入 HTML 註解標記，系統會自動發送給用戶：

```
<!-- send_file: /tmp/your-file.jpg -->
<!-- send_file: /tmp/report.pdf | 報告標題說明 -->
```

### 格式規則

| 規則 | 說明 |
|------|------|
| 格式 | `<!-- send_file: 本地路徑 -->` 或 `<!-- send_file: 本地路徑 \| 說明文字 -->` |
| 路徑 | 必須是 `/tmp/` 開頭的**本地路徑** |
| 類型 | 系統自動判斷：jpg/png/gif → 圖片，其他 → 文件 |
| 多檔 | 一次回應可放多個標記，每個分別發送 |

### ❌ 錯誤格式

```
[send_file: /tmp/file.jpg]          ← 方括號格式無效
```

## 圖片生成（Gemini）

```python
import os
from google import genai
from google.genai import types
import base64

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
response = client.models.generate_content(
    model="gemini-2.5-flash-preview-image-generation",
    contents="用中文描述你要的圖片內容",
    config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
)

# 儲存圖片
for part in response.candidates[0].content.parts:
    if part.inline_data:
        with open("/tmp/generated.png", "wb") as f:
            f.write(base64.b64decode(part.inline_data.data))
        break
```

生成後加上標記：`<!-- send_file: /tmp/generated.png -->`

## 自行生成文件（PDF 等）

用 Python 生成文件後，存到 `/tmp/` 再用標記發送：

```
<!-- send_file: /tmp/report.pdf | 月報告 -->
```

## 接收用戶檔案

用戶傳送圖片或文件時，你會收到檔案路徑提示，例如：
`[用戶傳送了一張圖片，檔案路徑: /tmp/aegis-media/123.jpg]`

你可以用 Read 工具讀取圖片，或用 Bash 執行 Python 解析文件（PDF、Excel 等）。
