import { useEffect, useRef, useState } from "react";
import { tr, type Lang } from "../../shared/strings.ts";
import type { RecoResult, ScoredReco } from "../../shared/types.ts";
import { lookupMedia, postChat, type ChatMsg } from "../api.ts";

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
  onOpen: (reco: ScoredReco) => void;
}) {
  const { lang, result } = props;
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [q, setQ] = useState("");
  const [lookup, setLookup] = useState<{ busy: boolean; recos: ScoredReco[] | null }>({ busy: false, recos: null });
  const [extraIds, setExtraIds] = useState<number[]>([]);
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
    setLookup({ busy: false, recos: null });
    setExtraIds([]);
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
      const r = await postChat(props.username, lang, history.slice(-12), extraIds);
      setMsgs([...history, { role: "assistant", content: r.reply }]);
    } catch {
      setErr(true);
    } finally {
      setBusy(false);
    }
  }

  async function search() {
    const query = q.trim();
    if (query.length < 2 || lookup.busy || !props.result) return;
    setLookup({ busy: true, recos: null });
    try {
      const r = await lookupMedia(props.username, query, lang);
      setLookup({ busy: false, recos: r.recos });
    } catch {
      setLookup({ busy: false, recos: [] });
    }
  }

  /** Open a looked-up title: it must stay discussable in the chat context. */
  function openLookup(r: ScoredReco) {
    setExtraIds((cur) => (cur.includes(r.media.id) ? cur : [...cur, r.media.id]));
    props.onOpen(r);
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
        className="chat-lookup"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <input
          value={q}
          placeholder={tr(lang, "lookupPlaceholder")}
          onChange={(e) => setQ(e.target.value)}
          maxLength={80}
          aria-label={tr(lang, "lookupGo")}
        />
        <button className="btn-line" type="submit" disabled={q.trim().length < 2 || lookup.busy}>
          {lookup.busy ? "…" : tr(lang, "lookupGo")}
        </button>
      </form>
      {lookup.recos !== null && (
        <div className="chat-cards lookup-res">
          {lookup.recos.length === 0 ? (
            <p className="lookup-none">{tr(lang, "lookupNoRes")}</p>
          ) : (
            lookup.recos.map((r) => (
              <button key={r.media.id} className="chat-card" type="button" onClick={() => openLookup(r)}>
                {r.media.coverImage && <img src={r.media.coverImage} alt="" />}
                <span>
                  {r.media.title}
                  <em>{Math.round(r.final * 100)}/110</em>
                </span>
              </button>
            ))
          )}
        </div>
      )}
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
