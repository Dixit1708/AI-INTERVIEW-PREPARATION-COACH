"""AI Interview Preparation Coach - Flask + SQLite + JWT."""
import os, time, json, hmac, hashlib, base64, sqlite3, uuid
from collections import Counter
from functools import wraps
from flask import Flask, request, jsonify, g, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import coach

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
DB_PATH = os.path.join(DATA_DIR, "coach.db")
os.makedirs(DATA_DIR, exist_ok=True)
DAILY_LIMIT = int(os.environ.get("DAILY_SESSION_LIMIT", "30"))     # protects AI usage/cost
TOKEN_TTL = 60 * 60 * 24 * 7

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

# ------------------------------------------------------------ JWT
def _secret():
    if os.environ.get("SECRET_KEY"): return os.environ["SECRET_KEY"].encode()
    p = os.path.join(DATA_DIR, "secret.key")
    if not os.path.exists(p):
        with open(p, "w") as f: f.write(uuid.uuid4().hex + uuid.uuid4().hex)
    return open(p).read().encode()
SECRET = _secret()
_b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
_unb64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def make_token(uid):
    h = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    b = _b64(json.dumps({"sub": uid, "exp": int(time.time()) + TOKEN_TTL}).encode())
    return f"{h}.{b}." + _b64(hmac.new(SECRET, f"{h}.{b}".encode(), hashlib.sha256).digest())

def read_token(tok):
    try:
        h, b, s = tok.split(".")
        if not hmac.compare_digest(s, _b64(hmac.new(SECRET, f"{h}.{b}".encode(), hashlib.sha256).digest())): return None
        d = json.loads(_unb64(b)); return d["sub"] if d["exp"] > time.time() else None
    except Exception: return None

# ------------------------------------------------------------ DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
  email TEXT NOT NULL, password_hash TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL, itype TEXT NOT NULL, level TEXT NOT NULL, total INTEGER NOT NULL, mode TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', avg_score REAL, created_at INTEGER NOT NULL, finished_at INTEGER);
CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL, question TEXT NOT NULL, hint TEXT, keywords TEXT NOT NULL, ref_answer TEXT,
  answer TEXT, score REAL, strengths TEXT, improvements TEXT, model_answer TEXT, seconds INTEGER, eval_mode TEXT, answered_at INTEGER,
  UNIQUE(session_id, idx));
CREATE INDEX IF NOT EXISTS idx_sess_user ON sessions(user_id);
"""
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH); g.db.row_factory = sqlite3.Row; g.db.execute("PRAGMA foreign_keys=ON")
    return g.db
@app.teardown_appcontext
def _close(_):
    d = g.pop("db", None)
    if d: d.close()
with sqlite3.connect(DB_PATH) as _c: _c.executescript(SCHEMA)

def err(m, c=400): return jsonify(error=m), c
def auth_required(fn):
    @wraps(fn)
    def w(*a, **k):
        h = request.headers.get("Authorization", "")
        uid = read_token(h[7:]) if h.startswith("Bearer ") else None
        u = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
        if not u: return err("Unauthorized", 401)
        g.user = u; return fn(*a, **k)
    return w

@app.route("/")
def index(): return send_from_directory("static", "index.html")

# ------------------------------------------------------------ auth
_attempts = {}
def _ip(): return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?"

@app.post("/api/auth/register")
def register():
    d = request.get_json(silent=True) or {}
    u, e, p = (d.get("username") or "").strip(), (d.get("email") or "").strip(), d.get("password") or ""
    if len(u) < 3 or not u.replace("_", "").replace(".", "").isalnum(): return err("Username: 3+ letters/digits/_/.")
    if "@" not in e: return err("Enter a valid email")
    if len(p) < 6: return err("Password must be at least 6 characters")
    try:
        cur = db().execute("INSERT INTO users(username,email,password_hash,created_at) VALUES(?,?,?,?)", (u, e, generate_password_hash(p), int(time.time())))
        db().commit()
    except sqlite3.IntegrityError: return err("Username already taken", 409)
    return jsonify(token=make_token(cur.lastrowid), username=u), 201

@app.post("/api/auth/login")
def login():
    now, ip = time.time(), _ip()
    recent = [t for t in _attempts.get(ip, []) if now - t < 60]
    if len(recent) >= 10: return err("Too many attempts. Try again in a minute.", 429)
    d = request.get_json(silent=True) or {}
    r = db().execute("SELECT * FROM users WHERE username=?", ((d.get("username") or "").strip(),)).fetchone()
    if not r or not check_password_hash(r["password_hash"], d.get("password") or ""):
        _attempts[ip] = recent + [now]; return err("Invalid username or password", 401)
    return jsonify(token=make_token(r["id"]), username=r["username"])

@app.get("/api/me")
@auth_required
def me(): return jsonify(username=g.user["username"], email=g.user["email"])

@app.get("/api/config")
@auth_required
def config():
    return jsonify(roles=coach.ROLES, types=[dict(id=k, label=v, hint=coach.HINTS[k]) for k, v in coach.TYPES.items()], levels=coach.LEVELS, ai=coach.ai_available())

# ------------------------------------------------------------ sessions
def payload(s):
    qs = []
    for r in db().execute("SELECT * FROM answers WHERE session_id=? ORDER BY idx", (s["id"],)):
        q = dict(idx=r["idx"], question=r["question"], hint=r["hint"], answered=r["answer"] is not None)
        if q["answered"]:
            q.update(answer=r["answer"], score=r["score"], strengths=json.loads(r["strengths"] or "[]"), improvements=json.loads(r["improvements"] or "[]"),
                     model_answer=r["model_answer"], seconds=r["seconds"], eval_mode=r["eval_mode"])
        qs.append(q)
    out = {k: s[k] for k in ("id", "role", "itype", "level", "total", "mode", "status", "avg_score", "created_at", "finished_at")}
    out["questions"] = qs
    if s["status"] == "done":
        imp = Counter(i for q in qs for i in q.get("improvements", [])); st = Counter(i for q in qs for i in q.get("strengths", []))
        out["insights"] = dict(focus=imp.most_common(1)[0][0] if imp else None, strength=st.most_common(1)[0][0] if st else None)
    return out

def owned(sid):
    return db().execute("SELECT * FROM sessions WHERE id=? AND user_id=?", (sid, g.user["id"])).fetchone()

def finish(s):
    row = db().execute("SELECT AVG(score) a, COUNT(*) c FROM answers WHERE session_id=? AND answer IS NOT NULL", (s["id"],)).fetchone()
    if not row["c"]:
        db().execute("DELETE FROM sessions WHERE id=?", (s["id"],)); db().commit(); return None
    db().execute("UPDATE sessions SET status='done', avg_score=?, finished_at=? WHERE id=?", (round(row["a"], 1), int(time.time()), s["id"])); db().commit()
    return owned(s["id"])

@app.post("/api/sessions")
@auth_required
def create_session():
    d = request.get_json(silent=True) or {}
    role = (d.get("custom_role") or "").strip()[:60] if d.get("role") == "custom" else d.get("role")
    itype, level, count = d.get("itype"), d.get("level"), d.get("count", 5)
    if not role or (d.get("role") != "custom" and role not in coach.ROLES): return err("Choose a role")
    if itype not in coach.TYPES or level not in coach.LEVELS: return err("Invalid interview type or level")
    try: count = max(1, min(10, int(count)))
    except (TypeError, ValueError): return err("Invalid question count")
    if db().execute("SELECT COUNT(*) FROM sessions WHERE user_id=? AND created_at>?", (g.user["id"], time.time() - 86400)).fetchone()[0] >= DAILY_LIMIT:
        return err("Daily practice limit reached. Come back tomorrow!", 429)
    qs, mode = coach.generate_questions(role, itype, level, count)
    sid = db().execute("INSERT INTO sessions(user_id,role,itype,level,total,mode,created_at) VALUES(?,?,?,?,?,?,?)",
                       (g.user["id"], role, itype, level, len(qs), mode, int(time.time()))).lastrowid
    for i, q in enumerate(qs):
        db().execute("INSERT INTO answers(session_id,idx,question,hint,keywords,ref_answer) VALUES(?,?,?,?,?,?)", (sid, i, q["q"], q["hint"], json.dumps(q["kw"]), q["a"]))
    db().commit()
    return jsonify(id=sid, mode=mode, total=len(qs)), 201

@app.get("/api/sessions")
@auth_required
def list_sessions():
    rows = db().execute("""SELECT s.*, (SELECT COUNT(*) FROM answers a WHERE a.session_id=s.id AND a.answer IS NOT NULL) AS answered
                           FROM sessions s WHERE user_id=? ORDER BY id DESC LIMIT 100""", (g.user["id"],)).fetchall()
    return jsonify(sessions=[{k: r[k] for k in ("id", "role", "itype", "level", "total", "mode", "status", "avg_score", "created_at", "finished_at", "answered")} for r in rows])

@app.get("/api/sessions/<int:sid>")
@auth_required
def get_session(sid):
    s = owned(sid)
    return jsonify(payload(s)) if s else err("Session not found", 404)

@app.delete("/api/sessions/<int:sid>")
@auth_required
def delete_session(sid):
    if not owned(sid): return err("Session not found", 404)
    db().execute("DELETE FROM sessions WHERE id=?", (sid,)); db().commit(); return jsonify(ok=True)

@app.post("/api/sessions/<int:sid>/answer")
@auth_required
def submit_answer(sid):
    s = owned(sid)
    if not s: return err("Session not found", 404)
    if s["status"] != "active": return err("This session is already finished", 409)
    d = request.get_json(silent=True) or {}
    answer = str(d.get("answer") or "").strip()[:4000]
    row = db().execute("SELECT * FROM answers WHERE session_id=? AND idx=?", (sid, d.get("idx"))).fetchone()
    if not row: return err("Question not found", 404)
    if row["answer"] is not None: return err("Already answered", 409)
    fb = coach.evaluate(row["question"], answer, json.loads(row["keywords"]), s["itype"], s["level"], s["role"], row["ref_answer"])
    secs = max(0, min(3600, int(d.get("seconds") or 0))) if str(d.get("seconds") or "0").lstrip("-").isdigit() else 0
    db().execute("""UPDATE answers SET answer=?, score=?, strengths=?, improvements=?, model_answer=?, seconds=?, eval_mode=?, answered_at=? WHERE id=?""",
                 (answer, fb["score"], json.dumps(fb["strengths"]), json.dumps(fb["improvements"]), fb["model_answer"], secs, fb["mode"], int(time.time()), row["id"]))
    db().commit()
    left = db().execute("SELECT COUNT(*) FROM answers WHERE session_id=? AND answer IS NULL", (sid,)).fetchone()[0]
    s = finish(s) if left == 0 else owned(sid)
    return jsonify(feedback=fb, done=left == 0, session=payload(s))

@app.post("/api/sessions/<int:sid>/finish")
@auth_required
def finish_session(sid):
    s = owned(sid)
    if not s: return err("Session not found", 404)
    if s["status"] == "done": return jsonify(session=payload(s))
    s = finish(s)
    return jsonify(session=payload(s)) if s else jsonify(deleted=True)

# ------------------------------------------------------------ stats
@app.get("/api/stats")
@auth_required
def stats():
    uid = g.user["id"]
    done = db().execute("SELECT * FROM sessions WHERE user_id=? AND status='done' ORDER BY finished_at", (uid,)).fetchall()
    scores = [r["avg_score"] for r in done]
    by = {}
    for r in done: by.setdefault(r["itype"], []).append(r["avg_score"])
    days = {r["finished_at"] // 86400 for r in done}; today = int(time.time()) // 86400
    d = today if today in days else today - 1 if today - 1 in days else None; streak = 0
    while d in days: streak += 1; d -= 1
    a = db().execute("""SELECT COUNT(*) c, COALESCE(SUM(seconds),0) t FROM answers a JOIN sessions s ON s.id=a.session_id
                        WHERE s.user_id=? AND a.answer IS NOT NULL AND a.answer<>''""", (uid,)).fetchone()
    return jsonify(sessions=len(done), avg=round(sum(scores) / len(scores), 1) if scores else 0, best=max(scores) if scores else 0, streak=streak,
                   answers=a["c"], minutes=round(a["t"] / 60),
                   by_type=[dict(type=k, label=coach.TYPES[k], avg=round(sum(v) / len(v), 1), count=len(v)) for k, v in by.items()],
                   recent=[dict(id=r["id"], score=r["avg_score"], itype=r["itype"], role=r["role"], date=r["finished_at"]) for r in done[-10:]])

@app.errorhandler(413)
def _big(_): return err("Request too large", 413)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG", "0") == "1")
