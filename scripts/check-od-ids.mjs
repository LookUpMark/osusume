#!/usr/bin/env node
/**
 * Verifica che TUTTI i marker `data-od-id` canonici (frontend/od-ids.txt) siano
 * presenti nel bundle costruito in dist/ — sono i punti di aggancio OpenDesign
 * e non devono mai perdersi in una rigenerazione del frontend.
 *
 * Uso: pnpm build && node scripts/check-od-ids.mjs
 * Formato od-ids.txt: un marker per riga; il suffisso `{id}` = prefisso dinamico
 * (es. `reco-card-{id}` matcha `reco-card-${...}` nel markup generato).
 * Exit 0 se tutto presente, 1 altrimenti.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const idsFile = join(root, "frontend", "od-ids.txt");
const distDir = join(root, "dist");

const ids = readFileSync(idsFile, "utf8")
  .split("\n")
  .map((l) => l.trim())
  .filter((l) => l && !l.startsWith("#"));
if (ids.length === 0) {
  console.error(`check-od-ids: ${idsFile} vuoto`);
  process.exit(1);
}

/** Concatena i JS (e l'HTML) di dist: i marker literal finiscono lì così come sono. */
const collect = (dir) => {
  const out = [];
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) out.push(...collect(p));
    else if (/\.(js|html)$/.test(e)) out.push(readFileSync(p, "utf8"));
  }
  return out;
};

let bundle;
try {
  bundle = collect(distDir).join("\n");
} catch {
  console.error("check-od-ids: dist/ mancante o illeggibile — lancia `pnpm build` prima.");
  process.exit(1);
}

const missing = [];
for (const id of ids) {
  const dynamic = id.includes("{id}");
  const prefix = id.replace("{id}", "");
  // literal: data-od-id":"name" (esbuild) — con o senza template literal attorno
  const needle = dynamic
    ? `data-od-id":\`${prefix}` // data-od-id":`reco-card-${...}
    : `data-od-id":"${prefix}"`;
  if (!bundle.includes(needle)) missing.push(id);
}

if (missing.length > 0) {
  console.error(`check-od-ids: ${missing.length}/${ids.length} marker ASSENTI da dist/:\n  ${missing.join("\n  ")}`);
  process.exit(1);
}
console.log(`check-od-ids: ${ids.length}/${ids.length} marker data-od-id presenti in dist/`);
