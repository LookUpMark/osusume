import type { Lang } from "../lib/i18n.ts";
import { tr } from "../lib/i18n.ts";
import { badgeKey, metaJoin, score110 } from "../lib/logic/display.ts";
import type { ScoredReco } from "../lib/types.ts";

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
      {m.coverImage && (
        <>
          <img className="hero-bg" src={m.coverImage} alt="" aria-hidden="true" />
          <img className="hero-art" src={m.coverImage} alt="" aria-hidden="true" />
        </>
      )}
      <div className="hero-scrim" aria-hidden="true" />
      <span className="hero-score mono">{score110(r.final)}/110</span>
      <div className="hero-body">
        <p className="eyebrow">{tr(lang, "heroTop", { u: props.user })}</p>
        <h1>
          <a href={m.siteUrl ?? "#"} target="_blank" rel="noreferrer">
            {m.title}
          </a>
        </h1>
        <div className="chips">
          {r.badges.map((b) => (
            <span key={b} className={`chip-badge ${b === "HIDDEN_GEM" ? "gem" : b === "ENTRY_POINT" ? "entry" : ""}`}>
              {tr(lang, badgeKey(b))}
            </span>
          ))}
          {r.groupSize > 1 && <span className="chip-badge">{tr(lang, "moreInSeries", { n: r.groupSize - 1 })}</span>}
        </div>
        <p className="hero-meta">
          {metaJoin([m.seasonYear, m.format, m.studio, m.averageScore != null ? `${m.averageScore}/100 AniList` : null])}
        </p>
        <p className="hero-why">{r.why}</p>
        <div className="hero-cta">
          <button className="btn btn-primary" type="button" onClick={() => props.onOpen(r)}>
            {tr(lang, "heroOpen")}
          </button>
          <button className="btn btn-ghost" type="button" onClick={props.onAll}>
            {tr(lang, "allRecos")}
          </button>
        </div>
      </div>
    </div>
  );
}
