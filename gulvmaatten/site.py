"""Hjemmesiden: bygger statiske HTML-sider ud fra databasen.

    python -m gulvmaatten site                     Publicér godkendte artikler og byg site/
    python -m gulvmaatten site --forhaandsvisning  Tag også udkast med (markeret UDKAST)

Layoutet er inspireret af en trykt lokalavis' forside: teasere øverst,
stor avishoved, en tophistorie med stort billede og derefter sektioner.
På brede skærme er forsiden i tre kolonner, på telefoner i én.

Billeder linkes direkte fra kilden (de kopieres ikke) og vises altid med
kreditering. Kilder med `billeder: nej` giver aldrig billeder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

from .config import load_settings
from .db import Database
from .mad import karakter
from .models import Article, Publication, RawItem, ReviewStatus

SITE_DIR = Path("site")
BOLIG_KILDE = "boliger-til-salg"

MAANEDER = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august",
            "september", "oktober", "november", "december"]

# Kategori -> sektion på forsiden
SEKTIONER = {
    "havnen": "havn", "kultur": "havn", "arrangementer": "havn", "foreningsliv": "havn",
    "folkely": "folkely",
    "sport": "sport",
    "mad": "mad",
    "udlandsstof": "udland",
}
SEKTION_NAVNE = {
    "nyheder": "Nyheder", "havn": "Havnen & kultur", "folkely": "Folkely",
    "sport": "Sport", "mad": "Mad", "udland": "Udlandsstof",
}
KATEGORI_NAVNE = {
    "nyheder": "Nyheder", "havnen": "Havnen", "kultur": "Kultur", "folkely": "Folkely",
    "sport": "Sport", "mad": "Mad", "arrangementer": "Arrangementer", "kommune": "Kommunen",
    "foreningsliv": "Foreningsliv", "byudvikling": "Byudvikling", "trafik": "Trafik",
    "udlandsstof": "Udlandsstof",
}


# --- Hjælpere ---------------------------------------------------------------------

def slugify(tekst: str) -> str:
    t = tekst.lower()
    for a, b in (("æ", "ae"), ("ø", "oe"), ("å", "aa"), ("é", "e"), ("ü", "u"), ("ö", "oe"), ("ä", "ae")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:70].rstrip("-") or "artikel"


def ugedato(nu: datetime) -> str:
    return f"Uge {nu.isocalendar().week} | {MAANEDER[nu.month - 1].capitalize()} {nu.year}"


def dansk_dato(d: datetime) -> str:
    return f"{d.day}. {MAANEDER[d.month - 1]} {d.year}"


def kr(beloeb) -> str:
    return f"{int(beloeb):,} kr.".replace(",", ".") if beloeb else "Pris ikke oplyst"


def sektion(a: Article) -> str:
    if a.kategori == "folkely" or "folkely" in (t.lower() for t in a.tags):
        return "folkely"
    return SEKTIONER.get(a.kategori, "nyheder")


@dataclass
class Side:
    """En artikel klar til visning."""
    artikel: Article
    slug: str
    score: int
    udkast: bool
    sektion: str = ""
    rettelse: str = ""

    @property
    def href(self) -> str:
        return f"artikel/{self.slug}.html"

    @property
    def kicker(self) -> str:
        return KATEGORI_NAVNE.get(self.artikel.kategori, self.artikel.kategori.capitalize())


@dataclass
class Forside:
    sider: list[Side]
    boliger: list[RawItem] = field(default_factory=list)
    annoncer: list[dict] = field(default_factory=list)


# --- Udvælgelse ---------------------------------------------------------------------

def publicer_godkendte(db: Database, nu: datetime | None = None) -> list[Publication]:
    """Godkendte artikler får en adresse og status published."""
    nye = []
    brugte = {r["slug"] for r in db.conn.execute("SELECT slug FROM publications")}
    for a in db.get_articles(ReviewStatus.APPROVED):
        slug = slugify(a.overskrift)
        if slug in brugte:
            slug = f"{slug}-{a.id}"
        brugte.add(slug)
        p = Publication(article_id=a.id, slug=slug, publiceret=nu or datetime.now())
        db.save_publication(p)
        a.status = ReviewStatus.PUBLISHED
        db.save_article(a)
        nye.append(p)
    return nye


def saml_sider(db: Database, forhaandsvisning: bool = False) -> list[Side]:
    statusser = [ReviewStatus.PUBLISHED]
    if forhaandsvisning:
        statusser += [ReviewStatus.APPROVED, ReviewStatus.NEEDS_REVIEW]
    sider = []
    for a in db.get_articles(statusser):
        pub = db.get_publication(a.id) if a.status == ReviewStatus.PUBLISHED else None
        if pub and pub.trukket_tilbage:
            continue
        slug = pub.slug if pub else f"{slugify(a.overskrift)}-{a.id}"
        score = max([db.score_for(r) for r in a.raw_item_ids[:1]] or [0])
        sider.append(Side(artikel=a, slug=slug, score=score, udkast=a.status != ReviewStatus.PUBLISHED,
                          sektion=sektion(a), rettelse=pub.rettelsesnote if pub else ""))
    # Vigtigst og nyest først
    sider.sort(key=lambda s: (s.score, s.artikel.oprettet), reverse=True)
    return sider


def nyeste_boliger(db: Database, antal: int = 2) -> list[RawItem]:
    """De boliger, der senest er kommet til salg."""
    boliger = [b for b in db.get_raw_items(source_id=BOLIG_KILDE, limit=200) if b.data]
    boliger.sort(key=lambda b: (b.data.get("dage_til_salg") is None, b.data.get("dage_til_salg") or 0))
    return boliger[:antal]


def fordel(forside: Forside) -> dict:
    """Fordel artiklerne på forsidens pladser. Hver artikel bruges én gang."""
    brugt: set[int] = set()

    def tag(kandidater, antal):
        valgt = [s for s in kandidater if id(s) not in brugt][:antal]
        brugt.update(id(s) for s in valgt)
        return valgt

    alle = [s for s in forside.sider if s.sektion != "udland"]
    med_billede = [s for s in alle if s.artikel.billede_url]
    mad = [s for s in forside.sider if s.sektion == "mad"]
    pladser = {
        "mad": tag(mad, 1),
        "tophistorie": tag(med_billede or alle, 1),
    }
    pladser["topstrimmel"] = tag([s for s in alle if s.sektion != "mad"], 2)
    pladser["sidekolonne"] = tag([s for s in alle if s.sektion != "mad"], 2)
    for sek, antal in (("folkely", 3), ("havn", 6), ("sport", 3), ("nyheder", 6), ("udland", 2)):
        pladser[sek] = tag([s for s in forside.sider if s.sektion == sek], antal)
    pladser["oevrige"] = tag([s for s in alle if s.sektion != "mad"], 8)
    return pladser


# --- HTML ---------------------------------------------------------------------------

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700'
         '&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap" rel="stylesheet">')


def _dokument(titel: str, krop: str, rod: str = "", beskrivelse: str = "") -> str:
    return f"""<!doctype html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(titel)}</title>
<meta name="description" content="{escape(beskrivelse or 'Gulvmåtten: lokale nyheder fra Hundested')}">
{FONTS}
<link rel="stylesheet" href="{rod}style.css">
</head>
<body>
<div class="avis">
{krop}
</div>
</body>
</html>
"""


def _billede(a: Article, klasse: str = "", stoerrelse: str = "") -> str:
    if not a.billede_url:
        return ""
    kredit = f'<figcaption>{escape(a.billede_kredit)}</figcaption>' if a.billede_kredit else ""
    return (f'<figure class="foto {klasse}"><img src="{escape(a.billede_url)}" alt="" loading="lazy" '
            f'referrerpolicy="no-referrer"{stoerrelse}>{kredit}</figure>')


def _udkast_maerke(s: Side) -> str:
    return '<span class="udkast">Udkast</span> ' if s.udkast else ""


def _teaser(s: Side, rod: str = "") -> str:
    return (f'<a class="teaser" href="{rod}{s.href}">'
            f'<span class="teaser__titel">{_udkast_maerke(s)}{escape(s.artikel.overskrift)}</span>'
            f'<span class="kicker">{escape(s.kicker)}</span></a>')


def _kort(s: Side, rod: str = "", vis_billede: bool = True) -> str:
    a = s.artikel
    billede = _billede(a, "kort__foto") if vis_billede else ""
    return (f'<article class="kort{" kort--foto" if billede else ""}">'
            f'<a href="{rod}{s.href}">{billede}'
            f'<span class="kicker">{escape(s.kicker)}</span>'
            f'<h3>{_udkast_maerke(s)}{escape(a.overskrift)}</h3>'
            f'<p>{escape(a.resume)}</p></a></article>')


def _sektion(noegle: str, sider: list[Side], ekstra_klasse: str = "", intro: str = "") -> str:
    if not sider:
        return ""
    kort = "".join(_kort(s) for s in sider)
    intro_html = f'<p class="sektion__intro">{intro}</p>' if intro else ""
    return (f'<section class="sektion sektion--{noegle} {ekstra_klasse}">'
            f'<h2 class="sektion__titel">{SEKTION_NAVNE[noegle]}</h2>{intro_html}'
            f'<div class="gitter">{kort}</div></section>')


def _avishoved(nu: datetime, lille: bool = False, rod: str = "") -> str:
    klasse = "hoved hoved--lille" if lille else "hoved"
    return (f'<header class="{klasse}">'
            f'<div class="hoved__linje"><span class="dato">{ugedato(nu)}</span>'
            f'<span class="hoved__info">Hundested · gratis · ingen betalingsmur</span></div>'
            f'<a class="masthead" href="{rod}index.html">Gulvmåtten</a>'
            f'<div class="blaa-streg"></div></header>')


def _topboks(forside: Forside, mad: list[Side]) -> str:
    if mad:
        s = mad[0]
        return (f'<a class="topboks topboks--mad" href="{s.href}"><span class="topboks__lille">Ugens spisested</span>'
                f'<span class="topboks__stor">{escape(s.artikel.overskrift.split(":", 1)[-1].strip())}</span>'
                f'<span class="topboks__lille">Læs om stedet</span></a>')
    if forside.annoncer:
        return _annonce(forside.annoncer[0], "topboks")
    return ""


def _annonce(an: dict, klasse: str = "") -> str:
    tag = "a" if an.get("url") else "div"
    href = f' href="{escape(an["url"])}"' if an.get("url") else ""
    return (f'<{tag} class="annonce {klasse}"{href}><span class="annonce__maerke">Annonce</span>'
            f'<span class="annonce__tekst">{escape(an.get("tekst", ""))}</span>'
            f'<span class="annonce__under">{escape(an.get("undertekst", ""))}</span></{tag}>')


def _tophistorie(s: Side) -> str:
    a = s.artikel
    by = escape(a.by or "Hundested")
    return (f'<section class="top">'
            f'<div class="top__tekst"><a href="{s.href}"><h2>{_udkast_maerke(s)}{escape(a.overskrift)}</h2></a>'
            f'<p><b class="stednavn">{by}:</b> {escape(a.resume)}</p>'
            f'<a class="laes" href="{s.href}">Læs artiklen</a></div>'
            f'<a class="top__foto" href="{s.href}">{_billede(a, "top__billede")}</a>')


def _mad_boks(mad: list[Side]) -> str:
    if not mad:
        return ""
    s = mad[0]
    k = karakter(s.artikel)
    maatter = (f'<p class="maatter" aria-label="{k} ud af 6 gulvmåtter">'
               + "▮" * k + '<span class="tom">' + "▮" * (6 - k) + f"</span> {k}/6 gulvmåtter</p>") if k else ""
    return (f'<section class="mad"><h2 class="sektion__titel">Ugens spisested</h2>'
            f'<a href="{s.href}">{_billede(s.artikel, "mad__foto")}'
            f'<h3>{_udkast_maerke(s)}{escape(s.artikel.overskrift)}</h3></a>{maatter}'
            f'<p>{escape(s.artikel.resume)}</p></section>')


def _bolig_kort(b: RawItem) -> str:
    d = b.data
    fakta = " · ".join(x for x in [
        d.get("type", ""),
        f'{d["boligareal"]} m²' if d.get("boligareal") else "",
        f'{d["vaerelser"]} vær.' if d.get("vaerelser") else "",
        f'opført {d["byggeaar"]}' if d.get("byggeaar") else "",
    ] if x)
    billede = (f'<figure class="foto bolig__foto"><img src="{escape(b.billede_url)}" alt="" loading="lazy" '
               f'referrerpolicy="no-referrer"><figcaption>Foto: {escape(d.get("maegler", "mægleren"))}'
               f'</figcaption></figure>') if b.billede_url else ""
    return (f'<a class="bolig" href="{escape(b.url)}" rel="noopener">{billede}'
            f'<span class="bolig__pris">{kr(d.get("pris"))}</span>'
            f'<span class="bolig__adresse">{escape(d.get("adresse", b.titel))}</span>'
            f'<span class="bolig__fakta">{escape(fakta)}</span>'
            f'<span class="bolig__maegler">{escape(d.get("maegler", ""))}</span></a>')


def _boliger(boliger: list[RawItem]) -> str:
    if not boliger:
        return ""
    return (f'<section class="boliger"><h2 class="sektion__titel">Nye boliger til salg</h2>'
            f'<div class="boliger__liste">{"".join(_bolig_kort(b) for b in boliger)}</div>'
            f'<p class="lille">Data fra Boligsiden. Klik for mæglerens salgsopstilling.</p></section>')


def _udland(sider: list[Side]) -> str:
    if not sider:
        return ""
    punkter = "".join(f'<li><a href="{s.href}">{_udkast_maerke(s)}{escape(s.artikel.overskrift)}</a>'
                      f'<p>{escape(s.artikel.resume)}</p></li>' for s in sider)
    return (f'<section class="udland"><h2 class="sektion__titel">Udlandsstof</h2>'
            f'<p class="udland__stempel">Nyt fra Frederiksværk og omegn</p><ul>{punkter}</ul></section>')


def _fod(rod: str = "") -> str:
    return (f'<footer class="fod"><p><b>Gulvmåtten</b> er et lokalt netmedie for Hundested. Navnet kommer fra '
            f'den gamle gratisavis, som mange brugte som gulvmåtte.</p>'
            f'<p>Alle artikler bygger på offentlige kilder, som står under hver artikel, og er læst af en '
            f'redaktør før publicering. Billeder tilhører kilderne og vises med kreditering.</p></footer>')


def forside_html(forside: Forside, nu: datetime) -> str:
    p = fordel(forside)
    top = "".join(_teaser(s) for s in p["topstrimmel"])
    side = "".join(_teaser(s) for s in p["sidekolonne"])
    tophistorie = (_tophistorie(p["tophistorie"][0]) + f'<aside class="top__side">{side}</aside></section>'
                   if p["tophistorie"] else "")
    # Topboksen bruger første annonce, når der ikke er et ugens spisested. Så
    # gentages den ikke længere nede.
    annonce = (_annonce(forside.annoncer[-1], "annonce--bred")
               if forside.annoncer and (p["mad"] or len(forside.annoncer) > 1) else "")
    krop = (
        f'<div class="topstrimmel">{top}{_topboks(forside, p["mad"])}</div>'
        f'{_avishoved(nu)}'
        f'{tophistorie}'
        f'{_sektion("folkely", p["folkely"], intro="Sommerens hyggeligste hemmelighed, året rundt.")}'
        f'{_sektion("havn", p["havn"])}'
        f'<div class="to-kolonner">{_mad_boks(p["mad"])}{_boliger(forside.boliger)}</div>'
        f'{_sektion("sport", p["sport"])}'
        f'{annonce}'
        f'<div class="to-kolonner to-kolonner--bred">'
        f'{_sektion("nyheder", p["nyheder"] + p["oevrige"])}{_udland(p["udland"])}</div>'
        f'{_fod()}'
    )
    return _dokument("Gulvmåtten · Hundested", krop)


def _afsnit(tekst: str) -> str:
    dele = []
    for afsnit in [x.strip() for x in tekst.split("\n\n") if x.strip()]:
        if afsnit.startswith("Praktisk:"):
            dele.append(f'<aside class="praktisk"><h2>Praktisk</h2><p>{escape(afsnit[9:].strip())}</p></aside>')
        else:
            dele.append(f"<p>{escape(afsnit)}</p>".replace("\n", "<br>"))
    return "".join(dele)


def artikel_html(s: Side, nu: datetime) -> str:
    a = s.artikel
    rod = "../"
    kilder = "".join(f'<li><a href="{escape(k)}" rel="noopener">{escape(k)}</a></li>' for k in a.kilder)
    usikker = (f'<aside class="redaktion"><h2>Til redaktøren</h2><p><b>Usikkerheder:</b> {escape(a.usikkerheder)}</p>'
               + (f'<p>{escape(a.redaktoer_note)}</p>'.replace("\n", "<br>") if a.redaktoer_note else "")
               + f'<p><b>Risiko:</b> {a.risiko.value}</p></aside>'
               if s.udkast and (a.usikkerheder or a.redaktoer_note) else "")
    rettelse = f'<p class="rettelse"><b>Rettelse:</b> {escape(s.rettelse)}</p>' if s.rettelse else ""
    krop = (
        f'{_avishoved(nu, lille=True, rod=rod)}'
        f'<article class="artikel">'
        f'<p class="kicker">{escape(s.kicker)} · {escape(a.by)} · {dansk_dato(a.oprettet)}</p>'
        f'<h1>{_udkast_maerke(s)}{escape(a.overskrift)}</h1>'
        f'<p class="artikel__resume">{escape(a.resume)}</p>'
        f'{_billede(a, "artikel__foto")}{rettelse}'
        f'<div class="artikel__tekst">{_afsnit(a.broedtekst)}</div>'
        f'<aside class="kilder"><h2>Kilder</h2><ul>{kilder}</ul></aside>{usikker}'
        f'</article>{_fod(rod)}'
    )
    return _dokument(f"{a.overskrift} · Gulvmåtten", krop, rod=rod, beskrivelse=a.resume)


# --- Byg ------------------------------------------------------------------------------

def byg_site(db: Database, ud: Path = SITE_DIR, forhaandsvisning: bool = False,
             nu: datetime | None = None) -> list[Path]:
    nu = nu or datetime.now()
    if not forhaandsvisning:
        publicer_godkendte(db, nu)
    try:
        annoncer = load_settings().get("annoncer") or []
    except FileNotFoundError:
        annoncer = []
    forside = Forside(sider=saml_sider(db, forhaandsvisning), boliger=nyeste_boliger(db), annoncer=annoncer)
    (ud / "artikel").mkdir(parents=True, exist_ok=True)
    skrevet = []
    sti = ud / "index.html"
    sti.write_text(forside_html(forside, nu), encoding="utf-8")
    skrevet.append(sti)
    for s in forside.sider:
        sti = ud / s.href
        sti.write_text(artikel_html(s, nu), encoding="utf-8")
        skrevet.append(sti)
    css = Path(__file__).with_name("style.css")
    (ud / "style.css").write_text(css.read_text(encoding="utf-8"), encoding="utf-8")
    skrevet.append(ud / "style.css")
    return skrevet
