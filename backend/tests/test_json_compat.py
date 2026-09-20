"""Anti-drift del serializzatore JSON: deve produrre ESATTAMENTE ``JSON.stringify``.

I vettori (stringa attesa + sha256) sono generati con node:
    node -e "const c=require('crypto'); const v=[...]; \
             for(const x of v) console.log(JSON.stringify(x), \
             c.createHash('sha256').update('q'+JSON.stringify(x),'utf8').digest('hex'))"
Le chiavi di cache AniList sono sha256(query + JSON.stringify(variables)): un drift
qui invalida in silenzio la cache su disco condivisa con il backend TS.
"""

from __future__ import annotations

import hashlib

import pytest

from app.core.js_json import dumps, sha256_key

QUERY = "q"

# (variables, JSON.stringify atteso, sha256("q" + stringa) atteso)
VECTORS = [
    # oggetto vuoto / variabili vuote
    ({}, "{}", "16531a4347d90148bb57fdfe65ca765be68f7dcdd4232b60dec271d9c8a82e43"),
    # unicode non ascii, NON escapata
    (
        {"name": "café"},
        '{"name":"café"}',
        "dde96e4e4c405fd130abf64ff030a744b625f7d6db51644df1870fae4e07c142",
    ),
    # escape \n \t e slash NON escapata
    (
        {"text": "a\nb\tc/d"},
        '{"text":"a\\nb\\tc/d"}',
        "6e354d5539221097be7e4a0644da29bb1b655ade13f032bef60e45b7020d5334",
    ),
    # interi (nulla di float: le soglie esponenziali divergono, vedi docstring modulo)
    (
        {"id": 123, "page": 1, "zero": 0, "neg": -5},
        '{"id":123,"page":1,"zero":0,"neg":-5}',
        "f28981689b3bf07ef065a3c7aed3fac2d63f26e8a599ec8862beccc2fad96873",
    ),
    # ordine di inserimento delle chiavi (JS lo preserva, niente sort)
    (
        {"z": 1, "a": 2, "m": 3},
        '{"z":1,"a":2,"m":3}',
        "9b01769ade330612f11daa4b0d14cfb82acae8ca839af13760d736263d210f90",
    ),
    # payload realistico AniList (Page/page/perPage/sort) + annidamento
    (
        {"page": 2, "perPage": 50, "sort": "POPULARITY_DESC", "name": "café", "deep": {"x": [1, 2, {"y": "eé"}]}},
        '{"page":2,"perPage":50,"sort":"POPULARITY_DESC","name":"café","deep":{"x":[1,2,{"y":"eé"}]}}',
        "3f2d39113850ae6fa57cff9e996c1640492f9f370bde9455344590bbff1a1f6b",
    ),
]


@pytest.mark.parametrize("variables,stringified,_", VECTORS)
def test_dumps_uguale_a_json_stringify(variables, stringified, _):
    assert dumps(variables) == stringified


@pytest.mark.parametrize("variables,_,digest", VECTORS)
def test_sha256_key_uguale_a_node(variables, _, digest):
    assert sha256_key(QUERY, variables) == digest


def test_query_concatenata_prima_delle_variabili():
    raw = "query Q ($p: Int) {}"
    assert sha256_key(raw, {}) == hashlib.sha256(f"{raw}{{}}".encode("utf-8")).hexdigest()


def test_nan_rifiutato_allow_nan_false():
    with pytest.raises(ValueError):
        dumps({"x": float("nan")})
