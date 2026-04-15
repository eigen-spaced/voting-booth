import io
import secrets
from datetime import datetime, timedelta, timezone
from hmac import compare_digest

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_SECRET_KEY,
    ADMIN_SESSION_TIMEOUT_SECONDS,
    ADMIN_USERNAME,
    SESSION_SECRET_KEY,
    VOTER_CODE_DIGITS,
)
from app.crud import (
    AdminActionError,
    AlreadyVotedError,
    authenticate_voter,
    create_candidate,
    create_voter,
    delete_candidate,
    delete_voter,
    get_candidate,
    get_candidates_by_category,
    get_election_stats,
    get_results,
    get_results_by_category,
    get_voter_names,
    get_voters,
    import_candidates,
    import_voters,
    nuke_all_records,
    parse_candidate_csv,
    parse_voter_csv,
    record_vote,
    reset_all_voter_codes,
    reset_voter_code,
)
from app.database import Base, engine, ensure_schema, get_db
from app.models import CANDIDATE_CATEGORIES, HEAD_BOY, HEAD_GIRL


app = FastAPI(title="Voting Booth")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY, same_site="strict", https_only=False)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

Base.metadata.create_all(bind=engine)
ensure_schema()


def current_voter_id(request: Request) -> int | None:
    return request.session.get("voter_id")


def current_admin(request: Request) -> str | None:
    return request.session.get("admin_username")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_dubai_time(value: datetime | None) -> str:
    if value is None:
        return "Not recorded"
    dubai_tz = timezone(timedelta(hours=4))
    normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return normalized.astimezone(dubai_tz).strftime("%I:%M %p %d-%m-%Y")


def touch_admin_activity(request: Request) -> None:
    request.session["admin_last_seen"] = utc_now().isoformat()


def ensure_admin_session(request: Request) -> bool:
    if not (request.session.get("is_admin") and current_admin(request) == ADMIN_USERNAME):
        return False

    last_seen_raw = request.session.get("admin_last_seen")
    if not last_seen_raw:
        request.session.clear()
        return False

    try:
        last_seen = datetime.fromisoformat(last_seen_raw)
    except ValueError:
        request.session.clear()
        return False

    if utc_now() - last_seen > timedelta(seconds=ADMIN_SESSION_TIMEOUT_SECONDS):
        request.session.clear()
        return False

    touch_admin_activity(request)
    return True


def get_admin_csrf_token(request: Request) -> str:
    token = request.session.get("admin_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["admin_csrf_token"] = token
    return token


def pop_admin_notice(request: Request) -> tuple[str | None, str]:
    message = request.session.pop("admin_notice", None)
    level = request.session.pop("admin_notice_level", "success")
    return message, level


def set_admin_notice(request: Request, message: str, level: str = "success") -> None:
    request.session["admin_notice"] = message
    request.session["admin_notice_level"] = level


def apply_no_store(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


templates.env.globals["format_dubai_time"] = format_dubai_time


def login_context(request: Request, db: Session, error: str | None = None, form_name: str = "") -> dict:
    return {
        "request": request,
        "error": error,
        "form_name": form_name,
        "code_digits": VOTER_CODE_DIGITS,
        "code_pattern": rf"[0-9]{{{VOTER_CODE_DIGITS}}}",
        "voter_names": get_voter_names(db),
    }


def admin_login_context(request: Request, error: str | None = None) -> dict:
    return {"request": request, "error": error, "disable_cache": True}


def admin_dashboard_context(request: Request, db: Session, sort_by: str) -> dict:
    notice, notice_level = pop_admin_notice(request)
    normalized_sort = sort_by if sort_by in {"name", "class"} else "class"
    return {
        "request": request,
        "admin_username": current_admin(request),
        "csrf_token": get_admin_csrf_token(request),
        "notice": notice,
        "notice_level": notice_level,
        "voters": get_voters(db, normalized_sort),
        "candidate_categories": CANDIDATE_CATEGORIES,
        "candidates_by_category": get_candidates_by_category(db),
        "results_by_category": get_results_by_category(db),
        "export_url": f"/admin/export?key={ADMIN_SECRET_KEY}",
        "voter_export_url": f"/admin/voters/export?key={ADMIN_SECRET_KEY}",
        "code_digits": VOTER_CODE_DIGITS,
        "voter_sort": normalized_sort,
        "disable_cache": True,
    }


def validate_admin_request(request: Request, csrf_token: str) -> None:
    if not ensure_admin_session(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    session_token = request.session.get("admin_csrf_token")
    if not session_token or not compare_digest(session_token, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin form token.")


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_voter_id(request):
        return RedirectResponse("/ballot", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", login_context(request, db))


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, name: str = Form(...), code: str = Form(...), db: Session = Depends(get_db)):
    normalized_name = name.strip()
    normalized_code = code.strip()
    if not normalized_code.isdigit() or len(normalized_code) != VOTER_CODE_DIGITS:
        return templates.TemplateResponse(
            "login.html",
            login_context(request, db, f"Voting codes must be exactly {VOTER_CODE_DIGITS} digits.", normalized_name),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    voter = authenticate_voter(db, normalized_name, normalized_code)
    if voter is None:
        return templates.TemplateResponse(
            "login.html",
            login_context(request, db, "Invalid name or voting code.", normalized_name),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    if voter.has_voted:
        return templates.TemplateResponse(
            "login.html",
            login_context(request, db, "This account has already been used to vote.", normalized_name),
            status_code=status.HTTP_403_FORBIDDEN,
        )

    request.session.clear()
    request.session["voter_id"] = voter.id
    request.session["voter_name"] = voter.name
    return RedirectResponse("/ballot", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/ballot", response_class=HTMLResponse)
def ballot_page(request: Request, db: Session = Depends(get_db)):
    voter_id = current_voter_id(request)
    if not voter_id:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "ballot.html",
        {
            "request": request,
            "candidates_by_category": get_candidates_by_category(db),
            "voter_name": request.session.get("voter_name"),
            "error": None,
            "selected_head_boy_id": request.session.get("head_boy_candidate_id"),
            "selected_head_girl_id": request.session.get("head_girl_candidate_id"),
        },
    )


@app.post("/confirm", response_class=HTMLResponse)
def confirm_vote(
    request: Request,
    head_boy_candidate_id: int | None = Form(None),
    head_girl_candidate_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    voter_id = current_voter_id(request)
    if not voter_id:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    if head_boy_candidate_id is None or head_girl_candidate_id is None:
        return templates.TemplateResponse(
            "ballot.html",
            {
                "request": request,
                "candidates_by_category": get_candidates_by_category(db),
                "voter_name": request.session.get("voter_name"),
                "error": "Please select one Head Boy and one Head Girl before continuing.",
                "selected_head_boy_id": head_boy_candidate_id,
                "selected_head_girl_id": head_girl_candidate_id,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    head_boy_candidate = get_candidate(db, head_boy_candidate_id)
    head_girl_candidate = get_candidate(db, head_girl_candidate_id)
    if (
        head_boy_candidate is None
        or head_girl_candidate is None
        or head_boy_candidate.category != HEAD_BOY
        or head_girl_candidate.category != HEAD_GIRL
    ):
        return templates.TemplateResponse(
            "ballot.html",
            {
                "request": request,
                "candidates_by_category": get_candidates_by_category(db),
                "voter_name": request.session.get("voter_name"),
                "error": "Please select a valid candidate for each category before continuing.",
                "selected_head_boy_id": head_boy_candidate_id,
                "selected_head_girl_id": head_girl_candidate_id,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    request.session["head_boy_candidate_id"] = head_boy_candidate.id
    request.session["head_girl_candidate_id"] = head_girl_candidate.id
    return templates.TemplateResponse(
        "confirm.html",
        {
            "request": request,
            "head_boy_candidate": head_boy_candidate,
            "head_girl_candidate": head_girl_candidate,
        },
    )


@app.post("/vote")
def cast_vote(request: Request, db: Session = Depends(get_db)):
    voter_id = current_voter_id(request)
    head_boy_candidate_id = request.session.get("head_boy_candidate_id")
    head_girl_candidate_id = request.session.get("head_girl_candidate_id")
    if not voter_id or not head_boy_candidate_id or not head_girl_candidate_id:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    try:
        record_vote(
            db,
            voter_id=voter_id,
            selections={
                HEAD_BOY: head_boy_candidate_id,
                HEAD_GIRL: head_girl_candidate_id,
            },
        )
    except AlreadyVotedError:
        request.session.clear()
        return RedirectResponse("/?error=already-voted", status_code=status.HTTP_303_SEE_OTHER)
    except (ValueError, RuntimeError):
        return templates.TemplateResponse(
            "confirm.html",
            {
                "request": request,
                "head_boy_candidate": get_candidate(db, head_boy_candidate_id),
                "head_girl_candidate": get_candidate(db, head_girl_candidate_id),
                "error": "The vote could not be recorded. Please ask an administrator for assistance.",
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    request.session.clear()
    return RedirectResponse("/thank-you", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/thank-you", response_class=HTMLResponse)
def thank_you_page(request: Request):
    return templates.TemplateResponse("thank_you.html", {"request": request})


@app.get("/healthz")
def healthcheck():
    return {"status": "ok"}


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    if ensure_admin_session(request):
        return apply_no_store(RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER))
    return apply_no_store(templates.TemplateResponse("admin_login.html", admin_login_context(request)))


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    secret_key: str = Form(...),
):
    if not compare_digest(username.strip(), ADMIN_USERNAME):
        return apply_no_store(templates.TemplateResponse(
            "admin_login.html",
            admin_login_context(request, "Invalid admin credentials."),
            status_code=status.HTTP_401_UNAUTHORIZED,
        ))
    if not compare_digest(password, ADMIN_PASSWORD):
        return apply_no_store(templates.TemplateResponse(
            "admin_login.html",
            admin_login_context(request, "Invalid admin credentials."),
            status_code=status.HTTP_401_UNAUTHORIZED,
        ))
    if not compare_digest(secret_key.strip(), ADMIN_SECRET_KEY):
        return apply_no_store(templates.TemplateResponse(
            "admin_login.html",
            admin_login_context(request, "Invalid admin credentials."),
            status_code=status.HTTP_401_UNAUTHORIZED,
        ))

    request.session.clear()
    request.session["is_admin"] = True
    request.session["admin_username"] = ADMIN_USERNAME
    request.session["admin_csrf_token"] = secrets.token_urlsafe(32)
    touch_admin_activity(request)
    return apply_no_store(RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER))


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, sort: str = Query("class"), db: Session = Depends(get_db)):
    if not ensure_admin_session(request):
        return apply_no_store(RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER))
    return apply_no_store(templates.TemplateResponse("admin_dashboard.html", admin_dashboard_context(request, db, sort)))


@app.get("/admin/export")
def export_results(request: Request, key: str = Query(...), db: Session = Depends(get_db)):
    if not ensure_admin_session(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin session required.")
    if not compare_digest(key, ADMIN_SECRET_KEY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin key.")

    output = io.StringIO()
    import csv
    writer = csv.writer(output)
    writer.writerow(["Candidate Name", "Category", "Total Votes"])
    for category, candidate_name, total_votes in get_results(db):
        writer.writerow([candidate_name, category, total_votes])

    response = StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = 'attachment; filename="results.csv"'
    return apply_no_store(response)


@app.get("/admin/voters/export")
def export_voters(request: Request, key: str = Query(...), db: Session = Depends(get_db)):
    if not ensure_admin_session(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin session required.")
    if not compare_digest(key, ADMIN_SECRET_KEY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin key.")

    output = io.StringIO()
    import csv
    writer = csv.writer(output)
    writer.writerow(["Name", "Class", "Code", "Has Voted", "Voted At"])
    for voter in get_voters(db):
        writer.writerow([voter.name, voter.class_name, voter.code, "Yes" if voter.has_voted else "No", voter.voted_at.isoformat() if voter.voted_at else ""])

    response = StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = 'attachment; filename="voters.csv"'
    return apply_no_store(response)


@app.post("/admin/candidates")
def add_admin_candidate(
    request: Request,
    candidate_name: str = Form(...),
    candidate_category: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_admin_request(request, csrf_token)
    try:
        candidate = create_candidate(db, candidate_name.strip(), candidate_category.strip())
        set_admin_notice(request, f'Candidate "{candidate.name}" added to {candidate.category}.')
    except AdminActionError as exc:
        set_admin_notice(request, str(exc), "error")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/candidates/import")
async def import_admin_candidates(
    request: Request,
    candidate_file: UploadFile = File(...),
    candidate_import_category: str = Form(...),
    replace_existing_candidates: str | None = Form(None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_admin_request(request, csrf_token)
    if candidate_import_category not in CANDIDATE_CATEGORIES:
        set_admin_notice(request, "Invalid candidate category.", "error")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    if not candidate_file.filename.lower().endswith(".csv"):
        set_admin_notice(request, "Only CSV candidate imports are supported.", "error")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    try:
        names = parse_candidate_csv(await candidate_file.read())
        count = import_candidates(db, names, candidate_import_category, replace_existing_candidates == "yes")
        set_admin_notice(request, f"Imported {count} {candidate_import_category} candidate(s).")
    except AdminActionError as exc:
        set_admin_notice(request, str(exc), "error")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/candidates/{candidate_id}/delete")
def remove_admin_candidate(
    candidate_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_admin_request(request, csrf_token)
    try:
        delete_candidate(db, candidate_id)
        set_admin_notice(request, "Candidate removed.")
    except AdminActionError as exc:
        set_admin_notice(request, str(exc), "error")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/voters")
def add_admin_voter(
    request: Request,
    voter_name: str = Form(...),
    voter_class: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_admin_request(request, csrf_token)
    try:
        voter, code = create_voter(db, voter_name.strip(), voter_class.strip(), VOTER_CODE_DIGITS)
        set_admin_notice(request, f'Voter "{voter.name}" ({voter.class_name}) added. New code: {code}')
    except AdminActionError as exc:
        set_admin_notice(request, str(exc), "error")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/voters/import")
async def import_admin_voters(
    request: Request,
    voter_file: UploadFile = File(...),
    replace_existing: str | None = Form(None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_admin_request(request, csrf_token)
    if not voter_file.filename.lower().endswith(".csv"):
        set_admin_notice(request, "Only CSV voter imports are supported.", "error")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    try:
        voters = parse_voter_csv(await voter_file.read(), VOTER_CODE_DIGITS)
        imported_count = import_voters(db, voters, replace_existing == "yes")
        set_admin_notice(request, f"Imported {imported_count} voter records.")
    except AdminActionError as exc:
        set_admin_notice(request, str(exc), "error")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/voters/{voter_id}/delete")
def remove_admin_voter(
    voter_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_admin_request(request, csrf_token)
    try:
        delete_voter(db, voter_id)
        set_admin_notice(request, "Voter removed.")
    except AdminActionError as exc:
        set_admin_notice(request, str(exc), "error")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/voters/reset-all-codes")
def admin_reset_all_voter_codes(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_admin_request(request, csrf_token)
    try:
        count = reset_all_voter_codes(db, VOTER_CODE_DIGITS)
        set_admin_notice(request, f"All codes reset. {count} voter(s) updated.")
    except AdminActionError as exc:
        set_admin_notice(request, str(exc), "error")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/voters/{voter_id}/reset-code")
def admin_reset_voter_code(
    voter_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_admin_request(request, csrf_token)
    try:
        voter, code = reset_voter_code(db, voter_id, VOTER_CODE_DIGITS)
        set_admin_notice(request, f'Code reset for "{voter.name}". New code: {code}')
    except AdminActionError as exc:
        set_admin_notice(request, str(exc), "error")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/nuke", response_class=HTMLResponse)
def admin_nuke_confirm(request: Request, db: Session = Depends(get_db)):
    if not ensure_admin_session(request):
        return apply_no_store(RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER))
    stats = get_election_stats(db)
    return apply_no_store(templates.TemplateResponse(
        "admin_nuke_confirm.html",
        {
            "request": request,
            "csrf_token": get_admin_csrf_token(request),
            "stats": stats,
            "disable_cache": True,
        },
    ))


@app.post("/admin/nuke")
def admin_nuke_execute(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_admin_request(request, csrf_token)
    try:
        stats = nuke_all_records(db)
        set_admin_notice(
            request,
            f"All records deleted: {stats['voter_count']} voters, {stats['candidate_count']} candidates, {stats['vote_count']} votes removed.",
        )
    except AdminActionError as exc:
        set_admin_notice(request, str(exc), "error")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return apply_no_store(RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER))


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
