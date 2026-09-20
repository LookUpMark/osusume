import { useEffect, useRef, useState } from "react";
import { tr, type Lang } from "../lib/i18n.ts";
import type { RecoResult, ScoredReco } from "../lib/types.ts";
import { postChat, type ChatMsg } from "../lib/api.ts";

/** Titles among the current recos that the reply mentions by name — clickable
 *  cards under the message (substring match; the prompt makes the model cite
 *  titles verbatim). */
function mentionedRecos(text: string, recos: ScoredReco[]): ScoredReco[] {
  const hay = text.toLowerCase();
  return recos.filter((r) => r.media.title.length >= 4 && hay.includes(r.media.title.toLowerCase()));
}

export function ChatPanel(props: {
  lang: Lang;
  result: RecoResult | null;
  llmOn: boolean | null;
  username: string;
  extraIds: number[];
  onOpen: (reco: ScoredReco) => void;
}) {
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
      // looked-up titles (opened from the topbar search) ride along as extra
      // context so the model can answer questions about non-recommended anime
      const r = await postChat(props.username, lang, history.slice(-12), props.extraIds);
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
            <div key={i} style={{ display: "contents" }}>
              <div className={`chat-msg ${m.role}`} aria-label={m.role}>
                <p>{m.content.replace(/\*/g, "")}</p>
              </div>
              {m.role === "assistant" && props.result && mentionedRecos(m.content, props.result.recos).length > 0 && (
                <div className="chat-cards">
                  {mentionedRecos(m.content, props.result.recos).map((r) => (
                    <button key={r.media.id} className="chat-card" type="button" onClick={() => props.onOpen(r)}>
                      {r.media.coverImage && <img src={r.media.coverImage} alt="" />}
                      <span>{r.media.title}</span>
                    </button>
                  ))}
                </div>
              )}
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
