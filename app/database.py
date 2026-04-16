from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL, VOTER_CODE_DIGITS


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def ensure_schema() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    with engine.begin() as connection:
        voter_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(voters)"))}
        if "voted_at" not in voter_columns:
            connection.execute(text("ALTER TABLE voters ADD COLUMN voted_at DATETIME"))
        if "class_name" not in voter_columns:
            connection.execute(text("ALTER TABLE voters ADD COLUMN class_name TEXT"))
            connection.execute(text("UPDATE voters SET class_name = 'Unassigned' WHERE class_name IS NULL OR TRIM(class_name) = ''"))
        if "code" not in voter_columns:
            connection.execute(text("ALTER TABLE voters ADD COLUMN code TEXT"))
        connection.execute(text("UPDATE voters SET class_name = 'Unassigned' WHERE class_name IS NULL OR TRIM(class_name) = ''"))
        missing_codes = connection.execute(text("SELECT id FROM voters WHERE code IS NULL OR TRIM(code) = ''")).fetchall()
        from app.crud import generate_voter_code
        for row in missing_codes:
            code = generate_voter_code(VOTER_CODE_DIGITS)
            connection.execute(
                text("UPDATE voters SET code = :code WHERE id = :voter_id"),
                {"code": code, "voter_id": row[0]},
            )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
