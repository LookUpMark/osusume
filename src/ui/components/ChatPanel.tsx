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
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [msgs, busy]);

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
          <div className="chat-msg assistant thinking" aria-label={tr(lang, "chatThinking")}>
            <span className="dots" aria-hidden="true">
              <span /><span /><span />
            </span>
          </div>
        )}
        {err && <p className="error">{tr(lang, "chatErr")}</p>}
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
          aria-label={tr(lang, "chatPlaceholder")}
        />
        <button className="btn btn-primary" type="submit" disabled={disabled || !input.trim()}>
          {tr(lang, "chatSend")}
        </button>
      </form>
    </div>
  );
}
