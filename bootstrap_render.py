from sqlalchemy import select

from app.config import CREDENTIALS_PATH
from app.database import Base, SessionLocal, engine, ensure_schema
from app.models import Candidate, Voter
from init_db import export_credentials


def existing_credentials() -> list[tuple[str, str]]:
    with SessionLocal() as db:
        return db.execute(select(Voter.name, Voter.code).order_by(Voter.name.asc())).all()


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema()

    with SessionLocal() as db:
        candidate_count = db.query(Candidate).count()
        voter_count = db.query(Voter).count()

    if candidate_count == 0 and voter_count == 0:
        print("Database is empty. No automatic seed was applied.")
        return

    if not CREDENTIALS_PATH.exists():
        export_credentials(existing_credentials(), CREDENTIALS_PATH)
        print(f"Rebuilt missing credentials export at {CREDENTIALS_PATH}")
        return

    print("Schema check completed; existing election data preserved.")


if __name__ == "__main__":
    main()
