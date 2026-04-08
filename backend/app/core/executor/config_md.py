"""
AI 設定檔模板產生器 — 多 Provider / Chat / Task 共用

支援 Provider：Claude (CLAUDE.md)、Gemini (Gemini.md)、Codex、Ollama
內容模板相同（soul + security + task/chat context），檔名和 dot 目錄因 provider 而異。

合併原本分散在 chat_workspace.py 和 task_workspace.py 中的模板邏輯。
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Literal

logger = logging.getLogger(__name__)

# ── 安全限制（內聯 failsafe，即使 .claude/rules/ 缺失也生效）──
_SECURITY_RESTRICTIONS = """
禁止存取：
- ~/.claude/、~/.ssh/、~/.config/
- 任何 .env、*.db、credentials 檔案
禁止操作：
- 禁止修改系統檔案（MCP 原始碼、設定檔、.env、CLAUDE.md、skill 檔案等）
- 禁止安裝套件（pip install、npm install、apt install 等）
- 禁止執行破壞性指令（rm -rf、kill、systemctl 等）
- 禁止執行 kill/pkill/killall/taskkill 等進程管理命令
- 禁止修改系統設定或安裝全域套件
""".strip()

_INSTALL_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# ── Provider 設定檔映射 ──
# 從 task_workspace.py 搬遷而來
PROVIDER_CONFIG = {
    "claude": {"config_file": "CLAUDE.md", "dot_dir": ".claude"},
    "gemini": {"config_file": "Gemini.md", "dot_dir": ".gemini"},
    "codex":  {"config_file": "CODEX.md",  "dot_dir": ".codex"},
    "ollama": {"config_file": "OLLAMA.md", "dot_dir": ".ollama"},
}


def get_config_filename(provider: str) -> str:
    """回傳 provider 對應的設定檔名（CLAUDE.md / Gemini.md / ...）"""
    cfg = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["claude"])
    return cfg["config_file"]


def get_dot_dir(provider: str) -> str:
    """回傳 provider 對應的 dot 目錄名（.claude / .gemini / ...）"""
    cfg = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["claude"])
    return cfg["dot_dir"]


def build_config_md(
    mode: Literal["chat", "task"],
    soul: str = "",
    member_slug: str = "",
    *,
    # Task-specific
    project_path: str = "",
    card_content: str = "",
    stage_name: str = "",
    stage_description: str = "",
    stage_instruction: str = "",
    # Chat-specific
    user_context=None,
    accessible_projects: Optional[List] = None,
    user_level: int = 0,
    chat_id: str = "",
    platform: str = "",
    user_extra: Optional[dict] = None,
) -> str:
    """生成 AI 設定檔內容（provider-agnostic，檔名由呼叫端決定）。

    mode="chat": 即時對話用（Telegram/LINE，ProcessPool cwd）
    mode="task": 卡片任務用（Worker 臨時 workspace）
    """
    if mode == "task":
        return _build_task_md(
            soul=soul,
            member_slug=member_slug,
            project_path=project_path,
            card_content=card_content,
            stage_name=stage_name,
            stage_description=stage_description,
            stage_instruction=stage_instruction,
        )
    else:
        return _build_chat_md(
            soul=soul,
            member_slug=member_slug,
            user_context=user_context,
            accessible_projects=accessible_projects or [],
            user_level=user_level,
            chat_id=chat_id,
            platform=platform,
            user_extra=user_extra,
        )


# 向後相容別名
build_claude_md = build_config_md


# ── Chat 模板 ──

def _build_chat_md(
    soul: str,
    member_slug: str = "",
    user_context=None,
    accessible_projects: list = None,
    user_level: int = 0,
    chat_id: str = "",
    platform: str = "",
    user_extra: Optional[dict] = None,
) -> str:
    """生成 chat 專用設定檔（不含歷史和用戶訊息）。"""
    lines = []

    # 身份
    if soul:
        lines.append(soul.strip())
        lines.append("")

    # 記憶（讓 AI 知道自己有長短期記憶可讀取）
    if member_slug:
        from app.core.member_profile import get_member_memory_dir
        memory_path = get_member_memory_dir(member_slug)
        lines.append("# 記憶")
        lines.append(f"你的個人記憶存放在：{memory_path}")
        lines.append("- short-term/ 短期記憶（近期任務摘要）")
        lines.append("- long-term/ 長期記憶（累積的經驗與模式）")
        lines.append("回答問題或參加會議前，可以先讀取近期記憶來回顧最近做了什麼。")
        lines.append("")

    # 用戶身份
    if user_context:
        lines.append("# 當前用戶")
        if hasattr(user_context, "display_name") and user_context.display_name:
            lines.append(f"姓名：{user_context.display_name}")
        if hasattr(user_context, "description") and user_context.description:
            lines.append(f"身份描述：{user_context.description}")
        lines.append("")
        lines.append("請根據用戶的身份和權限範圍回答，用適當的稱呼和語氣。")
        lines.append("")

    # 用戶額外資料
    if user_extra:
        lines.append("# 用戶額外資料")
        for k, v in user_extra.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
        lines.append("這些資料可用於 MCP 工具存取外部系統。")
        lines.append("如果缺少必要認證資料（如 ad_user, ad_pass），請引導用戶使用 /profile 指令。")
        lines.append("")

    # 可存取專案
    if accessible_projects:
        lines.append("# 用戶可存取的專案")
        for p in accessible_projects:
            lines.append(f"- {p.name}（ID: {p.id}）")
        lines.append("")
        lines.append("回答問題時只能提供這些專案的資訊。")
        lines.append("")

    # 任務建立引導
    if user_level >= 2 and accessible_projects:
        lines.append("# 複雜任務處理")
        lines.append("如果用戶的請求太複雜（需要寫程式、分析大量資料、多步驟操作等），")
        lines.append("你可以詢問用戶是否要建立任務卡片，讓更強大的 AI 來處理。")
        lines.append("回覆格式：[CREATE_TASK:專案ID:任務標題:任務描述]")
        if platform and chat_id:
            lines.append(f"任務描述最後請加上：「完成後請透過 {platform} 通知 chat_id={chat_id}」")
        lines.append("")

    # 安全限制（內聯 failsafe + .claude/rules/ 雙重保障）
    lines.append("# 安全限制")
    lines.append(_SECURITY_RESTRICTIONS)
    lines.append("")

    # 回應風格
    lines.append("# 回應風格")
    lines.append("請以你的角色身份回應（簡潔、友善、專業）。")
    lines.append("")

    # 下一步操作建議（Telegram 顯示為按鈕）
    if platform in ("telegram", "line", "discord"):
        lines.append("# 下一步操作建議")
        lines.append("每次回應後，思考用戶接下來最可能想做什麼，提供 2-4 個操作選項。")
        lines.append("在回應文字的**最後**加上 `<!--actions-->` 區塊：")
        lines.append("")
        lines.append("```")
        lines.append("<!--actions")
        lines.append("[按鈕文字](https://url)     ← URL 按鈕（開連結）")
        lines.append("[按鈕文字](callback:動作名)  ← 回調按鈕")
        lines.append("-->")
        lines.append("```")
        lines.append("")
        lines.append("範例：找到檔案後 → `[📄 打開文件](分享連結URL)` `[🔍 搜尋更多](callback:search)`")
        lines.append("分析完成後 → `[📨 發送報告](callback:send)` `[🔄 重新分析](callback:rerun)`")
        lines.append("不是每次都要加，只在有明確下一步時才加。每行 1 個按鈕，最多 4 行。")
        lines.append("")

    return "\n".join(lines)


# ── Task 模板 ──

def _build_task_md(
    soul: str,
    member_slug: str,
    project_path: str,
    card_content: str,
    stage_name: str = "",
    stage_description: str = "",
    stage_instruction: str = "",
) -> str:
    """生成 task 專用設定檔（含 workspace 資訊、記憶路徑、階段指令、歷史記憶注入）。"""
    from app.core.member_profile import get_member_memory_dir
    from app.core.executor.memory import retrieve_task_memory

    memory_path = get_member_memory_dir(member_slug)

    # 獲取相關過往經驗（在新 event loop 中執行，避免巢狀 loop crash）
    task_memories: list = []
    try:
        loop = asyncio.new_event_loop()
        try:
            task_memories = loop.run_until_complete(
                asyncio.wait_for(
                    retrieve_task_memory(
                        card_title=card_content.split('\n')[0][:100],
                        card_description=card_content,
                        member_slug=member_slug,
                    ),
                    timeout=2.0
                )
            )
        finally:
            loop.close()
    except asyncio.TimeoutError:
        logger.warning("Task memory retrieval timeout for %s", member_slug)
    except Exception as e:
        logger.warning("Failed to retrieve task memory: %s", e)

    # 階段說明區塊
    stage_section = ""
    if stage_name or stage_description or stage_instruction:
        parts = [f"# 當前階段：{stage_name}" if stage_name else "# 當前階段"]
        if stage_description:
            parts.append(stage_description)
        if stage_instruction:
            parts.append(f"\n## 階段指令\n{stage_instruction}")
        stage_section = "\n".join(parts) + "\n"

    # 安全限制（內聯 failsafe + .claude/rules/ 雙重保障）
    install_root = str(_INSTALL_ROOT)
    security_section = f"""# 安全限制
你只能在以下目錄操作：
1. {project_path} — 專案目錄
2. 當前工作區目錄（臨時）

禁止存取的路徑：
- Aegis 安裝目錄（{install_root}）
{_SECURITY_RESTRICTIONS}
"""

    # 相關過往經驗 section
    memories_section = ""
    if task_memories:
        memories_text = "\n".join([f"- {m['content']}" for m in task_memories])
        memories_section = f"\n## 相關過往經驗\n{memories_text}\n"

    return f"""# 工作目錄
你的工作目錄（cwd）是臨時工作區，專案檔案已透過 symlink 連結進來。
可以直接用相對路徑操作（如 backend/worker.py），改動會直接反映在專案目錄。

專案實際路徑：{project_path}
git 操作在此目錄中可直接執行（.git 已連結）。

# 你的身份
{soul}

{security_section}

# 記憶
你的個人記憶存放在：
{memory_path}
- short-term/ 短期記憶（近期任務摘要）
- long-term/ 長期記憶（累積的經驗與模式）
需要回憶時可以去讀取。{memories_section}
{stage_section}
# 本次任務
{card_content}

# 任務完成後
請在你所有輸出的最末行，用你的角色語氣寫一句簡短的任務總結（70字以內），格式如下：
<!-- dialogue: 你的總結 -->
這句話會顯示在你的對話框中，請用自然、符合你性格的口吻。
"""
