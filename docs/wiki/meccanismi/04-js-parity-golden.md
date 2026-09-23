# 04 — JS parity & golden master

**Abstract.** The backend is a byte-faithful port of a TypeScript server: a compatibility layer reproduces JavaScript number/string semantics, serialization emits JS-shaped JSON, and a golden harness replays a fixed session against both servers and diffs the bytes.

## Purpose

Guarantee that switching from the Node server to the Python one changes nothing observable: same numbers (V8 float formatting, `Math.round`), same strings (`trim`, UTF-16 lengths), same JSON shapes (key order, `null` vs omitted), same error codes.

## How it works

**Compatibility layer** (`backend/app/domain/js_compat.py`):
- `js_round(x) = floor(x+0.5)` (`js_compat.py:20-22`) — never Python banker's rounding.
- `js_trim` with the exact ECMA-262 WhiteSpace+LineTerminator set `_JS_WS` (`js_compat.py:28-42`) — differs from `str.strip()` on `\x1c-\x1f`, `\x85`, U+FEFF.
- `js_length` = UTF-16 units, not code points (`js_compat.py:45-47`) — used by the tokenizer and `/lookup` bounds.
- `js_number` / `js_num_str` (`js_compat.py:50-76`): integral floats serialize as `90` not `90.0`; `String(number)` semantics (documented ceiling: exponent thresholds diverge for |x| ≥ 1e16 — unreachable in this domain).
- `to_locale_string` (`js_compat.py:79-106`): hardcoded en/it separators with Italian `minimumGroupingDigits=2` (5000 → "5000", 90000 → "90.000").
- `js_log10` (`js_compat.py:169-245`): fdlibm port of V8 12.4's `ieee754::log/log10`, including FMA (`math.fma`, exact `Fraction` fallback below 3.13). V8's libm is *not* correctly rounded and diverges from CPython by up to 1 ULP — validated differentially against node on 130k inputs, 0 mismatches (`js_compat.py:109-123`). Negative input → NaN, rendered as `null` (`js_compat.py:226-229`).

**Serialization** (`backend/app/shared/models.py`):
- `_js_numbers` (`models.py:23-31`): recursive — non-finite floats → `null` (as `JSON.stringify`), otherwise `js_number`. Applied to every pydantic model via `JsModel` (`models.py:34-45`).
- `reco_payload` (`backend/app/queries/recommend.py:14-34`): key order = TS assignment order; `links`/`mmRank` omitted when undefined; `rootId: null` explicit.

**Golden master** (`tests/golden/`):
- `tests/golden/record.mjs` recorded the session against the ORIGINAL TS server; `backend/scripts/golden_actual.py` replays the same steps against the Python server through the same env recipe as the test harness (`backend/tests/harness.py`): repo-root cwd, `ANILIST_FIXTURES`, dead LLM endpoints, fresh tmpdir, no `APP_VERSION` (`golden_actual.py:7-12`).
- Steps in fixed order (local-mode transitions are sequential): health-pre/post, recommend-en/it, profile, lookup×3, explain-fallback, chat-503, setup-status, config, app-update, error-403/400-username/q/ids/chat, localmode-off, localmode-retry-live (`golden_actual.py:49-95`). Volatile paths scrubbed (`golden_actual.py:101-113`).
- `tests/golden/compare.py`: objects key-order-insensitive, arrays order-SENSITIVE, numbers compared via `repr` so `1 != 1.0`; exit 1 on any mismatch (`compare.py:8-9,53-58,88-98`).

## Edge cases

- The TS source wins over ported tests when they disagree (settled doctrine after the v1.0.1 audit — e.g. junk JSON body → `invalid_username`, not `invalid_request`).
- JSON body parsing rejects `NaN`/`Infinity` literals like `JSON.parse` (`parse_constant`), and Python `$` regex semantics require `\A…\Z` instead of `^…$` (Python `$` accepts a trailing `\n`, JS `$` doesn't).
- `pytest-asyncio` 1.4: module-scoped async fixtures need `@pytest_asyncio.fixture(loop_scope="module")`.

## Dependencies

- Used by: AniList adapter (cache keys, header `Number()`) ([01](meccanismi/01-anilist-adapter.md)), scoring/popularity ([03](meccanismi/03-recommendation-pipeline.md)), profile formatting ([02](meccanismi/02-taste-profile.md)), API parsing ([05](meccanismi/05-api-server.md)), card `score` rounding ([06-llm-layer.md](meccanismi/06-llm-layer.md)).

## Files covered

- `backend/app/domain/js_compat.py`
- `backend/app/shared/models.py`
- `backend/app/core/js_json.py`
- `backend/scripts/golden_actual.py`
- `tests/golden/record.mjs`, `tests/golden/compare.py`
- `backend/tests/harness.py`, `backend/tests/fake_http.py`

## Studio

1. Give a concrete case where `math.log10` and V8's `log10` differ, and why it matters for the golden test.
2. Why are golden arrays order-sensitive while objects are not?
3. Where would a Python `$`-anchored username regex accept input JS would reject?
