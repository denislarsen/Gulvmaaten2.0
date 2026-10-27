"""Crawler: henter kilder og registrerer nye og ændrede opslag.

Fire slags kilder:
- rss         Et feed, som parses med feedparser. Mest pålideligt.
- html        En almindelig side. Opslag udpeges med CSS-selektorer fra kildeprofilen.
- sitemap     Hjemmesidens sitemap.xml. Bruges når nyhedslisten laves med JavaScript
              og derfor er tom i det, vi henter. Sitemappet giver URL og ændringsdato;
              titel og resumé hentes fra hver enkelt artikelside.
- boligsiden  Boligsidens JSON-søgning. Hver bolig bliver et opslag med pris, areal
              m.m. i `data`.

Billeder gemmes som URL i `billede_url`, men kun for kilder hvor `billeder`
er tilladt i kildeprofilen.

Selve hentningen (`hent`) er adskilt fra fortolkningen (`parse_rss`, `parse_html`,
`parse_sitemap`), så fortolkningen kan testes på gemte filer uden internet.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

from .db import Database
from .models import RawItem, Source, SourceType

USER_AGENT = "Gulvmaatten/0.1 (lokalt bymedie; kontakt via GitHub denislarsen/gulvmaaten2.0)"
TIMEOUT = 20.0
SITEMAP_MAX_DEFAULT = 20

Fetcher = Callable[[str], str]


@dataclass
class FetchResult:
    source_id: str
    ok: bool
    nye: int = 0
    aendrede: int = 0
    uaendrede: int = 0
    fejl: str = ""

    def __str__(self) -> str:
        if not self.ok:
            return f"{self.source_id}: FEJL {self.fejl}"
        return f"{self.source_id}: {self.nye} nye, {self.aendrede} ændrede, {self.uaendrede} uændrede"


def hent(url: str) -> str:
    """Hent en side som tekst. Kaster ved netværksfejl eller HTTP-fejl."""
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


# --- Billeder ------------------------------------------------------------------

def _brugbart_billede(url: str) -> bool:
    """Sorterer emojis, sporingspixels og lignende fra."""
    return bool(url) and not url.startswith("data:") and "/emoji/" not in url and not url.endswith(".svg")


def _img_src(img, base: str) -> str:
    """Find den rigtige billedadresse i et <img>, også når siden lazy-loader."""
    if img is None:
        return ""
    for attr in ("data-lazy-src", "data-src", "src"):
        v = (img.get(attr) or "").strip()
        if _brugbart_billede(v):
            return urljoin(base, v)
    srcset = img.get("data-lazy-srcset") or img.get("srcset") or ""
    if srcset.strip():
        return urljoin(base, srcset.split(",")[0].split()[0])
    return ""


def _og_image(soup, base: str) -> str:
    meta = soup.find("meta", attrs={"property": "og:image"}) or soup.find("meta", attrs={"name": "og:image"})
    return urljoin(base, meta["content"].strip()) if meta and meta.get("content") else ""


def _rss_billede(entry) -> str:
    for m in entry.get("media_content", []) + entry.get("media_thumbnail", []):
        if m.get("url"):
            return m["url"]
    for enc in entry.get("enclosures", []):
        if enc.get("href") and (enc.get("type", "").startswith("image") or not enc.get("type")):
            return enc["href"]
    for html in [c.get("value", "") for c in entry.get("content", [])] + [entry.get("summary", "")]:
        for img in BeautifulSoup(html or "", "html.parser").find_all("img"):
            src = _img_src(img, entry.get("link", ""))
            if src:
                return src
    return ""


# --- RSS ---------------------------------------------------------------------

def parse_rss(source: Source, content: str) -> list[RawItem]:
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        url = entry.get("link") or ""
        titel = (entry.get("title") or "").strip()
        if not url or not titel:
            continue
        tekst = entry.get("summary") or entry.get("description") or ""
        tekst = BeautifulSoup(tekst, "html.parser").get_text(" ", strip=True)
        dato = entry.get("published") or entry.get("updated") or ""
        items.append(RawItem(source_id=source.id, url=url, titel=titel, tekst=tekst, dato_tekst=dato,
                             billede_url=_rss_billede(entry)))
    return items


# --- HTML --------------------------------------------------------------------

def _first_text(node, selector: str) -> str:
    if not selector:
        return ""
    found = node.select_one(selector)
    return found.get_text(" ", strip=True) if found else ""


def _all_text(node, selector: str) -> str:
    """Som _first_text, men samler alle matchende elementer. Bruges til datoer,
    der ofte står i flere <time>-elementer (dato og klokkeslæt)."""
    if not selector:
        return ""
    parts = [el.get_text(" ", strip=True) for el in node.select(selector)]
    parts = [p for p in parts if p]
    # Fjern gentagelser, bevar rækkefølge
    return " ".join(dict.fromkeys(parts))


def parse_hel_side(source: Source, content: str) -> list[RawItem]:
    """Hele siden som ét opslag. Bruges til sider uden en liste, fx en
    festivals forside, hvor vi vil se, når indholdet ændrer sig."""
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    titel = soup.title.get_text(strip=True) if soup.title else source.navn
    tekst = _first_text(soup, source.html.get("resume", "")) or (soup.body.get_text(" ", strip=True) if soup.body else "")
    return [RawItem(source_id=source.id, url=source.url, titel=titel, tekst=tekst[:15000],
                    billede_url=_og_image(soup, source.url))]


def parse_html(source: Source, content: str) -> list[RawItem]:
    sel = source.html
    if sel.get("hel_side"):
        return parse_hel_side(source, content)
    if not sel.get("opslag"):
        raise ValueError(f"Kilden {source.id} mangler html.opslag-selektor")
    soup = BeautifulSoup(content, "html.parser")
    items = []
    seen: set[str] = set()
    for node in soup.select(sel["opslag"]):
        titel = _first_text(node, sel.get("titel", "")) or node.get_text(" ", strip=True)[:120]
        # Opslaget kan selv være linket (<a> der omslutter hele kortet)
        link_node = node if node.name == "a" and node.get("href") else node.select_one(sel.get("link", "a"))
        href = link_node.get("href") if link_node else None
        if not href or not titel:
            continue
        url = urljoin(source.url, href)
        if sel.get("url_uden_query"):
            url = url.split("?")[0]
        if url in seen:
            continue
        seen.add(url)
        items.append(RawItem(
            source_id=source.id,
            url=url,
            titel=titel,
            tekst=_first_text(node, sel.get("resume", "")),
            dato_tekst=_all_text(node, sel.get("dato", "")),
            billede_url=_img_src(node.select_one(sel["billede"]), source.url) if sel.get("billede") else "",
        ))
    return items


# --- Sitemap -----------------------------------------------------------------

def parse_sitemap(source: Source, content: str) -> list[tuple[str, str]]:
    """Returnerer (url, lastmod) for de sider i sitemappet, der matcher kildens
    `sitemap.prefix`, nyeste først, højst `sitemap.max` stk."""
    prefix = source.sitemap.get("prefix")
    if not prefix:
        raise ValueError(f"Kilden {source.id} mangler sitemap.prefix")
    moenster = re.compile(source.sitemap["moenster"]) if source.sitemap.get("moenster") else None
    soup = BeautifulSoup(content, "xml")
    found = []
    for url_node in soup.find_all("url"):
        loc = url_node.find("loc")
        if not loc:
            continue
        loc_text = loc.get_text(strip=True)
        if not loc_text.startswith(prefix) or loc_text.rstrip("/") == prefix.rstrip("/"):
            continue
        if moenster and not moenster.search(loc_text):
            continue
        lastmod = url_node.find("lastmod")
        found.append((loc_text, lastmod.get_text(strip=True) if lastmod else ""))
    found.sort(key=lambda t: t[1], reverse=True)
    return found[: int(source.sitemap.get("max", SITEMAP_MAX_DEFAULT))]


def parse_article_page(source: Source, url: str, content: str, dato_tekst: str = "") -> RawItem:
    """Lav et RawItem ud fra en enkelt artikelside. Titel tages fra <h1> eller
    <title>, resumé fra meta description."""
    soup = BeautifulSoup(content, "html.parser")
    sel = source.html
    titel = _first_text(soup, sel.get("titel", "")) or _first_text(soup, "h1")
    if not titel and soup.title:
        titel = soup.title.get_text(strip=True).split("|")[0].strip()
    tekst = _first_text(soup, sel.get("resume", ""))
    if not tekst:
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        tekst = (meta.get("content") or "").strip() if meta else ""
    billede = _img_src(soup.select_one(sel["billede"]), url) if sel.get("billede") else ""
    return RawItem(source_id=source.id, url=url, titel=titel or url, tekst=tekst, dato_tekst=dato_tekst,
                   billede_url=billede or _og_image(soup, url))


def fetch_sitemap_items(db: Database, source: Source, content: str, fetcher: Fetcher) -> list[RawItem]:
    """Find artikler via sitemap og hent kun de sider, vi ikke allerede har
    med samme ændringsdato. Det holder antallet af kald nede."""
    items = []
    for url, lastmod in parse_sitemap(source, content):
        existing = db.get_raw_item(source.id, url)
        if existing and existing.dato_tekst == lastmod:
            items.append(existing)
            continue
        items.append(parse_article_page(source, url, fetcher(url), dato_tekst=lastmod))
    return items


# --- Boligsiden ---------------------------------------------------------------

BOLIGTYPER = {
    "villa": "Villa", "terraced house": "Rækkehus", "condo": "Ejerlejlighed",
    "holiday house": "Fritidshus", "cooperative": "Andelsbolig", "farm": "Landejendom",
    "hobby farm": "Landejendom", "full year plot": "Helårsgrund", "holiday plot": "Fritidsgrund",
    "villa apartment": "Villalejlighed",
}


def _stoerste_billede(img: dict | None, max_bredde: int = 1000) -> str:
    """Boligsiden giver hvert billede i flere størrelser. Vælg den største op til max_bredde."""
    if not img:
        return ""
    kilder = [k for k in img.get("imageSources", []) if k.get("url")]
    passende = [k for k in kilder if k.get("size", {}).get("width", 0) <= max_bredde] or kilder
    if not passende:
        return ""
    return max(passende, key=lambda k: k.get("size", {}).get("width", 0))["url"]


def parse_boligsiden(source: Source, content: str) -> list[RawItem]:
    data = json.loads(content)
    items = []
    for c in data.get("cases", []):
        adr = c.get("address") or {}
        vej = " ".join(x for x in [adr.get("roadName", ""), str(adr.get("houseNumber", "") or "")] if x).strip()
        url = c.get("caseUrl") or ""
        if not vej or not url:
            continue
        pris = c.get("priceCash") or c.get("casePrice")
        typ = BOLIGTYPER.get(c.get("addressType", ""), (c.get("addressType") or "Bolig").capitalize())
        maegler = (c.get("realtor") or {}).get("name", "")
        felter = {
            "adresse": vej,
            "by": adr.get("cityName") or (adr.get("city") or {}).get("name", ""),
            "postnr": adr.get("zipCode"),
            "type": typ,
            "pris": pris,
            "boligareal": c.get("housingArea"),
            "grundareal": c.get("lotArea"),
            "vaerelser": c.get("numberOfRooms"),
            "byggeaar": c.get("yearBuilt"),
            "energimaerke": (c.get("energyLabel") or "").upper(),
            "dage_til_salg": c.get("daysOnMarket"),
            "maegler": maegler,
            "overskrift": c.get("descriptionTitle", ""),
        }
        pris_tekst = f"{pris:,} kr.".replace(",", ".") if pris else "pris ikke oplyst"
        tekst = f"{typ}, {felter['boligareal'] or '?'} m², {felter['vaerelser'] or '?'} vær. {pris_tekst}. {maegler}"
        items.append(RawItem(
            source_id=source.id, url=url, titel=f"{vej}, {felter['by']}".strip(", "),
            tekst=tekst, billede_url=_stoerste_billede(c.get("defaultImage")), data=felter,
        ))
    return items


# --- Samlet ------------------------------------------------------------------

def fetch_source(db: Database, source: Source, content: str | None = None,
                 fetcher: Fetcher = hent) -> FetchResult:
    """Hent én kilde og registrér opslag i databasen.

    `content` kan gives direkte (til tests og offline-kørsel); ellers hentes URL'en.
    `fetcher` bruges til eventuelle ekstra sider (sitemap-kilder) og kan byttes ud i tests.
    """
    result = FetchResult(source_id=source.id, ok=True)
    try:
        if content is None:
            content = fetcher(source.url)
        if source.type == SourceType.RSS:
            items = parse_rss(source, content)
        elif source.type == SourceType.SITEMAP:
            items = fetch_sitemap_items(db, source, content, fetcher)
        elif source.type == SourceType.BOLIGSIDEN:
            items = parse_boligsiden(source, content)
        else:
            items = parse_html(source, content)
    except Exception as e:  # noqa: BLE001 - vi vil rapportere alle fejl pr. kilde
        return FetchResult(source_id=source.id, ok=False, fejl=f"{type(e).__name__}: {e}")

    for item in items:
        # Stockfotos (fx kommunens Colourbox-billeder) har kilden licens til, men vi har ikke
        if not source.billeder or "colourbox" in item.billede_url.lower():
            item.billede_url = ""
        status = db.record_raw_item(item)
        if status == "ny":
            result.nye += 1
        elif status == "aendret":
            result.aendrede += 1
        else:
            result.uaendrede += 1
    db.mark_fetched(source.id, datetime.now())
    return result


def fetch_all(db: Database, kun_forfaldne: bool = False) -> list[FetchResult]:
    """Hent alle aktive kilder. Med kun_forfaldne=True springes kilder over,
    der er hentet for nylig ifølge deres frekvens."""
    results = []
    now = datetime.now()
    for source in db.get_sources():
        if kun_forfaldne and source.sidst_hentet:
            timer_siden = (now - source.sidst_hentet).total_seconds() / 3600
            if timer_siden < source.frekvens_timer:
                continue
        results.append(fetch_source(db, source))
    return results
