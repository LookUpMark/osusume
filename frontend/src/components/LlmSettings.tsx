import { useEffect, useState } from "react";
import type { Lang } from "../lib/i18n.ts";
import { tr } from "../lib/i18n.ts";
import { fetchLlmModels, fetchSettings, patchSettings, type Settings } from "../lib/api.ts";
import { errorMessage } from "../lib/logic/errors.ts";

/** Settings → AI backend section: base URL (presets + custom), model picker fed
 *  by the live backend, custom system-prompt additions. Wizard keeps ownership
 *  of download/serve — here you only point at a backend already running. */
export function LlmSettings(props: { lang: Lang; onSaved: () => void }) {
  const { lang } = props;
  const [s, setS] = useState<Settings | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [extra, setExtra] = useState("");
  const [models, setModels] = useState<string[] | null>(null);
  const [modelsErr, setModelsErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings()
      .then((v) => {
        setS(v);
        setBaseUrl(v.baseUrl);
        setModel(v.model ?? "");
        setExtra(v.systemPromptExtra);
      })
      .catch(() => setErr(tr(lang, "errGeneric")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = s !== null && (baseUrl.trim() !== s.baseUrl || model !== (s.model ?? "") || extra !== s.systemPromptExtra);

  const save = () => {
    if (!s || !dirty || busy) return;
    setBusy(true);
    setSaved(false);
    setErr(null);
    const patch: Record<string, string> = {};
    if (baseUrl.trim() !== s.baseUrl) patch.baseUrl = baseUrl.trim();
    if (model !== (s.model ?? "")) patch.model = model;
    if (extra !== s.systemPromptExtra) patch.systemPromptExtra = extra;
    patchSettings(patch)
      .then((v) => {
        setS(v);
        setBaseUrl(v.baseUrl);
        setModel(v.model ?? "");
        setExtra(v.systemPromptExtra);
        setModels(null); // backend may have changed — the cached list is stale
        setSaved(true);
        props.onSaved();
      })
      .catch((e) => setErr(errorMessage(lang, e)))
      .finally(() => setBusy(false));
  };

  const loadModels = () => {
    if (busy) return;
    setBusy(true);
    setModelsErr(null);
    fetchLlmModels()
      .then((r) => setModels(r.models))
      .catch((e) => setModelsErr(errorMessage(lang, e)))
      .finally(() => setBusy(false));
  };

  const presets: [string, string][] = [
    ["LM Studio", "http://127.0.0.1:1234/v1"],
    ["Ollama", "http://127.0.0.1:11434/v1"],
    ["oMLX", "http://127.0.0.1:8080/v1"],
  ];

  return (
    <>
      <div className="set-row">
        <span>{tr(lang, "setLlmBackend")}</span>
        <div className="set-stack set-form">
          <input
            type="text"
            aria-label={tr(lang, "setLlmBackend")}
            spellCheck={false}
            autoComplete="off"
            maxLength={200}
            placeholder="http://127.0.0.1:1234/v1"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <div className="set-presets">
            {presets.map(([label, url]) => (
              <button key={url} type="button" className="linklike" onClick={() => setBaseUrl(url)}>
                {label}
              </button>
            ))}
          </div>
          {s?.envOverride && <small className="err">{tr(lang, "setLlmEnv")}</small>}
        </div>
      </div>

      <div className="set-row">
        <span>{tr(lang, "setLlmModel")}</span>
        <div className="set-stack set-form">
          <div className="set-model-line">
            <select aria-label={tr(lang, "setLlmModel")} value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">{tr(lang, "setLlmDefault", { m: s?.defaultModel ?? "" })}</option>
              {(models ?? []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
              {model && !(models ?? []).includes(model) && <option value={model}>{model}</option>}
            </select>
            <button type="button" className="linklike" disabled={busy} onClick={loadModels}>
              {models !== null ? tr(lang, "setLlmReload") : tr(lang, "setLlmLoadModels")}
            </button>
          </div>
          {modelsErr && <small className="err">{modelsErr}</small>}
          {models !== null && !modelsErr && (
            <small>{models.length === 0 ? tr(lang, "setLlmModelsNone") : tr(lang, "setLlmModelsOk", { n: models.length })}</small>
          )}
        </div>
      </div>

      <div className="set-row set-row-top">
        <span>{tr(lang, "setLlmPrompt")}</span>
        <div className="set-stack set-form">
          <textarea
            aria-label={tr(lang, "setLlmPrompt")}
            maxLength={4000}
            rows={4}
            placeholder={tr(lang, "setLlmPromptHint")}
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
          />
          <small className="hint">{tr(lang, "setLlmPromptHint")}</small>
        </div>
      </div>

      <div className="set-row">
        <span>{tr(lang, "setTitleLlm")}</span>
        <div className="set-stack set-form">
          <button type="button" className="btn btn-primary set-save" disabled={!dirty || busy} onClick={save}>
            {busy ? tr(lang, "checking") : tr(lang, "setLlmSave")}
          </button>
          {saved && !dirty && <small className="ok">{tr(lang, "setLlmSaved")}</small>}
          {err && <small className="err">{err}</small>}
        </div>
      </div>
    </>
  );
}
