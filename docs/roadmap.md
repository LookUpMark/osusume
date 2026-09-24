# Roadmap (fuori scope v1)

- **Collaborative filtering (v2)**: dataset Turan (HF `mramazan/User-Animelist-Dataset`, 148M rating, CC-BY-4.0, 2025, include liste AniList) come segnale ibrido; join ID via anime-offline-database (frozen 2026-27, ODbL). v1 resta content-based puro.
- ~~**OAuth AniList**~~: FATTO (2026-09-23) — liste private + watchlist add (PLANNING) dal dialog; authorization code con callback loopback su porta fissa (`backend/app/adapters/anilist/auth.py`); token server-side, credenziali in Impostazioni. Da validare live con l'app registrata su anilist.co.
- **Fallback MAL/Kitsu** se AniList giù a lungo (Jikan API / Kitsu API).
- **LLM whyNot narrativo** (v1: whyNot solo deterministico) e re-ranking LLM opzionale.
- ~~**Streaming progress** (SSE)~~: FATTO (2026-09-23) — `GET /api/recommend/stream` con 9 fasi osservate da `recommend_for` (mai riordinate), stepper UI.
- **Manga** (AniList type: MANGA): quasi gratis, ma profilo/testi da ricontrollare.
- **i18n estesa** oltre EN/IT: file stringhe unico già predisposto.
- **SQLite** se mai serve multi-utente concorrente (oggi: filesystem cache + in-memory result cache).
