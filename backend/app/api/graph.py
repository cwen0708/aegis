"""關聯圖 API — 以任意節點為中心展開實體關係"""
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from typing import Optional
from app.database import get_session
from app.models.core import (
    Project, Member, MemberAccount, Account,
    Domain, Room, RoomProject, RoomMember,
    BotUser, BotUserProject, StageList, CronJob,
)
import json as json_module

router = APIRouter()


def _node(type: str, id: int, label: str, **extra) -> dict:
    return {"type": type, "id": id, "label": label, **extra}


def _edge(source_type: str, source_id: int, target_type: str, target_id: int, relation: str = "") -> dict:
    return {
        "source": f"{source_type}:{source_id}",
        "target": f"{target_type}:{target_id}",
        "relation": relation,
    }


@router.get("/graph/relations")
def get_relations(
    center_type: str = Query(..., description="domain|room|project|member|user"),
    center_id: int = Query(...),
    session: Session = Depends(get_session),
):
    """以指定節點為中心，回傳一層關聯的 nodes 和 edges"""
    nodes: dict[str, dict] = {}  # key = "type:id"
    edges: list[dict] = []

    def add_node(n: dict):
        key = f"{n['type']}:{n['id']}"
        nodes[key] = n

    def add_edge(e: dict):
        edges.append(e)

    if center_type == "project":
        project = session.get(Project, center_id)
        if not project:
            return {"nodes": [], "edges": []}
        add_node(_node("project", project.id, project.name, is_system=project.is_system))

        # → 成員（透過 StageList）
        lists = session.exec(select(StageList).where(
            StageList.project_id == project.id, StageList.member_id.is_not(None)
        )).all()
        member_ids = set()
        for sl in lists:
            if sl.member_id and sl.member_id not in member_ids:
                member_ids.add(sl.member_id)
                m = session.get(Member, sl.member_id)
                if m:
                    add_node(_node("member", m.id, m.name, slug=m.slug))
                    add_edge(_edge("project", project.id, "member", m.id, "成員"))

        # → 空間（透過 RoomProject）
        rps = session.exec(select(RoomProject).where(RoomProject.project_id == project.id)).all()
        for rp in rps:
            room = session.get(Room, rp.room_id)
            if room:
                add_node(_node("room", room.id, room.name))
                add_edge(_edge("project", project.id, "room", room.id, "空間"))

        # → 用戶（透過 BotUserProject）
        bups = session.exec(select(BotUserProject).where(BotUserProject.project_id == project.id)).all()
        for bup in bups:
            bu = session.get(BotUser, bup.bot_user_id)
            if bu:
                add_node(_node("user", bu.id, bu.username or bu.platform_user_id, platform=bu.platform, level=bu.level))
                add_edge(_edge("project", project.id, "user", bu.id, "用戶"))

        # → 排程數量
        cron_count = session.exec(
            select(CronJob).where(CronJob.project_id == project.id, CronJob.is_enabled == True)
        ).all()
        if cron_count:
            add_node(_node("info", -1, f"{len(cron_count)} 個排程", icon="clock"))
            add_edge(_edge("project", project.id, "info", -1, "排程"))

    elif center_type == "member":
        member = session.get(Member, center_id)
        if not member:
            return {"nodes": [], "edges": []}
        add_node(_node("member", member.id, member.name, slug=member.slug))

        # → 專案
        lists = session.exec(select(StageList).where(StageList.member_id == member.id)).all()
        project_ids = set()
        for sl in lists:
            if sl.project_id not in project_ids:
                project_ids.add(sl.project_id)
                p = session.get(Project, sl.project_id)
                if p:
                    add_node(_node("project", p.id, p.name))
                    add_edge(_edge("member", member.id, "project", p.id, "專案"))

        # → 帳號
        bindings = session.exec(select(MemberAccount).where(MemberAccount.member_id == member.id)).all()
        for b in bindings:
            acc = session.get(Account, b.account_id)
            if acc:
                add_node(_node("account", acc.id, acc.name or acc.provider, provider=acc.provider))
                add_edge(_edge("member", member.id, "account", acc.id, "帳號"))

        # → 空間
        rms = session.exec(select(RoomMember).where(RoomMember.member_id == member.id)).all()
        for rm in rms:
            room = session.get(Room, rm.room_id)
            if room:
                add_node(_node("room", room.id, room.name))
                add_edge(_edge("member", member.id, "room", room.id, "空間"))

        # → 用戶（透過 BotUser.default_member_id 或 BotUserProject 交叉）
        bus = session.exec(select(BotUser).where(BotUser.default_member_id == member.id)).all()
        for bu in bus:
            add_node(_node("user", bu.id, bu.username or bu.platform_user_id, platform=bu.platform))
            add_edge(_edge("member", member.id, "user", bu.id, "用戶"))

    elif center_type == "user":
        bu = session.get(BotUser, center_id)
        if not bu:
            return {"nodes": [], "edges": []}
        extra_json = json_module.loads(bu.extra_json) if bu.extra_json else {}
        has_ad = bool(extra_json.get("ad_user") and extra_json.get("ad_pass"))
        add_node(_node("user", bu.id, bu.username or bu.platform_user_id,
                        platform=bu.platform, level=bu.level, has_ad=has_ad))

        # → 專案
        bups = session.exec(select(BotUserProject).where(BotUserProject.bot_user_id == bu.id)).all()
        for bup in bups:
            p = session.get(Project, bup.project_id)
            if p:
                add_node(_node("project", p.id, p.name))
                add_edge(_edge("user", bu.id, "project", p.id, "專案"))

        # → 對話成員
        if bu.default_member_id:
            m = session.get(Member, bu.default_member_id)
            if m:
                add_node(_node("member", m.id, m.name, slug=m.slug))
                add_edge(_edge("user", bu.id, "member", m.id, "對話對象"))

        # → AD 狀態
        if has_ad:
            add_node(_node("info", -2, f"AD: {extra_json.get('ad_user', '')}", icon="key"))
            add_edge(_edge("user", bu.id, "info", -2, "NAS 帳號"))

    elif center_type == "domain":
        domain = session.get(Domain, center_id)
        if not domain:
            return {"nodes": [], "edges": []}
        add_node(_node("domain", domain.id, domain.hostname))

        # → 空間
        room_ids = json_module.loads(domain.room_ids_json or "[]")
        for rid in room_ids:
            room = session.get(Room, rid)
            if room:
                add_node(_node("room", room.id, room.name))
                add_edge(_edge("domain", domain.id, "room", room.id, "空間"))

                # 空間 → 專案
                rps = session.exec(select(RoomProject).where(RoomProject.room_id == room.id)).all()
                for rp in rps:
                    p = session.get(Project, rp.project_id)
                    if p:
                        add_node(_node("project", p.id, p.name))
                        add_edge(_edge("room", room.id, "project", p.id, "專案"))

                # 空間 → 成員
                rms = session.exec(select(RoomMember).where(RoomMember.room_id == room.id)).all()
                for rm in rms:
                    m = session.get(Member, rm.member_id)
                    if m:
                        add_node(_node("member", m.id, m.name, slug=m.slug))
                        add_edge(_edge("room", room.id, "member", m.id, "成員"))

    elif center_type == "room":
        room = session.get(Room, center_id)
        if not room:
            return {"nodes": [], "edges": []}
        add_node(_node("room", room.id, room.name))

        # → 網域
        domains = session.exec(select(Domain).where(Domain.is_active == True)).all()
        for d in domains:
            rids = json_module.loads(d.room_ids_json or "[]")
            if room.id in rids:
                add_node(_node("domain", d.id, d.hostname))
                add_edge(_edge("room", room.id, "domain", d.id, "網域"))

        # → 專案
        rps = session.exec(select(RoomProject).where(RoomProject.room_id == room.id)).all()
        for rp in rps:
            p = session.get(Project, rp.project_id)
            if p:
                add_node(_node("project", p.id, p.name))
                add_edge(_edge("room", room.id, "project", p.id, "專案"))

        # → 成員
        rms = session.exec(select(RoomMember).where(RoomMember.room_id == room.id)).all()
        for rm in rms:
            m = session.get(Member, rm.member_id)
            if m:
                add_node(_node("member", m.id, m.name, slug=m.slug))
                add_edge(_edge("room", room.id, "member", m.id, "成員"))

    return {
        "center": f"{center_type}:{center_id}",
        "nodes": list(nodes.values()),
        "edges": edges,
    }


@router.get("/graph/entities")
def list_entities(session: Session = Depends(get_session)):
    """列出所有可選的實體（供下拉選單用）"""
    projects = session.exec(select(Project).where(Project.is_active == True)).all()
    members = session.exec(select(Member)).all()
    domains = session.exec(select(Domain).where(Domain.is_active == True)).all()
    rooms = session.exec(select(Room)).all()
    users = session.exec(select(BotUser).where(BotUser.is_active == True)).all()

    return {
        "project": [{"id": p.id, "label": p.name} for p in projects],
        "member": [{"id": m.id, "label": m.name} for m in members],
        "domain": [{"id": d.id, "label": d.hostname} for d in domains],
        "room": [{"id": r.id, "label": r.name} for r in rooms],
        "user": [{"id": u.id, "label": u.username or u.platform_user_id} for u in users],
    }
