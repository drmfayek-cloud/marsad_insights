"""MARSAD Insights: stakeholder dashboard for the CNHI audit and approval project.

Run locally:  MARSAD_DEMO=1 python app.py   (synthetic data, demo accounts)
Production:   gunicorn -w 2 -b 0.0.0.0:8000 app:app   (see DEPLOY.md)
"""
import datetime as dt
import hashlib
import os
import secrets
import tempfile

from flask import (Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for)

from insights import auth, config, db, deid, kpi, store, theme
from insights.i18n import lang, pick, t
from insights.parsers import ParseError, parse
from insights.xlsx_templates import governance_template

ALLOWED = {".xlsx", ".xlsm"}


def env_flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def create_app():
    app = Flask(__name__)
    data_dir = os.path.abspath(os.environ.get("MARSAD_DATA", os.path.join(os.path.dirname(__file__), "data")))
    os.makedirs(data_dir, exist_ok=True)
    key_file = os.path.join(data_dir, "secret.key")
    secret = os.environ.get("MARSAD_SECRET_KEY", "")
    if not secret:
        if not os.path.exists(key_file):
            with open(key_file, "w") as f:
                f.write(secrets.token_hex(32))
            os.chmod(key_file, 0o600)
        secret = open(key_file).read().strip()
    app.config.update(SECRET_KEY=secret, MAX_CONTENT_LENGTH=40 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=env_flag("MARSAD_HTTPS", "1"))
    app.config["DEMO"] = env_flag("MARSAD_DEMO")
    app.config["REQUIRE_MFA"] = env_flag("MARSAD_REQUIRE_MFA", "0" if app.config["DEMO"] else "1")
    db.init(os.path.join(data_dir, "insights.db"))
    deid.init(data_dir)
    store.init(data_dir)
    bootstrap(app)

    app.jinja_env.globals.update(t=t, pick=pick, lang=lang, csrf_token=auth.csrf_token, ROLES=auth.ROLES, theme=theme,
                                 PAGES=config.PAGES, KINDS=store.KINDS, KINDS_AR=store.KINDS_AR)

    @app.before_request
    def before():
        g.user = auth.current_user()
        g.lang = session.get("lang") or (g.user["lang"] if g.user else "en")
        auth.check_csrf()

    @app.after_request
    def headers(resp):
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                                   "script-src 'self'; frame-ancestors 'none'; form-action 'self'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["X-Frame-Options"] = "DENY"
        if request.endpoint not in ("static",):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(400)
    @app.errorhandler(413)
    def err(e):
        msg = {403: "You do not have access to this page.", 404: "Page not found.",
               400: "The request could not be processed. Reload the page and try again.",
               413: "The file is larger than 40 MB."}.get(getattr(e, "code", 500), "Error")
        return render_template("error.html", msg=msg), getattr(e, "code", 500)

    # ------------------------------------------------------------------ sign-in
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            u = db.q1("SELECT * FROM users WHERE email=? AND active=1", (email,))
            session.clear()
            if u is None or auth.is_locked(u) or not auth.check_pw(request.form.get("password", ""), u["pw_hash"]):
                if u is not None and not auth.is_locked(u):
                    auth.register_failure(u)
                session["pending_email"] = email
                auth.audit("login_failed", email)
                flash(pick("Sign-in failed. Check the email and password, or wait 15 minutes after 5 attempts.",
                           "تعذر تسجيل الدخول. تحقق من البريد وكلمة المرور، أو انتظر 15 دقيقة بعد 5 محاولات."), "error")
                return render_template("login.html", demo_users=demo_users()), 401
            db.update("users", u["id"], failed_logins=0, locked_until="")
            session["pending_uid"] = u["id"]
            session["pending_email"] = u["email"]
            if u["mfa_enabled"]:
                return redirect(url_for("login_mfa"))
            if app.config["REQUIRE_MFA"]:
                return redirect(url_for("mfa_setup"))
            return finish_login(u)
        return render_template("login.html", demo_users=demo_users())

    def finish_login(u):
        nxt = session.get("next")
        session.clear()
        session.update(uid=u["id"], full=True, at=dt.datetime.now().timestamp(), lang=u["lang"] or "en")
        db.update("users", u["id"], last_login=db.now())
        g.user = u
        auth.audit("login")
        return redirect(nxt or url_for("page", slug="executive"))

    @app.route("/login/mfa", methods=["GET", "POST"])
    def login_mfa():
        uid = session.get("pending_uid")
        u = db.q1("SELECT * FROM users WHERE id=?", (uid,)) if uid else None
        if u is None:
            return redirect(url_for("login"))
        if request.method == "POST":
            if auth.check_totp(u["mfa_secret"], request.form.get("code")):
                return finish_login(u)
            auth.register_failure(u)
            flash(pick("The code is not valid. Use the current code from your authenticator app.",
                       "الرمز غير صحيح. استخدم الرمز الحالي من تطبيق المصادقة."), "error")
        return render_template("mfa.html")

    @app.route("/mfa/setup", methods=["GET", "POST"])
    def mfa_setup():
        uid = session.get("pending_uid")
        u = db.q1("SELECT * FROM users WHERE id=?", (uid,)) if uid else None
        if u is None:
            return redirect(url_for("login"))
        secret = session.get("mfa_secret") or auth.new_mfa_secret()
        session["mfa_secret"] = secret
        if request.method == "POST" and auth.check_totp(secret, request.form.get("code")):
            db.update("users", u["id"], mfa_secret=secret, mfa_enabled=1)
            session.pop("mfa_secret", None)
            return finish_login(db.q1("SELECT * FROM users WHERE id=?", (u["id"],)))
        if request.method == "POST":
            flash(pick("The code did not match. Check the phone's clock and try the next code.",
                       "الرمز غير مطابق. تحقق من ساعة الهاتف وجرب الرمز التالي."), "error")
        grouped = " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
        return render_template("mfa_setup.html", secret=grouped, uri=auth.otpauth_uri(secret, u["email"]))

    @app.route("/logout")
    def logout():
        if g.user:
            auth.audit("logout")
        session.clear()
        return redirect(url_for("login"))

    @app.route("/lang/<code>")
    def set_lang(code):
        if code in ("en", "ar"):
            session["lang"] = code
            if g.user:
                db.update("users", g.user["id"], lang=code)
        return redirect(request.referrer or url_for("page", slug="executive"))

    @app.route("/account", methods=["GET", "POST"])
    @auth.login_required
    def account():
        if request.method == "POST":
            cur, new, rep = request.form.get("current", ""), request.form.get("new", ""), request.form.get("repeat", "")
            problem = auth.pw_problem(new)
            if not auth.check_pw(cur, g.user["pw_hash"]):
                flash(pick("The current password is not correct.", "كلمة المرور الحالية غير صحيحة."), "error")
            elif new != rep:
                flash(pick("The new passwords do not match.", "كلمتا المرور الجديدتان غير متطابقتين."), "error")
            elif problem:
                flash(problem, "error")
            else:
                db.update("users", g.user["id"], pw_hash=auth.hash_pw(new), must_change_pw=0)
                auth.audit("password_changed")
                flash(pick("Password changed.", "تم تغيير كلمة المرور."), "ok")
                return redirect(url_for("page", slug="executive"))
        return render_template("account.html")

    # ------------------------------------------------------------------ dashboard pages
    @app.route("/")
    def home():
        return redirect(url_for("page", slug="executive"))

    @app.route("/p/<slug>")
    @auth.login_required
    def page(slug):
        pg = config.PAGE_BY_SLUG.get(slug) or abort(404)
        data = store.current()
        ms = kpi.months(data)
        period = request.args.get("period") or kpi.default_month(data)
        if period != "all" and period not in ms:
            period = kpi.default_month(data)
        tpa = request.args.get("tpa", "")
        tpa_list = kpi.tpas(data)
        if tpa and tpa not in tpa_list:
            tpa = ""
        snap = db.q1("SELECT * FROM snapshots WHERE month=?", (period,)) if period != "all" else None
        if snap and not tpa:
            stored = db.loads(snap["data"])
            results = kpi.deserialise({k: v for k, v in stored.get(lang(), stored.get("en", {})).items()
                                       if k in {x["id"] for x in config.kpis_for(pg["code"])}})
            badge = "approved"
        else:
            ctx = kpi.Ctx(data, period, tpa, internal=g.user["role"] in auth.INTERNAL)
            results = kpi.compute_page(pg["code"], ctx)
            badge = "filtered" if (snap and tpa) else "provisional"
        trend, sparks = None, {}
        if pg["code"] == "EX" and data:
            trend = kpi.exec_trend(kpi.Ctx(data, "all", tpa), selected=period)
            hist = kpi.history([k["id"] for k in config.kpis_for("EX")], data, period, tpa)
            sparks = {k: theme.sparkline(v, theme.style(k)[0]) for k, v in hist.items()}
        defs = config.kpis_for(pg["code"])
        return render_template("page.html", pg=pg, defs=defs, results=results, months=ms, period=period, tpa=tpa,
                               tpas=tpa_list, badge=badge, snap=snap, trend=trend, sparks=sparks, has_data=bool(data),
                               as_of=data_as_of())

    # ------------------------------------------------------------------ data uploads (admin)
    @app.route("/data", methods=["GET", "POST"])
    @auth.roles_required("admin")
    def data_page():
        if request.method == "POST":
            kind = request.form.get("kind")
            f = request.files.get("file")
            if kind not in store.KINDS or f is None or not f.filename:
                flash("Choose the workbook type and a file.", "error")
                return redirect(url_for("data_page"))
            ext = os.path.splitext(f.filename)[1].lower()
            if ext not in ALLOWED:
                flash("Upload an Excel workbook (.xlsx or .xlsm).", "error")
                return redirect(url_for("data_page"))
            raw = f.read()
            if raw[:2] != b"PK":
                flash("The file is not a valid Excel workbook.", "error")
                return redirect(url_for("data_page"))
            fd, tmp = tempfile.mkstemp(suffix=ext)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(raw)
                result = parse(kind, tmp, request.form.get("label", ""))
            except ParseError as e:
                auth.audit("upload_rejected", f"{kind} {f.filename}: {e}")
                flash(f"{store.KINDS[kind]}: {e}", "error")
                return redirect(url_for("data_page"))
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)            # the workbook itself is never kept
            uid = db.insert("uploads", kind=kind, filename=os.path.basename(f.filename)[:200],
                            sha256=hashlib.sha256(raw).hexdigest(), size=len(raw),
                            label=result["data"].get("quarter", "") if kind == "F4" else "",
                            status="staged", summary=db.dumps(result["summary"]), warnings=db.dumps(result["warnings"]),
                            created_by=g.user["email"], created_at=db.now())
            store.save(uid, result["data"])
            auth.audit("upload_staged", f"{kind} #{uid} {f.filename}")
            return redirect(url_for("data_view", uid=uid))
        ups = db.q("SELECT * FROM uploads WHERE status<>'discarded' ORDER BY id DESC LIMIT 60")
        cur = {k: db.q1("SELECT * FROM uploads WHERE id=?", (uid,)) for k, uid in store.current_ids().items()}
        return render_template("data.html", uploads=ups, current=cur)

    @app.route("/data/<int:uid>", methods=["GET", "POST"])
    @auth.roles_required("admin")
    def data_view(uid):
        up = db.q1("SELECT * FROM uploads WHERE id=?", (uid,)) or abort(404)
        if request.method == "POST":
            act = request.form.get("act")
            if act == "publish" and up["status"] in ("staged", "superseded"):
                store.publish(uid, g.user["email"])
                auth.audit("published", f"{up['kind']} #{uid}")
                flash(pick("Published. The dashboard now uses this version.", "تم النشر. تستخدم اللوحة هذه النسخة الآن."), "ok")
            elif act == "discard" and up["status"] == "staged":
                store.discard(uid)
                auth.audit("discarded", f"{up['kind']} #{uid}")
                flash(pick("Discarded.", "تم الاستبعاد."), "ok")
                return redirect(url_for("data_page"))
            return redirect(url_for("data_view", uid=uid))
        return render_template("data_view.html", up=up, summary=db.loads(up["summary"]), warnings=db.loads(up["warnings"], []),
                               is_current=store.current_ids().get(up["kind"]) == uid)

    @app.route("/data/template/governance.xlsx")
    @auth.roles_required("admin")
    def governance_xlsx():
        return Response(governance_template(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=MARSAD_Governance_Register_template.xlsx"})

    # ------------------------------------------------------------------ period close (admin)
    @app.route("/periods", methods=["GET", "POST"])
    @auth.roles_required("admin")
    def periods():
        data = store.current()
        if request.method == "POST":
            month, act = request.form.get("month", ""), request.form.get("act")
            if act == "close" and month in kpi.months(data):
                snap = {}
                saved_lang = g.lang
                for lg in ("en", "ar"):
                    g.lang = lg
                    ctx = kpi.Ctx(data, month, "", internal=False)
                    res = {}
                    for p in config.PAGES:
                        res.update(kpi.compute_page(p["code"], ctx))
                    snap[lg] = kpi.serialise(res)
                g.lang = saved_lang
                db.ex("INSERT OR REPLACE INTO snapshots(month,data,datasets,note,created_by,created_at) VALUES(?,?,?,?,?,?)",
                      (month, db.dumps(snap), db.dumps(store.current_ids()), request.form.get("note", "")[:300],
                       g.user["email"], db.now()))
                auth.audit("month_closed", month)
                flash(f"{month}: figures frozen as approved.", "ok")
            elif act == "reopen":
                db.ex("DELETE FROM snapshots WHERE month=?", (month,))
                auth.audit("month_reopened", month)
                flash(f"{month}: reopened; figures are live again.", "ok")
            return redirect(url_for("periods"))
        snaps = {r["month"]: r for r in db.q("SELECT month, note, created_by, created_at FROM snapshots")}
        return render_template("periods.html", months=list(reversed(kpi.months(data))), snaps=snaps)

    # ------------------------------------------------------------------ users and audit (admin)
    @app.route("/admin/users", methods=["GET", "POST"])
    @auth.roles_required("admin")
    def users():
        temp = None
        if request.method == "POST":
            act = request.form.get("act")
            if act == "add":
                email, name, role = (request.form.get("email", "").strip(), request.form.get("name", "").strip(),
                                     request.form.get("role"))
                if "@" not in email or not name or role not in auth.ROLES:
                    flash("Enter an email, a name and a role.", "error")
                elif db.q1("SELECT id FROM users WHERE email=?", (email,)):
                    flash("A user with this email already exists.", "error")
                else:
                    temp = auth.temp_password()
                    db.insert("users", email=email, name=name, role=role, pw_hash=auth.hash_pw(temp), must_change_pw=1,
                              created_at=db.now())
                    auth.audit("user_added", f"{email} {role}")
            else:
                u = db.q1("SELECT * FROM users WHERE id=?", (request.form.get("uid", 0),))
                if u and u["id"] != g.user["id"]:
                    if act == "toggle":
                        db.update("users", u["id"], active=0 if u["active"] else 1)
                    elif act == "reset_pw":
                        temp = auth.temp_password()
                        db.update("users", u["id"], pw_hash=auth.hash_pw(temp), must_change_pw=1, failed_logins=0, locked_until="")
                    elif act == "reset_mfa":
                        db.update("users", u["id"], mfa_enabled=0, mfa_secret="")
                    elif act == "role" and request.form.get("role") in auth.ROLES:
                        db.update("users", u["id"], role=request.form["role"])
                    auth.audit(f"user_{act}", u["email"])
                    if temp:
                        flash(f"Temporary password for {u['email']}: {temp}  (shown once; the user must change it at sign-in)", "ok")
                        temp = None
        if temp:
            flash(f"User added. Temporary password: {temp}  (shown once; the user must change it at sign-in)", "ok")
        return render_template("users.html", users=db.q("SELECT * FROM users ORDER BY role, email"))

    @app.route("/admin/audit")
    @auth.roles_required("admin")
    def audit_log():
        return render_template("audit.html", rows=db.q("SELECT * FROM audit ORDER BY id DESC LIMIT 500"))

    @app.route("/health")
    def health():
        return {"status": "ok"}

    def demo_users():
        if not app.config["DEMO"]:
            return []
        return db.q("SELECT email, name, role FROM users WHERE active=1 ORDER BY role")

    return app


def data_as_of():
    row = db.q1("SELECT MAX(published_at) AS p FROM uploads WHERE status='published'")
    return (row["p"] or "")[:16] if row else ""


def bootstrap(app):
    """First administrator from the environment; demo users and synthetic data in demo mode."""
    if db.val("SELECT COUNT(*) FROM users", default=0) == 0:
        email, pw = os.environ.get("MARSAD_ADMIN_EMAIL", ""), os.environ.get("MARSAD_ADMIN_PASSWORD", "")
        if email and pw:
            db.insert("users", email=email, name=os.environ.get("MARSAD_ADMIN_NAME", "Administrator"), role="admin",
                      pw_hash=auth.hash_pw(pw), must_change_pw=1, created_at=db.now())
    if app.config["DEMO"] and not store.current_ids():
        import seed_demo
        seed_demo.seed()


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False)
