#!/usr/bin/env python3
"""遷移腳本：將 classic Room 的 layout_json 轉換為 Tiled 格式。

用法：
    python scripts/migrate_room_layout.py                     # 遷移全部 classic 房間
    python scripts/migrate_room_layout.py --dry-run            # 只印報告不寫 DB
    python scripts/migrate_room_layout.py --room-id 1          # 只遷移指定房間
    python scripts/migrate_room_layout.py --rollback           # 從備份還原
    python scripts/migrate_room_layout.py --rollback --room-id 1
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from dataclasses import dataclass, field

# 確保 backend/ 在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402
from app.database import engine  # noqa: E402
from app.models.core import Room  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── 備份目錄 ─────────────────────────────────────────────────────
BACKUP_DIR = Path(__file__).resolve().parent.parent / "room_backups"

# ── Classic GroundType → Tiled FloorAndGround GID ────────────────
# FloorAndGround tileset: firstgid=1, 64 columns, 2048×1280 atlas
# 0 = empty（無 tile），其餘為 atlas 中最具代表性的地板 GID
GROUND_TYPE_TO_GID: dict[int, int] = {
    0: 0,      # VOID → empty
    1: 0,      # WALL → empty（牆用 Wall object layer 處理）
    2: 412,    # FLOOR → 標準辦公室地板
    3: 348,    # WOOD → 木地板
    4: 92,     # DARK → 深色地板
    5: 154,    # MARBLE → 大理石
    6: 217,    # STONE → 石磚
    7: 415,    # BEIGE → 米色地板
    8: 351,    # BAMBOO → 竹地板風格
    9: 152,    # CHECKER → 格子磚
    10: 786,   # CARPET → 地毯
    11: 594,   # RED → 紅磚
    12: 546,   # LAVENDER → 薰衣草
    13: 0,     # WALL_MARBLE → empty（牆）
    14: 0,     # WALL_GRAY → empty（牆）
    15: 0,     # WALL_BRICK → empty（牆）
    16: 0,     # WALL_PINK → empty（牆）
}

# ── Classic slot direction → Chair GID ───────────────────────────
# Chair tileset firstgid = 2561
DIR_TO_CHAIR_GID: dict[str, int] = {
    "down": 2562,
    "up": 2566,
    "left": 2573,
    "right": 2574,
}

# ── Classic 家具類型 → Tiled object GID 映射 ─────────────────────
# Modern_Office_Black_Shadow tileset: firstgid=2584
# 無法精確映射的家具類型記錄在報告中
FURNITURE_TYPE_TO_GID: dict[str, tuple[int, int, int, str]] = {
    # type: (gid, width, height, target_layer)
    "desk":       (2596, 32, 32, "Objects"),
    "desk_gray":  (2596, 32, 32, "Objects"),
    "desk_r":     (2596, 32, 32, "Objects"),
    "chair":      (2562, 32, 64, "Chair"),
    "chair_exec": (2568, 32, 64, "Chair"),
    "cabinet":    (2782, 32, 32, "ObjectsOnCollide"),
    "plant":      (3067, 32, 32, "GenericObjects"),
    "sofa":       (2836, 32, 32, "Objects"),
    "server":     (2798, 32, 32, "ObjectsOnCollide"),
    "copier":     (3003, 32, 32, "ObjectsOnCollide"),
    "monitor":    (4680, 96, 64, "Computer"),
    "laptop":     (4680, 96, 64, "Computer"),
    "phone":      (2702, 32, 32, "Objects"),
}

# ── Tiled 預設 tileset 定義（從 map.json 萃取）────────────────────
DEFAULT_TILESETS = [
    {"columns": 64, "firstgid": 1, "image": "FloorAndGround.png",
     "imageheight": 1280, "imagewidth": 2048, "margin": 0,
     "name": "FloorAndGround", "spacing": 0,
     "tilecount": 2560, "tileheight": 32, "tilewidth": 32},
    {"columns": 1, "firstgid": 2561, "image": "items/chair.png",
     "imageheight": 1472, "imagewidth": 32, "margin": 0,
     "name": "chair", "spacing": 0,
     "tilecount": 23, "tileheight": 64, "tilewidth": 32},
    {"columns": 16, "firstgid": 2584, "image": "tileset/Modern_Office_Black_Shadow.png",
     "imageheight": 1696, "imagewidth": 512, "margin": 0,
     "name": "Modern_Office_Black_Shadow", "spacing": 0,
     "tilecount": 848, "tileheight": 32, "tilewidth": 32},
    {"columns": 16, "firstgid": 3432, "image": "tileset/Generic.png",
     "imageheight": 2496, "imagewidth": 512, "margin": 0,
     "name": "Generic", "spacing": 0,
     "tilecount": 1248, "tileheight": 32, "tilewidth": 32},
    {"columns": 1, "firstgid": 4680, "image": "items/computer.png",
     "imageheight": 320, "imagewidth": 96, "margin": 0,
     "name": "computer", "spacing": 0,
     "tilecount": 5, "tileheight": 64, "tilewidth": 96},
    {"columns": 1, "firstgid": 4685, "image": "items/whiteboard.png",
     "imageheight": 192, "imagewidth": 64, "margin": 0,
     "name": "whiteboard", "spacing": 0,
     "tilecount": 3, "tileheight": 64, "tilewidth": 64},
    {"columns": 16, "firstgid": 4688, "image": "tileset/Basement.png",
     "imageheight": 1600, "imagewidth": 512, "margin": 0,
     "name": "Basement", "spacing": 0,
     "tilecount": 800, "tileheight": 32, "tilewidth": 32},
    {"columns": 1, "firstgid": 5488, "image": "items/vendingmachine.png",
     "imageheight": 72, "imagewidth": 48, "margin": 0,
     "name": "vendingmachine", "spacing": 0,
     "tilecount": 1, "tileheight": 72, "tilewidth": 48},
]

# Tiled object layer 順序（與 mapSerializer.ts OBJECT_LAYER_ORDER 一致）
OBJECT_LAYER_ORDER = [
    "Wall", "Chair", "Objects", "ObjectsOnCollide",
    "GenericObjects", "GenericObjectsOnCollide",
    "Computer", "Whiteboard", "Basement", "VendingMachine",
]

TILE_SIZE = 32


# ── 轉換報告 ─────────────────────────────────────────────────────
@dataclass
class ConversionReport:
    room_id: int
    room_name: str
    cols: int = 0
    rows: int = 0
    slot_count: int = 0
    furniture_mapped: int = 0
    furniture_skipped: list[str] = field(default_factory=list)
    props_mapped: int = 0
    props_skipped: list[str] = field(default_factory=list)
    wall_cells: int = 0
    floor_cells: int = 0

    def summary(self) -> str:
        lines = [
            f"  Room #{self.room_id} 「{self.room_name}」 ({self.cols}×{self.rows})",
            f"    地板格數: {self.floor_cells}, 牆壁格數: {self.wall_cells}",
            f"    座位(slots): {self.slot_count}",
            f"    家具: 映射 {self.furniture_mapped}, 跳過 {len(self.furniture_skipped)}",
            f"    道具: 映射 {self.props_mapped}, 跳過 {len(self.props_skipped)}",
        ]
        for item in self.furniture_skipped:
            lines.append(f"      ⚠ 跳過家具: {item}")
        for item in self.props_skipped:
            lines.append(f"      ⚠ 跳過道具: {item}")
        return "\n".join(lines)


# ── 轉換邏輯 ─────────────────────────────────────────────────────

def convert_ground(classic: dict, report: ConversionReport) -> list[int]:
    """將 classic ground[] 映射為 Tiled Ground layer data[]。"""
    cols = classic.get("cols", 0)
    rows = classic.get("rows", 0)
    ground = classic.get("ground", [])
    report.cols = cols
    report.rows = rows

    data: list[int] = []
    for i in range(cols * rows):
        gt = ground[i] if i < len(ground) else 0
        gid = GROUND_TYPE_TO_GID.get(gt, 0)
        if gid > 0:
            report.floor_cells += 1
        if gt >= 1 and gt <= 16 and gt != 2 and gid == 0:
            report.wall_cells += 1
        data.append(gid)
    return data


def convert_slots(classic: dict, report: ConversionReport) -> list[dict]:
    """將 classic slots/workstations 轉換為 Chair layer 的 TiledObject[]。"""
    slots = classic.get("slots", [])
    workstations = classic.get("workstations", [])
    furniture = classic.get("furniture", [])

    objects: list[dict] = []
    obj_id = 1

    # 優先使用 slots（新格式）
    if slots:
        for slot in slots:
            col = slot.get("col", 0)
            row = slot.get("row", 0)
            direction = slot.get("dir", "down")
            gid = DIR_TO_CHAIR_GID.get(direction, 2562)
            objects.append({
                "id": obj_id,
                "gid": gid,
                "x": col * TILE_SIZE,
                "y": (row + 1) * TILE_SIZE + TILE_SIZE,  # 底邊 = (row+2)*32（椅子高度 64px）
                "width": 32,
                "height": 64,
                "rotation": 0,
                "visible": True,
            })
            obj_id += 1
        report.slot_count = len(slots)
    elif workstations:
        # 從 workstations 找椅子位置
        furniture_map = {f["id"]: f for f in furniture}
        for ws in workstations:
            chair_id = ws.get("chairId", "")
            chair = furniture_map.get(chair_id)
            if not chair:
                continue
            col = chair.get("col", 0)
            row = chair.get("row", 0)
            objects.append({
                "id": obj_id,
                "gid": 2562,  # 預設朝下
                "x": col * TILE_SIZE,
                "y": (row + 1) * TILE_SIZE + TILE_SIZE,
                "width": 32,
                "height": 64,
                "rotation": 0,
                "visible": True,
            })
            obj_id += 1
        report.slot_count = len(objects)

    return objects


def convert_furniture_and_props(
    classic: dict, report: ConversionReport, start_obj_id: int,
) -> dict[str, list[dict]]:
    """將 classic furniture/props 轉換為各 object layer 的物件。

    回傳: {layer_name: [TiledObject, ...]}
    """
    layers: dict[str, list[dict]] = {}
    obj_id = start_obj_id
    furniture = classic.get("furniture", [])
    props = classic.get("props", [])

    # 已經由 convert_slots 處理的椅子 ID
    slot_chair_ids: set[str] = set()
    for ws in classic.get("workstations", []):
        slot_chair_ids.add(ws.get("chairId", ""))

    # 轉換家具
    for item in furniture:
        item_type = item.get("type", "")
        item_id = item.get("id", "")
        col = item.get("col", 0)
        row = item.get("row", 0)

        # 跳過已在 slots/workstations 處理的椅子
        if item_id in slot_chair_ids:
            continue

        mapping = FURNITURE_TYPE_TO_GID.get(item_type)
        if not mapping:
            report.furniture_skipped.append(f"{item_id} ({item_type}) at ({col},{row})")
            continue

        gid, w, h, layer_name = mapping
        # Tiled 物件座標：x = 左上角 px, y = 底邊 px
        obj = {
            "id": obj_id,
            "gid": gid,
            "x": col * TILE_SIZE,
            "y": row * TILE_SIZE + h,
            "width": w,
            "height": h,
            "rotation": 0,
            "visible": True,
        }
        layers.setdefault(layer_name, []).append(obj)
        obj_id += 1
        report.furniture_mapped += 1

    # 轉換道具
    for item in props:
        item_type = item.get("type", "")
        item_id = item.get("id", "")
        col = item.get("col", 0)
        row = item.get("row", 0)

        mapping = FURNITURE_TYPE_TO_GID.get(item_type)
        if not mapping:
            report.props_skipped.append(f"{item_id} ({item_type}) at ({col},{row})")
            continue

        gid, w, h, layer_name = mapping
        obj = {
            "id": obj_id,
            "gid": gid,
            "x": col * TILE_SIZE,
            "y": row * TILE_SIZE + h,
            "width": w,
            "height": h,
            "rotation": 0,
            "visible": True,
        }
        layers.setdefault(layer_name, []).append(obj)
        obj_id += 1
        report.props_mapped += 1

    return layers


def classic_to_tiled(classic: dict, report: ConversionReport) -> dict:
    """將完整的 classic OfficeLayout 轉換為 TiledMapJson。"""
    cols = classic.get("cols", 32)
    rows = classic.get("rows", 22)

    # 1. Ground layer
    ground_data = convert_ground(classic, report)

    # 2. Chair objects（from slots）
    chair_objects = convert_slots(classic, report)

    # 3. Furniture & props objects
    start_id = len(chair_objects) + 1
    object_layers = convert_furniture_and_props(classic, report, start_id)

    # 計算最大 object id
    max_obj_id = 0
    for obj in chair_objects:
        max_obj_id = max(max_obj_id, obj["id"])
    for objs in object_layers.values():
        for obj in objs:
            max_obj_id = max(max_obj_id, obj["id"])

    # 組裝 layers
    layer_id = 1
    layers: list[dict] = []

    # Ground tile layer
    layers.append({
        "id": layer_id,
        "name": "Ground",
        "type": "tilelayer",
        "data": ground_data,
        "width": cols,
        "height": rows,
        "x": 0,
        "y": 0,
        "opacity": 1,
        "visible": True,
    })
    layer_id += 1

    # Object layers（按標準順序）
    for name in OBJECT_LAYER_ORDER:
        if name == "Chair":
            objs = chair_objects
        else:
            objs = object_layers.get(name, [])

        layers.append({
            "id": layer_id,
            "name": name,
            "type": "objectgroup",
            "objects": objs,
            "x": 0,
            "y": 0,
            "opacity": 1,
            "visible": True,
            "draworder": "topdown",
        })
        layer_id += 1

    # 組裝完整 TiledMapJson
    return {
        "compressionlevel": -1,
        "height": rows,
        "width": cols,
        "tileheight": 32,
        "tilewidth": 32,
        "type": "map",
        "version": "1.6",
        "tiledversion": "1.7.0",
        "orientation": "orthogonal",
        "renderorder": "right-down",
        "infinite": False,
        "nextlayerid": layer_id,
        "nextobjectid": max_obj_id + 1,
        "layers": layers,
        "tilesets": DEFAULT_TILESETS,
    }


# ── 備份 / 還原 ──────────────────────────────────────────────────

def backup_room(room: Room) -> Path:
    """將房間的 layout_json 備份到檔案。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"room_backup_{room.id}.json"
    backup_data = {
        "room_id": room.id,
        "room_name": room.name,
        "layout_type": room.layout_type,
        "layout_json": room.layout_json,
    }
    backup_path.write_text(json.dumps(backup_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_path


def rollback_room(session: Session, room_id: int) -> bool:
    """從備份檔案還原房間的 layout_json。"""
    backup_path = BACKUP_DIR / f"room_backup_{room_id}.json"
    if not backup_path.exists():
        logger.error(f"找不到備份檔案: {backup_path}")
        return False

    backup_data = json.loads(backup_path.read_text(encoding="utf-8"))
    room = session.get(Room, room_id)
    if not room:
        logger.error(f"找不到 Room #{room_id}")
        return False

    room.layout_json = backup_data["layout_json"]
    room.layout_type = backup_data["layout_type"]
    session.add(room)
    logger.info(f"✓ Room #{room_id} 已從備份還原為 layout_type='{backup_data['layout_type']}'")
    return True


# ── 主流程 ────────────────────────────────────────────────────────

def migrate(dry_run: bool, room_id: int | None) -> None:
    """執行遷移：查詢 classic 房間 → 轉換 → 寫入 DB。"""
    with Session(engine) as session:
        stmt = select(Room).where(Room.layout_type == "classic")
        if room_id is not None:
            stmt = stmt.where(Room.id == room_id)
        rooms = list(session.exec(stmt))

        if not rooms:
            logger.info("沒有找到需要遷移的 classic 房間。")
            return

        logger.info(f"找到 {len(rooms)} 個 classic 房間待遷移")
        reports: list[ConversionReport] = []

        for room in rooms:
            report = ConversionReport(room_id=room.id, room_name=room.name)

            # 解析 classic layout
            try:
                classic = json.loads(room.layout_json) if room.layout_json else {}
            except json.JSONDecodeError:
                logger.warning(f"Room #{room.id} layout_json 無法解析，跳過")
                continue

            if not classic.get("cols") or not classic.get("ground"):
                logger.warning(f"Room #{room.id} layout 缺少 cols/ground，跳過")
                continue

            # 轉換
            tiled = classic_to_tiled(classic, report)
            reports.append(report)

            if dry_run:
                logger.info(f"[DRY-RUN] Room #{room.id} 轉換完成（不寫入）")
                continue

            # 備份
            backup_path = backup_room(room)
            logger.info(f"備份 Room #{room.id} → {backup_path}")

            # 寫入 DB
            room.layout_json = json.dumps(tiled, ensure_ascii=False)
            room.layout_type = "tiled"
            session.add(room)

        if not dry_run:
            session.commit()
            logger.info("所有房間已遷移完成並寫入 DB")

        # 印出報告
        print("\n" + "=" * 60)
        print("  遷移報告" + ("（DRY-RUN 模式）" if dry_run else ""))
        print("=" * 60)
        for r in reports:
            print(r.summary())
        print("=" * 60)
        print(f"  共 {len(reports)} 個房間" + ("（未寫入 DB）" if dry_run else "（已寫入 DB）"))
        print("=" * 60 + "\n")


def rollback(room_id: int | None) -> None:
    """從備份還原房間。"""
    with Session(engine) as session:
        if room_id is not None:
            rollback_room(session, room_id)
        else:
            if not BACKUP_DIR.exists():
                logger.error(f"備份目錄不存在: {BACKUP_DIR}")
                return
            backup_files = sorted(BACKUP_DIR.glob("room_backup_*.json"))
            if not backup_files:
                logger.error("找不到任何備份檔案")
                return
            for bf in backup_files:
                data = json.loads(bf.read_text(encoding="utf-8"))
                rollback_room(session, data["room_id"])
        session.commit()
        logger.info("回滾完成")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="將 classic Room layout 遷移為 Tiled 格式",
    )
    parser.add_argument("--dry-run", action="store_true", help="只顯示報告，不寫入 DB")
    parser.add_argument("--room-id", type=int, default=None, help="只遷移指定房間 ID")
    parser.add_argument("--rollback", action="store_true", help="從備份還原房間")
    args = parser.parse_args()

    if args.rollback:
        rollback(args.room_id)
    else:
        migrate(args.dry_run, args.room_id)


if __name__ == "__main__":
    main()
