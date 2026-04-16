from __future__ import annotations

from functools import wraps
from html import escape
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from .config import Config, ensure_dirs
    from .db import (
        create_user,
        delete_user,
        get_ticket,
        get_user_by_username,
        init_db,
        insert_log,
        list_logs_for_ticket,
        list_tickets,
        list_users,
        set_user_role,
        upsert_ticket,
        user_count,
    )
    from .token_utils import verify_transcript_token
except ImportError:
    from config import Config, ensure_dirs
    from db import (
        create_user,
        delete_user,
        get_ticket,
        get_user_by_username,
        init_db,
        insert_log,
        list_logs_for_ticket,
        list_tickets,
        list_users,
        set_user_role,
        upsert_ticket,
        user_count,
    )
    from token_utils import verify_transcript_token

ensure_dirs()

app = Flask(__name__)
app.secret_key = Config.FLASK_SECRET_KEY

init_db()


def create_app() -> Flask:
    return app


def _resolve_transcript_path(transcript_path: str) -> Path:
    path = Path(transcript_path)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parent / transcript_path).resolve()
    return path


def _render_transcript_html(data: dict) -> str:
    transcript_html = (data.get("transcript_html") or "").strip()
    if transcript_html:
        return transcript_html

    transcript_text = data.get("transcript_text") or ""
    if transcript_text:
        return f"<pre>{escape(transcript_text)}</pre>"

    return ""


# ---------------- API KEY SECURITY ----------------
def api_key_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = Config.LOG_API_KEY
        if not expected:
            return jsonify({"ok": False, "error": "server_not_configured"}), 500

        provided = request.headers.get("X-API-KEY")
        if provided != expected:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        return fn(*args, **kwargs)

    return wrapper


# ---------------- AUTH HELPERS ----------------
def current_user():
    if "username" not in session:
        return None
    return get_user_by_username(session["username"])


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def role_required(*roles: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            u = current_user()
            if not u:
                return redirect(url_for("login", next=request.path))
            if u["role"] not in roles:
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------- SETUP (FIRST RUN) ----------------
@app.get("/setup")
def setup_page():
    if user_count() > 0:
        return redirect(url_for("login"))
    return render_template("setup.html")


@app.post("/setup")
def setup_post():
    if user_count() > 0:
        return redirect(url_for("login"))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if not username or len(password) < 6:
        return render_template(
            "setup.html", error="Username nötig und Passwort min. 6 Zeichen."
        )

    create_user(username, generate_password_hash(password), "owner")
    session["username"] = username
    return redirect(url_for("tickets_page"))


# ---------------- LOGIN/LOGOUT ----------------
@app.get("/login")
def login():
    if current_user():
        return redirect(url_for("tickets_page"))
    if user_count() == 0:
        return redirect(url_for("setup_page"))
    return render_template("login.html")


@app.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    u = get_user_by_username(username)
    if not u or not check_password_hash(u["password_hash"], password):
        return render_template("login.html", error="Login falsch.")
    session["username"] = username
    return redirect(url_for("tickets_page"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- PAGES ----------------
@app.get("/")
def home():
    if user_count() == 0:
        return redirect(url_for("setup_page"))
    if not current_user():
        return redirect(url_for("login"))
    return redirect(url_for("tickets_page"))


@app.get("/tickets")
@login_required
def tickets_page():
    u = current_user()
    q = request.args.get("q", "")
    limit_raw = request.args.get("limit", "200")
    try:
        limit = max(1, min(1000, int(limit_raw)))
    except ValueError:
        limit = 200

    items = list_tickets(q=q, limit=limit)
    return render_template(
        "tickets.html",
        items=items,
        q=q,
        limit=limit,
        role=u["role"],
        username=u["username"],
    )


@app.get("/tickets/<ticket_id>")
@login_required
def ticket_detail(ticket_id: str):
    u = current_user()
    t = get_ticket(ticket_id)
    if not t:
        abort(404)

    logs = list_logs_for_ticket(ticket_id, limit=200)
    return render_template(
        "ticket_detail.html", t=t, logs=logs, role=u["role"], username=u["username"]
    )


@app.get("/tickets/<ticket_id>/transcript")
@login_required
def ticket_transcript(ticket_id: str):
    t = get_ticket(ticket_id)
    if not t or not t.get("transcript_path"):
        abort(404)

    path = _resolve_transcript_path(t["transcript_path"])
    if not path.exists():
        abort(404)

    html = path.read_text(encoding="utf-8")
    u = current_user()
    return render_template(
        "transcript.html",
        ticket_id=ticket_id,
        html=html,
        username=u["username"] if u else None,
        role=u["role"] if u else None,
    )


# ---------------- PUBLIC TRANSCRIPT (TOKEN LINK) ----------------
@app.get("/t/<ticket_id>")
def public_transcript(ticket_id: str):
    """
    Link für Ticket-Ersteller (ohne Login), aber nur mit Token.
    Beispiel: /t/123?token=XYZ
    """
    token = request.args.get("token") or ""
    if not token:
        if current_user():
            return ticket_transcript(ticket_id)
        abort(403)

    data = verify_transcript_token(
        app.secret_key, token, max_age_seconds=60 * 60 * 24 * 7
    )  # 7 Tage
    if not data:
        abort(403)

    if str(data.get("ticket_id")) != str(ticket_id):
        abort(403)

    t = get_ticket(ticket_id)
    if not t:
        abort(404)

    # Optional extra check (wenn creator_user_id gespeichert ist):
    # if str(t.get("creator_user_id")) != str(data.get("user_id")):
    #     abort(403)

    transcript_path = t.get("transcript_path") or ""
    if not transcript_path:
        abort(404)

    path = _resolve_transcript_path(transcript_path)
    if not path.exists():
        abort(404)

    html = path.read_text(encoding="utf-8")
    u = current_user()
    return render_template(
        "transcript.html",
        ticket_id=ticket_id,
        html=html,
        username=u["username"] if u else None,
        role=u["role"] if u else None,
    )


# ---------------- OWNER ADMIN ----------------
@app.get("/admin/users")
@role_required("owner")
def admin_users():
    users = list_users()
    return render_template(
        "admin_users.html",
        users=users,
        username=current_user()["username"],
        role="owner",
    )


@app.post("/admin/users/create")
@role_required("owner")
def admin_users_create():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    role = request.form.get("role") or "discord_mod"
    if role not in {"owner", "discord_mod", "twitch_mod"}:
        role = "discord_mod"
    if not username or len(password) < 6:
        return redirect(url_for("admin_users"))

    create_user(username, generate_password_hash(password), role)
    return redirect(url_for("admin_users"))


@app.post("/admin/users/delete")
@role_required("owner")
def admin_users_delete():
    user_id = int(request.form.get("user_id"))
    delete_user(user_id)
    return redirect(url_for("admin_users"))


@app.post("/admin/users/role")
@role_required("owner")
def admin_users_role():
    user_id = int(request.form.get("user_id"))
    role = request.form.get("role") or "discord_mod"
    if role not in {"owner", "discord_mod", "twitch_mod"}:
        role = "discord_mod"
    set_user_role(user_id, role)
    return redirect(url_for("admin_users"))


# ---------------- API: LOGS (OPTIONAL) ----------------
@app.post("/api/logs")
@api_key_required
def api_logs():
    data = request.get_json(silent=True) or {}
    if not data.get("ticket_id"):
        return jsonify({"ok": False, "error": "ticket_id missing"}), 400
    insert_log(data)
    return jsonify({"ok": True})


# ---------------- API: TICKET CLOSE + TRANSCRIPT UPLOAD ----------------
@app.post("/api/tickets/close")
@api_key_required
def api_ticket_close():
    """
    Bot sendet:
    {
      "ticket_id": "123",
      "guild_id": "...",
      "channel_id": "...",
      "creator_user_id": "123456789",
      "status": "closed",
      "subject": "Support",
      "closed_at": "2026-02-17T09:00:00Z",
      "transcript_html": "<html>...</html>"
    }
    """
    data = request.get_json(silent=True) or {}
    ticket_id = str(data.get("ticket_id") or "").strip()
    if not ticket_id:
        return jsonify({"ok": False, "error": "ticket_id missing"}), 400

    transcript_html = _render_transcript_html(data)
    if not transcript_html:
        return jsonify({"ok": False, "error": "transcript content missing"}), 400

    # Datei speichern
    transcript_rel = f"data/transcripts/{ticket_id}.html"
    transcript_abs = (Path(__file__).resolve().parent / transcript_rel).resolve()
    transcript_abs.parent.mkdir(parents=True, exist_ok=True)
    transcript_abs.write_text(transcript_html, encoding="utf-8")

    upsert_ticket(
        {
            "ticket_id": ticket_id,
            "guild_id": data.get("guild_id"),
            "channel_id": data.get("channel_id") or ticket_id,
            "creator_user_id": str(
                data.get("creator_user_id") or data.get("creator_id") or ""
            ),
            "status": data.get("status") or "closed",
            "subject": data.get("subject") or data.get("category_label") or "",
            "closed_at": data.get("closed_at") or "",
            "transcript_path": transcript_rel,  # relativ speichern
        }
    )

    return jsonify(
        {"ok": True, "ticket_id": ticket_id, "transcript_path": transcript_rel}
    )


# Bot zusammen mit app.py starten oder zentrale Datei anlegen
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=Config.PORT, debug=True)
