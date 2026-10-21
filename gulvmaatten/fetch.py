"""Crawler: henter kilder og registrerer nye og ændrede opslag.

To slags kilder:
- rss   Et feed, som parses med feedparser. Mest pålideligt.
- html  En almindelig side. Opslag udpeges med CSS-selektorer fra kildeprofilen.

Selve hentningen (`hent`) er adskilt fra fortolkningen (`parse_rss`, `parse_html`),
så fortolkningen kan testes på gemte filer uden internet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

from .db import Database
from .models import RawItem, Source, SourceType

USER_AGENT = "Gulvmaatten/0.1 (lokalt bymedie; kontakt via GitHub denislarsen/gulvmaaten2.0)"
TIMEOUT = 20.0


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
        items.append(RawItem(source_id=source.id, url=url, titel=titel, tekst=tekst, dato_tekst=dato))
    return items


def _first_text(node, selector: str) -> str:
    if not selector:
        return ""
    found = node.select_one(selector)
    return found.get_text(" ", strip=True) if found else ""


def parse_html(source: Source, content: str) -> list[RawItem]:
    sel = source.html
    if not sel.get("opslag"):
        raise ValueError(f"Kilden {source.id} mangler html.opslag-selektor")
    soup = BeautifulSoup(content, "html.parser")
    items = []
    seen: set[str] = set()
    for node in soup.select(sel["opslag"]):
        titel = _first_text(node, sel.get("titel", "")) or node.get_text(" ", strip=True)[:120]
        link_node = node.select_one(sel.get("link", "a"))
        href = link_node.get("href") if link_node else None
        if not href or not titel:
            continue
        url = urljoin(source.url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(RawItem(
            source_id=source.id,
            url=url,
            titel=titel,
            tekst=_first_text(node, sel.get("resume", "")),
            dato_tekst=_first_text(node, sel.get("dato", "")),
        ))
    return items


def parse(source: Source, content: str) -> list[RawItem]:
    if source.type == SourceType.RSS:
        return parse_rss(source, content)
    return parse_html(source, content)


def fetch_source(db: Database, source: Source, content: str | None = None) -> FetchResult:
    """Hent én kilde og registrér opslag i databasen.

    `content` kan gives direkte (til tests og offline-kørsel); ellers hentes URL'en.
    """
    result = FetchResult(source_id=source.id, ok=True)
    try:
        if content is None:
            content = hent(source.url)
        items = parse(source, content)
    except Exception as e:  # noqa: BLE001 - vi vil rapportere alle fejl pr. kilde
        return FetchResult(source_id=source.id, ok=False, fejl=f"{type(e).__name__}: {e}")

    for item in items:
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
