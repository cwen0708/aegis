"""
Prompt Hardening — 每次任務執行時附加精簡版安全規則提醒

長對話中 CLAUDE.md 的安全限制可能被稀釋，此模組在 prompt 末尾
注入 <security-reminder> 區塊，強化安全邊界意識。
"""

# 精簡版安全規則（控制在 ~150 tokens 以內）
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


def harden_prompt(prompt: str, project_path: str) -> str:
    """將安全提醒附加到 prompt 末尾。

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
