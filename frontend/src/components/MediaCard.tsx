import type { Lang } from "../lib/i18n.ts";
import { tr } from "../lib/i18n.ts";
import { badgeKey, metaJoin, score110 } from "../lib/logic/display.ts";
import type { ScoredReco } from "../lib/types.ts";

/** Card media (pattern Verba): poster sopra, corpo testuale su surface —
 *  titolo, meta mono, barra affinità pill, riga studio/affinità, badge. */
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
        {m.coverImage ? (
          <img
            src={m.coverImage}
            alt={tr(lang, "coverOf", { t: m.title })}
            loading={props.eager ? "eager" : "lazy"}
          />
        ) : (
          <span className="cover-fallback" style={{ background: m.coverColor ?? "var(--surface-warm)" }} aria-hidden="true">
            {m.title[0] ?? "?"}
          </span>
        )}
        <span className="score-tag mono">{score110(r.final)}/110</span>
      </span>
      <span className="mbody">
        <span className="t">{m.title}</span>
        <span className="m">{metaJoin([m.seasonYear, m.format])}</span>
        <span className="aff-bar" aria-hidden="true">
          <span style={{ width: `${aff}%` }} />
        </span>
        <span className="row1">
          <span className="meta">{m.studio ?? ""}</span>
          <span className="aff">{tr(lang, "kAffinity")} {aff}%</span>
        </span>
        {(r.badges.length > 0 || r.groupSize > 1) && (
          <span className="chips">
            {r.badges.map((b) => (
              <span key={b} className={`chip-badge ${b === "HIDDEN_GEM" ? "gem" : b === "ENTRY_POINT" ? "entry" : ""}`}>
                {tr(lang, badgeKey(b))}
              </span>
            ))}
            {r.groupSize > 1 && <span className="chip-badge">{tr(lang, "moreInSeries", { n: r.groupSize - 1 })}</span>}
          </span>
        )}
      </span>
    </button>
  );
}
