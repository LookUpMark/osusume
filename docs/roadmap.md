# Roadmap (fuori scope v1)

- ~~**Collaborative filtering (v2)**~~: FATTO (2026-09-29) — artefatto ALS 96-dim (15.379 titoli AniList, 3MB) costruito offline da Turan 148M rating + anime-offline-database (recall@20 2.52× popularity); segnale opzionale nel ranking (cap 0.1) con download automatico + toggle in Impostazioni (`scripts/cf/`, `backend/app/adapters/cf.py`). Eval live LookUpMark: 8/20 titoli nuovi in top.
- ~~**OAuth AniList**~~: FATTO (2026-09-23) — liste private + watchlist add (PLANNING) dal dialog; authorization code con callback loopback su porta fissa (`backend/app/adapters/anilist/auth.py`); token server-side, credenziali in Impostazioni. Validato live 2026-09-30, 7/7 casi (`docs/validations/OAUTH-LIVE-2026-09-30.md`).
- **Fallback MAL/Kitsu** se AniList giù a lungo (Jikan API / Kitsu API).
- **LLM whyNot narrativo** (v1: whyNot solo deterministico) e re-ranking LLM opzionale.
- ~~**Streaming progress** (SSE)~~: FATTO (2026-09-23) — `GET /api/recommend/stream` con 9 fasi osservate da `recommend_for` (mai riordinate), stepper UI.
- ~~**Manga**~~: FATTO (2026-09-24) — secondo mondo con switch ANIME/MANGA in Rail (`mediaType` su tutti gli endpoint, `$type: MediaType` nelle query, fixtures-manga, prompt per tipo, profilo unico da lista anime).
- **i18n estesa** oltre EN/IT: file stringhe unico già predisposto.
- **SQLite** se mai serve multi-utente concorrente (oggi: filesystem cache + in-memory result cache).
