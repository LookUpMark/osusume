# Domain concepts (glossary)

Every entry links the mechanism that owns it and the code that defines it.

- **RecoResult** — the unit of a recommendation run: `{profile, recos, avoided}`. Defined `backend/app/shared/models.py:171-174`; produced by [03-recommendation-pipeline.md](meccanismi/03-recommendation-pipeline.md); cached 10 min in memory.
- **ScoredReco** — one recommendation: `media, final 0..1.1, breakdown {affinity, quality, community, mood?}, badges, rootId, groupSize, why, links?, mmRank?`. `models.py:146-158`; serialized with TS key order by `reco_payload` (`backend/app/queries/recommend.py:14-34`).
- **MediaLite** — trimmed media metadata for prompts/UI (title fallback chain, spoiler-safe tags, relations). `backend/app/adapters/anilist/media.py:48-82`; TS mirror `frontend/src/lib/types.ts`.
- **TasteProfile / DimValue** — loved/disliked dimensions with affinity, support and examples. [02-taste-profile.md](meccanismi/02-taste-profile.md); `models.py:95-114`.
- **WhyNot** — an anti-recommendation with an honest reason (dropped prequel, disliked dimensions). `scoring.py:218-252`; shown in the Avoid view.
- **Badges** — `NEXT_STEP` (+0.12 bonus), `ENTRY_POINT` (franchise gate, no bonus), `SPIN_OFF`, `HIDDEN_GEM` (popularity < 40k, score ≥ 72, gem_score ≥ 0.45). [03](meccanismi/03-recommendation-pipeline.md), `scoring.py:115-133,281-312`; UI labels via `badgeKey` (`frontend/src/lib/logic/display.ts:13-14`).
- **mmRank** — 1-based MMR-diversified position; drives the UI default sort. `scoring.py:321-348`; consumed by `applyFilters` (`frontend/src/lib/logic/recos.ts:19-29`).
- **Franchise chain / rootId** — PREQUEL-linked entries collapsed to a canonical `rootId = min(chain ids)`; classification EXCLUDED / STANDALONE / NEXT_STEP / ENTRY_POINT. `backend/app/domain/franchise.py:13-94`.
- **Explanation (why)** — deterministic (from `loved_overlap`) or LLM text; `source: "llm" | "cache" | "fallback"` decides the dialog dot. [06-llm-layer.md](meccanismi/06-llm-layer.md).
- **ChatCard** — server-extracted model-recommended title (bold protocol): `{id, title, coverImage, coverColor, seasonYear, format, score 0..110, siteUrl}`. `backend/app/adapters/llm/chat.py:56-68`, TS `frontend/src/lib/types.ts`; rendered by [09-chat-ui.md](meccanismi/09-chat-ui.md).
- **PROMPT_VERSION** — cache-busting constant for the explain cache; bumped when the doctrine voice changes. `explain.py:29`.
- **Local mode / fixtures** — recorded AniList data served offline; env `ANILIST_FIXTURES` pins it, auto-fallback flips it on first outage. `backend/app/core/config.py:52-94`; UI banner toggle.
- **Golden master** — byte-level parity harness vs the original TS server; arrays order-sensitive, numbers via `repr`. [04-js-parity-golden.md](meccanismi/04-js-parity-golden.md).
- **JS-parity helpers** — `js_round/js_trim/js_length/js_number/js_num_str/to_locale_string/js_log10`: JavaScript semantics in Python. `backend/app/domain/js_compat.py`.
- **Setup wizard states** — `needsSetup`, job `idle|installing-cli|downloading|done|error`, backend `up|starting|off|skipped|custom`. [07-setup-wizard.md](meccanismi/07-setup-wizard.md).
- **envOverride** — settings-UI flag: `LLM_BASE_URL`/`LLM_MODEL` env vars beat file config at runtime. `backend/app/core/config.py:174-176`, `routes.py:167-179`.
- **Owner notes** — user's `systemPromptExtra` appended to both LLM prompts as OWNER NOTES; never replaces the doctrine. `backend/app/adapters/llm/prompts.py:62-72`.
