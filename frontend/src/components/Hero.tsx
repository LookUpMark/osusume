import type { Lang } from "../lib/i18n.ts";
import { tr } from "../lib/i18n.ts";
import { badgeKey, metaJoin, score110 } from "../lib/logic/display.ts";
import type { ScoredReco } from "../lib/types.ts";

/** Hero (pattern Verba): card surface con copertina a lato, eyebrow accent,
 *  titolo serif, CTA primary/secondary. Sostituisce il vecchio full-bleed blur. */
export function Hero(props: {
  reco: ScoredReco;
  lang: Lang;
  user: string;
  onOpen: (reco: ScoredReco) => void;
  onAll: () => void;
}) {
  const r = props.reco;
  const m = r.media;
  const lang = props.lang;
  return (
    <div className="hero" data-od-id="hero">
      {m.coverImage ? (
        <img className="hero-art" src={m.coverImage} alt="" aria-hidden="true" />
      ) : (
        <div className="hero-fallback cover-fallback" style={{ background: m.coverColor ?? "var(--surface-warm)" }} aria-hidden="true">
          {m.title[0] ?? "?"}
        </div>
      )}
      <div className="hero-body">
        <p className="eyebrow">{tr(lang, "heroTop", { u: props.user })}</p>
        <h1>
          <a href={m.siteUrl ?? "#"} target="_blank" rel="noreferrer">
            {m.title}
          </a>
        </h1>
        {(r.badges.length > 0 || r.groupSize > 1) && (
          <div className="chips">
            {r.badges.map((b) => (
              <span key={b} className={`chip-badge ${b === "HIDDEN_GEM" ? "gem" : b === "ENTRY_POINT" ? "entry" : ""}`}>
                {tr(lang, badgeKey(b))}
              </span>
            ))}
            {r.groupSize > 1 && <span className="chip-badge">{tr(lang, "moreInSeries", { n: r.groupSize - 1 })}</span>}
          </div>
        )}
        <p className="hero-meta">
          {metaJoin([m.seasonYear, m.format, m.studio, m.averageScore != null ? `${m.averageScore}/100 AniList` : null])}
        </p>
        {r.why && <p className="hero-why">{r.why}</p>}
        <div className="hero-cta">
          <button className="btn btn-primary" type="button" onClick={() => props.onOpen(r)}>
            {tr(lang, "heroOpen")}
          </button>
          <button className="btn btn-secondary" type="button" onClick={props.onAll}>
            {tr(lang, "allRecos")}
          </button>
        </div>
      </div>
      <span className="score-tag mono">{score110(r.final)}/110</span>
    </div>
  );
}
