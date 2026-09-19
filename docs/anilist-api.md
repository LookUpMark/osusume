# API AniList — fatti verificati (docs.anilist.co, 2026-09-07)

## Endpoint

POST `https://graphql.anilist.co` con body `{query, variables}`. Nessuna chiave per dati pubblici.

## Lista utente

- `MediaListCollection(userName, type: ANIME)`: intera lista; `perChunk` max 500, loop su `hasNextChunk`; **tetto 11.000 entry**; **includere le custom lists** (entry nascoste vivono lì; i gruppi custom arrivano nello stesso campo `lists` con flag `isCustomList`).
- Entry: `status` (CURRENT/PLANNING/COMPLETED/DROPPED/PAUSED/REPEATING), `score(format: POINT_100)` (0-100), `progress`, `repeat`, `notes`.
- `User.mediaListOptions.scoreFormat` dice il formato nativo; forzando POINT_100 si evita la normalizzazione.

## Metadata Media

- `genres [String]`, `tags {name rank(0-100) category isGeneralSpoiler isMediaSpoiler}`, `averageScore`, `popularity`, `favourites`, `studios(isMain: true)`, `seasonYear`, `format`, `episodes`, `coverImage{large color}`, `siteUrl`, `description`.
- `relations {edges {relationType node {id}}}` — MediaRelation: PREQUEL, SEQUEL, PARENT, SIDE_STORY, SPIN_OFF, ADAPTATION, ALTERNATIVE, SUMMARY, SAME_UNIVERSE...; connections perPage max 25.
- `Media.recommendations(sort: RATING_DESC, perPage ≤ 25)` → recommendation user-submitted con `rating` community: usato come segnale community (pre-cotto, ToS-ok).
- `Media.reviews(sort: RATING_DESC, perPage: 3)` → recensioni utente (`summary`, `body`, `score`, `rating`): grounding per le narrazioni LLM (explain + chat). Una query per titolo spiegato/discusso (non per lookup), cache 7gg, degrada in silenzio: fallimento o fixtures → niente riga reception, mai blocco del flusso né trigger del fallback local-mode.

## Candidate pool

`Page(perPage ≤ 50) { media(type: ANIME, isAdult: false, genre_in, tag_in, minimumTagRank, sort: [POPULARITY_DESC|SCORE_DESC]) }`.
Paginazione SOLO via `pageInfo { hasNextPage }` (total/lastPage NON affidabili). Un solo campo dati per query Page.

## Rate limit

- Nominale 90 req/min; **degradata a 30 req/min fino a nuovo ordine** (banner ufficiale 2026-09-07). Header `X-RateLimit-Remaining`/`X-RateLimit-Reset`; 429 con `Retry-After`. Burst limiter aggiuntivo. No SLA: outage possibili (2026-09-07: "temporarily disabled due to severe stability issues").
- Strategia del progetto: token bucket 25/min, backoff su Retry-After (cap 60s) e 5xx (1/2/4s), cache disco TTL (lista 1h, media 7gg), modalità fixture per dev/test offline.

## ToS (cruciali)

- "Hoarding or mass collection of data from the AniList API is strictly prohibited"; vietato usarla come storage/backup.
- → NO mirror del catalogo: solo query mirate (~13-16/utente) sui top generi/tag del profilo; cache con TTL; sezione compliance nel README.
- OAuth: Authorization Code / Implicit grant, niente PKCE, token 1 anno senza refresh — NON serve in v1 (liste pubbliche leggibili senza token).

## Fixtures

`ANILIST_FIXTURES=fixtures` → il client legge `fixtures/userlist.json` (ListEntry[]), `fixtures/candidates.json` (MediaLite[]), `fixtures/recommendations.json` (Record<mediaId, {targetId, rating}[]>) invece della rete. `pnpm record-fixtures <username>` registra dalla API reale.
