import { tr, type Lang } from "../lib/i18n.ts";
import { PHASES, phaseKey, phaseStep } from "../lib/logic/progress.ts";

/** Generation progress stepper (fed by the /api/recommend/stream phases).
 *  Idempotent per phase: a local-mode flush or a cache hit lands all events at
 *  once / none at all — both render as "done" without artifacts. */
export function Progress(props: { lang: Lang; phase: string }) {
  const step = phaseStep(props.phase);
  return (
    <div className="progress" role="status" aria-live="polite" data-od-id="recos-progress">
      <p className="loading">{tr(props.lang, phaseKey(props.phase))}</p>
      <div className="bar" aria-hidden="true">
        <span className="fill" style={{ width: step > 0 ? `${Math.round((step / PHASES.length) * 100)}%` : "0%" }} />
      </div>
      {step > 0 && (
        <small className="mono">
          {tr(props.lang, "stepOf", { n: step, m: PHASES.length })}
        </small>
      )}
    </div>
  );
}
