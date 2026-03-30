# Ollama 本地推理環境設置報告

**日期**：2026-03-30
**執行者**：小茵（Aegis 自我開發分析師）

---

## 1. GPU 資源確認

### 系統環境
- **平台**：Google Cloud Platform（GCP） VM
- **OS**：Ubuntu 24.04，Linux 6.17.0-1008-gcp
- **CPU**：Intel(R) Xeon(R) CPU @ 2.20GHz
- **RAM**：15.6 GiB（可用 ~10 GiB）
- **磁碟**：96 GB（可用 81 GB）

### GPU 狀態
- ❌ **無獨立 GPU**（GCP VM，純 CPU 環境）
- `nvidia-smi` 指令不存在
- `lspci` 未偵測到 VGA/GPU 裝置
- Ollama 日誌確認：`WARNING: No NVIDIA/AMD GPU detected. Ollama will run in CPU-only mode.`

**結論**：本機為 CPU-only 環境，無 VRAM，Ollama 使用系統 RAM 進行推理。

---

## 2. Ollama 安裝

### 安裝方式
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 安裝結果
- **版本**：`ollama version is 0.19.0`
- **安裝路徑**：`/usr/local/bin/ollama`
- **服務狀態**：`active (running)`（systemd service，開機自動啟動）
- **API 端點**：`http://127.0.0.1:11434`

---

## 3. 模型下載與推理測試

### 模型資訊
| 欄位 | 值 |
|------|-----|
| 模型名稱 | llama3.1:8b |
| Model ID | 46e0c10c039e |
| 大小 | 4.9 GB |
| 下載時間 | ~2 分鐘（GCP 網路） |

### 推理測試 1：基本數學
```bash
ollama run llama3.1:8b "Hello, what is 2+2?"
```
**回應**：`The answer to 2+2 is... 4!`
**狀態**：✅ 通過

### 推理測試 2：中文 stdin 輸入
```bash
echo "計算 3 + 4 等於多少" | ollama run llama3.1:8b
```
**回應**：`3 + 4 = <<3+4=7>>7`
**狀態**：✅ 通過

---

## 4. 系統整合確認

### providers.py 配置驗證
路徑：`backend/app/core/executor/providers.py`

```python
"ollama": {
    "cmd_base": ["ollama", "run"],
    "json_output": False,
    "default_model": "llama3.1:8b",
    "stdin_prompt": True,
}
```

**配置吻合度**：✅ 完全相符
- `default_model` 設定為 `llama3.1:8b`，與本次安裝版本一致
- `stdin_prompt: True` 對應 stdin 輸入方式，測試驗證可用

---

## 5. 總結

| 驗證項目 | 狀態 |
|---------|------|
| GPU 環境確認（CPU-only 模式） | ✅ 已確認 |
| Ollama 安裝（v0.19.0） | ✅ 成功 |
| llama3.1:8b 模型下載 | ✅ 成功（4.9 GB） |
| 基本推理測試（英文） | ✅ 通過 |
| stdin 中文輸入測試 | ✅ 通過 |
| providers.py 配置吻合 | ✅ 完全相符 |

### 注意事項
- 無 GPU，推理速度較慢（CPU-only），適合開發測試，不建議正式生產使用
- 若需 GPU 加速，需升級 GCP VM 至 GPU 型號（如 n1-standard + T4）
- Ollama 服務已設為 systemd 開機自啟，服務持續在 `127.0.0.1:11434` 運行
