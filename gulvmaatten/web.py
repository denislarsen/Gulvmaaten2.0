"""Hjemmesiden og redaktionsværktøjet.

Offentlige sider:
    /                    Forsiden: nyheder og arrangementer i to kolonner
    /?by=glostrup        Vælg by. Valget huskes i en cookie
    /kategori/<navn>     Alle artikler i en kategori
    /artikel/<slug>      Én artikel

Redaktionen (kræver kodeordet i GULVMAATTEN_ADMIN_PASSWORD):
    /redaktion                Oversigt, autogodkendelse og robottens status
    /redaktion/artikel/<id>   Ret, publicér, afvis eller træk tilbage
    /redaktion/backup         Hent en kopi af databasen
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import tempfile
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, after_this_request, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from markupsafe import Markup, escape

from . import robot
from .config import load_settings
from .datoer import dansk_dato, klokken
from .db import DEFAULT_DB, Database
from .models import ReviewStatus, RiskLevel
from .publicering import afpublicer, autogodkend, publicer, saet_autogodkend

BYER = {"glostrup": "Glostrup", "brondby": "Brøndby"}
BY_VALG = ["Glostrup", "Brøndby", "Glostrup og Brøndby"]

STATUS_NAVNE = {
    ReviewStatus.NEW.value: "Ny",
    ReviewStatus.NEEDS_REVIEW.value: "Venter",
    ReviewStatus.APPROVED.value: "Godkendt",
    ReviewStatus.PUBLISHED.value: "Publiceret",
    ReviewStatus.REJECTED.value: "Afvist",
    ReviewStatus.RETRACTED.value: "Trukket tilbage",
}
RISIKO_NAVNE = {RiskLevel.LOW.value: "lav", RiskLevel.MEDIUM.value: "mellem", RiskLevel.HIGH.value: "høj"}


def _afsnit(tekst: str) -> Markup:
    """Tekst med tomme linjer mellem afsnit -> <p>-afsnit."""
    dele = [d.strip() for d in (tekst or "").split("\n\n") if d.strip()]
    return Markup("".join(f"<p>{escape(d).replace(chr(10), Markup('<br>'))}</p>" for d in dele))


def _linjer(tekst: str) -> list[str]:
    """Én linje pr. punkt. Tankestreger foran fjernes."""
    return [l.strip().lstrip("-•").strip() for l in (tekst or "").splitlines() if l.strip().lstrip("-•").strip()]


def _praktisk(tekst: str) -> list[tuple[str, str]]:
    """'Hvor: Glostrup Sognegård' -> ('Hvor', 'Glostrup Sognegård')"""
    punkter = []
    for linje in _linjer(tekst):
        navn, sep, vaerdi = linje.partition(":")
        punkter.append((navn.strip(), vaerdi.strip()) if sep and len(navn) <= 20 else ("", linje))
    return punkter


def create_app(db_path: Path | str | None = None) -> Flask:
    app = Flask(__name__)
    db_path = str(db_path or DEFAULT_DB)
    kodeord = os.environ.get("GULVMAATTEN_ADMIN_PASSWORD", "")
    app.secret_key = os.environ.get("GULVMAATTEN_SECRET_KEY") or hashlib.sha256(
        f"gulvmaatten:{kodeord}".encode()).hexdigest()
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    try:
        kategorier = load_settings().get("kategorier", [])
    except OSError:
        kategorier = []

    app.jinja_env.filters.update(dato=dansk_dato, klokken=klokken, afsnit=_afsnit, linjer=_linjer,
                                 praktisk=_praktisk)
    app.jinja_env.globals.update(STATUS_NAVNE=STATUS_NAVNE, RISIKO_NAVNE=RISIKO_NAVNE, BYER=BYER,
                                 kategorier=kategorier, i_dag=lambda: datetime.now())

    def db() -> Database:
        if "db" not in g:
            g.db = Database(db_path)
        return g.db

    @app.teardown_appcontext
    def luk_db(_exc) -> None:
        d = g.pop("db", None)
        if d is not None:
            d.close()

    # --- Byvalg -------------------------------------------------------------

    def valgt_by() -> str:
        """'glostrup', 'brondby' eller '' for begge."""
        if "by" in request.args:
            return request.args["by"] if request.args["by"] in BYER else ""
        return request.cookies.get("by", "") if request.cookies.get("by", "") in BYER else ""

    @app.before_request
    def husk_by() -> None:
        g.by = valgt_by()

    @app.after_request
    def gem_by(response):
        if "by" in request.args:
            response.set_cookie("by", g.get("by", ""), max_age=365 * 24 * 3600, samesite="Lax")
        return response

    # --- Offentlige sider ---------------------------------------------------

    @app.get("/")
    def forside():
        by = BYER.get(g.by)
        nyheder = db().get_published(by=by, arrangement=False, limit=20)
        nu = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        arrangementer = db().get_published(by=by, arrangement=True, fra=nu, limit=20)
        return render_template("forside.html", nyheder=nyheder, arrangementer=arrangementer)

    @app.get("/kategori/<navn>")
    def kategori(navn: str):
        if navn not in kategorier:
            abort(404)
        artikler = db().get_published(by=BYER.get(g.by), kategori=navn, limit=50)
        return render_template("kategori.html", navn=navn, artikler=artikler)

    @app.get("/artikel/<slug>")
    def artikel(slug: str):
        p = db().get_publication_by_slug(slug)
        a = db().get_article(p.article_id) if p else None
        if not a or a.status != ReviewStatus.PUBLISHED or p.trukket_tilbage:
            abort(404)
        return render_template("artikel.html", a=a, p=p)

    @app.get("/sundhed")
    def sundhed():
        db().count_articles()
        return "ok"

    @app.errorhandler(404)
    def ikke_fundet(_e):
        return render_template("404.html"), 404

    # --- Redaktionen --------------------------------------------------------

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    def kraever_login(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not kodeord:
                return render_template("redaktion/lukket.html"), 503
            if not session.get("redaktoer"):
                return redirect(url_for("login", naeste=request.path))
            if request.method == "POST":
                forventet = session.get("csrf", "")
                if not forventet or not hmac.compare_digest(request.form.get("csrf", ""), forventet):
                    abort(400)
            return fn(*args, **kwargs)
        return wrapper

    @app.route("/redaktion/login", methods=["GET", "POST"])
    def login():
        if not kodeord:
            return render_template("redaktion/lukket.html"), 503
        if request.method == "POST":
            if hmac.compare_digest(request.form.get("kodeord", "").encode(), kodeord.encode()):
                session.clear()
                session["redaktoer"] = True
                session.permanent = True
                naeste = request.args.get("naeste", "")
                return redirect(naeste if naeste.startswith("/redaktion") else url_for("redaktion"))
            flash("Forkert kodeord.")
        return render_template("redaktion/login.html")

    @app.post("/redaktion/logud")
    @kraever_login
    def logud():
        session.clear()
        return redirect(url_for("forside"))

    @app.get("/redaktion")
    @kraever_login
    def redaktion():
        vis = request.args.get("status", ReviewStatus.NEEDS_REVIEW.value)
        status = ReviewStatus(vis) if vis in {s.value for s in ReviewStatus} else None
        artikler = db().get_articles(status)
        return render_template("redaktion/oversigt.html", artikler=artikler, vis=vis if status else "alle",
                               antal=db().count_articles(), autogodkend=autogodkend(db()),
                               robot=robot.STATUS, har_noegle=bool(robot.api_noegle()))

    @app.post("/redaktion/indstillinger")
    @kraever_login
    def indstillinger():
        til = request.form.get("autogodkend") == "1"
        saet_autogodkend(db(), til)
        flash("Autogodkendelse er slået til." if til else
              "Autogodkendelse er slået fra. Nye udkast venter nu på dig.")
        return redirect(url_for("redaktion"))

    @app.post("/redaktion/robot")
    @kraever_login
    def koer_robot():
        if robot.STATUS.koerer:
            flash("Robotten er allerede i gang.")
        else:
            robot.koer_nu_i_baggrunden(db_path)
            flash("Robotten er startet. Opdatér siden om et par minutter.")
        return redirect(url_for("redaktion"))

    @app.route("/redaktion/artikel/<int:article_id>", methods=["GET", "POST"])
    @kraever_login
    def ret_artikel(article_id: int):
        a = db().get_article(article_id)
        if not a:
            abort(404)
        p = db().get_publication(a.id)
        if request.method == "POST":
            f = request.form
            a.overskrift = f.get("overskrift", a.overskrift).strip() or a.overskrift
            a.resume = f.get("resume", "").strip()
            a.broedtekst = f.get("broedtekst", "").replace("\r\n", "\n").strip()
            a.praktisk = f.get("praktisk", "").replace("\r\n", "\n").strip()
            a.usikkerheder = f.get("usikkerheder", "").replace("\r\n", "\n").strip()
            a.redaktoer_note = f.get("redaktoer_note", "").strip()
            if f.get("kategori") in kategorier:
                a.kategori = f["kategori"]
            if f.get("by") in BY_VALG:
                a.by = f["by"]
            a.tags = [t.strip() for t in f.get("tags", "").split(",") if t.strip()]
            a.er_arrangement = f.get("er_arrangement") == "1"
            try:
                a.arrangement_start = datetime.fromisoformat(f["arrangement_start"]) \
                    if f.get("arrangement_start") else None
            except ValueError:
                flash("Datoen for arrangementet kunne ikke læses, så den er ikke ændret.")
            handling = f.get("handling", "gem")
            if handling == "publicer":
                p = publicer(db(), a)
                flash("Artiklen er publiceret.")
            elif handling == "afvis":
                if p and not p.trukket_tilbage:
                    afpublicer(db(), a)
                a.status = ReviewStatus.REJECTED
                db().save_article(a)
                flash("Artiklen er afvist og vises ikke på hjemmesiden.")
            elif handling == "afpublicer":
                afpublicer(db(), a)
                flash("Artiklen er trukket tilbage fra hjemmesiden.")
            else:
                db().save_article(a)
                flash("Ændringerne er gemt.")
            if p is not None and "rettelsesnote" in f:
                p.rettelsesnote = f["rettelsesnote"].strip()
                db().update_publication(p)
            return redirect(url_for("ret_artikel", article_id=a.id))
        return render_template("redaktion/artikel.html", a=a, p=p, by_valg=BY_VALG)

    @app.get("/redaktion/backup")
    @kraever_login
    def backup():
        fd, sti = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db().backup(sti)

        @after_this_request
        def ryd_op(response):
            try:
                os.remove(sti)
            except OSError:
                pass
            return response

        navn = f"gulvmaatten-{datetime.now():%Y-%m-%d}.db"
        return send_file(sti, as_attachment=True, download_name=navn)

    return app
