"""CF v2 builder — offline preprocessing + ALS training + export.

Esegue in un env DEDICATO (scripts/cf/pyproject.toml): mai dipendenze dell'app.
Dataset: Turan (HF, CC-BY-4.0) ratings.npy [user_id, mal_id, rating] + ponte ID
via anime-offline-database (ODbL, sources con URL MAL+AniList).

Output: osusume-cf-v1.bin
  header JSON (una riga) + anilist_ids int32[count] + vectors f16[count×dim]
Il backend carica SOLO questo file: niente dataset esterni a runtime.

Uso:
  uv run build.py --smoke          # 50k utenti, factors 32 — smoke del pipeline
  uv run build.py                  # full training + eval
  uv run build.py --skip-download  # riusa i file già in data/
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

import numpy as np
import requests

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
OUT_PATH = pathlib.Path(__file__).resolve().parent / "osusume-cf-v1.bin"

RATINGS_URL = "https://huggingface.co/datasets/mramazan/User-Animelist-Dataset/resolve/main/ratings.npy"
ANIMES_URL = "https://huggingface.co/datasets/mramazan/User-Animelist-Dataset/resolve/main/animes.csv"
AODB_LATEST = "https://api.github.com/repos/manami-project/anime-offline-database/releases/latest"

MIN_RATING = 7.0  # implicit positive
MIN_USER_POSITIVES = 10
HOLDOUT_USERS = 10_000
RECALL_K = 20


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def download(url: str, dest: pathlib.Path, token: str | None = None) -> pathlib.Path:
    if dest.exists() and dest.stat().st_size > 0:
        log(f"già scaricato: {dest.name} ({dest.stat().st_size / 1e6:.0f} MB)")
        return dest
    headers = {"user-agent": "osusume-cf-build"} | ({"authorization": f"Bearer {token}"} if token else {})
    log(f"download {url} → {dest.name}")
    with requests.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 22):
                f.write(chunk)
                done += len(chunk)
                if total and (done % (100 << 20)) < (1 << 22):
                    log(f"  {done / 1e6:.0f}/{total / 1e6:.0f} MB")
    log(f"scaricato: {dest.name} ({dest.stat().st_size / 1e6:.0f} MB)")
    return dest


def fetch_aodb_jsonl(data_dir: pathlib.Path) -> list[dict]:
    """Ultima release di anime-offline-database: asset jsonl.zst (o minified)."""
    dest = data_dir / "aodb.jsonl"
    if dest.exists():
        log("aodb.jsonl già estratto")
        return [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()]
    rel = requests.get(AODB_LATEST, timeout=30, headers={"user-agent": "osusume-cf-build"}).json()
    assets = [a for a in rel["assets"] if a["name"].endswith("jsonl.zst")]
    assets.sort(key=lambda a: ("minified" in a["name"], a["size"]))  # full prima del minified
    asset = assets[0]
    zst_path = download(asset["browser_download_url"], data_dir / asset["name"])
    import zstandard

    log(f"estraggo {asset['name']}")
    dctx = zstandard.ZstdDecompressor()
    with open(zst_path, "rb") as fh, open(dest, "wb") as out:
        with dctx.stream_reader(fh) as reader:
            out.write(reader.read())
    entries = [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()]
    log(f"aodb entries: {len(entries)}")
    return entries


def mal_to_anilist_map(entries: list[dict]) -> dict[int, int]:
    """`sources` → {mal_id: anilist_id}. Un MAL id può puntare a più AniList: primo vince (deterministico)."""
    out: dict[int, int] = {}
    for e in entries:
        mal = anilist = None
        for src in e.get("sources", []):
            if src.startswith("https://myanimelist.net/anime/"):
                mal = int(src.rsplit("/", 1)[1])
            elif src.startswith("https://anilist.co/anime/"):
                anilist = int(src.rsplit("/", 1)[1])
        if mal is not None and anilist is not None and mal not in out:
            out[mal] = anilist
    return out


def dataset_id_to_anilist(data_dir: pathlib.Path, mal2al: dict[int, int]) -> dict[int, int]:
    """`animeID` del dataset NON è il MAL id (Howl = 1, MAL 431): animes.csv fa da
    ponte con la colonna `mal_url`. Risultato: {dataset_anime_id: anilist_id}."""
    path = download(ANIMES_URL, data_dir / "animes.csv")
    import csv

    out: dict[int, int] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = row.get("mal_url") or ""
            if not url.startswith("https://myanimelist.net/anime/"):
                continue
            mal = int(url.rsplit("/", 1)[1])
            anilist = mal2al.get(mal)
            if anilist is not None:
                out[int(row["animeID"])] = anilist
    return out


def load_ratings(data_dir: pathlib.Path, token: str | None) -> np.ndarray:
    path = download(RATINGS_URL, data_dir / "ratings.npy", token)
    log("load ratings.npy (mmap)")
    return np.load(path, mmap_mode="r")


def build_matrix(ratings: np.ndarray, id2anilist: dict[int, int], args) -> tuple:
    """Filtri qualità → matrice implicita CSR + indici di mapping."""
    from scipy.sparse import csr_matrix

    log(f"ratings totali: {len(ratings):,}")
    mask = ratings[:, 2] >= args.min_rating
    sel = np.asarray(ratings[mask])  # copia in RAM (f64 → keep)
    log(f"positivi (rating ≥ {args.min_rating}): {len(sel):,}")

    # dataset animeID → anilist: vettorizzo con un lookup table
    ds_ids = sel[:, 1].astype(np.int64)
    keys = np.array(sorted(id2anilist.keys()), dtype=np.int64)
    values = np.array([id2anilist[k] for k in keys], dtype=np.int64)
    lut = np.full(int(keys.max()) + 1, -1, dtype=np.int64)
    lut[keys] = values
    anilist_ids = np.where(ds_ids <= keys.max(), lut[ds_ids], -1)
    keep = anilist_ids >= 0
    sel, anilist_ids = sel[keep], anilist_ids[keep]
    log(f"con join anilist: {len(sel):,} ({len(np.unique(anilist_ids)):,} titoli unici)")

    # utenti: minpositives sul positive set
    uniq_users, counts = np.unique(sel[:, 0], return_counts=True)
    ok_users = uniq_users[counts >= args.min_user_positives]
    keep = np.isin(sel[:, 0], ok_users)
    sel = sel[keep]
    anilist_ids = anilist_ids[keep]
    log(f"utenti con ≥ {args.min_user_positives} positivi: {len(ok_users):,} → righe {len(sel):,}")

    # sample per smoke
    if args.sample_users and len(ok_users) > args.sample_users:
        rng = np.random.default_rng(42)
        ok_users = rng.choice(ok_users, size=args.sample_users, replace=False)
        keep = np.isin(sel[:, 0], ok_users)
        sel = sel[keep]
        anilist_ids = anilist_ids[keep]
        log(f"SMOKE sample utenti: {len(ok_users):,} → righe {len(sel):,}")

    # indici compatti
    uniq_items = np.unique(anilist_ids)
    item_index = {aid: i for i, aid in enumerate(uniq_items)}
    user_index = {u: i for i, u in enumerate(ok_users)}
    rows = np.fromiter((user_index[u] for u in sel[:, 0]), dtype=np.int32, count=len(sel))
    cols = np.fromiter((item_index[a] for a in anilist_ids), dtype=np.int32, count=len(sel))
    # confidence implicit: scala lineare del rating (7..10 → 1..4)
    data = (sel[:, 2] - args.min_rating + 1.0).astype(np.float32)
    matrix = csr_matrix(
        (data, (rows, cols)), shape=(len(ok_users), len(uniq_items)), dtype=np.float32
    )
    return matrix, uniq_items.astype(np.int64), ok_users, sel


def holdout_split(matrix, rng) -> tuple:
    """Ultimo item (indice colonna maggiore tra i positivi... qui ordine array: ultimo inserito)
    di un campione di utenti → test. Ritorna (train_csr, test_dict user→item)."""
    matrix = matrix.tocsr()
    sample_n = min(HOLDOUT_USERS, matrix.shape[0])
    test_users = rng.choice(matrix.shape[0], size=sample_n, replace=False)
    train = matrix.copy().tolil()
    test: dict[int, int] = {}
    for u in test_users:
        cols = train.rows[u]
        if len(cols) < 2:
            continue
        test[u] = cols[-1]
        cols.remove(cols[-1])
    return train.tocsr(), test


def recall_at_k(model, train, test, item_pop) -> tuple[float, float]:
    """Recall@20 CF vs baseline popularity sugli stessi utenti."""
    factors = model.item_factors  # (items × k)
    norms = np.linalg.norm(factors, axis=1)
    norms[norms == 0] = 1e-9
    k = RECALL_K
    hits_cf = hits_pop = n = 0
    for u, true_item in test.items():
        seen = set(train[u].indices.tolist())
        user_vec = model.user_factors[u]
        un = np.linalg.norm(user_vec)
        scores = (factors @ user_vec) / (norms * (un or 1e-9))
        top = np.argpartition(-scores, k + len(seen))[: k + len(seen) + 1]
        top = [i for i in top if int(i) not in seen][:k]
        hits_cf += int(true_item in top)
        pop_top = [i for i in np.argsort(-item_pop)[: k + len(seen)] if int(i) not in seen][:k]
        hits_pop += int(true_item in pop_top)
        n += 1
    return hits_cf / n, hits_pop / n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="50k utenti + factors ridotti: solo smoke del pipeline")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--factors", type=int, default=96)
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--min-rating", type=float, default=MIN_RATING)
    ap.add_argument("--min-user-positives", type=int, default=MIN_USER_POSITIVES)
    ap.add_argument("--sample-users", type=int, default=0)
    ap.add_argument("--out", type=pathlib.Path, default=OUT_PATH)
    args = ap.parse_args()
    if args.smoke:
        args.sample_users = args.sample_users or 50_000
        args.factors = min(args.factors, 32)
        args.iters = min(args.iters, 8)
    args.min_user_positives = max(2, args.min_user_positives)

    import implicit  # noqa: F401  (fail fast: env dedicato)

    data_dir = DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    hf_token = os.environ.get("HF_TOKEN")  # dataset pubblico: opzionale

    if not args.skip_download:
        ratings = load_ratings(data_dir, hf_token)
        entries = fetch_aodb_jsonl(data_dir)
    else:
        ratings = np.load(data_dir / "ratings.npy", mmap_mode="r")
        entries = fetch_aodb_jsonl(data_dir)
    mal2al = mal_to_anilist_map(entries)
    log(f"mapping mal→anilist: {len(mal2al):,}")
    id2anilist = dataset_id_to_anilist(data_dir, mal2al)
    log(f"mapping datasetID→anilist: {len(id2anilist):,}")

    from scipy.sparse import csr_matrix  # noqa: F401  (verify avail prima del lavoro)

    matrix, items, users, sel = build_matrix(ratings, id2anilist, args)
    del ratings

    rng = np.random.default_rng(42)
    train, test = holdout_split(matrix, rng)
    log(f"train nnz: {train.nnz:,} · holdout utenti: {len(test)}")

    from implicit.als import AlternatingLeastSquares

    log(f"ALS factors={args.factors} iters={args.iters}")
    model = AlternatingLeastSquares(factors=args.factors, iterations=args.iters, regularization=0.05, num_threads=0)
    model.fit(train, show_progress=True)

    item_pop = np.asarray(train.sum(axis=0)).ravel()
    recall_cf, recall_pop = recall_at_k(model, train, test, item_pop)
    ratio = recall_cf / recall_pop if recall_pop > 0 else 0.0
    log(f"RECALL@{RECALL_K} cf={recall_cf:.4f} popularity={recall_pop:.4f} ratio={ratio:.2f}x (n={len(test)})")

    vectors = np.asarray(model.item_factors, dtype=np.float16)
    size_mb = (vectors.nbytes + items.nbytes) / 1e6
    log(f"artefatto: {len(items):,} titoli × {vectors.shape[1]} dim → {size_mb:.1f} MB")

    header = {
        "magic": "osusume-cf",
        "version": 1,
        "dim": int(vectors.shape[1]),
        "count": int(len(items)),
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": "turan-2025-07",
        "aodb": "2026-27",
        "minRating": args.min_rating,
        "smoke": bool(args.smoke),
        "recallAt20": round(recall_cf, 4),
        "recallPopularity": round(recall_pop, 4),
    }
    if not args.smoke:
        if ratio < 2.0:
            log(f"GATE FALLITO: ratio {ratio:.2f}x < 2x — artefatto NON scritto")
            return 1
        if size_mb > 12:
            log(f"GATE FALLITO: artefatto {size_mb:.1f} MB > 12 MB")
            return 1
        if len(items) < 15_000:
            log(f"GATE FALLITO: copertura {len(items):,} < 15.000 titoli")
            return 1
    header_bytes = (json.dumps(header, separators=(",", ":")) + "\n").encode("utf-8")
    with open(args.out, "wb") as f:
        f.write(len(header_bytes).to_bytes(4, "little"))
        f.write(header_bytes)
        f.write(items.astype(np.int32).tobytes())
        f.write(vectors.tobytes())
    log(f"scritto {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")
    print(json.dumps(header, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
