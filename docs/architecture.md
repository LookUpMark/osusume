# Architettura

## Pipeline

```
username
  → fetchUserList (1-2 req GraphQL, cache 1h)
  → buildProfile (sentiment per entry → loved/disliked per tag/genere/studio/era)
  → fetchCandidates (~13 req mirate: top generi/tag dell'utente, NO mirror catalogo)
  → community hits (Media.recommendations dei top-5 scored, 5 req)
  → analyzeFranchises (catene PREQUEL; 2a passata dopo aggiunta entry point mancanti)
  → scoreAll (pure) → top 50 con why deterministico
  → (async, opzionale) LLM explain per id
```

## Moduli (src/server/)

| File | Responsabilità |
|---|---|
| `anilist.ts` | Unico punto di rete: token bucket (~25/min), backoff 429 (Retry-After/X-RateLimit-Reset, cap 60s) e 5xx (1/2/4s), cache su disco con TTL, modalità fixture `ANILIST_FIXTURES=fixtures` |
| `profile.ts` | Normalizzazione lista + `buildProfile()`: μ utente, sentiment, aggregazione per dimensione con shrink support |
| `candidates.ts` | Pool candidati ToS-compatibile: top-3 generi × 2 pagine POPULARITY_DESC, top-5 tag × 1 pagina (minTagRank 60), 2 pagine SCORE_DESC (pool gemme). Dedup + esclusione lista utente |
| `scoring.ts` | SOLO funzioni pure: affinity/quality/gem/community/scoreAll + why/whyNot deterministici |
| `franchise.ts` | Grafo relations, catene PREQUEL (guardia cicli, max 10 hop), classificazione NEXT_STEP/ENTRY_POINT/STANDALONE/EXCLUDED |
| `llm.ts` | Spiegazioni batch da 10 via endpoint OpenAI-compatibile, cache su disco (username+profile.hash+ids+model+lang), timeout 30s, fallback deterministico |
| `setup.ts` | Setup wizard backend: hardware detect (chip/RAM/Apple Silicon con fallback Rosetta), suggerimento Qwen3.6-35B-A3B (≥32 GB RAM) o Gemma 4 12B 4bit, GGUF per LM Studio + pack MLX per backend (oMLX/LM Studio/Ollama), layer `data/config.json` (precedenza env > file > default, in `config.ts`), risoluzione `lms` (env LMS_PATH > config > default > PATH), install-cli one-click (script ufficiali a stringa fissa), job download singleton (`lms get` e stream HF→oMLX) con logTail, `ensureLlmServer()` a ogni avvio (daemon up → server start → get se assente → load → ready-poll; mai throw, log su `data/llm.log`), route `/api/setup/*` |
| `recommend.ts` | Orchestratore: pipeline completa + in-memory cache risultato (TTL 10 min) |
| `api.ts` | GET /api/health, /api/profile/:username, /api/config; POST /api/recommend {username, lang}, /api/explain {username, ids, lang}; mount /api/setup |
| `index.ts` | Hono + Vite middleware (dev) o serve dist (prod); bind 127.0.0.1; chiama `ensureLlmServer()` all'avvio |

Split `recommend`/`explain` = degrado grazioso strutturale: UI mostra subito le recos deterministiche, le spiegazioni LLM arrivano dopo (o mai). LLM morto ≠ app rotta.

## Formule (tutti i numeri in src/server/config.ts WEIGHTS)

### Sentimento per entry (score normalizzato 0-100 via POINT_100)
```
μ = media score > 0 (se < 3 scored: μ=60, confidence=low)
s_raw = clamp((score − μ)/40, −1, 1)
statusBase: COMPLETED 0 | CURRENT +0.10 | REPEATING +0.15 | PAUSED −0.25 | DROPPED −0.60 | PLANNING escluso
repeatBonus = 0.10 × min(repeat, 3)
sentiment = clamp(statusBase + s_raw + repeatBonus, −1, 1)
peso entry: scored 1.0 | unscored COMPLETED 0.4 | unscored DROPPED 0.6
```

### Profilo per dimensione
```
tag: contributo pesato per rank/100; genre/studio/era: peso 1 (era = bucket 5 anni su seasonYear)
aff(value) = meanSentiment × min(support, 10)/10
loved: aff > +0.05 && support ≥ 2 → top 20 tag / 8 generi / 5 studio
disliked: aff < −0.05 && support ≥ 2 → top 10
```

### Candidato
```
tagScore   = Σ aff(t)·(rank/100) / Σ (rank/100)   (tag non noti contribuiscono 0 al numeratore, restano al denominatore: diluizione neutra)
genreScore = mean(aff(g)) | studioScore = aff(main) | 0 | eraScore = aff(bucket) | 0
affinity01 = (0.50·tag + 0.30·genre + 0.12·studio + 0.08·era + 1) / 2
quality    = 0.80·(averageScore ?? 60)/100 + 0.20·popNorm,  popNorm = clamp((log10(popularity+1)−2)/4, 0, 1)
gemScore   = 0.65·affinity01 + 0.35·quality − 0.30·popNorm
HIDDEN_GEM: popularity < 40.000 && averageScore ≥ 72 && gemScore ≥ 0.45
communityBonus = min(0.10, Σ 0.03·max(0, sentiment_source))  (dai recommendation graph dei top-5 scored)
final01 = clamp(0.60·affinity01 + 0.28·quality + communityBonus + franchiseBonus(+0.12 NEXT_STEP), 0, 1.10)
```

## Franchise

- Solo `PREQUEL` è prerequisito; SIDE_STORY/SPIN_OFF/PARENT = badge `SPIN_OFF` informativo.
- Catena: traversal PREQUEL da ciascun candidato, visited-set anti-ciclo, max 10 hop. Prequel esterni al pool = fine catena (id noto, metadati fetchabili a parte).
- Classificazione per candidato:
  - un predecessore DROPPED → `EXCLUDED` (fuori dai risultati, motivo nel whyNot)
  - tutti i predecessori visti (COMPLETED/CURRENT/REPEATING/PAUSED) → `NEXT_STEP`
  - almeno un predecessore non visto → il candidato non si mostra; si mostra l'`ENTRY_POINT` = primo nodo non visto dalla parte del root (se già PLANNING → skip silenzioso)
- Entry point mancanti dal pool: `fetchMediaByIds` (1 req batch) → seconda passata di `analyzeFranchises` sul pool esteso, poi scoring.
- Dedup UI: un rappresentante per franchise (miglior final), `groupSize` per "altri N della serie".

## Limiti noti (ponytail)

- relations perPage 25 (franchigi mostruose tipo Fate possono troncare catene)
- MediaListCollection tetto 11.000 entry (limite API)
- prequel multipli: si usa il primo
- fixture mode ignora i filtri di query (ritorna sempre il pool registrato)
