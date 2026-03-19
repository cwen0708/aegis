"""關聯圖 API — 以任意節點為中心，遞迴展開實體關係"""
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
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


def _expand_node(
    node_type: str, node_id: int, session: Session,
    nodes: dict, edges: list, visited: set, depth: int, max_depth: int,
):
    """遞迴展開一個節點的關聯"""
    key = f"{node_type}:{node_id}"
    if key in visited or depth > max_depth:
        return
    visited.add(key)

    def add(n: dict):
        k = f"{n['type']}:{n['id']}"
        nodes[k] = n
        return k

    def link(st: str, si: int, tt: str, ti: int, rel: str):
        edges.append(_edge(st, si, tt, ti, rel))
        # 遞迴展開子節點
        if depth < max_depth:
            _expand_node(tt, ti, session, nodes, edges, visited, depth + 1, max_depth)

    if node_type == "project":
        project = session.get(Project, node_id)
        if not project:
            return
        add(_node("project", project.id, project.name, is_system=project.is_system))

        # → 成員
        lists = session.exec(select(StageList).where(
            StageList.project_id == project.id, StageList.member_id.is_not(None)
        )).all()
        seen_members: set[int] = set()
        for sl in lists:
            if sl.member_id and sl.member_id not in seen_members:
                seen_members.add(sl.member_id)
                m = session.get(Member, sl.member_id)
                if m:
                    add(_node("member", m.id, m.name, slug=m.slug))
                    link("project", project.id, "member", m.id, "成員")

        # → 空間
        rps = session.exec(select(RoomProject).where(RoomProject.project_id == project.id)).all()
        for rp in rps:
            room = session.get(Room, rp.room_id)
            if room:
                add(_node("room", room.id, room.name))
                link("project", project.id, "room", room.id, "空間")

        # → 用戶
        bups = session.exec(select(BotUserProject).where(BotUserProject.project_id == project.id)).all()
        for bup in bups:
            bu = session.get(BotUser, bup.bot_user_id)
            if bu:
                add(_node("user", bu.id, bu.username or bu.platform_user_id, platform=bu.platform, level=bu.level))
                link("project", project.id, "user", bu.id, "用戶")

    elif node_type == "member":
        member = session.get(Member, node_id)
        if not member:
            return
        add(_node("member", member.id, member.name, slug=member.slug))

        # → 專案
        lists = session.exec(select(StageList).where(StageList.member_id == member.id)).all()
        seen_projects: set[int] = set()
        for sl in lists:
            if sl.project_id not in seen_projects:
                seen_projects.add(sl.project_id)
                p = session.get(Project, sl.project_id)
                if p:
                    add(_node("project", p.id, p.name))
                    link("member", member.id, "project", p.id, "專案")

        # → 帳號
        bindings = session.exec(select(MemberAccount).where(MemberAccount.member_id == member.id)).all()
        for b in bindings:
            acc = session.get(Account, b.account_id)
            if acc:
                add(_node("account", acc.id, acc.name or acc.provider, provider=acc.provider))
                edges.append(_edge("member", member.id, "account", acc.id, "帳號"))
                nodes[f"account:{acc.id}"] = _node("account", acc.id, acc.name or acc.provider, provider=acc.provider)
                # 帳號是末端，不再遞迴

        # → 空間
        rms = session.exec(select(RoomMember).where(RoomMember.member_id == member.id)).all()
        for rm in rms:
            room = session.get(Room, rm.room_id)
            if room:
                add(_node("room", room.id, room.name))
                link("member", member.id, "room", room.id, "空間")

        # → 用戶
        bus = session.exec(select(BotUser).where(BotUser.default_member_id == member.id)).all()
        for bu in bus:
            extra_json = json_module.loads(bu.extra_json) if bu.extra_json else {}
            has_ad = bool(extra_json.get("ad_user") and extra_json.get("ad_pass"))
            add(_node("user", bu.id, bu.username or bu.platform_user_id, platform=bu.platform, level=bu.level, has_ad=has_ad))
            edges.append(_edge("member", member.id, "user", bu.id, "用戶"))
            nodes[f"user:{bu.id}"] = _node("user", bu.id, bu.username or bu.platform_user_id, platform=bu.platform, level=bu.level, has_ad=has_ad)

    elif node_type == "user":
        bu = session.get(BotUser, node_id)
        if not bu:
            return
        extra_json = json_module.loads(bu.extra_json) if bu.extra_json else {}
        has_ad = bool(extra_json.get("ad_user") and extra_json.get("ad_pass"))
        add(_node("user", bu.id, bu.username or bu.platform_user_id,
                   platform=bu.platform, level=bu.level, has_ad=has_ad))

        # → 專案
        bups = session.exec(select(BotUserProject).where(BotUserProject.bot_user_id == bu.id)).all()
        for bup in bups:
            p = session.get(Project, bup.project_id)
            if p:
                add(_node("project", p.id, p.name))
                link("user", bu.id, "project", p.id, "專案")

        # → 對話成員
        if bu.default_member_id:
            m = session.get(Member, bu.default_member_id)
            if m:
                add(_node("member", m.id, m.name, slug=m.slug))
                link("user", bu.id, "member", m.id, "對話對象")

    elif node_type == "domain":
        domain = session.get(Domain, node_id)
        if not domain:
            return
        add(_node("domain", domain.id, domain.hostname))

        room_ids = json_module.loads(domain.room_ids_json or "[]")
        for rid in room_ids:
            room = session.get(Room, rid)
            if room:
                add(_node("room", room.id, room.name))
                link("domain", domain.id, "room", room.id, "空間")

    elif node_type == "room":
        room = session.get(Room, node_id)
        if not room:
            return
        add(_node("room", room.id, room.name))

        # → 網域
        domains = session.exec(select(Domain).where(Domain.is_active == True)).all()
        for d in domains:
            rids = json_module.loads(d.room_ids_json or "[]")
            if room.id in rids:
                add(_node("domain", d.id, d.hostname))
                link("room", room.id, "domain", d.id, "網域")

        # → 專案
        rps = session.exec(select(RoomProject).where(RoomProject.room_id == room.id)).all()
        for rp in rps:
            p = session.get(Project, rp.project_id)
            if p:
                add(_node("project", p.id, p.name))
                link("room", room.id, "project", p.id, "專案")

        # → 成員
        rms = session.exec(select(RoomMember).where(RoomMember.room_id == room.id)).all()
        for rm in rms:
            m = session.get(Member, rm.member_id)
            if m:
                add(_node("member", m.id, m.name, slug=m.slug))
                link("room", room.id, "member", m.id, "成員")


@router.get("/graph/relations")
def get_relations(
    center_type: str = Query(..., description="domain|room|project|member|user"),
    center_id: int = Query(...),
    depth: int = Query(2, ge=1, le=4, description="展開深度（1-4）"),
    session: Session = Depends(get_session),
):
    """以指定節點為中心，遞迴展開關聯"""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    visited: set[str] = set()

    _expand_node(center_type, center_id, session, nodes, edges, visited, 0, depth)

    # 去重邊
    seen_edges: set[str] = set()
    unique_edges = []
    for e in edges:
        ek = f"{e['source']}-{e['target']}"
        if ek not in seen_edges:
            seen_edges.add(ek)
            unique_edges.append(e)

    return {
        "center": f"{center_type}:{center_id}",
        "nodes": list(nodes.values()),
        "edges": unique_edges,
    }


@router.get("/graph/entities")
def list_entities(session: Session = Depends(get_session)):
    """列出所有可選的實體"""
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
