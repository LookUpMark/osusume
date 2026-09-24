# Third-party notices

Runtime dependencies of this project (fastapi, uvicorn, httpx, regex, numpy; react, react-dom) are MIT- or BSD-licensed.

One transitive **dev-time only** dependency is distributed under different terms:

- **caniuse-lite** (transitive of vite → browserslist): data licensed **CC-BY-4.0**. It is used exclusively at build time to compute browser compatibility targets and ships in none of the runtime artifacts.

## Downloaded at runtime

All model weights downloaded at runtime by the setup wizard come from `lmstudio-community/*`, `mlx-community/*` or `unsloth/*` on Hugging Face and are distributed under their respective open licenses (typically **Apache 2.0**).

The optional **collaborative signal** model (`osusume-cf-v1.bin`, Settings → Collaborative signal) is built by this project from the datasets below:

- **User-Animelist-Dataset** (ratings) by mramazan — licensed **CC-BY-4.0**. Source: <https://huggingface.co/datasets/mramazan/User-Animelist-Dataset>. © The dataset authors. Changes: ratings were filtered (score ≥ 7), ID-joined to AniList and reduced to latent item vectors.
- **anime-offline-database** (ID mapping MAL → AniList) by manami-project — licensed **ODbL 1.0 + DbCL 1.0**. Source: <https://github.com/manami-project/anime-offline-database>. Changes: used to derive an anime-ID mapping only. The derived mapping ships inside the artifact; per ODbL share-alike, the mapping itself is treated as a derivative of the database.

## Removed earlier

- **hono / @hono/node-server** (MIT) — the Node server they powered was replaced by the Python/FastAPI backend in v1.0.0; they no longer ship with any release.
