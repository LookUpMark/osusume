import { parseMarkdown, type MdBlock, type MdInline } from "../lib/logic/markdown.ts";

const Inline = ({ inl }: { inl: MdInline[] }) => (
  <>
    {inl.map((n, i) =>
      n.t === "text" ? (
        <span key={i}>{n.s}</span>
      ) : n.t === "strong" ? (
        <strong key={i}>{n.s}</strong>
      ) : n.t === "em" ? (
        <em key={i}>{n.s}</em>
      ) : (
        <a key={i} href={n.href} target="_blank" rel="noopener noreferrer">
          {n.label}
        </a>
      ),
    )}
  </>
);

const Block = ({ b }: { b: MdBlock }) =>
  b.t === "p" ? (
    <p>
      <Inline inl={b.inl} />
    </p>
  ) : (
    <ul className="md-ul">
      {b.items.map((it, i) => (
        <li key={i}>
          <Inline inl={it} />
        </li>
      ))}
    </ul>
  );

/** LLM chat reply rendered as conversational markdown (see logic/markdown.ts). */
export function Markdown(props: { text: string }) {
  return (
    <>
      {parseMarkdown(props.text).map((b, i) => (
        <Block key={i} b={b} />
      ))}
    </>
  );
}
