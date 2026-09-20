import type { Lang } from "../lib/i18n.ts";
import { tr } from "../lib/i18n.ts";
import type { DimValue, TasteProfile } from "../lib/types.ts";

const KIND_KEY: Record<DimValue["dim"], string> = {
  tag: "dimTag",
  genre: "dimGenre",
  studio: "dimStudio",
  era: "dimEra",
};

function DimRow(props: { d: DimValue; lang: Lang; negative?: boolean }) {
  const d = props.d;
  const pct = Math.min(100, Math.max(0, Math.round(Math.abs(d.aff) * 100)));
  return (
    <div className="dim-row">
      <span className="dim-top">
        <span className="dim-name">{d.value}</span>
        <span className="dim-kind">{tr(props.lang, KIND_KEY[d.dim])}</span>
        <span className="dim-pct">{props.negative ? "−" : ""}{pct}%</span>
      </span>
      <span className="bar">
        <span className={props.negative ? "neg" : "taste"} style={{ width: `${pct}%` }} />
      </span>
      {d.examples.length > 0 && <span className="dim-ex">{d.examples.slice(0, 3).join(" · ")}</span>}
    </div>
  );
}

export function ProfileView(props: { profile: TasteProfile; lang: Lang }) {
  const p = props.profile;
  const lang = props.lang;
  return (
    <>
      <div className="stats five" data-od-id="profile-stats">
        <div className="stat"><div className="num">{p.meanScore}</div><div className="lbl">{tr(lang, "meanScore")}</div></div>
        <div className="stat"><div className="num">{p.counts.CURRENT}</div><div className="lbl">{tr(lang, "stCur")}</div></div>
        <div className="stat"><div className="num">{p.counts.COMPLETED}</div><div className="lbl">{tr(lang, "statDone")}</div></div>
        <div className="stat"><div className="num">{p.counts.PAUSED}</div><div className="lbl">{tr(lang, "stPaused")}</div></div>
        <div className="stat"><div className="num">{p.counts.DROPPED}</div><div className="lbl">{tr(lang, "dropped")}</div></div>
      </div>

      <div className="profile-grid" data-od-id="profile-dims">
        <div className="panel">
          <h3><span className="sign">+</span>{tr(lang, "loved")}</h3>
          <div className="dim">
            {p.loved.map((d) => <DimRow key={`${d.dim}:${d.value}`} d={d} lang={lang} />)}
          </div>
        </div>
        <div className="panel">
          <h3><span className="sign neg">−</span>{tr(lang, "disliked")}</h3>
          <div className="dim">
            {p.disliked.map((d) => <DimRow key={`${d.dim}:${d.value}`} d={d} lang={lang} negative />)}
          </div>
        </div>
      </div>
    </>
  );
}
