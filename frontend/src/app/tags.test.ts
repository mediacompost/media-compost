import test from "node:test";
import assert from "node:assert/strict";

import {
  normalizeTagName, sanitizeLinkTagInput, sanitizeTagInput, tagBaseName,
  tagFieldInput, tagFieldName, tagNamespace,
} from "./tags.ts";

test("whitespace still collapses to underscores", () => {
  assert.equal(sanitizeTagInput("white shirt"), "white_shirt");
  assert.equal(sanitizeTagInput("a\tb\nc"), "a_b_c");
  assert.equal(sanitizeTagInput("plain"), "plain");
});

test("interior colons are KEPT, however many there are", () => {
  assert.equal(sanitizeTagInput("costume:tiger"), "costume:tiger");
  // Turning them into underscores did not stop anybody thinking in
  // hierarchies — it only stopped them writing one down, and stored something
  // else without saying so.
  assert.equal(sanitizeTagInput("a:b:c"), "a:b:c");
  assert.equal(sanitizeTagInput("a:b:c:d"), "a:b:c:d");
  assert.equal(normalizeTagName("costume:hat:straw"), "costume:hat:straw");
  assert.equal(sanitizeTagInput("a::b"), "a::b");
});

test("a leading colon is KEPT — the emoticon tags are names", () => {
  // `:o`, `:d` and `:3` are the booru tag set's most-used expression
  // tags; dropping the colon turned each into a letter.
  assert.equal(sanitizeTagInput(":foo"), ":foo");
  assert.equal(sanitizeTagInput(":o"), ":o");
  assert.equal(normalizeTagName(":o"), ":o");
  assert.equal(sanitizeTagInput(":::a:b"), ":::a:b");
});

test("a trailing colon survives typing AND commit", () => {
  // Danbooru spells three expression tags `d:`, `3:` and `c:`; eating the
  // colon turned each into a bare letter the app had decided it meant.
  assert.equal(sanitizeTagInput("costume:"), "costume:");
  assert.equal(normalizeTagName("costume:"), "costume:");
  assert.equal(normalizeTagName("costume:tiger"), "costume:tiger");
  assert.equal(normalizeTagName("d:"), "d:");
  assert.equal(normalizeTagName("3:"), "3:");
  assert.equal(normalizeTagName("c:"), "c:");
  // However many there are, and wherever the name ends.
  assert.equal(normalizeTagName("costume::"), "costume::");
  assert.equal(normalizeTagName("a:b:"), "a:b:");
  assert.equal(normalizeTagName("  spaced  out  "), "spaced_out");
});

test("a name the field produced is never one the API would refuse", () => {
  // The backend refuses anything `normalize` would have changed, so the two
  // must agree on every shape a field can emit.
  for (const s of ["costume:", ":x", "a:b:c", " a b ", "x", "a:", "::", "a::b",
                   "costume:hat:straw", ":a:b:", "a:b:c:d:e", ":"]) {
    assert.equal(normalizeTagName(normalizeTagName(s)), normalizeTagName(s),
                 `not idempotent for ${JSON.stringify(s)}`);
  }
  // A name that is nothing but colons is a name, silly as it is: the rule is
  // about whitespace, and nothing else.
  assert.equal(normalizeTagName("::"), "::");
});

test("the namespace is read, never stored", () => {
  assert.equal(tagNamespace("costume:tiger"), "costume");
  assert.equal(tagBaseName("costume:tiger"), "tiger");
  assert.equal(tagNamespace("plain"), "");
  assert.equal(tagBaseName("plain"), "plain");
  // Total on an old library's names: `a:b:c` is simply namespace `a`.
  assert.equal(tagNamespace("a:b:c"), "a");
  assert.equal(tagBaseName("a:b:c"), "b:c");
  // A leading colon names no namespace: `:o` is a plain name.
  assert.equal(tagNamespace(":foo"), "");
  assert.equal(tagBaseName(":foo"), ":foo");
  assert.equal(tagNamespace(":o"), "");
});

test("case is preserved, so two spellings stay two namespaces", () => {
  // Folding them together would be this module deciding something the names
  // do not say.
  assert.equal(tagNamespace("Costume:a"), "Costume");
  assert.equal(tagNamespace("costume:b"), "costume");
});

test("link tags take the same rules, plus lowercase", () => {
  assert.equal(sanitizeLinkTagInput("Costume:Tiger"), "costume:tiger");
  // A leading colon is kept, like every other; the first one is still
  // where `tagNamespace` would split — and it names no namespace.
  assert.equal(sanitizeLinkTagInput(":A B:C"), ":a_b:c");
});

test("a tag FIELD lowercases as well, typing and committing", () => {
  // Every tag the app creates from a typed name is lowercase; two spellings of
  // one word are two rows nobody meant to make.
  assert.equal(tagFieldInput("White Shirt"), "white_shirt");
  assert.equal(tagFieldInput("Costume:"), "costume:");   // still typing
  assert.equal(tagFieldName("Costume:"), "costume:");    // committed, colon and all
  assert.equal(tagFieldName("D:"), "d:");                // the emoticon tag
  assert.equal(tagFieldName("  A:B:C  "), "a:b:c");
  assert.equal(tagFieldName(":Leading"), ":leading");   // a leading colon is a name
});

test("lowercase is the FIELD's rule, not the name rule", () => {
  // `normalizeTagName` mirrors the backend, which accepts mixed case — an
  // import or an older library can hold it, and the API must not refuse it.
  assert.equal(normalizeTagName("Costume:Tiger"), "Costume:Tiger");
  assert.equal(tagFieldName("Costume:Tiger"), "costume:tiger");
});

test("meta tags are the same field rule, not a second one", () => {
  assert.equal(sanitizeLinkTagInput("A B:C"), tagFieldInput("A B:C"));
});

test("a field's commit is a fixed point of its keystroke rule", () => {
  // What the field showed is what it sends: committing what the keystroke
  // rule produced changes nothing but the trim, so a name can never be one
  // thing on screen and another on the wire.
  for (const s of ["Costume: Hat", "  :d ", "a  b:c", "D:", "héllo wörld", ""]) {
    const shown = tagFieldInput(s);
    assert.equal(tagFieldName(shown), shown.trim());
  }
});
