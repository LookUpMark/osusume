import { useEffect, useRef } from "react";
import type { Lang } from "../lib/i18n.ts";
import { tr } from "../lib/i18n.ts";
import { score110 } from "../lib/logic/display.ts";
import type { ScoredReco } from "../lib/types.ts";
import { VIEW_LABEL, type View } from "../views/index.ts";

/** Topbar: page title, ANIME search (any title, scored against the taste
 *  profile — the dropdown opens the detail and joins the chat context), and
 *  the signed-in user chip (click = switch user). */
export function Topbar(props: {
  view: View;
  lang: Lang;
  user: string;
  busy: boolean;
  query: string;
  results: ScoredReco[] | null;
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
    <header className="topbar" data-od-id="topbar">
      <p className="page-title" id="page-title" aria-live="polite">
        {tr(lang, VIEW_LABEL[props.view])}
      </p>
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
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
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
      {props.user && (
        <button type="button" className="user-link" onClick={props.onSwitchUser} title={tr(lang, "loginSwitch")} data-od-id="user-link">
          <span className="at">@</span>
          {props.user}
        </button>
      )}
    </header>
  );
}
