import type { ReactElement } from "react";
import type { Lang } from "../../shared/strings.ts";
import { tr } from "../../shared/strings.ts";
import type { AppUpdate, LocalMode } from "../api.ts";
import { VIEW_LABEL, type View } from "../views.ts";

const ICONS: Record<View, ReactElement> = {
  home: <path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1z" />,
  recos: <path d="M12 3.5 14.7 9l6 .9-4.3 4.2 1 6-5.4-2.9L6.6 20l1-6L3.3 9.9 9.3 9z" />,
  gems: (
    <>
      <path d="M7 4h10l4 5-9 11L3 9z" />
      <path d="M3 9h18M9.5 9 12 20 14.5 9M7 4l2.5 5M17 4l-2.5 5" />
    </>
  ),
  chat: (
    <>
      <path d="M21 12a8.5 8.5 0 0 1-8.5 8.5c-1.3 0-2.6-.3-3.7-.8L3.5 21l1.3-4.6A8.5 8.5 0 1 1 21 12z" />
      <path d="M8.5 10.5h7M8.5 14h4.5" />
    </>
  ),
  profile: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 20c1.4-3.4 4.2-5 7.5-5s6.1 1.6 7.5 5" />
    </>
  ),
  avoid: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M6 6l12 12" />
    </>
  ),
  settings: (
    <>
      {/* gear (lucide "settings", ISC) */}
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
};

export function Rail(props: {
  view: View;
  lang: Lang;
  llmOn: boolean | null;
  local: LocalMode | null;
  onToggleLocal: () => void;
  update: AppUpdate | null;
  updateChecking?: boolean;
  onCheckUpdates: () => void;
  onNav: (v: View) => void;
  onLang: () => void;
}) {
  const { lang } = props;
  const items: View[] = ["home", "recos", "gems", "chat", "profile", "avoid", "settings"];
  return (
    <aside className="sidebar" data-od-id="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            {/* torii gate — the Osusume mark */}
            <path d="M4.4 8Q12 5.4 19.6 8" />
            <path d="M12 6.6V9.6" />
            <path d="M6.3 9.6h11.4" />
            <path d="M7.7 9.6V19M16.3 9.6V19" />
            <path d="M5.9 14.2h12.2" />
          </svg>
        </span>
      </div>
      <nav className="nav" aria-label={tr(lang, "appName")}>
        {items.map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => props.onNav(v)}
            aria-current={props.view === v}
            title={tr(lang, VIEW_LABEL[v])}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              {ICONS[v]}
            </svg>
            <span className="txt">{tr(lang, VIEW_LABEL[v])}</span>
          </button>
        ))}
      </nav>
      <div className="side-foot">
        <span className="llm-chip" data-od-id="llm-chip" title={props.llmOn ? tr(lang, "llmOn") : tr(lang, "llmOff")}>
          <span className={`llm-dot${props.llmOn ? " on" : ""}`} aria-hidden="true" />
        </span>
        {props.local?.available && (
          <button
            type="button"
            className="llm-chip"
            role="switch"
            aria-checked={props.local.auto}
            data-od-id="local-toggle"
            data-tip={`${tr(lang, "localAuto")} — ${props.local.on ? tr(lang, "localOn") : tr(lang, "localData")}`}
            onClick={props.onToggleLocal}
          >
            <span className={`llm-dot auto${props.local.on ? " on" : ""}`} aria-hidden="true" />
          </button>
        )}
        {props.update && (
          <>
            {props.update.available ? (
              <button
                type="button"
                className="llm-chip upd-chip"
                data-od-id="update-chip"
                data-tip={tr(lang, "updateAvailable", { v: props.update.latest ?? "" })}
                onClick={() => {
                  const { url } = props.update!;
                  if (url) window.open(url, "_blank", "noopener");
                }}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                  <path d="M12 4v11m0 0 4-4m-4 4-4-4M4.5 20h15" />
                </svg>
              </button>
            ) : (
              <button
                type="button"
                className="llm-chip"
                data-od-id="update-check"
                data-tip={props.updateChecking ? tr(lang, "checking") : tr(lang, "checkUpdates")}
                onClick={props.onCheckUpdates}
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  aria-hidden="true"
                  className={props.updateChecking ? "spin" : undefined}
                >
                  <path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v4h-4" />
                </svg>
              </button>
            )}
          </>
        )}
        <button type="button" className="lang-btn" onClick={props.onLang} aria-label="IT / EN" title="IT / EN">
          IT
        </button>
      </div>
    </aside>
  );
}
