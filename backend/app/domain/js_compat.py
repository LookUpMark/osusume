"""Compatibilità numerica con JavaScript (spec §2.2.1 e §2.2.2).

- ``Math.round`` ≠ ``round()`` Python (banker's): qui ``floor(x + 0.5)``.
- ``toLocaleString(lang)`` con separatori HARDCODED en=`,` it=`.` — mai la
  locale di sistema (ICU).
"""

from __future__ import annotations

import math

# N.B. nessun import da app.shared.models: models.py usa js_number per la
# serializzazione JS-style e l'arco inverso creerebbe un import circolare.
# ``lang`` è quindi ``str`` (i chiamanti passano il Literal Lang di models).

_EXPONENT = 1e21  # oltre 1e21 JS passa alla notazione esponenziale


def js_round(x: float) -> int:
    """Math.round: floor(x + 0.5) — MAI round() Python (banker's rounding)."""
    return math.floor(x + 0.5)


def js_number(x: float | int) -> float | int:
    """Numero JS come valore Python: un float integrale diventa ``int``.

    ``Math.round(900)/10`` in JS è il numero ``90`` (JSON ``"90"``), non ``90.0``.
    """
    if isinstance(x, float) and x.is_integer() and abs(x) < _EXPONENT:
        return int(x)
    return x


def js_num_str(x: float | int) -> str:
    """``String(number)`` JS: integrali senza decimali (80 → ``"80"``, non ``"80.0"``).

    Usato nelle interpolazioni TS (``${e.score}`` nell'hash del profilo, ``avg``
    nei template why): un drift qui invalida la cache spiegazioni.

    ponytail: per |x| ≥ 1e16 o 0 < |x| < 1e-6 ``repr`` Python usa l'esponenziale
    dove JS no (String(1e16)="10000000000000000" vs repr="1e+16"; String(1e-6)
    ="0.000001" vs repr="1e-06" — le soglie dell'esponenziale divergono).
    Unreachable coi valori di dominio: id/score/rank/popularity stanno tra
    1e-6 e 1e16; da estendere solo se il dominio tocca scala astronomica.
    """
    if isinstance(x, int):
        return str(x)
    if x.is_integer() and abs(x) < _EXPONENT:
        return str(int(x))
    return repr(x)  # shortest round-trip, come la conversione number→string di JS


def to_locale_string(value: float | int, lang: str) -> str:
    """``Number.prototype.toLocaleString(lang)`` con separatori HARDCODED (spec §2.2.2).

    en: migliaia ``,`` decimal ``.`` (grouping minimo 1) — it: migliaia ``.``
    decimal ``,`` con minimumGroupingDigits = 2 (CLDR ``it``): l'intero non si
    raggruppa finché le cifre − 3 < 2, cioè 4 cifre restano ``5000`` NON
    ``5.000``. Valore PINNATO dai golden ``recommend-it.json`` ("solo 5000
    membri" ma "90.000 membri") = output reale di node 22/ICU.
    """
    thousands, decimal = (",", ".") if lang == "en" else (".", ",")
    min_grouping = 1 if lang == "en" else 2
    sign = "-" if value < 0 else ""
    if isinstance(value, int):
        int_part, frac = str(abs(value)), ""
    else:
        text = repr(abs(value))
        if "e" in text or "E" in text:  # forma esponenziale: espansa (mai per popularity)
            text = f"{abs(value):.20f}".rstrip("0")
        int_part, _, frac = text.partition(".")
        frac = frac.rstrip("0")  # shortest repr: 5.0 → "5"
    if len(int_part) - 3 >= min_grouping:
        groups: list[str] = []
        while len(int_part) > 3:
            int_part, group = int_part[:-3], int_part[-3:]
            groups.insert(0, group)
        groups.insert(0, int_part)
        int_part = thousands.join(groups)
    return f"{sign}{int_part}{decimal + frac if frac else ''}"
