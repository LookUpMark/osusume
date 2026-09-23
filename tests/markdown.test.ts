import assert from "node:assert/strict";
import { test } from "node:test";
import type { ScoredReco } from "../frontend/src/lib/types.ts";
import { parseMarkdown } from "../frontend/src/lib/logic/markdown.ts";
import { cardToReco } from "../frontend/src/lib/logic/recos.ts";

const inline = (text: string) => parseMarkdown(text);

test("parseMarkdown: bold, italic, link", () => {
  assert.deepEqual(inline("**hey**"), [{ t: "p", inl: [{ t: "strong", s: "hey" }] }]);
  assert.deepEqual(inline("a *soft* b"), [
    { t: "p", inl: [{ t: "text", s: "a " }, { t: "em", s: "soft" }, { t: "text", s: " b" }] },
  ]);
  assert.deepEqual(inline("[site](https://anilist.co)"), [
    { t: "p", inl: [{ t: "link", label: "site", href: "https://anilist.co" }] },
  ]);
});

test("parseMarkdown: link only http(s), other schemes stay text", () => {
  assert.deepEqual(inline("[x](javascript:alert(1))"), [
    { t: "p", inl: [{ t: "text", s: "[x](javascript:alert(1))" }] },
  ]);
  assert.deepEqual(inline("[x](/relative)"), [{ t: "p", inl: [{ t: "text", s: "[x](/relative)" }] }]);
});

test("parseMarkdown: lists, paragraphs, tolerance", () => {
  const ul = parseMarkdown("- **One** first\n- Two\n- Three");
  assert.equal(ul.length, 1);
  assert.equal(ul[0].t, "ul");
  assert.deepEqual(ul[0].items[0], [{ t: "strong", s: "One" }, { t: "text", s: " first" }]);

  // a lone "- " line among prose is NOT a list
  assert.equal(parseMarkdown("prose\n- stray").length, 1);
  assert.equal(parseMarkdown("prose\n- stray")[0].t, "p");

  // paragraphs split on blank lines
  const two = parseMarkdown("one\n\ntwo");
  assert.equal(two.length, 2);
  assert.equal(two[0].t, "p");
  assert.equal(two[1].t, "p");

  // unmatched asterisks and banned syntax stay literal
  assert.deepEqual(inline("a * b"), [{ t: "p", inl: [{ t: "text", s: "a * b" }] }]);
  assert.deepEqual(inline("# heading"), [{ t: "p", inl: [{ t: "text", s: "# heading" }] }]);
  assert.deepEqual(inline("`code`"), [{ t: "p", inl: [{ t: "text", s: "`code`" }] }]);

  // bold never spans lines
  assert.deepEqual(inline("**no\nway**"), [{ t: "p", inl: [{ t: "text", s: "**no\nway**" }] }]);

  // bold wins over italic at the same start
  assert.deepEqual(inline("**x**"), [{ t: "p", inl: [{ t: "strong", s: "x" }] }]);
});

test("cardToReco: pool hit returns the real object", () => {
  const reco = { media: { id: 7, title: "Monster" } } as unknown as ScoredReco;
  assert.equal(cardToReco({ id: 7, title: "Monster", coverImage: null, coverColor: null, seasonYear: null, format: null, score: null, siteUrl: null }, [reco]), reco);
});

test("cardToReco: miss builds a neutral shell (detail fetches why on demand)", () => {
  const reco = cardToReco(
    { id: 9, title: "Unknown", coverImage: "c.png", coverColor: "#123456", seasonYear: 2001, format: "MOVIE", score: 74, siteUrl: "https://anilist.co/anime/9" },
    [],
  );
  assert.equal(reco.media.id, 9);
  assert.equal(reco.media.title, "Unknown");
  assert.equal(reco.media.format, "MOVIE");
  assert.equal(reco.media.coverImage, "c.png");
  assert.equal(reco.media.siteUrl, "https://anilist.co/anime/9");
  assert.equal(reco.final, 0.74);
  assert.deepEqual(reco.breakdown, { affinity: 0, quality: 0, community: 0 });
  assert.deepEqual(reco.badges, []);
  assert.equal(reco.why, "");
});
