import { useEffect, useRef, useState } from "react";
import type { Lang } from "../../shared/strings.ts";
import { tr } from "../../shared/strings.ts";
import type { ScoredReco } from "../../shared/types.ts";
import { fetchExplain } from "../api.ts";

const clean = (html: string | null): string | null => {
  if (!html) return null;
  const d = document.createElement("div");
  d.innerHTML = html;
  const text = d.textContent?.replace(/\s+/g, " ").trim();
  return text || null;
};

function BrkRow(props: { k: string; cls: string; v: number; suffix?: string }) {
  const pct = Math.min(100, Math.max(0, Math.round(props.v * 100)));
  return (
    <div className="brk-row">
      <span className="k">{props.k}</span>
      <span className="bar">
        <span className={props.cls} style={{ width: `${pct}%` }} />
      </span>
      <span className="v">{pct}{props.suffix ?? "%"}</span>
    </div>
  );
}

export function DetailDialog(props: {
  reco: ScoredReco;
  lang: Lang;
  username: string;
  whySource: "llm" | "local";
  onWhy: (id: number, text: string, source: "llm" | "cache") => void;
  onClose: () => void;
  onSimilar: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const r = props.reco;
  const m = r.media;
  const lang = props.lang;
  const description = clean(m.description);
  const [writing, setWriting] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  // seconds next to the dots while the local model writes (see ChatPanel)
  useEffect(() => {
    if (!writing) return;
    setElapsed(0);
    const iv = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(iv);
  }, [writing]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") props.onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // LLM explanation ON-DEMAND: only this title, only when its detail is open.
  // Cached server-side (7d) — reopening is instant.
  useEffect(() => {
    if (props.whySource === "llm") return;
    let alive = true;
    setWriting(true);
    fetchExplain(props.username, [m.id], lang)
      .then((ex) => {
        const e = ex.explanations.find((x) => x.id === m.id);
        if (alive && e && e.text && e.source !== "fallback") props.onWhy(m.id, e.text, e.source);
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) setWriting(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m.id, props.username, lang]);

  return (
    <div
      className="dlg-scrim"
      data-od-id="detail-dialog"
      onClick={(e) => {
        if (e.target === e.currentTarget) props.onClose();
      }}
    >
      <div className="dlg" role="dialog" aria-modal="true" aria-labelledby="dlg-title">
        <div>
          {m.coverImage ? (
            <img src={m.coverImage} alt={tr(lang, "coverOf", { t: m.title })} />
          ) : (
            <div className="cover-fallback" style={{ background: m.coverColor ?? "var(--surface-2)" }} aria-hidden="true">
              {m.title[0] ?? "?"}
            </div>
          )}
        </div>
        <div>
          <div className="dlg-head">
            <div>
              <h2 id="dlg-title">{m.title}</h2>
              <p className="meta">
                {[
                  m.seasonYear,
                  m.format,
                  m.studio,
                  m.averageScore != null ? `${m.averageScore}/100 AniList` : null,
                  `${Math.round(m.popularity / 1000)}k`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            <button ref={closeRef} className="dlg-close" type="button" onClick={props.onClose} aria-label={tr(lang, "closeDialog")}>
              ✕
            </button>
          </div>
          <div className="chips">
            {r.badges.map((b) => (
              <span key={b} className={`chip-badge ${b === "HIDDEN_GEM" ? "gem" : b === "ENTRY_POINT" ? "entry" : ""}`}>
                {tr(lang, `badge${b.split("_").map((w) => w[0] + w.slice(1).toLowerCase()).join("")}`)}
              </span>
            ))}
            {r.groupSize > 1 && <span className="chip-badge">{tr(lang, "moreInSeries", { n: r.groupSize - 1 })}</span>}
            {m.genres.slice(0, 3).map((g) => (
              <span key={g} className="chip-badge">{g}</span>
            ))}
          </div>
          <div className="score-line">
            <span className="n">{Math.round(r.final * 100)}</span>
            <span className="m">/ 110</span>
          </div>
          <div className="brk">
            <BrkRow k={tr(lang, "kAffinity")} cls="taste" v={r.breakdown.affinity} />
            <BrkRow k={tr(lang, "kQuality")} cls="quality" v={r.breakdown.quality} />
            <BrkRow k={tr(lang, "kCommunity")} cls="community" v={r.breakdown.community / 0.1} />
            {(r.breakdown.mood ?? 0) > 0.0001 && (
              <BrkRow k={tr(lang, "kMood")} cls="taste" v={r.breakdown.mood!} />
            )}
          </div>
          {description && <p className="why">{description}</p>}
          {r.why && <p className="why-note">{r.why.replace(/\*/g, "")}</p>}
          <p className="src">
            <span className={`llm-dot${props.whySource === "llm" ? " on" : ""}`} aria-hidden="true" />
            {tr(lang, props.whySource === "llm" ? "whySrcLlm" : "whySrcLocal")}
          </p>
          {writing && props.whySource !== "llm" && (
            <p className="src llm-writing" role="status">
              <span className="dots" aria-hidden="true">
                <span /><span /><span />
              </span>
              {tr(lang, "llmWriting")} · {tr(lang, "secsShort", { s: elapsed })}
            </p>
          )}
          <div className="dlg-foot">
            {m.siteUrl && (
              <a className="btn btn-primary" href={m.siteUrl} target="_blank" rel="noreferrer">
                {tr(lang, "openAnilist")}
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M7 17 17 7M9 7h8v8" />
                </svg>
              </a>
            )}
            <button className="btn-line" type="button" onClick={props.onSimilar}>
              {tr(lang, "similar")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
