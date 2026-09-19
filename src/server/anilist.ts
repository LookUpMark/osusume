import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { ListEntry, MediaLite, MediaRelationLite, ListStatus } from "../shared/types.ts";
import {
  ANILIST_ENDPOINT,
  fixturesDir,
  localModeOn,
  CACHE_DIR,
  CACHE_TTL_LIST_MS,
  CACHE_TTL_MEDIA_MS,
  RATE_PER_MIN,
} from "./config.ts";

export class AniListError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const MEDIA_FIELDS = `
  id
  title { romaji }
  format
  seasonYear
  genres
  tags { name rank isGeneralSpoiler isMediaSpoiler }
  averageScore
  popularity
  coverImage { large color }
  studios(isMain: true) { nodes { name } }
  siteUrl
  description(asHtml: false)
`;

const LIST_LIST_QUERY = `
query ($userName: String, $chunk: Int) {
  MediaListCollection(userName: $userName, type: ANIME, chunk: $chunk, perChunk: 500) {
    hasNextChunk
    lists {
      isCustomList
      entries {
        status
        score(format: POINT_100)
        repeat
        updatedAt
        media { ${MEDIA_FIELDS} }
      }
    }
  }
}`;

const MEDIA_PAGE_QUERY = `
query ($page: Int, $genre_in: [String], $tag_in: [String], $sort: [MediaSort], $minimumTagRank: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(type: ANIME, isAdult: false, genre_in: $genre_in, tag_in: $tag_in, sort: $sort, minimumTagRank: $minimumTagRank) {
      ${MEDIA_FIELDS}
      relations { edges { relationType node { id } } }
    }
  }
}`;

const MEDIA_BY_IDS_QUERY = `
query ($id_in: [Int]) {
  Page(perPage: 50) {
    media(id_in: $id_in, type: ANIME) { ${MEDIA_FIELDS} relations { edges { relationType node { id } } } }
  }
}`;

const RECOMMENDATIONS_QUERY = `
query ($id: Int) {
  Media(id: $id) {
    recommendations(sort: RATING_DESC, perPage: 10) {
      nodes { rating mediaRecommendation { id } }
    }
  }
}`;

// --- rate limiting -------------------------------------------------------------

let tokens = 3;
let lastRefill = Date.now();
const refillPerSec = Math.max(0.1, RATE_PER_MIN / 60);

async function takeToken(): Promise<void> {
  for (;;) {
    const now = Date.now();
    tokens = Math.min(3, tokens + ((now - lastRefill) / 1000) * refillPerSec);
    lastRefill = now;
    if (tokens >= 1) {
      tokens -= 1;
      return;
    }
    await sleep(1000 / refillPerSec);
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// --- disk cache ----------------------------------------------------------------

// concurrent identical lookups share one in-flight request
const inflight = new Map<string, Promise<unknown>>();

async function cacheWrap<T>(key: string, ttlMs: number, fn: () => Promise<T>): Promise<T> {
  const file = join(CACHE_DIR, `${createHash("sha256").update(key).digest("hex")}.json`);
  try {
    const hit = JSON.parse(await readFile(file, "utf8"));
    if (Date.now() < hit.exp) return hit.data as T;
  } catch {
    /* miss */
  }
  const p = inflight.get(file) ?? fn().finally(() => inflight.delete(file));
  inflight.set(file, p);
  const data = (await p) as T;
  await mkdir(CACHE_DIR, { recursive: true });
  await writeFile(file, JSON.stringify({ exp: Date.now() + ttlMs, data }));
  return data;
}

// --- network -------------------------------------------------------------------

async function gql<T>(query: string, variables: object, ttlMs: number): Promise<T> {
  return cacheWrap(createHash("sha256").update(query).update(JSON.stringify(variables)).digest("hex"), ttlMs, async () => {
    for (let attempt = 0; ; attempt++) {
      await takeToken();
      let res: Response;
      try {
        res = await fetch(ANILIST_ENDPOINT, {
          method: "POST",
          headers: { "content-type": "application/json", accept: "application/json" },
          body: JSON.stringify({ query, variables }),
          signal: AbortSignal.timeout(15_000),
        });
      } catch (e) {
        if (attempt < 3) {
          await sleep(1000 * 2 ** attempt);
          continue;
        }
        throw new AniListError(`AniList unreachable: ${(e as Error).message}`, 502);
      }
      if (res.status === 429) {
        if (attempt >= 10) throw new AniListError("AniList rate-limited for too long", 429);
        const raw = Number(res.headers.get("retry-after"));
        // bounded: never hammer AniList (ToS) — cap 10 rounds, sanitized delay
        await sleep((Number.isFinite(raw) && raw > 0 ? Math.min(raw, 60) : 5) * 1000);
        continue;
      }
      if (res.status >= 500 && attempt < 3) {
        await sleep(1000 * 2 ** attempt);
        continue;
      }
      let json: { data?: T; errors?: { message: string; status?: number }[] };
      try {
        json = (await res.json()) as typeof json;
      } catch {
        if (attempt < 3) {
          await sleep(1000 * 2 ** attempt);
          continue; // the for-loop increments attempt — an extra ++ here shorted this path by one retry
        }
        throw new AniListError(`AniList HTTP ${res.status} (non-JSON body)`, res.status);
      }
      if (json.errors?.length) {
        const e = json.errors[0];
        throw new AniListError(e.message, e.status ?? res.status);
      }
      if (!json.data) throw new AniListError(`AniList HTTP ${res.status}`, res.status);
      return json.data;
    }
  });
}

// --- mapping -------------------------------------------------------------------

type RawMedia = {
  id: number;
  title: { romaji?: string; english?: string };
  format: string | null;
  seasonYear: number | null;
  genres: string[];
  tags: { name: string; rank: number; isGeneralSpoiler: boolean; isMediaSpoiler: boolean }[];
  averageScore: number | null;
  popularity: number;
  coverImage: { large: string | null; color: string | null };
  studios: { nodes: { name: string }[] };
  siteUrl: string | null;
  description: string | null;
  relations?: { edges: { relationType: string; node: { id: number } }[] };
};

export function mapMedia(m: RawMedia): MediaLite {
  return {
    id: m.id,
    title: m.title?.romaji ?? m.title?.english ?? `(id ${m.id})`,
    format: m.format,
    seasonYear: m.seasonYear,
    genres: m.genres ?? [],
    tags: (m.tags ?? [])
      .filter((t) => !t.isGeneralSpoiler && !t.isMediaSpoiler)
      .map((t) => ({ name: t.name, rank: t.rank, isSpoiler: false })),
    studio: m.studios?.nodes?.[0]?.name ?? null,
    averageScore: m.averageScore,
    popularity: m.popularity ?? 0,
    coverImage: m.coverImage?.large ?? null,
    coverColor: m.coverImage?.color ?? null,
    siteUrl: m.siteUrl,
    // ponytail: truncate description to 500 chars — enough for LLM context
    description: m.description ? m.description.slice(0, 500) : null,
    relations: (m.relations?.edges ?? [])
      .filter((e) =>
        ["PREQUEL", "SEQUEL", "SIDE_STORY", "SPIN_OFF", "PARENT"].includes(e.relationType),
      )
      .map((e) => ({ id: e.node.id, relationType: e.relationType })),
    // ponytail: relations perPage defaults to 25 — giant franchises (Fate) may truncate
  };
}

// --- fixture mode --------------------------------------------------------------

async function readFixture<T>(name: string): Promise<T> {
  return JSON.parse(
    await readFile(join(process.cwd(), fixturesDir(), name), "utf8"),
  ) as T;
}

// --- public API ----------------------------------------------------------------

export interface UserList {
  entries: ListEntry[];
  mediaById: Map<number, MediaLite>;
}

export async function fetchUserList(userName: string): Promise<UserList> {
  if (localModeOn()) {
    const f = await readFixture<{ entries: ListEntry[]; media: MediaLite[] }>("userlist.json");
    return { entries: f.entries, mediaById: new Map(f.media.map((m) => [m.id, m])) };
  }
  const entries = new Map<number, ListEntry & { custom: boolean }>();
  const media = new Map<number, MediaLite>();
  // ponytail: API ceiling is 11k entries (22 chunks of 500) — beyond that we miss tail entries
  for (let chunk = 0; chunk < 22; chunk++) {
    const data = await gql<{
      MediaListCollection: {
        hasNextChunk: boolean;
        lists: {
          isCustomList: boolean;
          entries: { status: ListStatus; score: number; repeat: number; updatedAt?: number; media: RawMedia }[];
        }[];
      };
    }>(LIST_LIST_QUERY, { userName, chunk }, CACHE_TTL_LIST_MS);
    for (const list of data.MediaListCollection.lists) {
      for (const e of list.entries) {
        const prev = entries.get(e.media.id);
        // status lists win over custom-list copies of the same entry
        if (prev && prev.custom && !list.isCustomList) entries.delete(e.media.id);
        if (!prev || (prev.custom && !list.isCustomList)) {
          entries.set(e.media.id, {
            mediaId: e.media.id,
            status: e.status,
            score: e.score ?? 0,
            repeat: e.repeat ?? 0,
            updatedAt: e.updatedAt ?? 0,
            title: e.media.title?.romaji ?? e.media.title?.english ?? `(${e.media.id})`,
            custom: list.isCustomList,
          });
          media.set(e.media.id, mapMedia(e.media));
        }
      }
    }
    if (!data.MediaListCollection.hasNextChunk) break;
  }
  return {
    entries: [...entries.values()].map(({ custom: _c, ...rest }) => rest),
    mediaById: media,
  };
}

export async function fetchMediaPage(p: {
  genres?: string[];
  tags?: string[];
  minimumTagRank?: number;
  sort: string[];
  page: number;
}): Promise<{ media: MediaLite[]; hasNextPage: boolean }> {
  if (localModeOn()) {
    // fixture mode ignores filters: the recorded pool is served whole
    const all = await readFixture<MediaLite[]>("candidates.json");
    return { media: all, hasNextPage: false };
  }
  const data = await gql<{
    Page: { pageInfo: { hasNextPage: boolean }; media: RawMedia[] };
  }>(
    MEDIA_PAGE_QUERY,
    {
      page: p.page,
      genre_in: p.genres ?? null,
      tag_in: p.tags ?? null,
      sort: p.sort,
      minimumTagRank: p.minimumTagRank ?? null,
    },
    CACHE_TTL_MEDIA_MS,
  );
  return { media: data.Page.media.map(mapMedia), hasNextPage: data.Page.pageInfo.hasNextPage };
}

export async function fetchMediaByIds(ids: number[]): Promise<MediaLite[]> {
  if (ids.length === 0) return [];
  if (localModeOn()) {
    const all = await readFixture<MediaLite[]>("candidates.json");
    return all.filter((m) => ids.includes(m.id));
  }
  // GraphQL Page depth cap is 5000, perPage max 50 → chunk the input
  const out: MediaLite[] = [];
  for (let i = 0; i < ids.length; i += 50) {
    const data = await gql<{ Page: { media: RawMedia[] } }>(
      MEDIA_BY_IDS_QUERY,
      { id_in: ids.slice(i, i + 50) },
      CACHE_TTL_MEDIA_MS,
    );
    out.push(...data.Page.media.map(mapMedia));
  }
  return out;
}

export async function fetchRecommendations(
  mediaId: number,
): Promise<{ targetId: number; rating: number }[]> {
  if (localModeOn()) {
    const map = await readFixture<Record<string, { targetId: number; rating: number }[]>>(
      "recommendations.json",
    );
    return map[String(mediaId)] ?? [];
  }
  const data = await gql<{
    Media: { recommendations: { nodes: { rating: number; mediaRecommendation: { id: number } }[] } };
  }>(RECOMMENDATIONS_QUERY, { id: mediaId }, CACHE_TTL_MEDIA_MS);
  return data.Media.recommendations.nodes.map((n) => ({
    targetId: n.mediaRecommendation.id,
    rating: n.rating,
  }));
}
