import { useEffect, useRef, useState } from "react";
import { tr, type Lang } from "../lib/i18n.ts";
import type { SetupStatus } from "../../../src/shared/types.ts";
import { fetchSetupStatus, postSetup } from "../lib/api.ts";

const osLabel = (s: SetupStatus, lang: Lang): string =>
  s.hardware.os === "mac"
    ? tr(lang, "osMac")
    : s.hardware.os === "win"
      ? tr(lang, "osWin")
      : tr(lang, "osLinux");

export function SetupWizard(props: {
  lang: Lang;
  setLang: (l: Lang) => void;
  initial: SetupStatus;
  onDone: () => void;
}) {
  const { lang } = props;
  const [status, setStatus] = useState<SetupStatus>(props.initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState<string>(props.initial.suggested.model);
  const [customOpen, setCustomOpen] = useState(false);
  const [customUrl, setCustomUrl] = useState("");
  const [backend, setBackend] = useState<"lmstudio" | "omlx" | null>(
    props.initial.omlx.installed && !props.initial.lms.serverUp ? "omlx" : null,
  );
  const pollReq = useRef(0);

  // Reopen after an app update: the version marker is acknowledged only when the
  // user deliberately leaves the wizard — closing the app earlier keeps it coming
  // back (an ack at mount could be lost to a quick close and lose the wizard forever).


  // poll while the wizard is open: job progress + backend state (drop stale responses)
  useEffect(() => {
    const t = setInterval(() => {
      const req = ++pollReq.current;
      fetchSetupStatus()
        .then((s) => {
          if (req === pollReq.current) setStatus(s);
        })
        .catch(() => undefined);
    }, 1500);
    return () => clearInterval(t);
  }, []);

  // step derives from server truth: the download job IS the progress screen
  const downloaded = status.downloadedModels.includes(model);
  const step = status.setupDone
    ? 3
    : status.job.state === "downloading" || status.job.state === "installing-cli"
      ? 2
      : downloaded
        ? 2
        : 1;

  // recommended MLX variant for this machine, matched against what the oMLX
  // server reports (it serves bare names, the catalogue uses org/repo ids)
  const mlx = status.suggested.mlx;
  const mlxLeaf = mlx ? (mlx.model.split("/").pop() ?? mlx.model) : null;
  const mlxPresent = !!mlx && status.omlx.models.some((m) => m === mlx.model || m === mlxLeaf);

  async function done() {
    // persist the version marker only on a deliberate exit (never at mount)
    if (props.initial.setupDone) void postSetup("ack").catch(() => undefined);
    props.onDone();
  }

  async function finish(body: object) {
    setBusy(true);
    setErr(null);
    try {
      await postSetup("finish", body);
      setStatus(await fetchSetupStatus());
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setBusy(true);
    setErr(null);
    try {
      await postSetup("download", { model }); // job singleton drives step 2
      setStatus(await fetchSetupStatus());
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  const jobBusy = status.job.state === "downloading" || status.job.state === "installing-cli";

  // a finished oMLX download becomes the selected model: the radio list comes
  // from the server's boot-time scan and won't show the new pack until a restart
  useEffect(() => {
    const jm = status.job.model;
    if (status.job.state === "done" && jm && backend === "omlx") {
      setModel((cur) => (cur === jm ? cur : jm));
    }
  }, [status.job.state, status.job.model, backend]);

  // job finished (or model already on disk) → auto-complete the setup once.
  // Strict ownership: only a "done" for THIS model auto-finishes — install-cli
  // jobs close with model:null and must never mark the setup complete, and an
  // oMLX download must finish with backend "omlx", not the lmstudio fallthrough.
  const finishedRef = useRef(false);
  const jobDoneThisModel = status.job.state === "done" && status.job.model === model;
  const modelDone = jobDoneThisModel || (status.job.state === "idle" && downloaded);
  useEffect(() => {
    if (finishedRef.current || busy || status.setupDone || !modelDone) return;
    finishedRef.current = true;
    void finish(backend === "omlx" ? { backend: "omlx", model } : { model });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelDone, status.setupDone, busy]);

  return (
    <main className="wizard-page">
      <div className="glow" aria-hidden="true" />
      <button
        type="button"
        className="wizard-lang"
        onClick={() => props.setLang(lang === "en" ? "it" : "en")}
        aria-label={tr(lang, "langToggle")}
      >
        {tr(lang, "langToggle")}
      </button>

      <div className="wizard-brand" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4.4 8Q12 5.4 19.6 8" />
          <path d="M12 6.6V9.6" />
          <path d="M6.3 9.6h11.4" />
          <path d="M7.7 9.6V19M16.3 9.6V19" />
          <path d="M5.9 14.2h12.2" />
        </svg>
      </div>
      <p className="wizard-wordmark">{tr(lang, "appName")}</p>

      <section className="wizard-card">
        <ol className="wizard-steps" aria-label={tr(lang, "setupTitle")}>
          {[1, 2, 3].map((n) => (
            <li key={n} className={n === step ? "cur" : n < step ? "done" : ""}>
              <span className="dot" aria-hidden="true">{n < step ? "✓" : n}</span>
              <span className="lbl">{tr(lang, `setStep${n}`)}</span>
            </li>
          ))}
        </ol>

        <h1>{tr(lang, "setupTitle")}</h1>
        <p className="wizard-sub">{tr(lang, "setupIntro")}</p>

        <div className="hw-row">
          <span className="hw-chip">{osLabel(status, lang)}</span>
          <span className="hw-chip">{status.hardware.chip}</span>
          <span className="hw-chip">{status.hardware.ramGb} GB RAM</span>
        </div>

        {step === 1 && (
          <>
            {status.omlx.installed && (
              <div className="backend-row">
                <button
                  className={backend === "omlx" ? "selected" : ""}
                  onClick={() => {
                    setBackend("omlx");
                    setModel(status.omlx.models[0] ?? model);
                  }}
                >
                  {tr(lang, "backendOmlx")}
                </button>
                <button
                  className={backend === "lmstudio" ? "selected" : ""}
                  onClick={() => {
                    setBackend("lmstudio");
                    setModel(status.suggested.model);
                  }}
                >
                  {tr(lang, "backendLms")}
                </button>
              </div>
            )}
            {backend === "omlx" && status.omlx.installed ? (
              <>
                <p className="profile-meta">{tr(lang, "omlxFound")}</p>
                <div className="omlx-models">
                  {status.omlx.models.map((m) => (
                    <label key={m} className="mlx-opt">
                      <input
                        type="radio"
                        name="omlx-model"
                        checked={model === m}
                        onChange={() => setModel(m)}
                      />
                      {m}
                    </label>
                  ))}
                </div>
                {mlx && !mlxPresent && (
                  <div className="model-card">
                    <span>
                      {tr(lang, "recModel")}: <strong>{mlx.model}</strong> ({mlx.sizeGb} GB)
                    </span>
                    <button className="btn-primary"
                      disabled={jobBusy || busy}
                      onClick={async () => {
                        setBusy(true);
                        await postSetup("omlx-download", { model: mlx.model }).catch(() => undefined);
                        setBusy(false);
                      }}
                    >
                      {status.job.model === mlx.model && status.job.state === "downloading"
                        ? `${Math.round(((status.job.bytesDone ?? 0) / (status.job.totalBytes || 1)) * 100)}%`
                        : tr(lang, "download")}
                    </button>
                  </div>
                )}
                {status.omlx.downloadable
                  .filter(
                    (d) =>
                      d.model !== mlx?.model &&
                      !status.omlx.models.some((m) => m === d.model || m === (d.model.split("/").pop() ?? "")),
                  )
                  .map((d) => (
                    <div className="model-card" key={d.model}>
                      <span>
                        <strong>{d.model}</strong> ({d.sizeGb} GB)
                      </span>
                      <button className="btn-primary"
                        disabled={jobBusy || busy}
                        onClick={async () => {
                          setBusy(true);
                          await postSetup("omlx-download", { model: d.model }).catch(() => undefined);
                          setBusy(false);
                        }}
                      >
                        {status.job.model === d.model && status.job.state === "downloading"
                          ? `${Math.round(((status.job.bytesDone ?? 0) / (status.job.totalBytes || 1)) * 100)}%`
                          : tr(lang, "download")}
                      </button>
                    </div>
                  ))}
                {status.job.state === "downloading" && status.job.totalBytes ? (
                  <>
                    <div className="progress" aria-hidden="true">
                      <span style={{ width: `${Math.round(((status.job.bytesDone ?? 0) / status.job.totalBytes) * 100)}%` }} />
                    </div>
                    <div className="action-row">
                      <button className="linklike" onClick={() => postSetup("cancel").catch(() => undefined)}>
                        ✕
                      </button>
                    </div>
                  </>
                ) : null}
                <p className="hint">{tr(lang, "omlxStartNote")}</p>
                <div className="action-row">
                  <button className="btn-primary" disabled={busy || jobBusy} onClick={() => finish({ backend: "omlx", model })}>
                    {tr(lang, "go")}
                  </button>
                </div>
              </>
            ) : (
              <>
            <div className="model-card">
              <span>
                {tr(lang, "recModel")}: <strong>{model}</strong>{" "}
                ({status.suggested.sizeGb} GB)
              </span>
              {status.suggested.mlxLms && (
                <label className="mlx-opt">
                  <input
                    type="checkbox"
                    checked={/-mlx/i.test(model)}
                    onChange={(e) =>
                      setModel(e.target.checked ? status.suggested.mlxLms!.model : status.suggested.model)
                    }
                  />
                  {tr(lang, "mlxOpt")}
                </label>
              )}
            </div>
            {!status.lms.installed && (
              <div className="action-row">
                <span className="warn-box">{tr(lang, "backendMissing")}</span>
                <button
                  disabled={jobBusy}
                  onClick={async () => {
                    setBusy(true);
                    await postSetup("install-cli").catch(() => undefined);
                    setBusy(false);
                  }}
                >
                  {status.job.state === "installing-cli"
                    ? tr(lang, "installingCli")
                    : tr(lang, "installCli")}
                </button>
                {status.hardware.os === "win" && <p className="hint">{tr(lang, "winFirstRun")}</p>}
              </div>
            )}
            <div className="action-row">
              <button className="btn-primary"
                disabled={busy || !status.lms.installed}
                onClick={download}
              >
                {tr(lang, "download")}
              </button>
              {status.hardware.os === "win" && status.lms.installed && (
                <p className="hint">{tr(lang, "winFirstRun")}</p>
              )}
            </div>
              </>
            )}
          </>
        )}

        {step === 2 && (
          <>
            <p className="loading">
              {tr(lang, "downloading")} <strong>{status.job.model ?? model}</strong>
            </p>
            <div className="progress" aria-hidden="true">
              <span />
            </div>
            {status.job.logTail && <pre className="joblog">{status.job.logTail}</pre>}
            <div className="action-row">
              <button disabled={busy} onClick={() => finish(backend === "omlx" ? { backend: "omlx", model } : { model })}>
                {tr(lang, "skipDownload")}
              </button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <h2>{tr(lang, "finishTitle")}</h2>
            <p className="loading">
              {status.llm.state === "starting"
                ? tr(lang, "llmStarting")
                : status.llm.state === "up"
                  ? tr(lang, "llmReady")
                  : tr(lang, "llmOffNote")}
            </p>
            <div className="action-row">
              <button className="btn-primary" disabled={busy} onClick={done}>
                {tr(lang, "startUsing")}
              </button>
            </div>
          </>
        )}

        <div className="wizard-footer">
          <button className="linklike" onClick={() => setCustomOpen(!customOpen)}>
            {tr(lang, "useCustom")}
          </button>
          {customOpen && (
            <div className="action-row">
              <input
                placeholder={tr(lang, "customUrl")}
                value={customUrl}
                onChange={(e) => setCustomUrl(e.target.value)}
              />
              <button disabled={busy || !/^https?:\/\//.test(customUrl)} onClick={() => finish({ baseUrl: customUrl, model })}>
                {tr(lang, "customUse")}
              </button>
            </div>
          )}
          <button
            className="linklike"
            disabled={busy}
            onClick={() => finish({ backend: "skipped" })}
          >
            {tr(lang, "skipSetup")}
          </button>
          {err && <p className="error">{err}</p>}
          {status.job.state === "error" && (
            <p className="error">
              {tr(lang, "downloadFailed")} {status.job.error}
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
