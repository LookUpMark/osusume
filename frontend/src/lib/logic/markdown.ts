/** Conversational markdown subset — **bold**, *italic*, http(s) links, "- "
 *  lists. Everything else (headings, code, tables, HTML) stays literal text:
 *  the chat prompt mandates this subset, the renderer tolerates everything.
 *  Pure data, no HTML strings — React escapes the lot, zero XSS surface. */

export type MdInline =
  | { t: "text"; s: string }
  | { t: "strong"; s: string }
  | { t: "em"; s: string }
  | { t: "link"; label: string; href: string };

export type MdBlock = { t: "p"; inl: MdInline[] } | { t: "ul"; items: MdInline[][] };

// ** before * (otherwise bold never matches); href only http(s) — any other
// scheme simply doesn't match, so "[t](javascript:…)" stays visible text
const INLINE_RE = /\*\*([^*\n]+)\*\*|\*([^*\n]+)\*|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g;

function parseInline(text: string): MdInline[] {
  const out: MdInline[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE_RE)) {
    const i = m.index;
    if (i > last) out.push({ t: "text", s: text.slice(last, i) });
    if (m[1] !== undefined) out.push({ t: "strong", s: m[1] });
    else if (m[2] !== undefined) out.push({ t: "em", s: m[2] });
    else out.push({ t: "link", label: m[3], href: m[4] });
    last = i + m[0].length;
  }
  if (last < text.length) out.push({ t: "text", s: text.slice(last) });
  return out.length > 0 ? out : [{ t: "text", s: text }];
}

export function parseMarkdown(text: string): MdBlock[] {
  const blocks: MdBlock[] = [];
  for (const chunk of text.split(/\n\s*\n/)) {
    const lines = chunk.split("\n").filter((l) => l.trim() !== "");
    if (lines.length === 0) continue;
    // a list only when EVERY line is a "- " item (a lone "- " is prose);
    // "* " is deliberately NOT a list marker — it collides with italic
    if (lines.every((l) => l.startsWith("- "))) {
      blocks.push({ t: "ul", items: lines.map((l) => parseInline(l.slice(2))) });
    } else {
      blocks.push({ t: "p", inl: parseInline(lines.join("\n")) });
    }
  }
  return blocks;
}
