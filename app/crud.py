from datetime import datetime
import secrets

from collections.abc import Sequence

import csv
from io import StringIO

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import CANDIDATE_CATEGORIES, Candidate, Vote, Voter
class AlreadyVotedError(Exception):
    pass


class AdminActionError(Exception):
    pass


def authenticate_voter(db: Session, name: str, code: str) -> Voter | None:
    voter = db.execute(select(Voter).where(Voter.name == name)).scalar_one_or_none()
    if not voter or voter.code != code:
        return None
    return voter


def get_candidates(db: Session) -> Sequence[Candidate]:
    return db.execute(select(Candidate).order_by(Candidate.category.asc(), Candidate.name.asc())).scalars().all()


def get_candidates_by_category(db: Session) -> dict[str, list[Candidate]]:
    grouped = {category: [] for category in CANDIDATE_CATEGORIES}
    for candidate in get_candidates(db):
        grouped.setdefault(candidate.category, []).append(candidate)
    return grouped


def get_candidate(db: Session, candidate_id: int) -> Candidate | None:
    return db.execute(select(Candidate).where(Candidate.id == candidate_id)).scalar_one_or_none()


def record_vote(db: Session, voter_id: int, selections: dict[str, int]) -> None:
    try:
        with db.begin():
            voter = db.execute(select(Voter).where(Voter.id == voter_id)).scalar_one_or_none()
            if voter is None:
                raise ValueError("Voter not found.")
            if voter.has_voted:
                raise AlreadyVotedError("This voter has already cast a ballot.")

            if set(selections.keys()) != set(CANDIDATE_CATEGORIES):
                raise ValueError("Both election categories must be selected.")

            seen_candidate_ids: set[int] = set()
            for category, candidate_id in selections.items():
                candidate = db.execute(select(Candidate).where(Candidate.id == candidate_id)).scalar_one_or_none()
                if candidate is None:
                    raise ValueError("Candidate not found.")
                if candidate.category != category:
                    raise ValueError("Candidate does not match the selected category.")
                if candidate.id in seen_candidate_ids:
                    raise ValueError("Duplicate candidate selection is not allowed.")
                seen_candidate_ids.add(candidate.id)
                db.add(Vote(candidate_id=candidate_id, category=category))

            result = db.execute(
                update(Voter)
                .where(Voter.id == voter_id, Voter.has_voted.is_(False))
                .values(has_voted=True, voted_at=datetime.utcnow())
            )
            if result.rowcount != 1:
                raise AlreadyVotedError("This voter has already cast a ballot.")
    except (AlreadyVotedError, ValueError):
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("Failed to record vote.") from exc


def get_results(db: Session) -> list[tuple[str, str, int]]:
    rows = db.execute(
        select(Candidate.category, Candidate.name, func.count(Vote.id))
        .outerjoin(Vote, Vote.candidate_id == Candidate.id)
        .group_by(Candidate.id, Candidate.category, Candidate.name)
        .order_by(Candidate.category.asc(), Candidate.name.asc())
    ).all()
    return [(category, name, total) for category, name, total in rows]


def get_results_by_category(db: Session) -> dict[str, list[tuple[str, int]]]:
    grouped = {category: [] for category in CANDIDATE_CATEGORIES}
    for category, name, total in get_results(db):
        grouped.setdefault(category, []).append((name, total))
    return grouped


def get_voters(db: Session, sort_by: str = "class") -> Sequence[Voter]:
    if sort_by == "name":
        ordering = (Voter.name.asc(), Voter.class_name.asc())
    else:
        ordering = (Voter.class_name.asc(), Voter.name.asc())
    return db.execute(select(Voter).order_by(*ordering)).scalars().all()


def get_voter_names(db: Session) -> list[str]:
    return db.execute(select(Voter.name).order_by(Voter.name.asc())).scalars().all()


def create_candidate(db: Session, name: str, category: str) -> Candidate:
    if not name:
        raise AdminActionError("Candidate name cannot be blank.")
    if category not in CANDIDATE_CATEGORIES:
        raise AdminActionError("Invalid candidate category.")
    candidate = Candidate(name=name, category=category)
    db.add(candidate)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AdminActionError("Candidate name must be unique within its category.") from exc
    db.refresh(candidate)
    return candidate


def delete_candidate(db: Session, candidate_id: int) -> None:
    candidate = get_candidate(db, candidate_id)
    if candidate is None:
        raise AdminActionError("Candidate not found.")

    vote_total = db.execute(select(func.count(Vote.id)).where(Vote.candidate_id == candidate_id)).scalar_one()
    if vote_total:
        raise AdminActionError("Candidates with recorded votes cannot be removed.")

    db.delete(candidate)
    db.commit()


def create_voter(db: Session, name: str, class_name: str, code_digits: int) -> tuple[Voter, str]:
    if not name:
        raise AdminActionError("Voter name cannot be blank.")
    if not class_name:
        raise AdminActionError("Class cannot be blank.")
    code = "".join(secrets.choice("0123456789") for _ in range(code_digits))
    voter = Voter(name=name, class_name=class_name, code=code, has_voted=False, voted_at=None)
    db.add(voter)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AdminActionError("Voter name must be unique.") from exc
    db.refresh(voter)
    return voter, code


def delete_voter(db: Session, voter_id: int) -> None:
    voter = db.execute(select(Voter).where(Voter.id == voter_id)).scalar_one_or_none()
    if voter is None:
        raise AdminActionError("Voter not found.")
    if voter.has_voted:
        raise AdminActionError("Voters who have already voted cannot be removed.")
    db.delete(voter)
    db.commit()


def reset_voter_code(db: Session, voter_id: int, code_digits: int) -> tuple[Voter, str]:
    voter = db.execute(select(Voter).where(Voter.id == voter_id)).scalar_one_or_none()
    if voter is None:
        raise AdminActionError("Voter not found.")
    code = "".join(secrets.choice("0123456789") for _ in range(code_digits))
    voter.code = code
    db.commit()
    db.refresh(voter)
    return voter, code


def reset_all_voter_codes(db: Session, code_digits: int) -> int:
    voters = db.execute(select(Voter)).scalars().all()
    if not voters:
        raise AdminActionError("No voters to reset.")
    count = 0
    for voter in voters:
        voter.code = "".join(secrets.choice("0123456789") for _ in range(code_digits))
        count += 1
    db.commit()
    return count


def parse_voter_csv(content: bytes, code_digits: int) -> list[tuple[str, str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AdminActionError("CSV file must be UTF-8 encoded.") from exc

    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        raise AdminActionError("CSV file must include a header row.")

    headers = {field.strip().lower(): field for field in reader.fieldnames if field}
    if "name" not in headers or "class" not in headers:
        raise AdminActionError('CSV file must include "name" and "class" columns.')

    voters: list[tuple[str, str, str]] = []
    seen_names: set[str] = set()
    for row in reader:
        name = (row.get(headers["name"]) or "").strip()
        class_name = (row.get(headers["class"]) or "").strip()
        if not name or not class_name:
            raise AdminActionError("Every voter row must include both name and class.")
        if name in seen_names:
            raise AdminActionError("Voter names must be unique within the CSV file.")
        seen_names.add(name)
        code = "".join(secrets.choice("0123456789") for _ in range(code_digits))
        voters.append((name, class_name, code))

    if not voters:
        raise AdminActionError("CSV file does not contain any voter rows.")
    return voters


def parse_candidate_csv(content: bytes) -> list[str]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AdminActionError("CSV file must be UTF-8 encoded.") from exc

    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        raise AdminActionError("CSV file must include a header row.")

    headers = {field.strip().lower(): field for field in reader.fieldnames if field}
    if "name" not in headers:
        raise AdminActionError('CSV file must include a "name" column.')

    names: list[str] = []
    seen: set[str] = set()
    for row in reader:
        name = (row.get(headers["name"]) or "").strip()
        if not name:
            raise AdminActionError("Every row must include a candidate name.")
        if name in seen:
            raise AdminActionError("Candidate names must be unique within the CSV file.")
        seen.add(name)
        names.append(name)

    if not names:
        raise AdminActionError("CSV file does not contain any candidate rows.")
    return names


def import_candidates(db: Session, names: list[str], category: str, replace_existing: bool) -> int:
    if category not in CANDIDATE_CATEGORIES:
        raise AdminActionError("Invalid candidate category.")

    existing_count = db.execute(
        select(func.count(Candidate.id)).where(Candidate.category == category)
    ).scalar_one()

    if existing_count and not replace_existing:
        raise AdminActionError(
            f"{category} candidates already exist. Confirm replacement before importing."
        )

    if replace_existing:
        vote_count = db.execute(
            select(func.count(Vote.id)).where(Vote.category == category)
        ).scalar_one()
        if vote_count:
            raise AdminActionError(
                f"Cannot replace {category} candidates after votes have been cast in that category."
            )

    try:
        if replace_existing:
            db.execute(delete(Candidate).where(Candidate.category == category))
        for name in names:
            db.add(Candidate(name=name, category=category))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AdminActionError("Imported candidate names must be unique within the category.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise AdminActionError("Failed to import candidate records.") from exc

    return len(names)


def get_election_stats(db: Session) -> dict:
    voter_count = db.execute(select(func.count(Voter.id))).scalar_one()
    candidate_count = db.execute(select(func.count(Candidate.id))).scalar_one()
    vote_count = db.execute(select(func.count(Vote.id))).scalar_one()
    voted_count = db.execute(select(func.count(Voter.id)).where(Voter.has_voted.is_(True))).scalar_one()
    return {
        "voter_count": voter_count,
        "candidate_count": candidate_count,
        "vote_count": vote_count,
        "voted_count": voted_count,
    }


def nuke_all_records(db: Session) -> dict:
    stats = get_election_stats(db)
    try:
        db.execute(delete(Vote))
        db.execute(delete(Voter))
        db.execute(delete(Candidate))
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AdminActionError("Failed to delete all records.") from exc
    return stats


def import_voters(db: Session, voters: list[tuple[str, str, str]], replace_existing: bool) -> int:
    existing_voter_count = db.execute(select(func.count(Voter.id))).scalar_one()
    existing_vote_count = db.execute(select(func.count(Vote.id))).scalar_one()

    if existing_voter_count and not replace_existing:
        raise AdminActionError("Voter records already exist. Confirm replacement before importing.")
    if replace_existing and existing_vote_count:
        raise AdminActionError("Cannot replace voter records after votes have been cast.")

    try:
        if replace_existing:
            db.execute(delete(Voter))
        for name, class_name, code in voters:
            db.add(Voter(name=name, class_name=class_name, code=code, has_voted=False, voted_at=None))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AdminActionError("Imported voter names must be unique.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise AdminActionError("Failed to import voter records.") from exc

    return len(voters)
