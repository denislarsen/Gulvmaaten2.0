"""Server til drift, fx på Railway.

    python -m gulvmaatten server

Gør tre ting i én proces:

1. Viser hjemmesiden (de byggede filer i site/).
2. Kører de faste opgaver (`planlagt`) med et fast interval, som standard hver
   time, og bygger hjemmesiden igen bagefter.
3. Giver redaktøren en side på /redaktion, hvor udkast kan læses, rettes,
   godkendes og afvises. Siden er beskyttet med en adgangskode fra
   miljøvariablen GULVMAATTEN_REDAKTOER_KODE. Uden den er siden slået fra.

Kun Pythons standardbibliotek bruges. SQLite tåler én skriver ad gangen, så
alt, der skriver, går gennem samme lås.
"""

from __future__ import annotations

import base64
import hmac
import os
import re
import threading
import time
import traceback
from datetime import datetime
from functools import partial
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .config import load_sources
from .db import DEFAULT_DB, Database
from .drift import IngenNoegle, KanIkkeGodkendes, afvis, claude_client, godkend, koer_planlagt
from .models import Article, ReviewStatus
from .site import SITE_DIR, byg_site

SKRIVELAAS = threading.Lock()
MAX_FORMULAR = 200_000


def log(besked: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {besked}", flush=True)


def adgangskode() -> str:
    return os.environ.get("GULVMAATTEN_REDAKTOER_KODE", "")


def byg(db_sti: Path) -> None:
    with SKRIVELAAS:
        db = Database(db_sti)
        try:
            byg_site(db, SITE_DIR)
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
                    byg_site(db, SITE_DIR)
                finally:
                    db.close()
            log("Fast kørsel færdig, hjemmesiden er bygget.")
        except IngenNoegle as e:
            log(f"Fast kørsel sprunget over: {e}")
        except Exception:  # noqa: BLE001 - serveren skal blive ved med at køre
            log("Fast kørsel fejlede:\n" + traceback.format_exc())
        time.sleep(max(60, hver_minutter * 60 - (time.monotonic() - start)))


# --- Redaktørsiden -------------------------------------------------------------------

def _css() -> str:
    return (Path(__file__).with_name("style.css")).read_text(encoding="utf-8") + """
.red { max-width: 900px; margin: 0 auto; }
.red h1 { font-family: var(--overskrift); font-size: 40px; margin: 0 0 6px; }
.red table { width: 100%; border-collapse: collapse; font-size: 15px; }
.red td, .red th { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--linje); vertical-align: top; }
.red th { font-family: var(--overskrift); font-weight: 600; text-transform: uppercase; letter-spacing: .08em; font-size: 12px; }
.red a { color: var(--link); }
.red label { display: block; font-family: var(--overskrift); font-weight: 600; margin: 14px 0 4px; }
.red input[type=text], .red textarea, .red select { width: 100%; font: inherit; padding: 8px; border: 1px solid #999; }
.red textarea { min-height: 260px; }
.red .knapper { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }
.red button { font-family: var(--overskrift); font-size: 17px; padding: 8px 18px; border: 2px solid var(--blaek); background: #fff; cursor: pointer; }
.red button.godkend { background: var(--groen); border-color: var(--groen); color: #fff; }
.red button.afvis { border-color: var(--lyserod-moerk); color: var(--lyserod-moerk); }
.red .besked { padding: 10px 14px; margin: 12px 0; background: #fff8e0; border-left: 4px solid var(--gul); }
.red .fejl { background: #fde8ee; border-left-color: var(--lyserod-moerk); }
.red .risiko-high { color: var(--lyserod-moerk); font-weight: 700; }
"""


def _side(titel: str, krop: str) -> bytes:
    return (f'<!doctype html><html lang="da"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(titel)}</title><style>{_css()}</style></head>'
            f'<body><div class="avis red">{krop}</div></body></html>').encode("utf-8")


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
    krop = (f'<h1>Redaktionen</h1><p><a href="/">Se hjemmesiden</a></p>'
            + (f'<div class="besked">{escape(besked)}</div>' if besked else "")
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
        f'<p><a href="/redaktion">Tilbage til listen</a></p>'
        + (f'<div class="besked{" fejl" if fejl else ""}">{escape(besked)}</div>' if besked else "")
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


class Haandtering(SimpleHTTPRequestHandler):
    db_sti: Path = DEFAULT_DB

    def log_message(self, format, *args):  # noqa: A002 - samme navn som i basisklassen
        if self.path.startswith("/redaktion") or (args and str(args[1])[:1] in "45"):
            log(f"{self.address_string()} {format % args}")

    # --- adgang --------------------------------------------------------------------

    def _logget_ind(self) -> bool:
        kode = adgangskode()
        if not kode:
            self._svar(503, _side("Redaktionen", "<h1>Redaktørsiden er slået fra</h1>"
                                  "<p>Sæt miljøvariablen GULVMAATTEN_REDAKTOER_KODE for at slå den til.</p>"))
            return False
        hoved = self.headers.get("Authorization", "")
        if hoved.startswith("Basic "):
            try:
                _, _, givet = base64.b64decode(hoved[6:]).decode("utf-8").partition(":")
            except ValueError:
                givet = ""
            if hmac.compare_digest(givet.encode(), kode.encode()):
                return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Gulvmaatten redaktion", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _svar(self, status: int, indhold: bytes, typ: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(indhold)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(indhold)

    def _videre(self, sti: str) -> None:
        self.send_response(303)
        self.send_header("Location", sti)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # --- GET -------------------------------------------------------------------------

    def do_GET(self):  # noqa: N802 - navnet kræves af http.server
        sti = urlsplit(self.path).path
        if sti == "/sundhed":
            return self._svar(200, b"ok", "text/plain; charset=utf-8")
        if not sti.startswith("/redaktion"):
            return super().do_GET()
        if not self._logget_ind():
            return
        db = Database(self.db_sti)
        try:
            besked = parse_qs(urlsplit(self.path).query).get("besked", [""])[0]
            if sti.rstrip("/") == "/redaktion":
                return self._svar(200, _liste(db, besked))
            m = re.fullmatch(r"/redaktion/(\d+)", sti)
            a = db.get_article(int(m.group(1))) if m else None
            if not a:
                return self._svar(404, _side("Ikke fundet", "<h1>Artiklen findes ikke</h1>"))
            return self._svar(200, _redigering(a, besked))
        finally:
            db.close()

    # --- POST ------------------------------------------------------------------------

    def do_POST(self):  # noqa: N802
        sti = urlsplit(self.path).path
        m = re.fullmatch(r"/redaktion/(\d+)", sti)
        if not m:
            return self._svar(404, b"")
        if not self._logget_ind():
            return
        # Formularen må kun sendes fra vores egen side
        oprindelse = self.headers.get("Origin")
        if oprindelse and urlsplit(oprindelse).netloc != self.headers.get("Host"):
            return self._svar(403, _side("Afvist", "<h1>Formularen kom fra en anden side</h1>"))
        laengde = int(self.headers.get("Content-Length") or 0)
        if laengde > MAX_FORMULAR:
            return self._svar(413, _side("For stor", "<h1>Teksten er for lang</h1>"))
        felter = {k: v[0] for k, v in parse_qs(self.rfile.read(laengde).decode("utf-8"),
                                               keep_blank_values=True).items()}
        artikel_id = int(m.group(1))
        handling = felter.get("handling", "gem")
        with SKRIVELAAS:
            db = Database(self.db_sti)
            try:
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
                        byg_site(db, SITE_DIR)
                        return self._videre(f"/redaktion?besked=%23{artikel_id}+er+godkendt+og+publiceret.")
                    if handling == "afvis":
                        afvis(db, artikel_id)
                        byg_site(db, SITE_DIR)
                        return self._videre(f"/redaktion?besked=%23{artikel_id}+er+afvist.")
                except KanIkkeGodkendes as e:
                    return self._svar(400, _redigering(db.get_article(artikel_id), str(e), fejl=True))
                return self._videre(f"/redaktion/{artikel_id}?besked=Rettelserne+er+gemt.")
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
        log("GULVMAATTEN_REDAKTOER_KODE er ikke sat, så /redaktion er slået fra.")
    Haandtering.db_sti = db_sti
    server = ThreadingHTTPServer(("0.0.0.0", port), partial(Haandtering, directory=str(SITE_DIR)))
    log(f"Gulvmåtten kører på port {port}. Hjemmesiden ligger i {SITE_DIR}.")
    server.serve_forever()
