import sys
from sqlmodel import Session, select
from app.database import engine, init_db
from app.models.core import Project, StageList, Card

def seed_data():
    init_db()
    with Session(engine) as session:
        # 檢查是否已經有資料
        if session.exec(select(Project)).first():
            print("Database already has data. Skipping seed.")
            return

        print("Seeding initial data...")
        
        # 1. 建立專案
        p1 = Project(name="Aegis", path=r"G:\Yooliang\Aegis", default_provider="gemini")
        p2 = Project(name="OneStack", path=r"G:\Yooliang\OneStack", deploy_type="firebase", default_provider="claude")
        session.add_all([p1, p2])
        session.commit()
        session.refresh(p1)
        session.refresh(p2)

        # 2. 為每個專案建立標準的 StageLists
        lists = []
        stages = ["Backlog", "Planning", "Developing", "Verifying", "Done", "Aborted"]
        
        for p in [p1, p2]:
            for idx, stage_name in enumerate(stages):
                lists.append(StageList(project_id=p.id, name=stage_name, position=idx))
        
        session.add_all(lists)
        session.commit()

        # 3. 建立幾張測試卡片
        backlog_list_id = session.exec(select(StageList).where(StageList.name == "Backlog").where(StageList.project_id == p1.id)).first().id
        
        c1 = Card(list_id=backlog_list_id, title="實作 Telegram 機器人整合", description="建立 BaseChannel 抽象層並串接 Webhook")
        c2 = Card(list_id=backlog_list_id, title="修復 SQLite 連線池過期問題", description="這是一個嚴重的 bug")
        
        session.add_all([c1, c2])
        session.commit()
        
        print("Seed completed successfully!")

if __name__ == "__main__":
    seed_data()
