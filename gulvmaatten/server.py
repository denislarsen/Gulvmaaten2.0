"""Server til drift, fx på Railway.

    python -m gulvmaatten server

Gør tre ting i én proces:

1. Viser hjemmesiden (de byggede filer i site/).
2. Kører de faste opgaver (`planlagt`) med et fast interval, som standard hver
   time, og bygger hjemmesiden igen bagefter.
3. Giver redaktøren en side på /redaktion, hvor udkast kan læses, rettes,
   godkendes og afvises, og hvor der laves personlige adgangslinks.

Adgang (se adgang.py): Så længe GULVMAATTEN_ADGANG ikke er "offentlig", kræver
hele siden, at man er logget ind med et personligt link eller ejerens kode
(GULVMAATTEN_REDAKTOER_KODE). Er siden offentlig, kræver kun /redaktion login.
Mens siden er privat, beder den søgemaskiner om ikke at indeksere den.

Kun Pythons standardbibliotek bruges. SQLite tåler én skriver ad gangen, så
alt, der skriver, går gennem samme lås.
"""

from __future__ import annotations

import hmac
import os
import re
import threading
import time
import traceback
from datetime import datetime
from functools import partial
from html import escape
from http.cookies import CookieError, SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from . import adgang
from .config import load_sources
from .db import DEFAULT_DB, Database
from .drift import IngenNoegle, KanIkkeGodkendes, afvis, claude_client, godkend, koer_planlagt
from .models import Article, ReviewStatus
from .site import SITE_DIR, byg_site

SKRIVELAAS = threading.Lock()
MAX_FORMULAR = 200_000
COOKIE = "gulvmaatten_session"
SESSION_SEKUNDER = adgang.SESSION_DAGE * 86400


def log(besked: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {besked}", flush=True)


def adgangskode() -> str:
    return os.environ.get("GULVMAATTEN_REDAKTOER_KODE", "")


def er_privat() -> bool:
    return os.environ.get("GULVMAATTEN_ADGANG", "privat").strip().lower() != "offentlig"


def vis_udkast() -> bool:
    """Mens siden er privat, vises udkast (markeret UDKAST), så man kan se strømmen
    af nyheder. GULVMAATTEN_VIS_UDKAST=nej slår det fra. En offentlig side viser
    aldrig udkast."""
    return er_privat() and os.environ.get("GULVMAATTEN_VIS_UDKAST", "ja").strip().lower() != "nej"


def byg(db_sti: Path) -> None:
    with SKRIVELAAS:
        db = Database(db_sti)
        try:
            byg_site(db, SITE_DIR, forhaandsvisning=vis_udkast())
        finally:
            db.close()


# --- Faste kørsler -------------------------------------------------------------------

def planlaegger(db_sti: Path, hver_minutter: int) -> None:
    time.sleep(30)  # Lad serveren komme op først
    while True:
        start = time.monotonic()
        try:
            with SKRIVELAAS:
                db = Database(db_sti)
                try:
                    koer_planlagt(db, claude_client(), log=log)
                    byg_site(db, SITE_DIR, forhaandsvisning=vis_udkast())
                finally:
                    db.close()
            log("Fast kørsel færdig, hjemmesiden er bygget.")
        except IngenNoegle as e:
            log(f"Fast kørsel sprunget over: {e}")
        except Exception:  # noqa: BLE001 - serveren skal blive ved med at køre
            log("Fast kørsel fejlede:\n" + traceback.format_exc())
        time.sleep(max(60, hver_minutter * 60 - (time.monotonic() - start)))


# --- Sider til redaktionen og log ind --------------------------------------------------

def _css() -> str:
    return (Path(__file__).with_name("style.css")).read_text(encoding="utf-8") + """
.red { max-width: 900px; margin: 0 auto; }
.red h1 { font-family: var(--overskrift); font-size: 40px; margin: 0 0 6px; }
.red table { width: 100%; border-collapse: collapse; font-size: 15px; }
.red td, .red th { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--linje); vertical-align: top; }
.red th { font-family: var(--overskrift); font-weight: 600; text-transform: uppercase; letter-spacing: .08em; font-size: 12px; }
.red a { color: var(--link); }
.red label { display: block; font-family: var(--overskrift); font-weight: 600; margin: 14px 0 4px; }
.red input[type=text], .red input[type=password], .red textarea, .red select { width: 100%; font: inherit; padding: 8px; border: 1px solid #999; }
.red textarea { min-height: 260px; }
.red .knapper { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }
.red button { font-family: var(--overskrift); font-size: 17px; padding: 8px 18px; border: 2px solid var(--blaek); background: #fff; cursor: pointer; }
.red button.godkend { background: var(--groen); border-color: var(--groen); color: #fff; }
.red button.afvis { border-color: var(--lyserod-moerk); color: var(--lyserod-moerk); }
.red td button { font-size: 14px; padding: 3px 10px; }
.red .besked { padding: 10px 14px; margin: 12px 0; background: #fff8e0; border-left: 4px solid var(--gul); }
.red .fejl { background: #fde8ee; border-left-color: var(--lyserod-moerk); }
.red .risiko-high { color: var(--lyserod-moerk); font-weight: 700; }
"""


def _side(titel: str, krop: str) -> bytes:
    return (f'<!doctype html><html lang="da"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="robots" content="noindex, nofollow">'
            f'<title>{escape(titel)}</title><style>{_css()}</style></head>'
            f'<body><div class="avis red">{krop}</div></body></html>').encode("utf-8")


def _besked(tekst: str, fejl: bool = False) -> str:
    return f'<div class="besked{" fejl" if fejl else ""}">{escape(tekst)}</div>' if tekst else ""


def _liste(db: Database, besked: str = "") -> bytes:
    udkast = db.get_articles(ReviewStatus.NEEDS_REVIEW)
    rigtige = [a for a in udkast if "tip" not in a.tags]
    tips = [a for a in udkast if "tip" in a.tags]
    publicerede = db.get_articles(ReviewStatus.PUBLISHED)[:10]

    def raekker(artikler: list[Article]) -> str:
        return "".join(
            f'<tr><td>#{a.id}</td><td><a href="/redaktion/{a.id}">{escape(a.overskrift)}</a></td>'
            f'<td>{escape(a.kategori)}</td><td class="risiko-{a.risiko.value}">{a.risiko.value}</td>'
            f'<td>{a.oprettet:%d/%m %H:%M}</td></tr>' for a in artikler) or '<tr><td colspan="5">Ingen.</td></tr>'

    hoved = '<tr><th>Nr.</th><th>Overskrift</th><th>Kategori</th><th>Risiko</th><th>Oprettet</th></tr>'
    krop = ('<h1>Redaktionen</h1><p><a href="/">Se hjemmesiden</a> · <a href="/redaktion/adgang">Adgang</a> · '
            '<a href="/log-ud">Log ud</a></p>' + _besked(besked)
            + f'<h2 class="sektion__titel">Udkast, der venter ({len(rigtige)})</h2><table>{hoved}{raekker(rigtige)}</table>'
            + f'<h2 class="sektion__titel">Tips fra andre medier ({len(tips)})</h2><table>{hoved}{raekker(tips)}</table>'
            + f'<h2 class="sektion__titel">Senest publiceret</h2><table>{hoved}{raekker(publicerede)}</table>')
    return _side("Redaktionen · Gulvmåtten", krop)


def _redigering(a: Article, besked: str = "", fejl: bool = False) -> bytes:
    from .mad import karakter

    kilder = "".join(f'<li><a href="{escape(k)}" rel="noopener" target="_blank">{escape(k)}</a></li>' for k in a.kilder)
    billede = (f'<figure class="foto"><img src="{escape(a.billede_url)}" alt="" referrerpolicy="no-referrer" '
               f'style="max-width:420px"><figcaption>{escape(a.billede_kredit)}</figcaption></figure>'
               if a.billede_url else "<p>Intet billede.</p>")
    k = karakter(a)
    karakter_felt = ""
    if a.kategori == "mad":
        valg = "".join(f'<option value="{n}"{" selected" if k == n else ""}>{n} gulvmåtter</option>' for n in range(1, 7))
        karakter_felt = (f'<label for="karakter">Karakter</label><select id="karakter" name="karakter">'
                         f'<option value="">Ingen</option>{valg}</select>')
    krop = (
        '<p><a href="/redaktion">Tilbage til listen</a></p>' + _besked(besked, fejl)
        + f'<p class="kicker">#{a.id} · {escape(a.kategori)} · {escape(a.by)} · status: {a.status.value} · '
          f'risiko: <span class="risiko-{a.risiko.value}">{a.risiko.value}</span></p>'
        + f'<form method="post" action="/redaktion/{a.id}">'
          f'<label for="overskrift">Overskrift</label>'
          f'<input type="text" id="overskrift" name="overskrift" value="{escape(a.overskrift)}">'
          f'<label for="resume">Resumé</label><textarea id="resume" name="resume" style="min-height:80px">'
          f'{escape(a.resume)}</textarea>'
          f'<label for="broedtekst">Brødtekst</label><textarea id="broedtekst" name="broedtekst">'
          f'{escape(a.broedtekst)}</textarea>{karakter_felt}'
          f'<div class="knapper"><button type="submit" name="handling" value="gem">Gem rettelser</button>'
          f'<button class="godkend" type="submit" name="handling" value="godkend">Gem og godkend</button>'
          f'<button class="afvis" type="submit" name="handling" value="afvis">Afvis</button></div></form>'
        + (f'<aside class="redaktion"><h2>Usikkerheder</h2><p>{escape(a.usikkerheder)}</p></aside>' if a.usikkerheder else "")
        + (f'<aside class="redaktion"><h2>Note</h2><p>{escape(a.redaktoer_note)}</p></aside>'.replace("\n", "<br>")
           if a.redaktoer_note else "")
        + f'<aside class="kilder"><h2>Kilder</h2><ul>{kilder}</ul></aside>'
        + f'<h2 class="sektion__titel">Billede</h2>{billede}'
    )
    return _side(f"#{a.id} · Redaktionen", krop)


def _log_ind_side(besked: str = "") -> bytes:
    kode_form = ('<form method="post" action="/log-ind"><label for="kode">Redaktørens kode</label>'
                 '<input type="password" id="kode" name="kode" autocomplete="current-password">'
                 '<div class="knapper"><button class="godkend" type="submit">Log ind</button></div></form>'
                 if adgangskode() else "")
    return _side("Log ind · Gulvmåtten", (
        '<h1>Gulvmåtten</h1><p>Siden er ikke offentlig endnu. Brug det personlige link, du har fået, '
        'eller log ind med redaktørens kode.</p>' + _besked(besked, fejl=True) + kode_form))


def _spaer_knap(adgang_id: int) -> str:
    return (f'<form method="post" action="/redaktion/adgang"><input type="hidden" name="spaer" value="{adgang_id}">'
            f'<button class="afvis" type="submit">Spær</button></form>')


def _adgang_side(db: Database, nyt_link: str = "", besked: str = "") -> bytes:
    raekker = "".join(
        f'<tr><td>{escape(r["navn"])}</td><td>{"Redaktør" if r["rolle"] == "redaktoer" else "Læser"}</td>'
        f'<td>{(r["sidst_brugt"] or "aldrig")[:16].replace("T", " ")}</td>'
        f'<td>{"Spærret" if r["spaerret"] else _spaer_knap(r["id"])}</td></tr>'
        for r in adgang.adgange(db)) or '<tr><td colspan="4">Ingen links endnu.</td></tr>'
    link_boks = (f'<div class="besked"><b>Nyt link.</b> Send det til personen, fx på sms. Det vises kun denne ene '
                 f'gang.<br><input type="text" readonly value="{escape(nyt_link)}" aria-label="Nyt link"></div>'
                 if nyt_link else "")
    krop = (
        '<p><a href="/redaktion">Tilbage til redaktionen</a></p><h1>Adgang</h1>'
        '<p>Hver person får sit eget link. Når linket åbnes, er man logget ind i 30 dage i den browser. '
        'Spærrer du et link, bliver personen logget ud med det samme.</p>'
        + _besked(besked) + link_boks
        + '<form method="post" action="/redaktion/adgang"><label for="navn">Navn</label>'
          '<input type="text" id="navn" name="navn" required>'
          '<label for="rolle">Rolle</label><select id="rolle" name="rolle">'
          '<option value="laeser">Læser: kan se siden</option>'
          '<option value="redaktoer">Redaktør: kan også godkende udkast og lave links</option></select>'
          '<div class="knapper"><button class="godkend" type="submit">Lav link</button></div></form>'
        + f'<h2 class="sektion__titel">Links</h2><table><tr><th>Navn</th><th>Rolle</th><th>Sidst brugt</th>'
          f'<th></th></tr>{raekker}</table>')
    return _side("Adgang · Gulvmåtten", krop)


# --- HTTP ----------------------------------------------------------------------------

class Haandtering(SimpleHTTPRequestHandler):
    db_sti: Path = DEFAULT_DB

    def log_message(self, format, *args):  # noqa: A002 - samme navn som i basisklassen
        # Personlige links skrives aldrig i loggen
        sti = "/adgang/…" if self.path.startswith("/adgang/") else self.path
        status = str(args[1]) if len(args) > 1 else ""
        if sti.startswith(("/redaktion", "/log-ind", "/adgang")) or status[:1] in ("4", "5"):
            log(f"{self.address_string()} {self.command} {sti} {status}")

    def list_directory(self, path):
        # Mappeoversigter vises aldrig
        self.send_error(404)
        return None

    def end_headers(self):
        if er_privat():
            self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    # --- svar ----------------------------------------------------------------------

    def _svar(self, status: int, indhold: bytes, typ: str = "text/html; charset=utf-8",
              cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(indhold)))
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(indhold)

    def _videre(self, sti: str, cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", sti)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _https(self) -> bool:
        # Railway og andre værter afslutter https foran serveren og sætter X-Forwarded-Proto
        return self.headers.get("X-Forwarded-Proto", "").startswith("https")

    def _cookie(self, vaerdi: str, max_alder: int) -> str:
        sikker = "; Secure" if self._https() else ""
        return f"{COOKIE}={vaerdi}; Max-Age={max_alder}; Path=/; HttpOnly; SameSite=Lax{sikker}"

    # --- adgang --------------------------------------------------------------------

    def _session_id(self) -> str:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        return jar[COOKIE].value if COOKIE in jar else ""

    def _kraev(self, db: Database, redaktoer: bool) -> adgang.Bruger | None:
        """Returnér brugeren, eller send log-ind-siden og returnér None."""
        bruger = adgang.bruger_fra_session(db, self._session_id())
        if bruger is None:
            self._videre("/log-ind")
            return None
        if redaktoer and not bruger.er_redaktoer:
            self._svar(403, _side("Ingen adgang", '<h1>Kun for redaktører</h1><p><a href="/">Til forsiden</a></p>'))
            return None
        return bruger

    def _fra_egen_side(self) -> bool:
        oprindelse = self.headers.get("Origin")
        return not oprindelse or urlsplit(oprindelse).netloc == self.headers.get("Host")

    def _formular(self) -> dict | None:
        laengde = int(self.headers.get("Content-Length") or 0)
        if laengde > MAX_FORMULAR:
            self._svar(413, _side("For stor", "<h1>Teksten er for lang</h1>"))
            return None
        return {k: v[0] for k, v in parse_qs(self.rfile.read(laengde).decode("utf-8"),
                                             keep_blank_values=True).items()}

    # --- GET -------------------------------------------------------------------------

    def do_HEAD(self):  # noqa: N802
        return self.do_GET()

    def do_GET(self):  # noqa: N802 - navnet kræves af http.server
        dele = urlsplit(self.path)
        sti, besked = dele.path, parse_qs(dele.query).get("besked", [""])[0]
        if sti == "/sundhed":
            return self._svar(200, b"ok", "text/plain; charset=utf-8")
        if sti == "/robots.txt":
            return self._svar(200, b"User-agent: *\nDisallow: /\n" if er_privat() else b"User-agent: *\nAllow: /\n",
                              "text/plain; charset=utf-8")
        db = Database(self.db_sti)
        try:
            if sti == "/log-ind":
                return self._svar(200, _log_ind_side(besked))
            if sti == "/log-ud":
                adgang.log_ud(db, self._session_id())
                return self._videre("/log-ind", cookie=self._cookie("", 0))
            m = re.fullmatch(r"/adgang/([A-Za-z0-9_-]{20,})", sti)
            if m:
                with SKRIVELAAS:
                    sid = adgang.log_ind_med_token(db, m.group(1))
                if not sid:
                    return self._svar(403, _log_ind_side("Linket virker ikke. Det kan være spærret."))
                # Videre til forsiden, så linket ikke bliver stående i adresselinjen
                return self._videre("/", cookie=self._cookie(sid, SESSION_SEKUNDER))
            if sti.startswith("/redaktion"):
                if not self._kraev(db, redaktoer=True):
                    return
                if sti.rstrip("/") == "/redaktion":
                    return self._svar(200, _liste(db, besked))
                if sti == "/redaktion/adgang":
                    return self._svar(200, _adgang_side(db, besked=besked))
                m = re.fullmatch(r"/redaktion/(\d+)", sti)
                a = db.get_article(int(m.group(1))) if m else None
                if not a:
                    return self._svar(404, _side("Ikke fundet", "<h1>Artiklen findes ikke</h1>"))
                return self._svar(200, _redigering(a, besked))
            if er_privat() and not self._kraev(db, redaktoer=False):
                return
        finally:
            db.close()
        return super().do_GET() if self.command == "GET" else super().do_HEAD()

    # --- POST ------------------------------------------------------------------------

    def do_POST(self):  # noqa: N802
        sti = urlsplit(self.path).path
        if not self._fra_egen_side():
            return self._svar(403, _side("Afvist", "<h1>Formularen kom fra en anden side</h1>"))
        if sti == "/log-ind":
            return self._post_log_ind()
        if sti == "/redaktion/adgang":
            return self._post_adgang()
        m = re.fullmatch(r"/redaktion/(\d+)", sti)
        if not m:
            return self._svar(404, b"")
        with SKRIVELAAS:
            db = Database(self.db_sti)
            try:
                if not self._kraev(db, redaktoer=True):
                    return
                felter = self._formular()
                if felter is None:
                    return
                artikel_id = int(m.group(1))
                handling = felter.get("handling", "gem")
                a = db.get_article(artikel_id)
                if not a:
                    return self._svar(404, _side("Ikke fundet", "<h1>Artiklen findes ikke</h1>"))
                for felt in ("overskrift", "resume", "broedtekst"):
                    if felt in felter and felter[felt].strip():
                        setattr(a, felt, felter[felt].replace("\r\n", "\n").strip())
                db.save_article(a)
                try:
                    if handling == "godkend":
                        karakter = int(felter["karakter"]) if felter.get("karakter", "").isdigit() else None
                        godkend(db, artikel_id, karakter)
                        byg_site(db, SITE_DIR, forhaandsvisning=vis_udkast())
                        return self._videre(f"/redaktion?besked=%23{artikel_id}+er+godkendt+og+publiceret.")
                    if handling == "afvis":
                        afvis(db, artikel_id)
                        byg_site(db, SITE_DIR, forhaandsvisning=vis_udkast())
                        return self._videre(f"/redaktion?besked=%23{artikel_id}+er+afvist.")
                except KanIkkeGodkendes as e:
                    return self._svar(400, _redigering(db.get_article(artikel_id), str(e), fejl=True))
                return self._videre(f"/redaktion/{artikel_id}?besked=Rettelserne+er+gemt.")
            finally:
                db.close()

    def _post_log_ind(self) -> None:
        felter = self._formular()
        if felter is None:
            return
        kode = adgangskode()
        if not kode or not hmac.compare_digest(felter.get("kode", "").encode(), kode.encode()):
            time.sleep(1)  # Gør det langsomt at gætte koden
            return self._svar(401, _log_ind_side("Forkert kode."))
        with SKRIVELAAS:
            db = Database(self.db_sti)
            try:
                sid = adgang.log_ind_som_ejer(db)
            finally:
                db.close()
        return self._videre("/redaktion", cookie=self._cookie(sid, SESSION_SEKUNDER))

    def _post_adgang(self) -> None:
        with SKRIVELAAS:
            db = Database(self.db_sti)
            try:
                if not self._kraev(db, redaktoer=True):
                    return
                felter = self._formular()
                if felter is None:
                    return
                if felter.get("spaer", "").isdigit():
                    adgang.spaer_adgang(db, int(felter["spaer"]))
                    return self._videre("/redaktion/adgang?besked=" + quote("Linket er spærret."))
                navn = felter.get("navn", "").strip()
                if not navn:
                    return self._svar(400, _adgang_side(db, besked="Skriv et navn."))
                rolle = felter.get("rolle") if felter.get("rolle") in adgang.ROLLER else "laeser"
                _, token = adgang.opret_adgang(db, navn, rolle)
                link = f"{'https' if self._https() else 'http'}://{self.headers.get('Host', 'localhost')}/adgang/{token}"
                return self._svar(200, _adgang_side(db, nyt_link=link))
            finally:
                db.close()


def start(port: int = 8000, db_sti: Path = DEFAULT_DB, hver_minutter: int = 60) -> None:
    db = Database(db_sti)
    try:
        for s in load_sources():
            db.upsert_source(s)
    finally:
        db.close()
    byg(db_sti)
    if hver_minutter > 0:
        threading.Thread(target=planlaegger, args=(db_sti, hver_minutter), daemon=True).start()
        log(f"Faste kørsler hvert {hver_minutter}. minut.")
    if not adgangskode():
        log("GULVMAATTEN_REDAKTOER_KODE er ikke sat. Ejeren kan ikke logge ind; kun personlige links virker.")
    log("Siden er privat: login kræves." if er_privat() else "Siden er offentlig: kun /redaktion kræver login.")
    if vis_udkast():
        log("Udkast vises på siden, markeret UDKAST.")
    Haandtering.db_sti = db_sti
    server = ThreadingHTTPServer(("0.0.0.0", port), partial(Haandtering, directory=str(SITE_DIR)))
    log(f"Gulvmåtten kører på port {port}. Hjemmesiden ligger i {SITE_DIR}.")
    server.serve_forever()
