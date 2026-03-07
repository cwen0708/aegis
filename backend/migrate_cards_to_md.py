"""Migrate existing Card ORM records to MD files + CardIndex."""
import sys
from pathlib import Path
from sqlmodel import Session, select
from app.database import engine, init_db
from app.models.core import Project, StageList, Card, Tag, CardTagLink, CardIndex
from app.core.card_file import CardData, write_card, card_file_path
from app.core.card_index import sync_card_to_index


def migrate():
    init_db()

    with Session(engine) as session:
        projects = session.exec(select(Project)).all()
        if not projects:
            print("No projects found. Nothing to migrate.")
            return

        total_cards = 0
        total_skipped = 0

        for project in projects:
            print(f"\nProject: {project.name} (path: {project.path})")

            # Ensure .aegis/cards/ directory exists
            cards_dir = Path(project.path) / ".aegis" / "cards"
            cards_dir.mkdir(parents=True, exist_ok=True)

            # Get all cards for this project via StageList
            lists = session.exec(
                select(StageList).where(StageList.project_id == project.id)
            ).all()
            list_ids = [l.id for l in lists]

            if not list_ids:
                print("  No stage lists found, skipping.")
                continue

            cards = session.exec(
                select(Card).where(Card.list_id.in_(list_ids))
            ).all()

            for card in cards:
                # Check if MD file already exists
                fpath = card_file_path(project.path, card.id)
                if fpath.exists():
                    print(f"  [SKIP] Card {card.id}: {card.title} (MD file already exists)")
                    total_skipped += 1
                    continue

                # Get tags for this card
                tag_links = session.exec(
                    select(CardTagLink).where(CardTagLink.card_id == card.id)
                ).all()
                tag_ids = [tl.tag_id for tl in tag_links]
                tags = []
                for tid in tag_ids:
                    tag = session.get(Tag, tid)
                    if tag:
                        tags.append(tag.name)

                # Create CardData
                card_data = CardData(
                    id=card.id,
                    list_id=card.list_id,
                    title=card.title,
                    description=card.description,
                    content=card.content or "",
                    status=card.status,
                    tags=tags,
                    created_at=card.created_at,
                    updated_at=card.updated_at,
                )

                # Write MD file
                write_card(fpath, card_data)

                # Sync to CardIndex
                sync_card_to_index(session, card_data, project.id, str(fpath))

                print(f"  [OK] Card {card.id}: {card.title} -> {fpath.name}")
                total_cards += 1

            session.commit()

        print(f"\nMigration complete: {total_cards} cards migrated, {total_skipped} skipped.")


if __name__ == "__main__":
    migrate()
