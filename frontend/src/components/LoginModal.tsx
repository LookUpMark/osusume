import { useEffect, useRef, useState } from "react";
import { tr, type Lang } from "../lib/i18n.ts";

const VALID = /^[A-Za-z0-9_-]{1,32}$/;

/** Fake single-user login: pick the AniList username once, everything stays local.
 *  When AniList OAuth is configured, a connect button opens the system browser —
 *  without credentials the modal is byte-for-byte the username-only one. */
export function LoginModal(props: {
  lang: Lang;
  busy: boolean;
  error: string | null;
  current?: string;
  oauthConfigured?: boolean;
  oauthPending?: boolean;
  onOauth?: () => void;
  onLogin: (username: string) => void;
}) {
  const { lang } = props;
  const [value, setValue] = useState("");
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setValue("");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const invalid = value.length > 0 && !VALID.test(value);
  const submit = () => {
    const u = value.trim();
    if (VALID.test(u) && !props.busy) props.onLogin(u);
  };

  return (
    <div className="dlg-scrim login-scrim" data-od-id="login-modal">
      <div className="login" role="dialog" aria-modal="true" aria-labelledby="login-title">
        <div className="wizard-brand" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="30" height="30" fill="none" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            {/* torii gate — line-art brand, kasagi = unico dettaglio sage */}
            <path className="mark-accent" d="M4.4 8Q12 5.4 19.6 8" />
            <path d="M12 6.6V9.6" />
            <path d="M6.3 9.6h11.4" />
            <path d="M7.7 9.6V19M16.3 9.6V19" />
            <path d="M5.9 14.2h12.2" />
          </svg>
        </div>
        <h1 id="login-title">{tr(lang, "loginTitle")}</h1>
        <p className="hint">{tr(lang, "loginHint")}</p>
        <form
          className="login-form"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <input
            ref={ref}
            value={value}
            placeholder={tr(lang, "loginField")}
            onChange={(e) => setValue(e.target.value)}
            maxLength={32}
            spellCheck={false}
            autoComplete="off"
            aria-label={tr(lang, "loginField")}
            aria-invalid={invalid}
          />
          <button className="btn btn-primary" type="submit" disabled={!VALID.test(value) || props.busy}>
            {props.busy ? "…" : tr(lang, "loginGo")}
          </button>
        </form>
        {props.oauthConfigured && (
          <>
            <p className="hint">{tr(lang, "loginOr")}</p>
            <button type="button" className="btn btn-secondary" disabled={props.busy} onClick={() => props.onOauth?.()}>
              {props.oauthPending ? tr(lang, "oauthPending") : tr(lang, "loginOauth")}
            </button>
          </>
        )}
        {props.error && (
          <p className="error" role="alert">
            {props.error}
          </p>
        )}
        {props.current && (
          <button type="button" className="foot-link underline" onClick={() => setValue(props.current!)}>
            {tr(lang, "loginSwitch")}: @{props.current}
          </button>
        )}
      </div>
    </div>
  );
}
