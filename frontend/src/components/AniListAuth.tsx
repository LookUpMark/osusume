import { useEffect, useState } from "react";
import { tr, type Lang } from "../lib/i18n.ts";
import {
  disconnectAniList,
  fetchAniListAuth,
  patchAniListAuth,
  startAniListLogin,
  type AniListAuth as Auth,
} from "../lib/api.ts";
import { errorMessage } from "../lib/logic/errors.ts";

/** Settings → AniList account: client credentials, connect (OAuth via system
 *  browser + fixed loopback callback), disconnect. Without credentials the
 *  whole section renders in "not configured" state and the app is unchanged. */
export function AniListAuth(props: { lang: Lang; onAuthChange: (auth: Auth) => void }) {
  const { lang } = props;
  const [auth, setAuth] = useState<Auth | null>(null);
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchAniListAuth()
      .then((a) => {
        setAuth(a);
        props.onAuthChange(a);
      })
      .catch(() => setErr(tr(lang, "errGeneric")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async (thenConnect: boolean) => {
    if (busy || auth === null) return;
    setBusy(true);
    setErr(null);
    try {
      const patch: Record<string, string> = {};
      if (clientId.trim()) patch.clientId = clientId.trim();
      if (secret.trim()) patch.clientSecret = secret.trim();
      let next: Auth = auth;
      if (Object.keys(patch).length > 0) next = await patchAniListAuth(patch);
      if (thenConnect) {
        const { url } = await startAniListLogin();
        window.open(url, "_blank", "noopener");
        next = { ...(next as Auth), flow: "pending" };
      }
      setAuth(next);
      setSecret("");
      props.onAuthChange(next);
    } catch (e) {
      setErr(errorMessage(lang, e));
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await disconnectAniList();
      const a = await fetchAniListAuth();
      setAuth(a);
      props.onAuthChange(a);
    } catch (e) {
      setErr(errorMessage(lang, e));
    } finally {
      setBusy(false);
    }
  };

  if (auth === null) return null;

  return (
    <>
      <div className="set-row set-row-top">
        <span>{tr(lang, "setTitleAnilist")}</span>
        <div className="set-stack set-form">
          {!auth.authenticated && (
            <>
              <input
                type="text"
                inputMode="numeric"
                aria-label={tr(lang, "anilistClientId")}
                placeholder={tr(lang, "anilistClientId")}
                spellCheck={false}
                autoComplete="off"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
              />
              <input
                type="password"
                aria-label={tr(lang, "anilistClientSecret")}
                placeholder={tr(lang, "anilistClientSecret")}
                autoComplete="off"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
              />
              <small className="hint">{tr(lang, "anilistRedirectHint", { uri: auth.redirectUri })}</small>
              <button
                type="button"
                className="btn btn-primary set-save"
                disabled={busy || !clientId.trim() || (!secret.trim() && !auth.configured)}
                onClick={() => void save(true)}
              >
                {busy ? tr(lang, "checking") : tr(lang, "anilistConnect")}
              </button>
              {auth.flow === "pending" && <small>{tr(lang, "oauthPending")}</small>}
            </>
          )}
          {auth.authenticated && (
            <>
              <small className="ok">{tr(lang, "anilistConnected", { u: auth.username ?? "" })}</small>
              <button type="button" className="linklike" disabled={busy} onClick={() => void disconnect()}>
                {tr(lang, "anilistDisconnect")}
              </button>
            </>
          )}
          {err && <small className="err">{err}</small>}
        </div>
      </div>
    </>
  );
}
