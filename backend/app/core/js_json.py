"""Serializzatore JSON equivalente a ``JSON.stringify`` (spec §2.2.6).

Serve per le chiavi di cache sha256: ``sha256(query + JSON.stringify(variables))``.
``json.dumps`` di default differisce (spazi dopo i separatori, escape ascii).
Divergenze note vs JS: soglie esponenziali sui float e ``0x7F`` — nessuna è
rilevante per le variabili AniList (solo stringhe/interi/oggetti/array).
"""

from __future__ import annotations

import hashlib
import json


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_key(query: str, variables) -> str:
    return hashlib.sha256((query + dumps(variables)).encode("utf-8")).hexdigest()
