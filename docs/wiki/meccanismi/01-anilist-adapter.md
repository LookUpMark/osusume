# 01 — AniList adapter

**Abstract.** The only outbound I/O of the backend: a token-bucket rate limiter, a GraphQL POST client with a retry ladder, a disk cache with in-flight dedup, media mapping into domain models, and a fixtures mode that serves recorded data offline.

## Purpose

Talk to `graphql.anilist.co` politely (AniList enforces rate limits), keep responses on disk, and never let an AniList outage crash the app — degrade to fixtures when possible.

## How it works

1. Every public call goes through `gql(query, variables, ttl_ms)` (`backend/app/adapters/anilist/client.py:157-159`): cache key = `js_json.sha256_key(query, variables)`, result wrapped by `cache.cache_wrap`.
2. `cache_wrap` (`backend/app/adapters/anilist/cache.py:38-64`) reads the file cache (hit iff `now_ms() < exp`), dedups concurrent misses via an in-flight task map (`cache.py:49-54`), writes `{"exp", "data"}` with `allow_nan=False` — deliberately non-atomic, matching the TS original (`cache.py:6-7`).
3. On miss, `_gql_fetch` (`backend/app/adapters/anilist/client.py:115-154`) runs a retry ladder with one shared `attempt` counter: token taken each iteration (`client.py:119`); transport/timeout/5xx → exponential backoff `1000*2**attempt`, max 3 (`client.py:122-126,135-137`); 429 → up to 10 rounds, delay `min(retry-after, 60)` or 5 s (`client.py:127-134`).
4. Body parsing is strict: `parse_constant=_reject_constant` rejects NaN/Infinity literals (`client.py:139`), then `_null_non_finite` converts non-finite floats to `None` so cache writes never explode (`client.py:38-48`).
5. GraphQL `errors[0]` → `AniListError(message, status)`; JS-falsy `data` → `AniListError` (`client.py:145-153`).
6. Rate limit: module-level token bucket, capacity 3, refill `RATE_PER_MIN/60` per second (default 25/min, `backend/app/core/config.py:45`); starving callers sleep outside the lock (`client.py:59-69`).

## Key actors

- `gql(query, variables, ttl_ms, token=None)` — `client.py:162-172`: with `token` the cache key is salted `auth|<sha256[:8]>|` so private responses never collide with anonymous ones (or with other accounts); `gql_uncached` (`client.py:175-179`) bypasses the cache entirely for mutations/Viewer.
- `cache_wrap(path, ttl_ms, fetch)` — `cache.py:38-64`
- `take_token()` — `client.py:59-69`; `reset_bucket_for_tests()` — `client.py:72-76`
- `map_media(m) -> MediaLite` — `backend/app/adapters/anilist/media.py:48-82` (title fallback romaji→english→`(id N)`, spoiler tags filtered, description truncated to 500, relations restricted to PREQUEL/SEQUEL/SIDE_STORY/SPIN_OFF/PARENT)
- `fetch_user_list` — `media.py:88-131` (≤22 chunks × 500; status lists win over custom-list duplicates; live branch attaches the OAuth token when the requested user is the connected one — [11-anilist-oauth.md](meccanismi/11-anilist-oauth.md))
- `fetch_media_list_status(user, media_id)` — `media.py` tail: entry status for the watchlist UI (failure → None = "not in list")
- `fetch_media_reviews` / `gather_reviews` — `media.py:197-231` (any failure → `data=None`, reviews never block explain/chat)
- `read_fixture(name)` — `backend/app/adapters/anilist/fixtures.py:12-16`
- GraphQL documents byte-identical to the TS originals (part of the cache key) — `backend/app/adapters/anilist/queries.py:1-7` (plus `VIEWER_QUERY` / `SAVE_PLANNING_MUTATION` / `MEDIA_LIST_STATUS_QUERY` appended for OAuth). The four catalog/list queries take `$type: MediaType` (post-manga): the type rides in the variables, so per-type disk-cache keys come for free.
- `_fixtures_dir(media_type)` — `media.py`: local mode reads `fixtures-manga/` (same three files) when the run is MANGA; a base dir already ending in `-manga` stays unchanged (env-pinned manga servers).

## Data & states

- Cache files: `{CACHE_DIR}/<sha256>.json`, `{"exp": epoch-ms, "data": …}`. TTLs chosen at call sites: list 1 h, media 7 d (`CACHE_TTL_LIST_MS`/`CACHE_TTL_MEDIA_MS`, `backend/app/core/config.py:183-184`). Expired files are never deleted; a parse error is a silent miss.
- Bucket state: `_tokens` (0..3), `_last_refill`, `_refill_per_sec` — test-resettable.

## Edge cases

- All retries exhausted → `AniListError(…, 502)` / `(…, 429)`; the API layer maps them (`routes.py:69-75`), and `with_local_fallback` may flip to fixtures (see [05-api-server.md](meccanismi/05-api-server.md)).
- Reviews are best-effort: empty summaries dropped, body/summary whitespace-collapsed and capped (120/260 chars), hard cap 2 reviews (`media.py:203-222`).
- Local mode ignores page filters and serves the recorded pool whole (`media.py:136-139`).

## Dependencies

- Config: `ANILIST_ENDPOINT`, `RATE_PER_MIN`, `CACHE_DIR` ([05-api-server.md](meccanismi/05-api-server.md) — settings & config).
- Consumed by the recommendation pipeline ([03-recommendation-pipeline.md](meccanismi/03-recommendation-pipeline.md)) and the LLM layer for reviews ([06-llm-layer.md](meccanismi/06-llm-layer.md)).
- OAuth token wiring: [11-anilist-oauth.md](meccanismi/11-anilist-oauth.md).
- JS-parity helpers for keys/trims: [04-js-parity-golden.md](meccanismi/04-js-parity-golden.md).

## Files covered

- `backend/app/adapters/anilist/client.py`
- `backend/app/adapters/anilist/cache.py`
- `backend/app/adapters/anilist/media.py`
- `backend/app/adapters/anilist/fixtures.py`
- `backend/app/adapters/anilist/queries.py`
- `backend/app/adapters/anilist/__init__.py`

## Studio

1. Why is the AniList cache write non-atomic on purpose, while the explanation cache is atomic?
2. What breaks first if `RATE_PER_MIN` is set above AniList's real limit?
3. Why must GraphQL query strings stay byte-identical to the TS originals?
4. Trace what happens when AniList is down mid-recommendation with fixtures available and auto-fallback on.
