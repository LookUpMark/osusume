# frontend/

UI di Osusume (React 19 + Vite 6). Costruita da qui: `pnpm build` → `dist/`;
in dev il server TS monta Vite middleware e serve lo stesso entry
(`index.html` → `/frontend/src/main.tsx`).

```
frontend/
  od-ids.txt                  inventario canonico dei marker data-od-id (35)
  src/
    main.tsx                  bootstrap + ErrorBoundary
    App.tsx                   ORCHESTRAZIONE: stato, boot, run(), polling, gate
    design-system/tokens.css  :root (tutte le CSS var) + primitive condivise
    styles.css                aree per sezione (shell, sidebar, hero, card, …)
    components/               11 componenti presentazionali
    views/index.ts            View, VIEW_LABEL, VIEW_ORDER
    lib/api.ts                client fetch (tale e quale all'ex src/ui/api.ts)
    lib/i18n.ts               tr() + dict en/it COMPLETI (owner: frontend)
    lib/logic/                LOGICA NON RIDISEGNABILE (vedi sotto)
```

`src/shared/types.ts` e `src/shared/strings.ts` restano nel repo finché il
server TS esiste (fase P9): `lib/i18n.ts` ne è la copia di proprietà frontend,
i tipi si importano ancora da lì.

## Contratto con OpenDesign

OpenDesign può **rigenerare** `components/` e `views/` e i **valori** dei token
in `design-system/tokens.css`. I `data-od-id` sono i punti di aggancio: ognuno
di quelli in `od-ids.txt` deve sopravvivere (`node scripts/check-od-ids.mjs`
fallisce se uno manca dal bundle). Tutto ciò che sta in `lib/logic/` è
**contratto**: si richiama, non si riscrive.

## Logica NON ridisegnabile

Check eseguibile del contratto: `node --test tests/frontend-logic.test.ts`.

Punteggio e formule display (`lib/logic/display.ts`):

- `score110(final)` = `Math.round(final * 100)` — sempre reso come `/110` (hero,
  card, topbar, dialog, stat "Highest match").
- `communityBar(community)` = `community / 0.1` — riga community del breakdown
  nel DetailDialog.
- `badgeKey(badge)` = `"NEXT_STEP"` → `"badgeNextStep"` (chiave i18n, stesso
  schema del server di scoring).
- `metaJoin([...])` = filtra i campi vuoti e unisce con `" · "`.

Ranking, filtri e derivati (`lib/logic/recos.ts`):

- `gemRank(r)` = `affinity − popularity/1_000_000` solo per gli HIDDEN_GEM,
  altrimenti `-Infinity` (fuori dominio, nessun accoppiamento a config).
- `applyFilters` — ordine dei filtri FISSO: gemsOnly → format → genre, poi il
  sort (`final` = ordine default diversificato del server via `mmRank ?? 1e6`,
  `gem` = gemRank desc, `affinity` = breakdown.affinity desc).
- `topPicksOf` = ordinati per `final` desc; `heroPick` = `[0]`;
  `carouselPicks` = `slice(0, 8)`.
- `gemsOf` = filter HIDDEN_GEM + sort affinity desc.
- `topGenres` = frequenza dei generi, `slice(0, 9)` (top-9), ordine per conteggio desc.
- `formatsOf` = formati distinti presenti, ordine di prima comparsa.

Error mapping (`lib/logic/errors.ts`):

- `user_not_found` → `errUserNotFound`, `anilist_error` → `errAnilistDown`,
  tutto il resto → `errGeneric`.

Gate di rendering e ordine `run()` (in `App.tsx`, NON spostabili nel JSX):

1. `setup === null` → splash minimo (mai la shell completa).
2. `setup === "error"` → pagina di errore con retry.
3. `setup.needsSetup && !setup.customEnv` → SetupWizard a tutto schermo; il
   wizard si auto-completa con **ownership stretta**: solo un job `done` per
   QUESTO modello (`job.model === model`) chiude il setup, mai `install-cli`.
4. Al boot: `localStorage.username` presente → `run(username)` diretto;
   altrimenti LoginModal aperto.
5. `run(u)`: reset stato/filtri → `showView("recos")` → `fetchProfile` →
   `fetchRecommend` → `setResult` → `setPhase("recos")`; in `finally` sempre
   `refreshHealth()` (il server può essere caduto in local-mode a metà richiesta).
   Login/switch persiste lo username SOLO se `run()` è andata a buon fine.

Timing e soglie (invariabili):

- polling health ogni **60 s**; polling setup wizard ogni **1500 ms**;
- cronaca chat: `history.slice(-12)` girata al server;
- carousel: 8 pick; grid: `eager={i < 6}` (prime 6 cover eager, resto lazy);
- ricerca anime (topbar): minimo **2 caratteri**, `maxLength` **80**;
  input login: regex `/^[A-Za-z0-9_-]{1,32}$/` + `maxLength` **32**;
  input chat: `maxLength` **4000**;
- localStorage, 3 chiavi: `lang` ("en"|"it", validato mai cast — il cambio
  lingua rilancia `run()` perché why e narrazioni sono per-lingua),
  `username` (persistito solo dopo un run riuscito), `alr-view` (ultima vista,
  accettata solo se in `VIEW_ORDER`);
- spiegazioni LLM **on-demand** per titolo all'apertura del DetailDialog
  (cache server 7d), con fold nel risultato via `onWhy` + `extraRecos` per i
  titoli aperti dalla ricerca/chat;
- local-mode: toggle via `POST /api/local-mode`, banner con "Retry live" che
  riaccende `auto=false` e rilancia `run(username)`.
