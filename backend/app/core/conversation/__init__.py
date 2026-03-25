"""
Conversation — 多成員會議 / 群聊系統

ConversationRoom: 管理一場會議的生命週期
Coordinator: 控制發言順序（輪流制 / 主持人制）
"""
from app.core.conversation.room import ConversationRoom  # noqa: F401
from app.core.conversation.coordinator import run_round_robin, run_moderated  # noqa: F401
