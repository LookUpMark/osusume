import { useEffect, useState } from "react";
import { tr, type Lang } from "../lib/i18n.ts";
import { errorMessage } from "../lib/logic/errors.ts";

interface CfState {
  state: "loaded" | "absent" | "downloading" | "disabled" | "error";
  enabled: boolean;
  version: number | null;
  builtAt: string | null;
  count: number | null;
  smoke: boolean;
  error: string | null;
}

const json = async (res: Response): Promise<any> => {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? `HTTP ${res.status}`);
  return body;
};

/** Settings → collaborative signal: model state, enable toggle, manual download.
 *  With no artifact the ranking engine is byte-identical — this section just
 *  explains why and offers the download. */
export function CfSettings(props: { lang: Lang }) {
  const { lang } = props;
  const [s, setS] = useState<CfState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = () =>
    fetch("/api/cf")
      .then(json)
      .then(setS)
      .catch(() => setErr(tr(lang, "errGeneric")));

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = () => {
    if (busy || !s) return;
    setBusy(true);
    setErr(null);
    fetch("/api/cf", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled: !s.enabled }),
    })
      .then(json)
      .then(setS)
      .catch((e) => setErr(errorMessage(lang, e)))
      .finally(() => setBusy(false));
  };

  const download = () => {
    if (busy) return;
    setBusy(true);
    setErr(null);
    fetch("/api/cf/download", { method: "POST" })
      .then(json)
      .then(setS)
      .catch((e) => setErr(errorMessage(lang, e)))
      .finally(() => setBusy(false));
  };

  const stateLabel = () =>
    s!.state === "loaded"
      ? tr(lang, "cfStateLoaded", { n: s!.count ?? 0 })
      : s!.state === "downloading"
        ? tr(lang, "checking")
        : s!.state === "error"
          ? tr(lang, "cfStateError")
          : tr(lang, "cfStateAbsent");

  return (
    <div className="set-row">
      <span>{tr(lang, "setTitleCf")}</span>
      <div className="set-stack">
        {s === null ? null : (
          <>
            <button type="button" className="linklike" role="switch" aria-checked={s.enabled} disabled={busy} onClick={toggle}>
              {tr(lang, "setTitleCf")} — {s.enabled ? tr(lang, "on") : tr(lang, "off")}
            </button>
            <small className={s.state === "loaded" ? "ok" : undefined}>
              {s.enabled ? stateLabel() : tr(lang, "cfDisabled")}
              {s.state === "loaded" && s.builtAt ? ` · ${s.builtAt.slice(0, 10)}` : ""}
            </small>
            {s.enabled && s.state !== "loaded" && (
              <button type="button" className="linklike" disabled={busy} onClick={download}>
                {s.state === "downloading" ? tr(lang, "checking") : tr(lang, "cfDownload")}
              </button>
            )}
            {err && <small className="err">{err}</small>}
          </>
        )}
      </div>
    </div>
  );
}
