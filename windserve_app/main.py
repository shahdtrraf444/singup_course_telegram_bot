import os
import uuid
from pathlib import Path
from typing import Dict, Any, List
import datetime as _dt

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .data import YEARS, material_details, COURSES, get_course
import requests
from app.models import User, CourseEnrollment
from app.db import init_db

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(BASE_DIR))).resolve()
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(DATA_DIR / "uploads"))).resolve()
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(DATA_DIR / "storage"))).resolve()
GROUP_LINKS_PATH = ROOT_DIR / "data" / "group_links.json"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "messages.json").write_text("[]", encoding="utf-8") if not (STORAGE_DIR / "messages.json").exists() else None
(STORAGE_DIR / "broadcast.json").write_text("[]", encoding="utf-8") if not (STORAGE_DIR / "broadcast.json").exists() else None
(STORAGE_DIR / "proofs.json").write_text("{}", encoding="utf-8") if not (STORAGE_DIR / "proofs.json").exists() else None

app = FastAPI(title="WindServe Educational Platform")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals['now'] = lambda: _dt.datetime.now()


# Simple session id via cookie
@app.middleware("http")
async def ensure_session(request: Request, call_next):
    sid = request.cookies.get("sid")
    response = await call_next(request)
    if not sid:
        sid = uuid.uuid4().hex
        response.set_cookie("sid", sid, max_age=60 * 60 * 24 * 30, httponly=False)
    return response


@app.on_event("startup")
async def startup():
    mongo_url = os.getenv("MONGODB_URL")
    db_name = os.getenv("MONGODB_DB_NAME")
    if mongo_url and db_name:
        await init_db(mongo_url, db_name)


def _tg_send_message(chat_id: int, text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": text})
    except Exception:
        pass


def _tg_send_photo_to_admin(file_path: Path, caption: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    admin_id = os.getenv("TELEGRAM_ADMIN_ID")
    if not token or not admin_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        with file_path.open("rb") as fp:
            files = {"photo": fp}
            data = {"chat_id": int(admin_id), "caption": caption}
            requests.post(url, data=data, files=files)
    except Exception:
        pass


def _get_group_link(item_type: str, item_id: str) -> str:
    import json
    try:
        with GROUP_LINKS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        key = "courses" if item_type == "course" else "materials"
        store = (data.get(key) or {})
        # direct hit
        link = store.get(item_id)
        if link:
            return link
        # aliases for materials ids used in UI
        aliases = {
            "y4_s1_nn": "year4_sem1_neural_networks",
            "y4_s1_multimedia": "year4_sem1_multimedia",
            "y4_s1_concurrent": "year4_sem1_concurrent",
            "y3_s1_os1": "year3_sem1_os",
            "y3_s2_ai_principles": "year3_sem2_ai_principles",
            "y3_s1_algo_ds": "year3_sem1_algorithms",
        }
        alt = aliases.get(item_id)
        return store.get(alt, "") if alt else ""
    except Exception:
        return ""


def _read_json(path: Path):
    import json
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Any):
    import json
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request}
    )


@app.get("/api/health")
async def api_health():
    return {"status": "ok"}


@app.get("/materials", response_class=HTMLResponse)
async def materials(request: Request):
    return templates.TemplateResponse(
        "materials.html",
        {"request": request, "years": YEARS},
    )


@app.get("/materials/{year_id}/{semester}", response_class=HTMLResponse)
async def list_semester(request: Request, year_id: int, semester: int):
    year = next((y for y in YEARS if y["id"] == year_id), None)
    mats = year["semesters"].get(semester, []) if year else []
    details = [{**m, "details": material_details(m["id"])} for m in mats]
    return templates.TemplateResponse(
        "semester.html",
        {
            "request": request,
            "year": year,
            "semester": semester,
            "materials": details,
            "sham_number": os.getenv("SHAM_CASH_NUMBER", ""),
            "haram_number": os.getenv("HARAM_NUMBER", ""),
        },
    )


@app.get("/courses", response_class=HTMLResponse)
async def courses_page(request: Request):
    return templates.TemplateResponse(
        "courses.html", {"request": request, "courses": COURSES}
    )


@app.get("/courses/{cid}", response_class=HTMLResponse)
async def course_details_page(request: Request, cid: str):
    course = get_course(cid)
    if not course:
        return RedirectResponse(url="/courses")
    # Enrich beginner with seat+monthly pricing
    seat_price = "50,000 ل.س"
    monthly_price = "100,000 ل.س"
    return templates.TemplateResponse(
        "course_details.html",
        {
            "request": request,
            "course": course,
            "seat_price": seat_price,
            "monthly_price": monthly_price,
            "sham_number": os.getenv("SHAM_CASH_NUMBER", ""),
            "haram_number": os.getenv("HARAM_NUMBER", ""),
        },
    )


# Contact messages
@app.get("/contact", response_class=HTMLResponse)
async def contact_form(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})


@app.post("/contact")
async def submit_contact(request: Request, message: str = Form(...)):
    sid = request.cookies.get("sid") or uuid.uuid4().hex
    messages = _read_json(STORAGE_DIR / "messages.json") or []
    messages.append({"sid": sid, "message": message})
    _write_json(STORAGE_DIR / "messages.json", messages)
    # Notify admin via Telegram
    admin_id = os.getenv("TELEGRAM_ADMIN_ID")
    if admin_id and admin_id.isdigit():
        _tg_send_message(int(admin_id), f"رسالة جديدة من موقع الويب\nSID: {sid}\n{message}")
    return RedirectResponse("/inbox", status_code=303)


@app.get("/inbox", response_class=HTMLResponse)
async def inbox(request: Request):
    # Show broadcasts + own proofs status
    broadcasts = _read_json(STORAGE_DIR / "broadcast.json") or []
    sid = request.cookies.get("sid")
    proofs = (_read_json(STORAGE_DIR / "proofs.json") or {}).get(sid, [])
    return templates.TemplateResponse(
        "inbox.html",
        {"request": request, "broadcasts": broadcasts, "proofs": proofs},
    )


@app.get("/admin/messages", response_class=HTMLResponse)
async def admin_messages(request: Request):
    messages = _read_json(STORAGE_DIR / "messages.json") or []
    broadcasts = _read_json(STORAGE_DIR / "broadcast.json") or []
    return templates.TemplateResponse(
        "admin_messages.html",
        {"request": request, "messages": list(reversed(messages)), "broadcasts": list(reversed(broadcasts))},
    )


@app.post("/admin/broadcast")
async def admin_broadcast(title: str = Form(...), body: str = Form("")):
    broadcasts = _read_json(STORAGE_DIR / "broadcast.json") or []
    broadcasts.append({"title": title, "body": body})
    _write_json(STORAGE_DIR / "broadcast.json", broadcasts)
    # send to all registered users via Telegram
    try:
        users = await User.find_all().to_list()
        for u in users:
            _tg_send_message(u.telegram_id, f"{title}\n\n{body}")
    except Exception:
        pass
    return RedirectResponse("/admin/messages", status_code=303)


# Payment
@app.post("/payment/upload")
async def upload_proof(
    request: Request,
    item_type: str = Form(...),  # course|material
    item_id: str = Form(...),
    payment_method: str = Form(...),
    telegram_id: str = Form(...),
    file: UploadFile = File(...),
):
    sid = request.cookies.get("sid") or uuid.uuid4().hex
    user_dir = UPLOADS_DIR / sid
    user_dir.mkdir(exist_ok=True, parents=True)
    target = user_dir / f"{uuid.uuid4().hex}_{file.filename}"
    with target.open("wb") as f:
        f.write(await file.read())
    proofs = _read_json(STORAGE_DIR / "proofs.json") or {}
    entry = {
        "id": uuid.uuid4().hex,
        "item_type": item_type,
        "item_id": item_id,
        "file": (Path("uploads") / sid / target.name).as_posix(),
        "payment_method": payment_method,
        "telegram_id": int(telegram_id) if telegram_id.isdigit() else None,
        "sid": sid,
        "status": "pending",
    }
    proofs.setdefault(sid, []).append(entry)
    _write_json(STORAGE_DIR / "proofs.json", proofs)
    cap = f"Proof upload\nType: {item_type}\nID: {item_id}\nMethod: {payment_method}\nTG: {telegram_id or '-'}"
    _tg_send_photo_to_admin(target, cap)
    return RedirectResponse("/inbox", status_code=303)


@app.post("/payment/proof/{sid}/{pid}/approve")
async def admin_approve_proof(sid: str, pid: str):
    proofs = _read_json(STORAGE_DIR / "proofs.json") or {}
    found = None
    for e in proofs.get(sid, []):
        if e["id"] == pid:
            e["status"] = "approved"
            found = e
            break
    _write_json(STORAGE_DIR / "proofs.json", proofs)
    if found:
        link = _get_group_link(found["item_type"], found["item_id"]) or ""
        if found.get("telegram_id"):
            msg = "تمت الموافقة على الدفع ✅. أهلاً بك! رابط المجموعة: " + (link or "")
            _tg_send_message(found["telegram_id"], msg)
            try:
                tg_id = found.get("telegram_id")
                if tg_id:
                    user = await User.find_one(User.telegram_id == tg_id)
                    if not user:
                        user = User(
                            telegram_id=tg_id,
                            full_name="",
                            phone="",
                            email="",
                        )
                    course_id = found.get("item_id")
                    payment_method = found.get("payment_method") or "sham"
                    updated = False
                    for enr in user.courses:
                        if enr.course_id == course_id:
                            enr.payment_method = payment_method
                            enr.approval_status = "approved"
                            updated = True
                            break
                    if not updated and course_id:
                        user.courses.append(
                            CourseEnrollment(
                                course_id=course_id,
                                payment_method=payment_method,
                                approval_status="approved",
                            )
                        )
                    await user.save()
            except Exception:
                pass
    return RedirectResponse("/admin/proofs", status_code=303)


@app.post("/payment/proof/{sid}/{pid}/reject")
async def admin_reject_proof(sid: str, pid: str):
    proofs = _read_json(STORAGE_DIR / "proofs.json") or {}
    for e in proofs.get(sid, []):
        if e["id"] == pid:
            e["status"] = "rejected"
            if e.get("telegram_id"):
                _tg_send_message(e["telegram_id"], "تم رفض الدفع ❌. يرجى التواصل مع الإدارة.")
            break
    _write_json(STORAGE_DIR / "proofs.json", proofs)
    return RedirectResponse("/admin/proofs", status_code=303)


@app.get("/admin/proofs", response_class=HTMLResponse)
async def admin_proofs(request: Request):
    data = _read_json(STORAGE_DIR / "proofs.json") or {}
    rows: List[Dict[str, Any]] = []
    for sid, lst in data.items():
        for e in lst:
            rows.append({**e, "sid": sid})
    rows = list(reversed(rows))
    return templates.TemplateResponse("admin_proofs.html", {"request": request, "rows": rows})


@app.get("/admin/students", response_class=HTMLResponse)
async def admin_students(request: Request):
    try:
        users = await User.find_all().to_list()
    except Exception:
        users = []
    return templates.TemplateResponse("admin_students.html", {"request": request, "users": users, "total": len(users)})


@app.get("/admin/students/{tid}/message", response_class=HTMLResponse)
async def admin_student_message_form(request: Request, tid: int):
    return templates.TemplateResponse("admin_student_message.html", {"request": request, "tid": tid})


@app.post("/admin/students/{tid}/message")
async def admin_student_message(tid: int, body: str = Form("")):
    if body:
        _tg_send_message(tid, body)
    return RedirectResponse(f"/admin/students", status_code=303)


@app.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(request: Request):
    try:
        users = await User.find_all().to_list()
    except Exception:
        users = []
    names = [u.full_name for u in users]
    return templates.TemplateResponse("admin_stats.html", {"request": request, "count": len(users), "names": names})
