import secrets
import string
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and apply lightweight schema migrations. Call on startup."""
    # Ensure every ORM model has registered its table/columns before metadata
    # creation and additive migrations are evaluated.  This also makes the
    # helper safe to call from scripts and tests, not only from FastAPI's
    # fully-imported application startup path.
    import app.models.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_schema()


def _migrate_schema():
    """Add columns that exist on the ORM models but are missing from the
    existing SQLite tables.

    `create_all` only creates missing tables; it never alters existing ones.
    When new columns are added to a model, older databases end up out of sync
    (e.g. `no such column: projects.created_at`). This performs a minimal
    additive migration so those databases keep working without a manual reset.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')
                )

        _repair_project_memberships(conn, existing_tables)
        _backfill_project_codes(conn, existing_tables)
        # Drop tables that belonged to the removed nested sub-agent feature
        # (TaskNode tree + SubAgentRun records). These are no longer referenced
        # by any model, so dropping them keeps legacy databases clean.
        for stale in ("task_nodes", "sub_agent_runs"):
            if stale in existing_tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{stale}"'))
        # Python-side column defaults do not populate rows that predate an
        # additive SQLite migration.  Preserve the product default for those
        # legacy tasks explicitly.
        if "tasks" in existing_tables:
            conn.execute(text("""
                UPDATE tasks SET approval_percent = 50
                WHERE approval_percent IS NULL
            """))


def _repair_project_memberships(conn, existing_tables: set[str]) -> None:
    """Repair legacy membership data and enforce one owner per project.

    Older databases allowed duplicate memberships and multiple OWNER rows.
    The project.owner_id is the canonical source of truth during cleanup.
    """
    if not {"projects", "project_members"}.issubset(existing_tables):
        return

    owner_role = "OWNER"
    member_role = "MEMBER"
    # Keep the oldest membership row for each (project, user) pair.
    conn.execute(text("""
        DELETE FROM project_members
        WHERE id NOT IN (
            SELECT MIN(id) FROM project_members GROUP BY project_id, user_id
        )
    """))

    projects = conn.execute(text("SELECT id, owner_id FROM projects")).mappings().all()
    for project in projects:
        project_id = project["id"]
        owner_id = project["owner_id"]
        conn.execute(text("""
            UPDATE project_members SET role = :member_role
            WHERE project_id = :project_id AND role = :owner_role
        """), {"member_role": member_role, "owner_role": owner_role, "project_id": project_id})
        owner_member = conn.execute(text("""
            SELECT id FROM project_members WHERE project_id = :project_id AND user_id = :user_id
        """), {"project_id": project_id, "user_id": owner_id}).first()
        if owner_member:
            conn.execute(text("UPDATE project_members SET role = :owner_role WHERE id = :id"), {
                "owner_role": owner_role, "id": owner_member[0]
            })
        else:
            conn.execute(text("""
                INSERT INTO project_members (project_id, user_id, role)
                VALUES (:project_id, :user_id, :owner_role)
            """), {"project_id": project_id, "user_id": owner_id, "owner_role": owner_role})

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_project_members_project_user_idx
        ON project_members(project_id, user_id)
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_project_members_single_owner_idx
        ON project_members(project_id) WHERE role = 'OWNER'
    """))


def _backfill_project_codes(conn, existing_tables: set[str]) -> None:
    """Give legacy projects a stable public code used by join requests."""
    if "projects" not in existing_tables:
        return

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_project_code_idx
        ON projects(project_id)
    """))
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    missing = conn.execute(text(
        "SELECT id FROM projects WHERE project_id IS NULL OR project_id = ''"
    )).scalars().all()
    for project_id in missing:
        while True:
            suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
            code = f"PROJ-{date_part}-{suffix}"
            exists = conn.execute(text(
                "SELECT 1 FROM projects WHERE project_id = :code"
            ), {"code": code}).first()
            if not exists:
                break
        conn.execute(text(
            "UPDATE projects SET project_id = :code WHERE id = :id"
        ), {"code": code, "id": project_id})
