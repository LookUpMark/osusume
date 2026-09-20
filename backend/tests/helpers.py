"""Fixture condivise dei test dominio (P2).

Base neutra = quella del fixture ``media`` di ``tests/scoring.test.ts``. Chi
serve basi diverse passa override espliciti: i valori pinned di ogni file di
test restano nel file (stessi valori dei test TS).
"""

from __future__ import annotations

from app.shared.models import MediaLite


def media(id: int, **over) -> MediaLite:
    base = dict(
        id=id,
        title=f"m{id}",
        format="TV",
        seasonYear=2015,
        genres=[],
        tags=[],
        studio=None,
        averageScore=70,
        popularity=100000,
        coverImage=None,
        coverColor=None,
        siteUrl=None,
        description=None,
        relations=[],
    )
    base.update(over)
    return MediaLite(**base)
