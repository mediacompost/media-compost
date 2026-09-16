# Search

Media Compost finds items with a predicate-based query builder: a search bar holding a compact query string, backed by a visual builder of condition rows.

## The search bar and the visual builder

The search sits above the item grid as a macOS-Finder-style predicate builder. A search bar (with a live "N items" count at the right end of the breadcrumb row above it) holds the query as a compact string; clicking the chevron expands a **visual builder** of nested, in-place-editable condition rows below it.

The two are **two-way bound**: typing in the bar rebuilds the rows, and editing a row rewrites the bar (which normalizes to a canonical form on blur). While a query is set, the field is outlined in the accent color, so an empty grid never reads as an empty library.

There is **no free-text search**: every condition targets tags, links, captions, or metadata.

## Condition kinds

Each condition row is one kind, switched by a dropdown — Tag, Tag value, Group, Subject, Place, Event, Taken, Colours like, Link, Caption, Instruction, Metadata:

### Tag

A **has / has-not** choice plus a small square toggle for **positive / negative** assignment (green / red), and a tag-name autocomplete (a closed list, with usage counts). The four combinations map to these string forms:

| Form | Meaning |
|---|---|
| `tag` | Has the tag (positively assigned or inherited). |
| `!tag` | Does not have the tag. |
| `-tag` | The tag is assigned **negatively** (an explicit removal of an inherited tag) — distinct from `!tag`. |
| `!-tag` | Does not have a negative assignment of the tag. |

The same row also asks about a tag by what the **tag set** says about it
rather than by its name — **has meta / has not meta**, narrowed by the same
meta-tag capsules the Link and Caption rows use (green = the tag must carry it,
red = it must not). `TAG:noflip` finds every picture carrying a tag somebody
marked `noflip`; `TAG:noflip,!draft` narrows that to tags marked `noflip` and
not `draft`. The test is per TAG, so a picture whose `hair` is marked `noflip`
matches whatever its other tags are marked. See
[meta tags on a tag](tags.md#meta-tags).

### Tag value

Listed right under Tag, because it asks about the item's tags too — read as **numbers**. Any tag whose name after the namespace is a number with an optional unit is a value tag: `people:3`, `height:172cm`, `height:1.72m`, `quality:7`. The row takes a **namespace** (its autocomplete lists the namespaces that hold value tags), an operator (`≥ ≤ > < = ≠`) and a number with an optional unit, and matches an item carrying *any* effective positive tag in that namespace whose value satisfies it:

- `VALUE:height>=1.70m` — metric lengths and masses convert (`172cm` is read as `1.72m`); an unknown unit compares only against tags in the same unit, and a number typed **without** a unit compares every value as written, so a namespace tagged consistently in one unit searches without the unit spelled out.
- `VALUE:quality>=7` — the tags a [ranking](rankings.md)'s **Assign ratings** writes are value tags like any other.
- `=` and `≠` are precision-aware, like a metadata comparison (`VALUE:height=1.70m` is a window in the unit you typed). `!VALUE:…` negates.

Training reads the same convention: a [value rule](training.md) turns `height:172cm` into prompt text.

### Group

A **has / has not / has directly / has not directly** choice plus a group autocomplete. Matches by the group's **path** from the root, case-insensitively: a name is unique within a LEVEL but not across the tree, so the whole path is what names one.

- **has** — the item is in that group **or in any group under it**, exactly what selecting the group in the sidebar shows: `GROUP:Name` / `!GROUP:Name`.
- **has directly** — the item is filed in that group *itself*, not in one of its child groups: `GROUPONLY:Name` / `!GROUPONLY:Name`.

**The value is the group's full path**: `GROUP:Trips/2024` is the *2024* inside *Trips*, `GROUP:Work/2024` the other one, and a bare `GROUP:2024` is a *2024* at the root — never the ones deeper down. (A bare name used to mean every group carrying it, and a path only had to match the end of a group's own; a group beside a same-named one inside another folder then answered for both.)

The **autocomplete lists the tree**: rows in the sidebar's own order, each showing its ancestors, and picking one fills in its full path. There is no escape syntax for a `/` inside a name — a root group actually called `a/b` still matches `GROUP:a/b`, because the whole value is tried against the path as well.

Quote the whole term when the name has spaces: `"GROUP:My Folder"`.

### Link

A direction — **has link / has no link / is linked / is not linked** (outgoing vs. incoming relationships) — plus a set of **meta tags** shown as capsules, each with an include/exclude toggle (green = the relationship must carry it, red = it must not). String forms: `LINK:` / `LINKEDBY:` with a comma list of tags, a `!`-prefixed tag excluded — for example `LINK:crop,!edit`.

### Caption

**Has caption / has no caption**, optionally narrowed by the same meta-tag capsules (green = a caption must carry it, red = it must not). With no tags it simply asks whether the item is captioned at all. Text forms: `CAPTION:`, `CAPTION:alt_text,!draft`, `!CAPTION:alt_text`.

### Instruction

Exactly the same row, asked of the item's [instructions](item-properties.md) instead — the captions that say how the picture was made from others. **Has instruction / has no instruction**, narrowed by the same meta tags: `INSTRUCTION:`, `INSTRUCTION:edit,!draft`, `!INSTRUCTION:`.

The two never overlap: an item with only instructions is not "captioned", and one with only captions has no instruction — so the pair is how you find the pictures that still need one. How many of each an item has is `INFO:caption_count` and `INFO:instruction_count`.

### Metadata

A name from the **metadata catalog** (an autocomplete of every filterable name), a **typed operator**, and a value. The catalog covers intrinsic properties — type (image/video/sequence), format (PNG/JPEG/…), the item's id (`INFO:id=<uid>` finds exactly that item, and `~` matches any part of the uid), width, height, resolution, aspect, length, fps, bitrate, import date, last import date, the live `tag_count`, `caption_count` and `instruction_count`, the detected-face counts `faces` and `unnamed_faces` (a dismissed face counts as neither), `text_blocks` (detected text blocks), `sequence_count` (how many distinct sequences the item is a member of) and `file_count` (how many source files it holds — 1 for an ordinary picture, more once a near-duplicate or an editor save has been folded in) — plus the pixel mode (RGB/RGBA/L/…, indexed for every image), a video's codec, audio codec and channels, the location line a file names (`location`) and its GPS pair (`gps_lat`, `gps_lon`), and indexed EXIF such as camera make/model, lens, ISO, aperture, exposure time, focal length, flash, white balance, orientation and capture date. Only names with a stored value somewhere in the library are offered.

Every name searches for what the item's Info section displays: values belonging to the **active file** (format, mode, EXIF) follow it when the item is edited, rotated, or switched to another source — a JPEG edited into a transparent PNG stops matching `INFO:format=JPEG` and starts matching `INFO:format=PNG` and `INFO:mode=RGBA`.

- **Numeric names** offer `≥ ≤ > < = ≠`. **Date names** offer *is on* / *is on or before* / *is on or after* in the builder (the query string additionally parses `>`, `<` and `≠` for dates).
- **Text names** offer is / is not / contains / doesn't contain. The value is a free-text field with autocomplete — names with known values suggest them, but any value can be typed.
- A name that supports several types shows a small type pill to switch.

**Numeric `=` and `≠` match at the precision you typed** — a value written with few decimals means "about that much":

| Query | Matches |
|---|---|
| `INFO:resolution=0.7` | 0.65 up to (but not including) 0.75 |
| `INFO:resolution=0.75` | 0.745 – 0.755 |
| `INFO:width=800` | 799.5 – 800.5 |

The window is always half of the last decimal place given, closed at the bottom and open at the top, so a value exactly on the boundary belongs to the higher bucket — like ordinary rounding. The ordered operators (`≥ ≤ > <`) stay exact.

**Dates match at whatever precision you give**: `INFO:import_date=2026-07-12` (or `20260712`) matches the whole day, `2026-07` a whole month, `2026` a year, and `2026-07-12T22:12:16` that exact second; the separators (`-`, `T`, `:`) are optional. The ordered operators compare against the near or far edge of the period — `>2026-07-12` means after that whole day. In the builder, a date value shows a day formatted per your [Language & Region settings](settings.md) with the system calendar, plus an optional time field (both `14:30` and `2:30 PM` are accepted); leave the time empty for a whole-day comparison.

### Place, Subject, and Event

Three further keywords search location, people, and event data. Their full forms live on their own pages:

- `PLACE:Shibuya` (the name of a place it is at contains that), `PLACE=Tokyo` (is exactly that), and bare `PLACE:` / `!PLACE:` for "has a location at all" / "has none". The name is the whole of what this matches: to ask for one particular place, search its **tag**, which is what the item carries. A place inside another implies it, so a broad place finds the pictures taken at the specific ones. See [Places](places.md).
- `SUBJECT:alice@1921`, `SUBJECT:alice@1910..1920` (a year or range), `SUBJECT:alice#12`, `SUBJECT:alice#10..14` (an age or range), and bare `SUBJECT:` for "has any". See [Subjects and Faces](subjects-and-faces.md).
- `EVENT:` ("was at some event at all"), `EVENT:san_diego_comic_con_2014`, and `EVENT:@2014` / `EVENT:@2014..2016`, which bound the event's own span with an overlap match. See [Events](events.md).

### Taken

`TAKEN:` asks **when the picture was taken**. It reads the first of three answers that speaks: a date somebody typed for the item, then the file's own EXIF capture date, then the span of the [events](events.md) the picture carries — so a photograph from a convention that ran 5–10 January is findable by that week even if the camera recorded nothing.

- `TAKEN:@2014` — taken in 2014; `TAKEN:@2014-01-05..2014-01-10` — a range. The match is an **overlap**, like `EVENT:` — a search for the first week of January finds a picture dated only "2020-01".
- `TAKEN:` bare — something says when it was taken.
- `!TAKEN:` — nothing says when it was taken. An item marked "It has no date" (a scanned print, say) counts here, even when its file carries a scanner date.

### Colours like

One keyword asks what a picture is *coloured* like, and it is the only
condition that names another item — likeness is between two pictures, so there
has to be one to compare against:

- `COLORLIKE:<uid>` — pictures with a similar *palette*: two unrelated
  photographs of the same blue sky are alike here.

It takes an optional tolerance — a bit distance between the two 56-bit colour
signatures. `COLORLIKE:<uid>~1` is stricter than the default, `~16` is as
loose as it goes and a larger value is refused rather than quietly answered.
Without one the default is **2**, which is measured rather than chosen: the
same picture re-encoded lands at distance 0, and 3 more than doubles the share
of unrelated pictures that come back.

You rarely type it. **Right-click one image in the grid** and pick *Find
similar colors*, and the query is written for you. It **narrows whatever you
are looking at** rather than replacing it, so asking inside a group answers
inside that group; and because it is a condition and not a sort you can edit
more onto it — `COLORLIKE:<uid> !portrait` — and save it as a search.

A video never matches: it carries no colour signature. Colour is a tool for
photographs — on line art, where nearly every page is a white page with ink on
it, palettes say very little.

There was a `SIMILAR:<uid>` beside it, over the perceptual hash the importer
deduplicates with, and it has been **removed** along with its *Find visually
similar* action. The importer folds a re-encode, a crop and a rotation onto the
item they match, so by the time pictures are in the library the visually
near-identical ones are one item — and the search reliably found that item and
nothing else. A saved search or bookmark still holding `SIMILAR:` now reads
that word as a tag name, so it finds nothing rather than something different.

## Combining conditions

Rows are combined with **groups**: the root is an implicit **All** (AND). A group header offers **All / Any / None** (AND / OR / negated-OR), and groups can nest arbitrarily deep, drawn with indentation rails. Each row and group header has a segmented **− ( ) +** control: remove, add a nested group, or add a sibling row.

## Query string grammar

The string in the search bar is the persisted form and the power-user entry point:

| Syntax | Meaning |
|---|---|
| whitespace | AND |
| `\|` | OR |
| `( … )` | Grouping |
| `!( … )` | None (negated OR) |
| `tag`, `!tag`, `-tag`, `!-tag` | Tag conditions (see above) |
| `TAG:noflip,!draft` | Carries a tag the tag set marks that way; `!`/`-` prefix as above |
| `VALUE:height>=1.70m` / `!VALUE:people=1` | Carries a tag in that namespace whose number satisfies the comparison |
| `GROUP:Name` / `!GROUP:Name` | In the group or any group under it, as the sidebar shows it (a `Parent/Name` path says which one) |
| `GROUPONLY:Name` / `!GROUPONLY:Name` | Filed in the group itself, not in a child group |
| `LINK:crop,!edit` / `LINKEDBY:…` | Outgoing / incoming links, with included and `!`-excluded meta tags |
| `CAPTION:alt_text,!draft` | Caption conditions |
| `INSTRUCTION:edit` | The same, over the item's instructions |
| `INFO:name op value` | Metadata, e.g. `INFO:width>=800`, `INFO:camera_make~canon` (quote when the value contains spaces) |
| `PLACE:` / `SUBJECT:` / `EVENT:` | See [Places](places.md), [Subjects and Faces](subjects-and-faces.md), [Events](events.md) |
| `TAKEN:@2014` / `TAKEN:` / `!TAKEN:` | When the picture was taken (typed date, else EXIF, else event span; overlap match) |
| `COLORLIKE:<uid>` / `COLORLIKE:<uid>~6` | Has a similar palette to that picture, optionally within a bit distance |

Two rules to know:

- **Keywords are UPPERCASE, and only uppercase.** `INFO:`, `TAG:`, `VALUE:`, `GROUP:`, `GROUPONLY:`, `PLACE:`, `SUBJECT:`, `EVENT:`, `TAKEN:`, `CAPTION:`, `INSTRUCTION:`, `LINK:`, `LINKEDBY:`, `COLORLIKE:` are matched case-sensitively — anything in lower or mixed case is a tag name, always. That is what lets a tag be called `place:berlin` (the default namespace the [Tagging settings](settings.md) give app-invented tags).
- **A backslash escapes** the characters the grammar owns, so a tag name may contain them: `CAPTION:test\,tag,abc` asks for the two tags "test,tag" and "abc", and `\!test` is the tag literally named "!test" rather than "not test". The same escaping applies to item tags, link tags, and group names, and the query bar writes it back that way.

The same grammar is what the [Python API](python-api.md) takes, so a query you
worked out in the search bar can be pasted straight into a script:

```python
lib.query("portrait !lowres INFO:width>=800")
```

`POST /api/query/parse` and `POST /api/query/serialize` convert between a
string and the condition tree for callers that are neither — the CLI, or a
client in another language.

## Saved searches

The magnifier menu at the left of the search bar opens a popover to apply, rename (inline, in the row), delete, or **save the current** query. Saved searches persist with the library and are kept **per user** when the library is shared by several people (see [Multi-user access](installation.md#multi-user-access)).
