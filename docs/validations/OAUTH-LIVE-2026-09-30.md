# Validazione live OAuth AniList — 2026-09-30

Chiude il caveat della roadmap (`docs/roadmap.md`): *"OAuth AniList … Da validare live con
l'app registrata su anilist.co"*. I test automatici (`backend/tests/test_auth.py`) coprono il
flow contro FakeServer; qui si valida contro **anilist.co reale** con browser e account veri.

## Ambiente

| Componente | Valore |
|---|---|
| Backend | uvicorn dev (`backend/run_dev.py`), `http://127.0.0.1:3000` |
| Frontend | vite dev, `http://localhost:5173` |
| Fixtures | OFF (cwd `backend/`, niente `ANILIST_FIXTURES`) — serving live |
| Callback loopback | porta fissa **47321** |
| Redirect URI da registrare | `http://127.0.0.1:47321/callback` (127.0.0.1, NON localhost) |
| Config | `data/config.json` (chiavi `anilistClientId`, `anilistClientSecret`, `anilistToken`, …) |

## Casi di test

### 1. Registrazione app su anilist.co (manuale, utente)
- [x] App creata su https://anilist.co/settings/developer con redirect URI esatto
      `http://127.0.0.1:47321/callback`.
- Esito: **OK** — app pre-esistente dell'utente, redirect URI corretto.

### 2. Credenziali via Impostazioni
- [x] `PATCH /api/auth/anilist` con clientId/secret dal pannello "AniList account" → status
      `configured: true`; il secret NON compare mai nelle risposte API.
- [x] Persistenza: chiavi presenti in `data/config.json`.
- Esito: **OK** — 6 chiavi anilist su disco; `/api/settings` e `/api/auth/anilist` senza leak
      del secret.

### 3. Login completo (authorization-code + callback loopback)
- [x] "Collega" → `POST /api/auth/anilist/start` → browser apre authorize URL con
      `redirect_uri=http://127.0.0.1:47321/callback` e `state` monouso.
- [x] Consenso su anilist.co → redirect alla callback → pagina "Signed in to Osusume".
- [x] `GET /api/auth/anilist` → `authenticated: true`, username Viewer reale (`LookUpMark`).
- [x] Auto-login frontend (polling 1.5 s durante `flow: pending`).
- Esito: **OK** — token valido 1 anno. **Bug trovato e fixato**: il pannello Impostazioni
      non ricontrollava mai lo stato dopo l'avvio del flow e restava su "Finish the sign-in
      in your browser…" per sempre (fix: polling 1.5 s in `AniListAuth.tsx` finché
      `flow === "pending"`).

### 4. Liste private col token
- [x] Un titolo presente **solo** in una lista privata dell'account risulta visibile/corretto
      nell'app (`fetch_user_list` con token, `media.py:111-122`). Se necessario si crea una
      lista privata da anilist.co durante la sessione.
- Esito: **OK** — confermato dall'utente con la propria lista privata.

### 5. Watchlist add (PLANNING) dal dialog
- [x] Dialog dettaglio di un titolo non in lista → "Aggiungi al piano" → entry **PLANNING**
      visibile su anilist.co.
- [x] Chip aggiornata ("nel piano"); riaprendo il dialog su un titolo già in lista → chip
      "già in lista" (`GET /api/watchlist/status`).
- Esito: **OK** — confermato dall'utente su 3 casi (pannello connesso, add, già in lista).

### 6. Percorsi d'errore
- [x] Doppio `POST /api/auth/anilist/start` mentre un flow è pending → 409 `oauth_busy`.
- [x] Porta 47321 occupata → 409 `oauth_port_busy`.
- [x] `POST /api/watchlist` senza token (dopo disconnect) → 401 `anilist_auth`.
- [x] State sbagliato alla callback → 404 e flow resta `pending` (esercitato live sul socket
      reale: `state mismatch`, flow `pending` intatto).
- Esito: **OK** — tutti i codici corretti; dopo `oauth_port_busy` il flow torna pulito
      (`idle`, nessuno stato residuo).

### 7. Disconnect
- [x] `POST /api/auth/anilist/disconnect` → token/user azzerati, credenziali (clientId/secret)
      conservate, porta 47321 rilasciata (`lsof` vuoto) — teardown SEC-3.
- [x] Riconnessione con credenziali conservate → "Connected as LookUpMark" senza reinserire
      nulla, transizione automatica del pannello (fix del caso 3 in azione).
- Esito: **OK**. Nota UX: dopo un disconnect avvenuto fuori dal pannello (es. lato server),
      il pannello mostra lo stato stantio fino al prossimo mount — in uso normale il
      disconnect passa dal pannello stesso, quindi non è un percorso reale.

## Esiti (compilare a fine sessione)

- Data sessione: 2026-09-30
- Account di test: LookUpMark
- Casi superati: 7/7
- Bug emersi e fix:
  1. `frontend/src/components/AniListAuth.tsx` — pannello bloccato su "oauthPending": aggiunto
     polling dello stato finché `flow === "pending"` (il backend flippa a `ok` in modo
     asincrono via callback del browser).
  2. `package.json` — `pnpm dev` falliva da root (`uv run --project backend run_dev.py` non
     risolveva lo script); ora `cd backend && uv run run_dev.py` (cwd `backend/` corretta anche
     per la detection fixtures, `config.py:91`).
- Note: test eseguiti dopo i fix — pytest 203/203, tsc ok, node --test 16/16. Token reale
  presente in `data/config.json` durante i test: harness pytest isola `ALR_DATA_DIR`/`CONFIG_PATH`
  in tmpdir, nessuna contaminazione.
