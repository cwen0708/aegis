"""更新站會排程 #63 為 api_call 模式（直接呼叫 meeting API，不建卡片）"""
import sys, json
sys.path.insert(0, "backend")

from sqlmodel import Session
from app.database import engine
from app.models.core import CronJob

NEW_METADATA = {
    "action": "api_call",
    "api_url": "/api/v1/agent-chat/meeting",
    "api_body": {
        "meeting_id": "standup-${DATE}",
        "title": "每日站會 ${DATE}",
        "moderator": "aegis",
        "speakers": ["xiao-liang", "xiao-yin"],
        "mode": "round_robin",
        "rounds": 1,
        "opening": "各位好，站會開始。請先讀取你的近期記憶（short-term），然後報告：1) 昨天完成什麼 2) 今天計畫做什麼 3) 有沒有阻礙。小良先請。"
    }
}

with Session(engine) as s:
    job = s.get(CronJob, 63)
    if not job:
        print("CronJob #63 not found!")
        sys.exit(1)

    old_meta = job.metadata_json or "{}"
    job.metadata_json = json.dumps(NEW_METADATA, ensure_ascii=False)
    # prompt_template 留著但不再被使用（api_call 模式跳過建卡片）
    s.commit()

    print(f"Updated CronJob #63 to api_call mode")
    print(f"  metadata: {job.metadata_json[:100]}...")
    print(f"  cron: {job.cron_expression}")
    print(f"  enabled: {job.is_enabled}")
