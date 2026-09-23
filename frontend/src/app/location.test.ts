// The URL <-> place mapping. Pure string work, so it is testable directly;
// `readPlace` reads window.location, which the tests stand in for.
import test from "node:test";
import assert from "node:assert/strict";
import { catFromScope, placeUrl, readPlace, samePlace, scopeFromPlace, type Place } from "./location.ts";

const place = (p: Partial<Place> = {}): Place => ({
  view: "library", overlay: null, settingsPage: "general",
  groupEditId: null, trainJobUid: null, tagsMode: "items", tagsPage: "tags",
  tagSetId: null,
  libCat: null, libKinds: "", search: "",
  itemIds: [], itemMode: "annotate", itemTab: null, ...p,
});

function at(url: string) {
  const u = new URL(url, "http://x");
  (globalThis as { window?: unknown }).window = {
    location: { pathname: u.pathname, search: u.search },
  };
  return readPlace();
}

test("each view is its own path", () => {
  assert.equal(placeUrl(place()), "/library");
  assert.equal(placeUrl(place({ view: "train" })), "/train");
  assert.equal(placeUrl(place({ view: "models" })), "/models");
});

test("the settings overlay travels with the page it is showing", () => {
  assert.equal(placeUrl(place({ view: "train", overlay: "settings",
                                settingsPage: "actions" })),
               "/train?settings=actions");
  const p = at("/train?settings=actions");
  assert.equal(p.view, "train");
  assert.equal(p.overlay, "settings");
  assert.equal(p.settingsPage, "actions");
});

test("a place round-trips through its URL", () => {
  for (const p of [place({ view: "tags" }),
                   place({ view: "train", trainJobUid: "abc123" }),
                   place({ overlay: "group", groupEditId: 7 }),
                   place({ view: "history", overlay: "settings" })]) {
    assert.ok(samePlace(at(placeUrl(p)), p), placeUrl(p));
  }
});

test("parameters that do not apply to the view are dropped", () => {
  // A selected job is a state of the Train tab; carrying it elsewhere would
  // leave stale state in the address bar.
  assert.equal(placeUrl(place({ view: "tags", trainJobUid: "abc" })), "/tags");
});

test("the open tag set rides the Sets sub-tab as ?set=, and nowhere else", () => {
  assert.equal(placeUrl(place({ view: "tags", tagsMode: "tagsets", tagSetId: 7 })),
               "/tags/tagsets?set=7");
  assert.equal(placeUrl(place({ view: "tags", tagsMode: "items", tagSetId: 7 })), "/tags");
  at("/tags/tagsets?set=7");
  assert.equal(readPlace().tagSetId, 7);
  at("/tags/tagsets?set=nope");
  assert.equal(readPlace().tagSetId, null);
});

test("the import overlay is not a place — a reload cannot restore its queue", () => {
  assert.equal(placeUrl(place({ overlay: "import" })), "/library");
});

test("an unknown path is the library, not a blank page", () => {
  assert.equal(at("/nonsense").view, "library");
  // The bare root still resolves (a bookmark, a hand-typed host); the app
  // rewrites it to the canonical /library on load.
  assert.equal(at("/").view, "library");
  assert.equal(at("/library").view, "library");
});

test("the library category, media filter and search live in the URL", () => {
  assert.equal(placeUrl(place({ libCat: "g5" })), "/library?cat=g5");
  assert.equal(placeUrl(place({ libKinds: "image,video" })), "/library?kinds=image%2Cvideo");
  assert.equal(placeUrl(place({ search: "cat" })), "/library?q=cat");
  // …but not on other views.
  assert.equal(placeUrl(place({ view: "tags", libCat: "g5", search: "cat" })), "/tags");
});

test("library category + search round-trip through the URL", () => {
  for (const p of [
    place({ libCat: "g5" }),
    place({ libCat: "untagged", search: "dog -cat" }),
    place({ libCat: "hidden" }),
    place({ libCat: "pending-tags" }),
    place({ libCat: "seq3", libKinds: "image" }),
  ]) {
    assert.ok(samePlace(at(placeUrl(p)), p), placeUrl(p));
  }
});

test("catFromScope and scopeFromPlace are inverse for each category", () => {
  const cases = ["g5", "g5,9,12", "ungrouped", "untagged", "trash", "hidden", "pending", "pending-tags", "pending-captions", "seq3", "rank7", "rank7.2", null];
  for (const cat of cases) {
    const scope = scopeFromPlace(place({ libCat: cat }));
    assert.equal(catFromScope(scope), cat, `category ${cat}`);
  }
});

test("SEVERAL selected groups all reach the URL", () => {
  // One of them did, which reloaded into a narrower view than the address was
  // copied from.
  assert.equal(catFromScope({
    selectedGroups: [5, 9, 12], ungrouped: false, untagged: false,
    trashView: false, hiddenView: false, pendingView: false, pendingKind: null,
    sequenceView: null, rankingView: null, rankingPool: null,
  }), "g5,9,12");
  assert.deepEqual(scopeFromPlace(place({ libCat: "g5,9,12" })).selectedGroups,
                   [5, 9, 12]);
  // Junk in the list is dropped rather than becoming a group id of NaN.
  assert.deepEqual(scopeFromPlace(place({ libCat: "g5,,x,9" })).selectedGroups,
                   [5, 9]);
});

test("the bare root and the canonical library path mean the same place", () => {
  assert.ok(samePlace(at("/"), at("/library")));
});

// ---- the item window, which is an overlay and so a parameter ------------

test("the item window rides on the view it is over, not instead of it", () => {
  // A path would have thrown the library's own state away, and closing the
  // window would land you somewhere you had never been.
  assert.equal(
    placeUrl(place({ libCat: "g2", search: "page", itemIds: [5], itemMode: "edit" })),
    "/library?item=5&mode=edit&cat=g2&q=page");
  assert.equal(placeUrl(place({ view: "tags", tagsMode: "subjects", itemIds: [7] })),
               "/tags/subjects?item=7&mode=annotate");
});

test("the active tab is named only when it is not the first", () => {
  assert.equal(placeUrl(place({ itemIds: [5, 9], itemMode: "edit", itemTab: 5 })),
               "/library?item=5%2C9&mode=edit");
  assert.equal(placeUrl(place({ itemIds: [5, 9], itemMode: "edit", itemTab: 9 })),
               "/library?item=5%2C9&mode=edit&tab=9");
});

test("an item window round-trips, library state and all", () => {
  for (const p of [
    place({ itemIds: [5], itemMode: "edit" }),
    place({ itemIds: [5, 9], itemMode: "annotate", itemTab: 9 }),
    place({ libCat: "g2,3", search: "cat", itemIds: [4], itemMode: "annotate" }),
  ]) {
    assert.ok(samePlace(at(placeUrl(p)), p), placeUrl(p));
  }
});

test("an unknown settings page name falls back rather than breaking", () => {
  assert.equal(at("/train?settings=models").settingsPage, "general");
  assert.equal(at("/library?settings=nonsense").settingsPage, "general");
});

test("no item in the address means no item window", () => {
  assert.deepEqual(at("/library?cat=g2").itemIds, []);
  assert.equal(at("/library").itemTab, null);
  // A `tab` naming an id the window does not hold is ignored.
  assert.equal(at("/library?item=5&tab=77").itemTab, null);
});

test("a ranking view rides the URL, with or without its pool", () => {
  // `rank7` is every pool the ranking holds — which is what one pool
  // always meant — and `rank7.2` is one of them.
  const all = scopeFromPlace(place({ libCat: "rank7" }));
  assert.equal(all.rankingView, 7);
  assert.equal(all.rankingPool, null);
  const one = scopeFromPlace(place({ libCat: "rank7.2" }));
  assert.equal(one.rankingView, 7);
  assert.equal(one.rankingPool, 2);
  // Junk is not a ranking id of NaN: it falls back to All Items, the way an
  // unknown path falls back to the library.
  assert.equal(scopeFromPlace(place({ libCat: "rankx" })).rankingView, null);
});

test("Faces is a page of the Tags tab, and its old address is not kept", () => {
  assert.equal(placeUrl(place({ view: "tags", tagsPage: "faces" })), "/tags/faces");
  // The list mode it was on is not in the address while Faces shows…
  assert.equal(placeUrl(place({ view: "tags", tagsPage: "faces",
                                tagsMode: "tagsets", tagSetId: 7 })), "/tags/faces");
  const p = at("/tags/faces");
  assert.equal(p.view, "tags");
  assert.equal(p.tagsPage, "faces");
  assert.equal(at("/tags").tagsPage, "tags");
  // …and `/faces` is an unknown view like any other.
  assert.equal(at("/faces").view, "library");
});

