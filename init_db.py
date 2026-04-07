import argparse
import secrets
from pathlib import Path

from app.config import CREDENTIALS_PATH, DATABASE_PATH, VOTER_CODE_DIGITS
from app.database import Base, SessionLocal, engine
from app.models import HEAD_BOY, HEAD_GIRL, Candidate, Voter


DEFAULT_CANDIDATES = [
    (HEAD_BOY, "Adam Carter"),
    (HEAD_BOY, "Benjamin Scott"),
    (HEAD_BOY, "Daniel Young"),
    (HEAD_GIRL, "Ava Collins"),
    (HEAD_GIRL, "Grace Mitchell"),
    (HEAD_GIRL, "Mia Turner"),
]

DEFAULT_VOTERS = [
    ("Voter 001", "5A"),
    ("Voter 002", "5A"),
    ("Voter 003", "5B"),
    ("Voter 004", "5B"),
    ("Voter 005", "5C"),
    ("Voter 006", "5C"),
    ("Voter 007", "4A"),
    ("Voter 008", "4A"),
    ("Voter 009", "4B"),
    ("Voter 010", "4B"),
]


def generate_code(length: int = 6) -> str:
    digits = "0123456789"
    return "".join(secrets.choice(digits) for _ in range(length))


def reset_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    Base.metadata.create_all(bind=engine)


def build_voters(voter_count: int) -> list[tuple[str, str]]:
    if voter_count <= len(DEFAULT_VOTERS):
        return DEFAULT_VOTERS[:voter_count]
    voters = list(DEFAULT_VOTERS)
    for index in range(len(DEFAULT_VOTERS) + 1, voter_count + 1):
        voters.append((f"Voter {index:03d}", "Unassigned"))
    return voters


def seed_database(candidates: list[tuple[str, str]], voter_count: int, code_digits: int) -> list[tuple[str, str]]:
    credentials: list[tuple[str, str]] = []
    voters = build_voters(voter_count)
    with SessionLocal() as db:
        for category, name in candidates:
            db.add(Candidate(name=name, category=category))

        for voter_name, class_name in voters:
            code = generate_code(code_digits)
            db.add(Voter(name=voter_name, class_name=class_name, code=code))
            credentials.append((voter_name, code))

        db.commit()
    return credentials


def export_credentials(credentials: list[tuple[str, str]], destination: Path) -> None:
    lines = ["Voting Booth Voter Credentials", "=" * 32, ""]
    lines.extend(f"{name}: {code}" for name, code in credentials)
    _ = destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize the voting booth database.")
    _ = parser.add_argument(
        "--candidate",
        dest="candidates",
        action="append",
        help='Candidate in the format "Head Boy:Name" or "Head Girl:Name". Pass multiple times to define the ballot.',
    )
    _ = parser.add_argument("--voters", type=int, default=10, help="Number of voter accounts to generate.")
    _ = parser.add_argument("--code-digits", type=int, default=VOTER_CODE_DIGITS, help="Number of digits to use for each voting code.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.candidates:
        candidates: list[tuple[str, str]] = []
        for raw_candidate in args.candidates:
            category, separator, name = raw_candidate.partition(":")
            if not separator or category.strip() not in {HEAD_BOY, HEAD_GIRL} or not name.strip():
                raise ValueError('Candidates must use the format "Head Boy:Name" or "Head Girl:Name".')
            candidates.append((category.strip(), name.strip()))
    else:
        candidates = DEFAULT_CANDIDATES
    if args.code_digits < 4:
        raise ValueError("Voting codes should be at least 4 digits.")
    reset_database()
    credentials = seed_database(candidates, args.voters, args.code_digits)
    export_credentials(credentials, CREDENTIALS_PATH)
    print(f"Initialized database with {len(candidates)} candidates and {len(credentials)} voters.")
    print(f"Exported voter credentials to {CREDENTIALS_PATH}")


if __name__ == "__main__":
    main()
