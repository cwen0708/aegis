"""關聯圖 API — 一次回傳所有實體和關聯"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.core import (
    Project, Member, MemberAccount, Account,
    Domain, Room, RoomMember,
    BotUser, Person, PersonProject, PersonMember, StageList, CronJob,
)
import json as json_module

router = APIRouter()


@router.get("/graph/all")
def get_all_relations(session: Session = Depends(get_session)):
    """一次回傳所有實體和關聯，前端自行處理佈局"""
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_edges: set[str] = set()

    def add_edge(st: str, si: int, tt: str, ti: int, rel: str):
        ek = f"{st}:{si}-{tt}:{ti}"
        if ek not in seen_edges:
            seen_edges.add(ek)
            edges.append({"source": f"{st}:{si}", "target": f"{tt}:{ti}", "relation": rel})

    # ── 專案 ──
    projects = session.exec(select(Project).where(Project.is_active == True)).all()
    for p in projects:
        nodes.append({"type": "project", "id": p.id, "label": p.name, "is_system": p.is_system})

    # ── 成員 ──
    members = session.exec(select(Member)).all()
    for m in members:
        nodes.append({"type": "member", "id": m.id, "label": m.name, "slug": m.slug})

    # ── 成員 ↔ 專案（透過 StageList）──
    stage_lists = session.exec(select(StageList).where(StageList.member_id.is_not(None))).all()
    project_member_pairs: set[tuple[int, int]] = set()
    for sl in stage_lists:
        if sl.member_id:
            pair = (sl.project_id, sl.member_id)
            if pair not in project_member_pairs:
                project_member_pairs.add(pair)
                add_edge("project", sl.project_id, "member", sl.member_id, "成員")

    # ── 成員 ↔ 帳號 ──
    member_accounts = session.exec(select(MemberAccount)).all()
    accounts = {a.id: a for a in session.exec(select(Account)).all()}
    for ma in member_accounts:
        acc = accounts.get(ma.account_id)
        if acc:
            nodes.append({"type": "account", "id": acc.id, "label": acc.name or acc.provider, "provider": acc.provider})
            add_edge("member", ma.member_id, "account", acc.id, "帳號")

    # ── 帳號去重（可能重複加入）──
    seen_account_ids: set[int] = set()
    unique_nodes = []
    for n in nodes:
        if n["type"] == "account":
            if n["id"] in seen_account_ids:
                continue
            seen_account_ids.add(n["id"])
        unique_nodes.append(n)
    nodes = unique_nodes

    # ── 網域 ──
    domains = session.exec(select(Domain).where(Domain.is_active == True)).all()
    for d in domains:
        nodes.append({"type": "domain", "id": d.id, "label": d.hostname})

    # ── 空間 ──
    rooms = session.exec(select(Room)).all()
    for r in rooms:
        nodes.append({"type": "room", "id": r.id, "label": r.name})

    # ── 專案 → 空間（透過 Project.room_id）──
    all_projects = session.exec(select(Project).where(Project.is_active == True)).all()
    for p in all_projects:
        if p.room_id:
            add_edge("project", p.id, "room", p.room_id, "所屬空間")

    # ── 空間 ↔ 成員 ──
    room_members = session.exec(select(RoomMember)).all()
    for rm in room_members:
        add_edge("room", rm.room_id, "member", rm.member_id, "成員")

    # ── 用戶（以 Person 為單位，同一人只出現一次）──
    persons = session.exec(select(Person)).all()
    for p in persons:
        extra = json_module.loads(p.extra_json) if p.extra_json else {}
        has_ad = bool(extra.get("ad_user") and extra.get("ad_pass"))
        # 找此 Person 的所有平台帳號
        bus = session.exec(select(BotUser).where(BotUser.person_id == p.id, BotUser.is_active == True)).all()
        platforms = [bu.platform for bu in bus]
        nodes.append({
            "type": "user", "id": p.id,
            "label": p.display_name or (bus[0].username if bus else f"Person#{p.id}"),
            "platforms": platforms, "level": p.level, "has_ad": has_ad,
        })

        # 用戶 ↔ 專案（PersonProject）
        pps = session.exec(select(PersonProject).where(PersonProject.person_id == p.id)).all()
        for pp in pps:
            add_edge("user", p.id, "project", pp.project_id, "專案")

        # 用戶 ↔ 成員（PersonMember）
        pms = session.exec(select(PersonMember).where(PersonMember.person_id == p.id)).all()
        for pm in pms:
            rel = "對話（預設）" if pm.is_default else "可切換"
            add_edge("user", p.id, "member", pm.member_id, rel)

    # ── 排程（專案 → 成員，跨專案關聯）──
    cron_jobs = session.exec(select(CronJob).where(CronJob.is_enabled == True, CronJob.target_list_id.is_not(None))).all()
    for cj in cron_jobs:
        # 排程的 target_list → 找到執行成員
        target_list = session.get(StageList, cj.target_list_id)
        if target_list and target_list.member_id:
            # 排程所屬專案 → 執行成員（如果跨專案才有意義）
            if target_list.project_id != cj.project_id:
                add_edge("project", cj.project_id, "member", target_list.member_id, "排程")
            else:
                # 同專案內的排程也加上，讓關聯更完整
                add_edge("project", cj.project_id, "member", target_list.member_id, "排程")

    return {"nodes": nodes, "edges": edges}
