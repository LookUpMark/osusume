import type { Lang } from "../lib/i18n.ts";
import { tr } from "../lib/i18n.ts";
import { badgeKey, metaJoin, score110 } from "../lib/logic/display.ts";
import type { ScoredReco } from "../../../src/shared/types.ts";

export function MediaCard(props: {
  reco: ScoredReco;
  lang: Lang;
  eager?: boolean;
  onOpen: (reco: ScoredReco) => void;
}) {
  const r = props.reco;
  const m = r.media;
  const lang = props.lang;
  const aff = Math.min(100, Math.max(0, Math.round(r.breakdown.affinity * 100)));
  return (
    <button
      type="button"
      className="mcard"
      data-od-id={`reco-card-${m.id}`}
      onClick={() => props.onOpen(r)}
      aria-label={`${m.title}: ${tr(lang, "heroOpen")}`}
    >
      <span className="poster">
        <span className="prog" aria-hidden="true">
          <span style={{ width: `${aff}%` }} />
        </span>
        {m.coverImage ? (
          <img
            src={m.coverImage}
            alt={tr(lang, "coverOf", { t: m.title })}
            loading={props.eager ? "eager" : "lazy"}
          />
        ) : (
          <span className="cover-fallback" style={{ background: m.coverColor ?? "var(--surface-2)" }} aria-hidden="true">
            {m.title[0] ?? "?"}
          </span>
        )}
        <span className="score-tag mono">{score110(r.final)}/110</span>
        <span className="ovl">
          <span className="t">{m.title}</span>
          <span className="m">{metaJoin([m.seasonYear, m.format])}</span>
        </span>
      </span>
      <span className="sub">
        <span className="row1">
          <span className="meta">{m.studio ?? ""}</span>
          <span className="aff">{tr(lang, "kAffinity")} {aff}%</span>
        </span>
        <span className="chips">
          {r.badges.map((b) => (
            <span key={b} className={`chip-badge ${b === "HIDDEN_GEM" ? "gem" : b === "ENTRY_POINT" ? "entry" : ""}`}>
              {tr(lang, badgeKey(b))}
            </span>
          ))}
          {r.groupSize > 1 && <span className="chip-badge">{tr(lang, "moreInSeries", { n: r.groupSize - 1 })}</span>}
        </span>
      </span>
    </button>
  );
}
