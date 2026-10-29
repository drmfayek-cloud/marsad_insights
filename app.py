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

from insights import actions, auth, candidates, library, config, db, deid, kpi, store, theme
from insights.i18n import lang, pick, t
from insights.parsers import ParseError, parse
from insights.xlsx_templates import corrective_template, governance_template

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
    library.init(data_dir)
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
            keep = session.get("lang")
            session.clear()
            if keep:
                session["lang"] = keep             # a language chosen on the sign-in page carries through MFA
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
        nxt, chosen = session.get("next"), session.get("lang")
        session.clear()
        lg = chosen or u["lang"] or "en"
        session.update(uid=u["id"], full=True, at=dt.datetime.now().timestamp(), lang=lg)
        db.update("users", u["id"], last_login=db.now(), lang=lg)
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
        uri = auth.otpauth_uri(secret, u["email"])
        return render_template("mfa_setup.html", secret=grouped, uri=uri, qr=auth.qr_svg(uri), email=u["email"])

    @app.route("/logout")
    def logout():
        if g.user:
            auth.audit("logout")
        keep = session.get("lang")
        session.clear()
        if keep:
            session["lang"] = keep
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
            ctx.meta = {"F6": actions.meta()}
            results = kpi.compute_page(pg["code"], ctx)
            badge = "filtered" if (snap and tpa) else "provisional"
        trend, sparks = None, {}
        if pg["code"] == "EX" and data:
            trend = kpi.exec_trend(kpi.Ctx(data, "all", tpa), selected=period)
            hist = kpi.history([k["id"] for k in config.kpis_for("EX")], data, period, tpa)
            sparks = {k: theme.sparkline(v, theme.style(k)[0]) for k, v in hist.items()}
        internal = g.user["role"] in auth.INTERNAL
        defs = [k for k in config.kpis_for(pg["code"]) if internal or k.get("audience") != "kpmg"]   # KPMG-only tiles
        results = {k: v for k, v in results.items() if k in {d["id"] for d in defs}}
        return render_template("page.html", pg=pg, defs=defs, results=results, months=ms, period=period, tpa=tpa,
                               tpas=tpa_list, badge=badge, snap=snap, trend=trend, sparks=sparks, has_data=bool(data),
                               as_of=data_as_of())

    # ------------------------------------------------------------------ corrective-action tracker (all signed-in users)
    def tracker_state():
        """F6 dataset, as-at date and comparison base for the tracker. A closed month uses the register version that was
        current when the month was closed, so its statuses are the month-end position."""
        asof_arg = request.args.get("asof", "")
        today = dt.date.today().isoformat()
        cur_ids = store.current_ids()
        uid, asof, frozen = cur_ids.get("F6"), today, False
        if asof_arg and len(asof_arg) == 7 and asof_arg[4] == "-" and asof_arg[:4].isdigit():
            y, m = int(asof_arg[:4]), int(asof_arg[5:7])
            end = dt.date(y, m, 28) + dt.timedelta(days=4)
            asof = min((end - dt.timedelta(days=end.day)).isoformat(), today)
            snap = db.q1("SELECT * FROM snapshots WHERE month=?", (asof_arg,))
            ids = db.loads(snap["datasets"], {}) if snap else {}
            if ids.get("F6"):
                uid, frozen = int(ids["F6"]), True
        f6 = store.load(uid) if uid else None
        prev = actions.previous_statuses(uid) if (uid and not frozen) else None
        return f6, asof, asof_arg, frozen, prev

    def tracker_filters():
        return dict(tpa=request.args.get("tpa", ""), target=request.args.get("target", ""), st=request.args.get("status", ""),
                    atype=request.args.get("type", ""))

    @app.route("/p/governance/actions")
    @auth.login_required
    def action_tracker():
        f6, asof, asof_arg, frozen, prev = tracker_state()
        f = tracker_filters()
        allrows = actions.rows(f6, asof, tpa=f["tpa"], target=f["target"], atype=f["atype"], prev=prev) if f6 else []
        counts, ages = actions.summary(allrows)
        rs = [r for r in allrows if not f["st"] or (r["st"] in actions.OPEN if f["st"] == "open" else r["st"] == f["st"])]
        months = [m for m in kpi.months(store.current()) if m]
        base = dict(asof=asof_arg, tpa=f["tpa"], target=f["target"], status=f["st"], type=f["atype"])

        def qs(**kw):
            from urllib.parse import urlencode
            return urlencode({k: v for k, v in dict(base, **kw).items() if v})
        clips = library.counts_for("action", g.user["role"] in auth.INTERNAL)
        return render_template("actions.html", qs=qs, clips=clips, rows=rs, counts=counts, ages=ages, asof=asof, asof_arg=asof_arg, frozen=frozen,
                               f=f, meta=actions.meta(), months=months, has=bool(f6), prev=prev is not None,
                               tpas=sorted({a["tpa"] for a in (f6 or {}).get("actions", []) if a["tpa"]}),
                               types=sorted({a["type"] for a in (f6 or {}).get("actions", []) if a["type"]}),
                               STATUS=actions.STATUS, label=actions.label, tname=actions.target_name, gl=kpi.gl, pg=config.PAGE_BY_SLUG["governance"])

    @app.route("/p/governance/actions/<aid>")
    @auth.login_required
    def action_detail(aid):
        f6, asof, asof_arg, frozen, prev = tracker_state()
        r = next((x for x in actions.rows(f6, asof, prev=prev) if x["id"] == aid), None) if f6 else None
        if r is None:
            abort(404)
        recs = {x["id"]: x for x in f6["recommendations"]}
        ins = g.user["role"] in auth.INTERNAL
        docs = [dict(x, via="action") for x in library.for_link("action", aid, ins)]
        if r["decision_id"]:
            docs += [dict(x, via="decision") for x in library.for_link("decision", r["decision_id"], ins)]
        return render_template("action.html", docs=docs, can_upload=ins, CATS=library.CATEGORIES, r=r, asof=asof, asof_arg=asof_arg, hist=actions.history().get(aid, []),
                               rec=recs.get(r["decision"].get("subject", "")), STATUS=actions.STATUS, label=actions.label,
                               tname=actions.target_name, gl=kpi.gl, pg=config.PAGE_BY_SLUG["governance"])

    @app.route("/p/governance/actions.xlsx")
    @auth.login_required
    def action_tracker_xlsx():
        f6, asof, asof_arg, frozen, prev = tracker_state()
        if not f6:
            abort(404)
        f = tracker_filters()
        rs = actions.rows(f6, asof, prev=prev, **f)
        desc = ", ".join(f"{k}={v}" for k, v in f.items() if v)
        meta = actions.meta()
        body = actions.to_xlsx(rs, asof, desc, meta.get("published", "-"), g.user["email"])
        auth.audit("download_actions", f"as at {asof}; {len(rs)} rows; {desc or 'no filter'}")
        return Response(body, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename=Corrective_action_tracker_{asof}.xlsx"})

    # ------------------------------------------------------------------ documents library (1.7)
    def internal():
        return g.user["role"] in auth.INTERNAL

    def doc_form_meta(form):
        links = [(k, ref) for k in library.LINK_KINDS for ref in form.getlist(f"link_{k}") if ref]
        return dict(title=form.get("title", ""), category=form.get("category", ""), period=form.get("period", ""),
                    description=form.get("description", ""), visibility=form.get("visibility", ""), links=links)

    def link_labels(data):
        return {k: dict(v) for k, v in library.link_options(data).items()}

    @app.route("/documents")
    @auth.login_required
    def documents():
        a = request.args
        docs = library.search(internal(), q=a.get("q", ""), category=a.get("category", ""), kind=a.get("kind", ""),
                              ref=a.get("ref", ""), period=a.get("period", ""))
        lk = {d["id"]: library.links(d["id"]) for d in docs}
        return render_template("documents.html", docs=docs, links=lk, labels=link_labels(store.current()), args=a,
                               CATS=library.CATEGORIES, KINDS=library.LINK_KINDS, can_upload=internal())

    @app.route("/documents/upload", methods=["GET", "POST"])
    @auth.roles_required("admin", "kpmg")
    def document_upload():
        parent = db.q1("SELECT * FROM documents WHERE id=? AND status='active'", (request.values.get("parent", type=int),)) \
            if request.values.get("parent") else None
        form = request.form if request.method == "POST" else None
        if request.method == "POST":
            f = request.files.get("file")
            meta = doc_form_meta(request.form)
            try:
                raw = f.read() if f else b""
                doc_id, check, n = library.save(raw, f.filename if f else "", meta, g.user["email"],
                                                confirm=request.form.get("confirm") == "1",
                                                parent=parent["id"] if parent else None)
            except library.LibraryError as e:
                auth.audit("document_rejected", f"{f.filename if f else '-'}: {e}")
                flash(str(e), "error")
            else:
                detail = f"#{doc_id} {meta['category']} {meta['visibility']} {f.filename}"
                if check != "clean":
                    detail += f" - uploader confirmed no patient identifiers ({check}, {n} matches)"
                auth.audit("document_new_version" if parent else "document_uploaded", detail)
                flash(pick("Document saved.", "تم حفظ المستند."), "ok")
                return redirect(url_for("document_view", doc_id=doc_id))
        pre = dict(parent) if parent else {}
        if parent:
            pre["links"] = library.links(parent["id"])
        elif request.args.get("kind") and request.args.get("ref"):
            pre["links"] = [(request.args["kind"], request.args["ref"])]
            pre["category"] = request.args.get("category", "")
        return render_template("document_upload.html", form=form, pre=pre, parent=parent, CATS=library.CATEGORIES,
                               KINDS=library.LINK_KINDS, options=library.link_options(store.current()))

    @app.route("/documents/<int:doc_id>", methods=["GET", "POST"])
    @auth.login_required
    def document_view(doc_id):
        d = library.get(doc_id, internal())
        if d is None:
            abort(404)
        if request.method == "POST":
            act = request.form.get("act")
            if act == "edit" and internal():
                meta = doc_form_meta(request.form)
                if meta["visibility"] in ("kpmg", "shared") and meta["category"] in library.CATEGORIES:
                    db.update("documents", doc_id, title=meta["title"].strip()[:200] or d["title"], category=meta["category"],
                              period=meta["period"][:7], description=meta["description"].strip()[:500], visibility=meta["visibility"])
                    library.set_links(doc_id, meta["links"])
                    auth.audit("document_edited", f"#{doc_id} visibility={meta['visibility']} links={len(meta['links'])}")
                    flash(pick("Changes saved.", "تم حفظ التغييرات."), "ok")
            elif act == "delete" and g.user["role"] == "admin":
                library.delete(d)
                auth.audit("document_deleted", f"#{doc_id} {d['filename']} and its earlier versions")
                flash(pick("Document deleted.", "تم حذف المستند."), "ok")
                return redirect(url_for("documents"))
            return redirect(url_for("document_view", doc_id=doc_id))
        vs = [v for v in library.versions(d) if v["status"] != "deleted" and (internal() or v["visibility"] == "shared")]
        return render_template("document.html", d=d, links=library.links(doc_id), labels=link_labels(store.current()), versions=vs,
                               CATS=library.CATEGORIES, KINDS=library.LINK_KINDS, can_edit=internal(),
                               options=library.link_options(store.current()))

    @app.route("/documents/<int:doc_id>/download")
    @auth.login_required
    def document_download(doc_id):
        d = library.get(doc_id, internal())
        if d is None or not os.path.exists(library.path(d)):
            abort(404)
        auth.audit("document_downloaded", f"#{doc_id} {d['filename']}")
        from flask import send_file
        resp = send_file(library.path(d), mimetype=library.EXT[d["ext"]], as_attachment=True, download_name=d["filename"],
                         max_age=0)
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

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
        try:
            cd, ca, cs = candidates.build(store.current())
            cand = dict(dec=len(cd), act=len(ca), skipped=cs)
        except Exception:  # noqa: BLE001 - the upload page must open even if a dataset is incomplete
            cand = None
        return render_template("data.html", uploads=ups, current=cur, cand=cand)

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
                        headers={"Content-Disposition": "attachment; filename=MARSAD_Project_Delivery_Register_template.xlsx"})

    @app.route("/data/candidates.xlsx")
    @auth.roles_required("admin")
    def candidates_xlsx():
        body, nd, na, skipped = candidates.to_xlsx(store.current())
        auth.audit("download_candidates", f"{nd} decision and {na} action candidates; {skipped} already in F6")
        return Response(body, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename=F6_candidates_{dt.date.today()}.xlsx"})

    @app.route("/data/template/corrective-actions.xlsx")
    @auth.roles_required("admin")
    def corrective_xlsx():
        return Response(corrective_template(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=MARSAD_Governance_Corrective_Actions_Register_template.xlsx"})

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
                    ctx.meta = {"F6": actions.meta()}
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
