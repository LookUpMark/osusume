import { useEffect, useRef, useState } from "react";
import { tr, type Lang } from "../../shared/strings.ts";
import type { RecoResult } from "../../shared/types.ts";
import { postChat, type ChatMsg } from "../api.ts";

export function ChatPanel(props: { lang: Lang; result: RecoResult | null; llmOn: boolean | null; username: string }) {
  const { lang, result } = props;
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [msgs, busy]);

  // waiting feedback: seconds next to the dots — a slow model is "working", a
  // dead server is visibly stuck instead of an eternal spinner
  useEffect(() => {
    if (!busy) return;
    const t0 = Date.now();
    setElapsed(0);
    const iv = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(iv);
  }, [busy]);

  // a new search is a new conversation — never keep turns about the old result
  useEffect(() => {
    setMsgs([]);
    setErr(false);
  }, [props.username, props.result?.profile.hash]);

  const disabled = busy || !result || props.llmOn === false;

  async function send() {
    const text = input.trim();
    if (!text || disabled || !props.result) return;
    const history = [...msgs, { role: "user" as const, content: text }];
    setMsgs(history);
    setInput("");
    setBusy(true);
    setErr(false);
    try {
      const r = await postChat(props.username, lang, history.slice(-12));
      setMsgs([...history, { role: "assistant", content: r.reply }]);
    } catch {
      setErr(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat-panel" data-od-id="chat-panel">
      <div className="chat-scroll">
        {msgs.length === 0 ? (
          <div className="state-box">
            <p className="big">
              {!result ? tr(lang, "chatEmpty") : props.llmOn === false ? tr(lang, "chatNoLlm") : tr(lang, "chatHello")}
            </p>
          </div>
        ) : (
          msgs.map((m, i) => (
            <div key={i} className={`chat-msg ${m.role}`} aria-label={m.role}>
              <p>{m.content}</p>
            </div>
          ))
        )}
        {busy && (
          <div className="chat-msg assistant thinking" role="status" aria-label={tr(lang, "chatThinking")}>
            <span className="dots" aria-hidden="true">
              <span /><span /><span />
            </span>
            {tr(lang, "chatThinking")} · {tr(lang, "secsShort", { s: elapsed })}
          </div>
        )}
        {err && (
          <p className="error" role="alert">
            {tr(lang, "chatErr")}
          </p>
        )}
        <div ref={endRef} />
      </div>
      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          value={input}
          placeholder={tr(lang, "chatPlaceholder")}
          onChange={(e) => setInput(e.target.value)}
          disabled={disabled}
          maxLength={4000}
          aria-label={tr(lang, "chatPlaceholder")}
        />
        <button className="btn btn-primary" type="submit" disabled={disabled || !input.trim()}>
          {tr(lang, "chatSend")}
        </button>
      </form>
    </div>
  );
}
