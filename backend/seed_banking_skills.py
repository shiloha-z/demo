"""Seed the skills table with banking-standard review checklists.

Run once per user or per instance to pre-populate the skill repository with
six bank security and compliance skill templates:

  1. Java/Python 安全编码规范
  2. API 权限校验规范
  3. 数据库访问规范
  4. 日志脱敏规范
  5. 密码与密钥管理规范
  6. 转账和账户类接口审查清单

Usage::

  # Seed for the first user in the database
  python -m seed_banking_skills

  # Seed for a specific user
  python -m seed_banking_skills --user-id 1

  # Dry-run: print what would be created without touching the database
  python -m seed_banking_skills --dry-run

  # Force re-import even if a skill with the same name already exists
  python -m seed_banking_skills --force
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

SEED_FILE = Path(__file__).resolve().parent / "seed_data" / "banking_skills.json"

# A small per-skill subtitle we store in the description column so the UI has
# something to display beyond the title.
BUILTIN_SOURCE = "builtin"


def load_skills() -> List[dict]:
    """Read and validate the seed data file."""
    if not SEED_FILE.exists():
        print(f"[ERROR] Seed file not found: {SEED_FILE}")
        sys.exit(1)

    with open(SEED_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, list):
        print("[ERROR] Seed file must contain a JSON array of skill objects")
        sys.exit(1)

    for i, skill in enumerate(data):
        for field in ("name", "description", "prompt_content"):
            if not skill.get(field):
                print(f"[ERROR] Skill entry {i} is missing required field: {field}")
                sys.exit(1)

    return data


def get_first_user_id():
    """Return the id of the first user in the database for auto-seeding."""
    from app.models.models import User
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).order_by(User.id.asc()).first()
        if not user:
            print("[ERROR] No users found in the database. Please create a user first.")
            sys.exit(1)
        return user.id
    finally:
        db.close()


def seed(user_id: int, dry_run: bool = False, force: bool = False):
    """Insert banking skill definitions for *user_id*."""
    from app.models.models import Skill
    from app.core.database import SessionLocal

    skills_data = load_skills()
    db = SessionLocal()

    created = 0
    skipped = 0

    try:
        existing_names = {
            row[0]
            for row in db.query(Skill.name).filter(
                Skill.creator_id == user_id,
                Skill.source == BUILTIN_SOURCE,
            ).all()
        }

        for entry in skills_data:
            name = entry["name"]

            if name in existing_names and not force:
                print(f"  [SKIP] Already exists: {name}")
                skipped += 1
                continue

            if name in existing_names and force:
                # Update the existing record in-place
                skill = db.query(Skill).filter(
                    Skill.creator_id == user_id,
                    Skill.source == BUILTIN_SOURCE,
                    Skill.name == name,
                ).first()
                if skill:
                    skill.description = entry["description"]
                    skill.prompt_content = entry["prompt_content"]
                    print(f"  [UPDATE] {name}")
                    created += 1
                    continue

            if dry_run:
                print(f"  [DRY-RUN] Would create: {name}")
                created += 1
                continue

            skill = Skill(
                creator_id=user_id,
                name=name,
                description=entry["description"],
                prompt_content=entry["prompt_content"],
                source=BUILTIN_SOURCE,
            )
            db.add(skill)
            created += 1
            print(f"  [CREATE] {name}")

        if not dry_run:
            db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] {exc}")
        sys.exit(1)
    finally:
        db.close()

    print(f"\nDone: {created} created/updated, {skipped} skipped.")
    if dry_run:
        print("(dry-run — no changes were committed)")


# ── CLI ─────────────────────────────────────────────────────────────────
def main():
    # Ensure the backend package is importable.
    backend_dir = Path(__file__).resolve().parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    parser = argparse.ArgumentParser(
        description="Seed banking-standard review skills into the local repository."
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Target user ID (default: first user in the database).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without modifying the database.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing builtin skills with the same name.",
    )
    args = parser.parse_args()

    user_id = args.user_id or get_first_user_id()
    print(f"Seeding banking skills for user_id={user_id} ...\n")
    seed(user_id=user_id, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
