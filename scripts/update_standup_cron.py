"""更新站會排程 #63：api_url 欄位 + prompt_template 改為 JSON body"""
import sys, json
sys.path.insert(0, "backend")

from sqlmodel import Session
from app.database import engine
from app.models.core import CronJob

MEETING_BODY = json.dumps({
    "meeting_id": "standup-${DATE}",
    "title": "每日站會 ${DATE}",
    "moderator": "aegis",
    "speakers": ["xiao-liang", "xiao-yin"],
    "mode": "round_robin",
    "rounds": 1,
    "opening": "各位好，站會開始。請先讀取你的近期記憶（short-term），然後報告：1) 昨天完成什麼 2) 今天計畫做什麼 3) 有沒有阻礙。小良先請。"
}, ensure_ascii=False, indent=2)

with Session(engine) as s:
    job = s.get(CronJob, 63)
    if not job:
        print("CronJob #63 not found!")
        sys.exit(1)

    job.api_url = "/api/v1/agent-chat/meeting"
    job.prompt_template = MEETING_BODY
    # 清理 metadata 中的舊 api_call 設定
    job.metadata_json = "{}"
    s.commit()

    print(f"Updated CronJob #63")
    print(f"  api_url: {job.api_url}")
    print(f"  prompt_template: {job.prompt_template[:80]}...")
