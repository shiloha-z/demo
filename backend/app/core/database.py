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
