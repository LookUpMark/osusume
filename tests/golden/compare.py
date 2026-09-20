#!/usr/bin/env python3
"""Deep-diff tra golden master e output reale (P0 migrazione Python/FastAPI).

Usage:
    python3 tests/golden/compare.py <goldenDir> <actualDir> [--only name1,name2] [--max N]

Confronta i file `*.json` di goldenDir con gli omonimi di actualDir. Regole:
oggetti chiave-insensibili all'ordine, array ordine-SENSIBILI, numeri confrontati
esatti via repr (1 != 1.0), stringhe esatte, bool/None per tipo. I path elencati in
<goldenDir>/volatile.json (tratti macchina, es. body.hardware.chip) sono scrubbed a
null su ENTRAMBI i lati prima del diff. Stampa i primi N mismatch con path JSON-style
(es. body.recos[3].final). Exit 0 se identici, 1 altrimenti. Stdlib only.
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_MAX = 20


def type_name(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def diff(a, b, path, out):
    """Appende (path, atteso, reale) a out per ogni mismatch."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else k
            if k not in a:
                out.append((p, "<assente>", b[k]))
            elif k not in b:
                out.append((p, a[k], "<assente>"))
            else:
                diff(a[k], b[k], p, out)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((f"{path} (length)", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out)
        return
    # scalari (e ogni mismatch di struttura): numeri via repr → 1 != 1.0
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        if repr(a) != repr(b):
            out.append((path, a, b))
        return
    if type_name(a) != type_name(b) or a != b:
        out.append((path, a, b))


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def scrub(doc, paths):
    """Azzera i path volatili (tratti macchina) su un documento {status, body}."""
    for p in paths:
        keys = p.split(".")
        cur = doc
        for k in keys[:-1]:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                cur = None
                break
        if isinstance(cur, dict) and keys[-1] in cur:
            cur[keys[-1]] = None
    return doc


def show(v):
    """Rendering per il report: numeri come repr grezzo (1, 1.0), resto come JSON troncato."""
    if isinstance(v, str) and v == "<assente>":
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return repr(v)
    return json.dumps(v, ensure_ascii=False)[:300]


def main():
    ap = argparse.ArgumentParser(description="Confronta golden master vs output reale")
    ap.add_argument("golden")
    ap.add_argument("actual")
    ap.add_argument("--only", default="", help="nomi (senza .json) separati da virgola")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX, help=f"mismatch massimi stampati (default {DEFAULT_MAX})")
    args = ap.parse_args()

    golden, actual = Path(args.golden), Path(args.actual)
    if not golden.is_dir():
        print(f"golden dir non trovata: {golden}", file=sys.stderr)
        return 1
    if not actual.is_dir():
        print(f"actual dir non trovata: {actual}", file=sys.stderr)
        return 1

    volatile_file = golden / "volatile.json"
    volatile = load(volatile_file) if volatile_file.exists() else []
    if not isinstance(volatile, list):
        print(f"volatile.json non è una lista di path: {volatile_file}", file=sys.stderr)
        return 1

    only = [n.strip() for n in args.only.split(",") if n.strip()]
    # "volatile" è la config dello scrub, non una cattura
    all_names = sorted(p.stem for p in golden.glob("*.json") if p.stem != "volatile")
    names = all_names
    if only:
        names = [n for n in all_names if n in only]
        missing = [n for n in only if n not in names]
        if missing:
            print(f"golden senza file per: {', '.join(missing)}", file=sys.stderr)
            return 1

    mismatches = 0
    compared = 0
    for name in names:
        ga, aa = golden / f"{name}.json", actual / f"{name}.json"
        if not aa.exists():
            print(f"FAIL {name}: file mancante in actual ({aa})")
            mismatches += 1
            continue
        compared += 1
        try:
            da = load(ga)
        except json.JSONDecodeError as e:
            print(f"FAIL {name}: JSON non valido nel GOLDEN {ga} ({e})")
            mismatches += 1
            continue
        try:
            db = load(aa)
        except json.JSONDecodeError as e:
            print(f"FAIL {name}: JSON non valido nell'ACTUAL {aa} ({e})")
            mismatches += 1
            continue
        scrub(da, volatile)
        scrub(db, volatile)
        found = []
        diff(da, db, "", found)
        if not found:
            print(f"ok   {name}")
            continue
        mismatches += len(found)
        print(f"FAIL {name}: {len(found)} mismatch")
        for p, exp, got in found[: args.max]:
            print(f"  {p or '<root>'}\n    golden: {show(exp)}\n    actual: {show(got)}")
        if len(found) > args.max:
            print(f"  … altri {len(found) - args.max} mismatch omessi")

    # extra solo a scope pieno: con --only il confronto è limitato a ciò che è stato chiesto
    if not only:
        extra = sorted(p.name for p in actual.glob("*.json") if p.stem not in all_names)
        for n in extra:
            print(f"FAIL extra: {n} presente in actual ma non in golden")
            mismatches += 1

    print(f"\n{compared} file confrontati, {mismatches} mismatch totali")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
