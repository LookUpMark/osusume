import { useEffect, useRef } from "react";
import type { Lang } from "../lib/i18n.ts";
import { tr } from "../lib/i18n.ts";
import { score110 } from "../lib/logic/display.ts";
import type { ScoredReco } from "../lib/types.ts";

/** Utility header: ricerca titoli (qualunque titolo, valutato sul profilo —
 *  il dropdown apre il dettaglio e entra nel contesto chat), toggle tema e
 *  chip utente (click = cambia utente). */

const SunIcon = () => (
  <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);
const MoonIcon = () => (
  <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M20 12.5A8 8 0 1111.5 4a6.5 6.5 0 008.5 8.5z" />
  </svg>
);

export function Topbar(props: {
  lang: Lang;
  user: string;
  busy: boolean;
  query: string;
  results: ScoredReco[] | null;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onQuery: (q: string) => void;
  onSearch: () => void;
  onClose: () => void;
  onOpen: (reco: ScoredReco) => void;
  onSwitchUser: () => void;
}) {
  const { lang } = props;
  const boxRef = useRef<HTMLDivElement>(null);

  // close the dropdown on outside click / Escape
  useEffect(() => {
    if (!props.results) return;
    const onDown = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) props.onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") props.onClose();
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.results]);

  const canSearch = props.user.length > 0 && props.query.trim().length >= 2;

  return (
    <header className="utility" data-od-id="topbar">
      <div className="search" ref={boxRef}>
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (canSearch && !props.busy) props.onSearch();
          }}
        >
          <input
            type="text"
            inputMode="text"
            autoComplete="off"
            spellCheck={false}
            maxLength={80}
            placeholder={tr(lang, "searchAnime")}
            aria-label={tr(lang, "lookupGo")}
            value={props.query}
            disabled={!props.user}
            onChange={(e) => props.onQuery(e.target.value)}
          />
          <button className="go" type="submit" aria-label={tr(lang, "lookupGo")} title={tr(lang, "lookupGo")} disabled={!canSearch || props.busy}>
            <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="6.5" />
              <path d="m16.2 16.2 4.3 4.3" />
            </svg>
          </button>
        </form>
        {props.results !== null && (
          <div className="top-results" role="listbox" aria-label={tr(lang, "searchAnime")}>
            {props.results.length === 0 ? (
              <p className="lookup-none">{tr(lang, "searchAnimeNone")}</p>
            ) : (
              props.results.map((r) => (
                <button
                  key={r.media.id}
                  type="button"
                  className="chat-card"
                  role="option"
                  aria-selected={false}
                  onClick={() => props.onOpen(r)}
                >
                  {r.media.coverImage && <img src={r.media.coverImage} alt="" />}
                  <span>
                    {r.media.title}
                    <em>
                      {score110(r.final)}/110 · {r.media.seasonYear ?? "?"}
                    </em>
                  </span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
      <div className="utility-side">
        <button
          type="button"
          className="btn btn-secondary btn-sm theme-toggle"
          onClick={props.onToggleTheme}
          aria-label={props.theme === "dark" ? tr(lang, "themeLight") : tr(lang, "themeDark")}
        >
          {props.theme === "dark" ? <SunIcon /> : <MoonIcon />}
          <span>{props.theme === "dark" ? tr(lang, "themeLight") : tr(lang, "themeDark")}</span>
        </button>
        {props.user && (
          <button type="button" className="user-link" onClick={props.onSwitchUser} title={tr(lang, "loginSwitch")} data-od-id="user-link">
            <span className="at">@</span>
            {props.user}
          </button>
        )}
      </div>
    </header>
  );
}
