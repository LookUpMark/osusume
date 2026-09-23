"""Compatibilità numerica con JavaScript (spec §2.2.1 e §2.2.2).

- ``Math.round`` ≠ ``round()`` Python (banker's): qui ``floor(x + 0.5)``.
- ``toLocaleString(lang)`` con separatori HARDCODED en=`,` it=`.` — mai la
  locale di sistema (ICU).
"""

from __future__ import annotations

import math
import struct

# N.B. nessun import da app.shared.models: models.py usa js_number per la
# serializzazione JS-style e l'arco inverso creerebbe un import circolare.
# ``lang`` è quindi ``str`` (i chiamanti passano il Literal Lang di models).

_EXPONENT = 1e21  # oltre 1e21 JS passa alla notazione esponenziale


def js_round(x: float) -> int:
    """Math.round: floor(x + 0.5) — MAI round() Python (banker's rounding)."""
    return math.floor(x + 0.5)


# WhiteSpace + LineTerminator di ECMA-262 (String.prototype.trim): differisce da
# str.strip() sia in più (\x1c-\x1f, \x85 sono whitespace Python, non JS) sia in
# meno (﻿ è ZWNBSP/WhiteSpace JS, non whitespace Python)
_JS_WS = (
    "\t\n\v\f\r \u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def js_trim(s: str) -> str:
    """``String.prototype.trim``: taglia SOLO i whitespace ECMA-262."""
    start, end = 0, len(s)
    while start < end and s[start] in _JS_WS:
        start += 1
    while end > start and s[end - 1] in _JS_WS:
        end -= 1
    return s[start:end]


def js_length(s: str) -> int:
    """``String.length``: unità UTF-16, NON code point (\"🦈\".repeat(41).length = 82)."""
    return len(s.encode("utf-16-le")) // 2


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


# --- Math.log10 bit-esatto (V8) ---------------------------------------------------
#
# ``popNorm`` (scoring.ts) usa Math.log10: la libm di CPython è correttamente
# arrotondata, quella di V8 NO (port fdlibm) → divergono fino a 1 ULP su ~3%
# degli input e ``quality``/``final`` non tornano più coi golden (verificato su
# fixtures-real: quality 0.8331809270421852 vs golden 0.833180927042185 per
# popularity 115775, cioè log10(115776) — pop+1). Il port sotto replica
# l'algoritmo di
# v8/src/base/ieee754.cc (``log`` + ``log10``, V8 12.4 = node 22), letto dal
# disassembly arm64 del binario node di Marco: clang contrae ``a*b ± c`` in
# fmadd/fmsub/fnmsub e l'arrotondamento unico È parte del risultato — niente
# fma, niente bit-esattezza. Validato differenzialmente contro node su 130k
# input (fixture di entrambe le dir + random mantissa/esponente): 0 mismatch.
# ponytail: solo il ramo dei double normali positivi — popularity+1 non tocca
# mai zero/subnormali/inf/NaN (i rami speciali di fdlibm non sono portati).

_LN2_HI = 6.93147180369123816490e-01
_LN2_LO = 1.90821492927058770002e-10
_TWO54 = 1.80143985094819840000e+16
_LG1 = 6.666666666666735130e-01
_LG2 = 3.999999999940941908e-01
_LG3 = 2.857142874366239149e-01
_LG4 = 2.222219843214978396e-01
_LG5 = 1.818357216161805012e-01
_LG6 = 1.531383769920937332e-01
_LG7 = 1.479819860511658591e-01
_IVLN10 = 4.34294481903251816668e-01
_LOG10_2HI = 3.01029995663611771306e-01
_LOG10_2LO = 3.69423907715893078616e-13


_have_fma = hasattr(math, "fma")
if not _have_fma:  # Python < 3.13
    from fractions import Fraction as _Fraction


def _fma(a: float, b: float, c: float) -> float:
    """``a*b + c`` con UN solo arrotondamento (l'fma dell'arm64 compilato).

    math.fma esiste da Python 3.13; il fallback Fraction è esatto (prodotto e
    somma in aritmetica razionale, un solo round finale) ma ~100x più lento —
    ~20ms per un'intera pipeline di recommend su 3.12, irrilevante qui.
    """
    if _have_fma:
        return math.fma(a, b, c)  # type: ignore[attr-defined]
    return float(_Fraction(a) * _Fraction(b) + _Fraction(c))


def _high_word(x: float) -> int:
    """Parola alta (segno+esponente+20 bit mantissa) del double."""
    return int.from_bytes(struct.pack(">d", x)[:4], "big")


def _set_high_word(x: float, hi: int) -> float:
    """``SET_HIGH_WORD`` di fdlibm: riscrive la parola alta tenendo la bassa."""
    b = bytearray(struct.pack(">d", x))
    b[0:4] = hi.to_bytes(4, "big")
    return struct.unpack(">d", bytes(b))[0]


def _v8_log(x: float) -> float:
    """``ieee754::log`` di V8 (fdlibm e_log), FMA contraction inclusa."""
    hx = _high_word(x)
    k = 0
    if hx < 0x00100000:  # subnormali: irraggiungibili, ma il branch è del sorgente
        k -= 54
        x *= _TWO54
        hx = _high_word(x)
    if hx >= 0x7FF00000:
        return x + x
    k += (hx >> 20) - 1023
    hx &= 0x000FFFFF
    i = (hx + 0x95F64) & 0x100000
    x = _set_high_word(x, hx | (i ^ 0x3FF00000))  # normalize x or x/2
    k += i >> 20
    f = x - 1.0
    if (0x000FFFFF & (2 + hx)) < 3:  # |f| < 2**-20
        if f == 0.0:
            if k == 0:
                return 0.0
            dk = float(k)
            return _fma(dk, _LN2_HI, dk * _LN2_LO)
        R = (f * f) * _fma(f, -0.33333333333333333, 0.5)
        if k == 0:
            return f - R
        dk = float(k)
        d = _fma(dk, -_LN2_LO, R)
        d = d - f
        return _fma(dk, _LN2_HI, -d)
    s = f / (2.0 + f)
    dk = float(k)
    z = s * s
    i = hx - 0x6147A
    w = z * z
    j = 0x6B851 - hx
    t1 = w * _fma(w, _fma(w, _LG6, _LG4), _LG2)
    t2 = z * _fma(w, _fma(w, _fma(w, _LG7, _LG5), _LG3), _LG1)
    i |= j
    R = t1 + t2
    if i > 0:
        hfsq = (0.5 * f) * f
        d = hfsq + R
        if k == 0:
            return f - _fma(-s, d, hfsq)  # fmsub
        d = _fma(s, d, dk * _LN2_LO)
        d = hfsq - d
    else:
        d = f - R
        if k == 0:
            return _fma(-s, d, f)  # fmsub
        d = _fma(s, d, -dk * _LN2_LO)
    d = d - f
    return _fma(dk, _LN2_HI, -d)  # fnmsub arm64: b*c - a


def js_log10(x: float) -> float:
    """``Math.log10`` di V8 (fdlibm e_log10), per ``popNorm`` — vedi sopra."""
    # x negativo: fdlibm lavora sull'high word CON segno (hx < 0 → ramo subnormali)
    # e V8 produce NaN; qui il confronto è su unsigned → gestire il segno a parte
    if x < 0:
        return math.nan
    hx = _high_word(x)
    k = 0
    if hx < 0x00100000:  # subnormali: irraggiungibili con popularity+1
        k -= 54
        x *= _TWO54
        hx = _high_word(x)
    if hx >= 0x7FF00000:
        return x + x
    if hx == 0x3FF00000 and struct.pack(">d", x)[4:] == b"\x00" * 4:
        return 0.0  # log(1) = +0
    k += (hx >> 20) - 1023
    i = (k & 0x80000000) >> 31
    hx = (hx & 0x000FFFFF) | ((0x3FF - i) << 20)
    y = float(k + i)
    x = _set_high_word(x, hx)
    return _fma(y, _LOG10_2HI, _fma(y, _LOG10_2LO, _v8_log(x) * _IVLN10))
