from sqlalchemy import select

from app.config import CREDENTIALS_PATH, VOTER_CODE_DIGITS
from app.database import Base, SessionLocal, engine, ensure_schema
from app.models import Candidate, Voter
from init_db import DEFAULT_CANDIDATES, export_credentials, seed_database


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
        credentials = seed_database(DEFAULT_CANDIDATES, 10, VOTER_CODE_DIGITS)
        export_credentials(credentials, CREDENTIALS_PATH)
        print(f"Bootstrapped database and exported credentials to {CREDENTIALS_PATH}")
        return

    if not CREDENTIALS_PATH.exists():
        export_credentials(existing_credentials(), CREDENTIALS_PATH)
        print(f"Rebuilt missing credentials export at {CREDENTIALS_PATH}")
        return

    print("Bootstrap skipped; existing election data detected.")


if __name__ == "__main__":
    main()
