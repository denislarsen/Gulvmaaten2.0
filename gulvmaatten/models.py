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
    regler: str = ""
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
            regler=d.get("regler", ""),
        )


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
    id: int | None = None


@dataclass
class Publication:
    article_id: int
    slug: str
    publiceret: datetime = field(default_factory=datetime.now)
    rettelsesnote: str = ""
    trukket_tilbage: datetime | None = None
    id: int | None = None
