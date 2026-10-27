"""Datamodel for Gulvmåtten.

Flowet gennem modellen:

    Source  ->  RawItem  ->  Event / Article  ->  ReviewStatus  ->  Publication

- Source      En kilde vi overvåger (kommune, bibliotek, klub ...).
- RawItem     Et opslag fundet hos en kilde, gemt som det er. Hvert opslag
              har en hash af indholdet, så vi kan se om det ændrer sig.
- Event       Et arrangement med tid og sted, udledt af et eller flere RawItems.
- Article     Et artikeludkast skrevet ud fra RawItems og evt. et Event.
- ReviewStatus  Hvor en artikel er i godkendelsen.
- Publication Det, der faktisk er lagt på hjemmesiden.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SourceType(str, Enum):
    RSS = "rss"
    HTML = "html"
    SITEMAP = "sitemap"  # Hjemmesidens sitemap.xml, til sider hvor listen laves med JavaScript
    BOLIGSIDEN = "boligsiden"  # Boligsidens JSON-søgning, til boksen med boliger til salg
    DBU_KAMPE = "dbu_kampe"    # Kampprogram fra en klubside i DBU's Klub-CMS


class ReviewStatus(str, Enum):
    """Status for et artikeludkast i den redaktionelle proces."""

    NEW = "new"                  # Udkast er lavet, ikke set af nogen
    NEEDS_REVIEW = "needs_review"  # Afventer redaktør
    APPROVED = "approved"        # Godkendt, klar til publicering
    REJECTED = "rejected"        # Afvist, publiceres ikke
    PUBLISHED = "published"      # Ligger på hjemmesiden
    RETRACTED = "retracted"      # Trukket tilbage efter publicering


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"  # Kræver altid menneskelig godkendelse


@dataclass
class Source:
    id: str
    navn: str
    url: str
    type: SourceType
    kategori: str
    by: str
    tillid: int = 3
    frekvens_timer: int = 24
    sprog: str = "da"
    verificeret: bool = False
    html: dict = field(default_factory=dict)
    sitemap: dict = field(default_factory=dict)
    regler: str = ""
    prioritet: int = 1            # 3 = særligt fokus (fx Folkely)
    billeder: bool = True         # Må kildens billeder vises (med kreditering)?
    kun_tip: bool = False         # Andre medier og borgergrupper: giver tips, aldrig artikler
    kalender: bool = False        # Alle opslag gennemgås for arrangementer til kalenderen
    kun_kalender: bool = False    # Bruges kun til kalenderen, ikke til nyheder (fx et spisesteds eventside)
    aktiv: bool = True
    sidst_hentet: datetime | None = None

    @classmethod
    def from_config(cls, d: dict) -> "Source":
        return cls(
            id=d["id"],
            navn=d["navn"],
            url=d["url"],
            type=SourceType(d["type"]),
            kategori=d.get("kategori", ""),
            by=d.get("by", ""),
            tillid=int(d.get("tillid", 3)),
            frekvens_timer=int(d.get("frekvens", 24)),
            sprog=d.get("sprog", "da"),
            verificeret=bool(d.get("verificeret", False)),
            html=d.get("html") or {},
            sitemap=d.get("sitemap") or {},
            regler=d.get("regler", ""),
            prioritet=int(d.get("prioritet", 1)),
            billeder=_ja_nej(d.get("billeder", "ja")),
            kun_tip=bool(d.get("kun_tip", False)),
            kalender=bool(d.get("kalender", False) or d.get("kun_kalender", False)),
            kun_kalender=bool(d.get("kun_kalender", False)),
            aktiv=bool(d.get("aktiv", True)),
        )


def _ja_nej(v) -> bool:
    """YAML læser `ja`/`nej` som tekst, men true/false som bool. Begge accepteres."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("ja", "yes", "true", "1")


@dataclass
class RawItem:
    """Et opslag som det blev fundet hos kilden."""

    source_id: str
    url: str
    titel: str
    tekst: str = ""
    dato_tekst: str = ""         # Datoen som kilden skrev den, ikke fortolket
    fundet: datetime = field(default_factory=datetime.now)
    sidst_set: datetime = field(default_factory=datetime.now)
    content_hash: str = ""
    billede_url: str = ""        # Billede fundet hos kilden, tomt hvis intet
    data: dict = field(default_factory=dict)  # Strukturerede felter, fx pris og areal for en bolig
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = self.compute_hash()

    def compute_hash(self) -> str:
        grund = "\n".join([self.titel.strip(), self.tekst.strip(), self.dato_tekst.strip()])
        return hashlib.sha256(grund.encode("utf-8")).hexdigest()


@dataclass
class Event:
    titel: str
    start: datetime | None
    slut: datetime | None = None
    sted: str = ""
    by: str = ""
    pris: str = ""
    tilmelding: str = ""
    arrangoer: str = ""
    aflyst: bool = False
    raw_item_ids: list[int] = field(default_factory=list)
    url: str = ""                 # Hvor man læser mere eller køber billet
    beskrivelse: str = ""         # Én sætning
    billede_url: str = ""
    source_id: str = ""
    id: int | None = None


@dataclass
class Article:
    overskrift: str
    resume: str
    broedtekst: str
    kategori: str
    by: str
    tags: list[str] = field(default_factory=list)
    kilder: list[str] = field(default_factory=list)  # URL'er artiklen bygger på
    usikkerheder: str = ""        # Hvad agenten ikke kunne bekræfte
    risiko: RiskLevel = RiskLevel.LOW
    status: ReviewStatus = ReviewStatus.NEW
    raw_item_ids: list[int] = field(default_factory=list)
    event_id: int | None = None
    oprettet: datetime = field(default_factory=datetime.now)
    opdateret: datetime = field(default_factory=datetime.now)
    redaktoer_note: str = ""
    billede_url: str = ""
    billede_kredit: str = ""      # Fx "Foto: Hundested Havn". Skal vises sammen med billedet
    id: int | None = None


@dataclass
class Publication:
    article_id: int
    slug: str
    publiceret: datetime = field(default_factory=datetime.now)
    rettelsesnote: str = ""
    trukket_tilbage: datetime | None = None
    id: int | None = None
