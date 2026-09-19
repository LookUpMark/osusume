export type Lang = "en" | "it";

export type ListStatus =
  | "CURRENT"
  | "PLANNING"
  | "COMPLETED"
  | "DROPPED"
  | "PAUSED"
  | "REPEATING";

export interface ListEntry {
  mediaId: number;
  status: ListStatus;
  /** Normalized 0-100 (0 = unscored). */
  score: number;
  repeat: number;
  title: string;
}

export interface MediaTagLite {
  name: string;
  rank: number;
  isSpoiler: boolean;
}

export interface MediaRelationLite {
  id: number;
  relationType: string;
}

export interface MediaLite {
  id: number;
  title: string;
  format: string | null;
  seasonYear: number | null;
  genres: string[];
  tags: MediaTagLite[];
  studio: string | null;
  averageScore: number | null;
  popularity: number;
  coverImage: string | null;
  coverColor: string | null;
  siteUrl: string | null;
  description: string | null;
  relations: MediaRelationLite[];
}

export type Dim = "tag" | "genre" | "studio" | "era";

export interface DimValue {
  dim: Dim;
  value: string;
  /** -1..1, shrunk by support. */
  aff: number;
  support: number;
  /** Titles the user rated highly that contain this value. */
  examples: string[];
}

export interface TasteProfile {
  userName: string;
  meanScore: number;
  scoredCount: number;
  confidence: "ok" | "low";
  counts: Record<ListStatus, number>;
  loved: DimValue[];
  disliked: DimValue[];
  /** Stable fingerprint of the list (ids+scores+statuses). */
  hash: string;
}

export type Badge = "NEXT_STEP" | "ENTRY_POINT" | "HIDDEN_GEM" | "SPIN_OFF";

export interface ScoredReco {
  media: MediaLite;
  /** 0..1.1, display x100. */
  final: number;
  breakdown: { affinity: number; quality: number; community: number };
  badges: Badge[];
  rootId: number | null;
  groupSize: number;
  why: string;
  /** Plot-text links to positively-rated watched titles (scoring v2, set in recommend). */
  links?: { title: string; shared: string[] }[];
}

export interface WhyNot {
  media: MediaLite;
  reason: string;
}

export interface RecoResult {
  profile: TasteProfile;
  recos: ScoredReco[];
  avoided: WhyNot[];
}

export interface Explanation {
  text: string;
  source: "llm" | "cache" | "fallback";
}

export interface SetupHardware {
  os: "mac" | "win" | "linux";
  chip: string;
  ramGb: number;
  appleSilicon: boolean;
}

export interface SetupStatus {
  setupDone: boolean;
  /** true anche dopo un aggiornamento (setupVersion mismatch) — riapre il wizard */
  needsSetup: boolean;
  customEnv: boolean;
  hardware: SetupHardware;
  suggested: {
    model: string;
    sizeGb: number;
    /** MLX pack for the oMLX backend */
    mlx: { model: string; sizeGb: number } | null;
    /** MLX variant loadable via lms/LM Studio (null when none exists, e.g. 27B Bonsai-2) */
    mlxLms: { model: string; sizeGb: number } | null;
  };
  lms: { installed: boolean; path: string | null; serverUp: boolean };
  omlx: { installed: boolean; serverUp: boolean; models: string[]; downloadable: { model: string; sizeGb: number }[] };
  downloadedModels: string[];
  job: {
    state: "idle" | "installing-cli" | "downloading" | "done" | "error";
    model: string | null;
    logTail: string;
    error?: string;
    bytesDone?: number;
    totalBytes?: number;
  };
  llm: { state: "up" | "starting" | "off" };
}
