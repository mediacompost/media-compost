import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildImportCommand, commandRoots, shellQuote, type ImportCommandOpts,
} from "./importCommand.ts";

const BASE: ImportCommandOpts = {
  rels: ["photos/a.png", "photos/b.png"],
  foldersAsGroups: true,
  // The CLI's own defaults, so BASE produces a command with nothing in it.
  archivesAsGroups: false,
  archiveSequences: false,
  minMegapixels: 0,
  minShortEdge: 0,
  minLongEdge: 0,
  ignoreKinds: [],
  sequenceGrouping: "both",
  tags: [],
  tagsImage: [],
  tagsVideo: [],
  tagsSequence: [],
  tagsExisting: true,
};

test("the default settings are the command with nothing added", () => {
  assert.deepEqual(buildImportCommand(BASE),
                   { command: "media-compost import",
                     paths: ["/path/to/photos"] });
});

test("the placeholders are LAST and are not part of the copyable command", () => {
  // They are the one part of this line nobody can fill in from here — a
  // browser is never told where a dropped file came from — so they are shown
  // apart and left out of the clipboard rather than pasted in as a path that
  // quietly does the wrong thing.
  const { command, paths } = buildImportCommand({
    ...BASE, dataDir: "/srv/library", tags: ["batch1"] });
  assert.equal(command,
               "media-compost import --data-dir /srv/library --tag=batch1");
  assert.deepEqual(paths, ["/path/to/photos"]);
  assert.ok(!command.includes("/path/to/"));
});

test("only what differs from the CLI's own defaults is spelled out", () => {
  const { command } = buildImportCommand({
    ...BASE, dataDir: "/srv/library", parentGroup: "Scans",
    foldersAsGroups: false, archivesAsGroups: true, archiveSequences: true,
    minMegapixels: 1.5, minShortEdge: 400, ignoreKinds: ["video", "archive"],
    sequenceGrouping: "container",
  });
  assert.equal(command,
    "media-compost import --data-dir /srv/library -g Scans "
    + "--no-folders-as-groups --archives-as-groups --archive-sequences "
    + "--min-resolution 1.5 --min-short-edge 400 --ignore-kinds video,archive "
    + "--sequence-grouping container");
  // A default that IS the default never appears — a flag in the line has to
  // mean something, or nobody reads any of them.
  assert.ok(!command.includes("--min-long-edge"));
  assert.ok(!buildImportCommand(BASE).command.includes("--sequence-grouping"));
  // Archives-as-groups is OFF by default now, so ON is what gets spelled out.
  assert.ok(!buildImportCommand(BASE).command.includes("archives-as-groups"));
});

test("an ambiguous parent group travels as its id, not its name", () => {
  // `Group.name` is indexed and NOT unique — a library can hold "abc" inside
  // "abc" — so a name is not an identity and `-g abc` cannot say which.
  const named = buildImportCommand({ ...BASE, parentGroup: "abc",
                                     parentGroupId: 7 });
  assert.ok(named.command.includes("-g abc"));
  const byId = buildImportCommand({ ...BASE, parentGroup: "abc",
                                    parentGroupId: 7, parentAmbiguous: true });
  assert.ok(byId.command.includes("--parent-group-id 7"));
  assert.ok(!byId.command.includes("-g abc"));
  // With no id to fall back on the name is still better than nothing.
  const noId = buildImportCommand({ ...BASE, parentGroup: "abc",
                                    parentAmbiguous: true });
  assert.ok(noId.command.includes("-g abc"));
});

test("a negative tag keeps its sign, which needs the `=` form", () => {
  const { command } = buildImportCommand({
    ...BASE, tags: ["batch1", "-blurry"], tagsImage: ["scan"],
    tagsExisting: false });
  // `--tag -blurry` is an OPTION to argparse; `--tag=-blurry` is a value.
  assert.ok(command.includes("--tag=batch1"));
  assert.ok(command.includes("--tag=-blurry"));
  assert.ok(!command.includes("--tag -blurry"));
  assert.ok(command.includes("--tag-image=scan"));
  assert.ok(command.includes("--no-tag-existing"));
});

test("a path with a space is quoted, and a plain word is left alone", () => {
  assert.equal(shellQuote("/srv/my library"), "'/srv/my library'");
  assert.equal(shellQuote("plain"), "plain");
  // Close, escape, reopen — the one form every POSIX shell reads.
  assert.equal(shellQuote("it's"), String.raw`'it'\''s'`);
  assert.equal(
    buildImportCommand({ ...BASE, dataDir: "/srv/my library" }).command,
    "media-compost import --data-dir '/srv/my library'");
});

test("a dropped folder's own name is escaped, whatever is in it", () => {
  // The placeholders are shown rather than copied, but they are still part
  // of a command somebody finishes by hand — a name with a space, a quote or
  // a shell metacharacter in it has to be quoted or the line means something
  // else entirely.
  const { paths } = buildImportCommand({
    ...BASE, rels: ["holiday 2024/a.png", "chapter:one/b.png",
                    "it's mine/c.png", "a$b;rm/d.png"] });
  assert.deepEqual(paths, [
    "'/path/to/holiday 2024'",
    // A colon is one word to every POSIX shell, so quoting it would only
    // make the line noisier.
    "/path/to/chapter:one",
    String.raw`'/path/to/it'\''s mine'`,
    "'/path/to/a$b;rm'",
  ]);
  // A tag or a group name with a space is quoted for the same reason.
  const { command } = buildImportCommand({
    ...BASE, parentGroup: "Old scans", tags: ["holiday 2024"] });
  assert.ok(command.includes("-g 'Old scans'"));
  assert.ok(command.includes("--tag='holiday 2024'"));
});

test("the roots are what was dropped, once each and in order", () => {
  assert.deepEqual(
    commandRoots(["a/1.png", "b/1.png", "a/2.png", "loose.png"]),
    ["/path/to/a", "/path/to/b", "/path/to/loose.png"]);
});

test("too many roots become one placeholder rather than an unreadable line", () => {
  const many = Array.from({ length: 20 }, (_, i) => `f${i}/x.png`);
  assert.deepEqual(commandRoots(many), ["/path/to/folder"]);
  // And nothing dropped at all still produces a runnable shape.
  assert.deepEqual(commandRoots([]), ["/path/to/folder"]);
});
