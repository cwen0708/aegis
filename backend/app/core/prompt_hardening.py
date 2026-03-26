"""
Prompt Hardening — 每次 LLM 呼叫時附加安全規則提醒

長對話中 CLAUDE.md 的安全限制可能被稀釋，此模組提供兩層注入：
1. harden_prompt() — 完整版，用於任務初始 prompt（~150 tokens）
2. harden_message() — 精簡版，用於對話中每則訊息（~60 tokens）
"""

# 完整版安全規則（~150 tokens），用於任務初始 prompt
SECURITY_REMINDER = """\
<security-reminder>
## 安全限制（強制執行）
- 禁止讀寫 .env、*.db、credentials、secrets 等敏感檔案
- 禁止存取 ~/.ssh/、~/.config/、~/.claude/ 等系統目錄
- 禁止存取 Aegis 安裝目錄（*/aegis/backend 執行環境）
- 禁止執行 kill/pkill/killall/taskkill 等進程管理命令
- 禁止安裝全域套件或修改系統設定
- 禁止將 API Key、Token、密碼等憑證輸出到回應中
- 所有操作限定在專案目錄與工作區內
</security-reminder>"""

# 精簡版安全規則（~60 tokens），用於 per-message 注入（chat session pool 等）
# 避免重複注入過長的規則浪費 context window
SECURITY_REMINDER_SHORT = """\
<security-reminder>
禁止：讀寫 .env/secrets/credentials、存取系統目錄、kill 進程、洩露憑證。操作限定在專案目錄內。
</security-reminder>"""


def harden_prompt(prompt: str, project_path: str) -> str:
    """將完整版安全提醒附加到 prompt 末尾（用於任務初始 prompt）。

    Parameters
    ----------
    prompt : str
        原始 prompt 內容。
    project_path : str
        任務執行的專案路徑（保留供未來依專案調整規則）。

    Returns
    -------
    str
        附加安全提醒後的 prompt。
    """
    if not prompt:
        return prompt
    return f"{prompt}\n\n{SECURITY_REMINDER}"


def harden_message(message: str) -> str:
    """將精簡版安全提醒附加到對話訊息末尾（用於 per-message 注入）。

    在持久 chat session 中，每則 user message 都附加精簡版安全規則，
    防止長對話稀釋初始 prompt 中的安全限制。

    Parameters
    ----------
    message : str
        使用者訊息內容。

    Returns
    -------
    str
        附加精簡版安全提醒後的訊息。
    """
    if not message:
        return message
    return f"{message}\n\n{SECURITY_REMINDER_SHORT}"
