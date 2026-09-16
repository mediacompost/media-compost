# Python API

The library is a Python package as well as a web app. Everything the UI can
read or edit, a script can read or edit — items, files, tags, groups, subjects,
faces, detected text, places, events, captions, sequences, links, history —
plus importing and the paths of the files on disk.

This page is the **guide** — what to reach for, in the order you need it, with
every example on it having been run. For the exhaustive list of every class,
method and property, see the [API reference](api/index.md), which is generated
from the source each time this site is built and so cannot fall behind it.

The `media_compost` package is installed in the backend virtual environment
(see [Installation](installation.md)), so run your scripts with that
interpreter:

```bash
.venv/bin/python my_script.py
```

## Opening a library

`open_library(data_dir)` opens the library at a path (defaulting to `./_data`)
and returns a `Library` you can use as a context manager:

```python
from media_compost import open_library

with open_library("/path/to/library") as lib:
    for item in lib.query("portrait"):
        print(item.uid, item.name, item.path)
```

Outside a `with` block, call `lib.close()` when you are done.

| Argument | Meaning |
| --- | --- |
| `data_dir` | The library folder. Defaults to `MEDIA_COMPOST_DATA` if set, else `./_data` — same as the server |
| `mode` | `"r+"` (default) or `"r"`. In `"r"` every mutator raises `ReadOnlyError` before touching the database |
| `user` | Recorded as the author of every change, so scripted edits are attributed in the [History](history.md) view instead of being anonymous |
| `source` | The History badge: `"cli"` by default, so scripted changes are distinguishable from the app's |
| `busy_timeout` | Seconds to wait for a database lock. Default 30 |

### Running next to the server

Opening with `mode="r"` is safe at any time. Writing while the server is
running is *allowed* — the database is in WAL mode with a busy timeout, so
writers queue rather than fail; every write call additionally holds the
library's cross-process write lease for its own commit, and a transient
`database is locked` (the one collision the busy timeout cannot cover: a
read-then-write whose snapshot another process's commit just invalidated) is
retried on a fresh snapshot automatically — by the single-call writes and by
the importer per file. But there is no row versioning anywhere in the
schema, so simultaneous edits to one field are last-write-wins. The app will
not see your changes until it refetches.

Writing to a library while a **training run** is using it is fine; deleting the
files it is reading is not.

The API talks to the database directly, never over HTTP, so the browser's
build check does not apply to it — a script is never refused for being "out of
date". Nothing pins a script to a version of the app, which is the other side
of the same coin: re-read this page after an update.

## Changes commit as you make them

Every call that changes something commits it:

```python
item.tags.add("portrait")        # written and committed
```

To batch, open a transaction. Everything inside it commits once at the end, and
an exception rolls the whole block back:

```python
with lib.transaction():
    for item in lib.query("INFO:width<800"):
        item.tags.add("lowres")
        item.hide()
```

Transactions nest — an inner `with lib.transaction():` joins the outer one
rather than committing early — so a helper that opens one still batches
correctly when called from inside a larger block. The exceptions are the
importer and the maintenance sweeps (`import_file`, `import_folder`, an
`importing()` run, `reindex_metadata`): those commit as they go — an import's
periodic commit is what keeps its write lease short — so run them outside a
transaction block whose rollback you might want.

Prefer a transaction for anything touching more than a few items: it is one
commit — and one held write lease — instead of thousands. (The log still
records one event per item; per-item events are what make each change
revertible. The History *view* folds a consecutive run of the same action
into a single row.) Bulk methods do this for you (see
[Bulk edits](#bulk-edits)).

## Querying

`lib.query()` returns an `ItemSet`: lazy, re-iterable, and composable. It
yields every non-trashed, non-hidden item unless you narrow it (pass
`show_hidden=True` to include the hidden ones).

### Query strings

The primary spelling is the same string the app's [search field](search.md)
takes:

```python
lib.query("portrait INFO:width>=800")
lib.query("SUBJECT:alice GROUP:Japan")
lib.query("!blurry (cat|dog)")
```

The grammar is the search field's, not SQL's — a **space** is AND, `|` is OR,
`!` negates, and keywords are **uppercase** (`INFO:`, `TAG:`, `GROUP:`,
`GROUPONLY:`, `SUBJECT:`, `PLACE:`, `EVENT:`, `CAPTION:`, `INSTRUCTION:`,
`LINK:`, `LINKEDBY:`, `TAKEN:`, `VALUE:`, `COLORLIKE:`). A bare lowercase
word is a tag name, so `width>=600` is a tag called `width>=600` and the
metadata comparison is `INFO:width>=600`. See
[Search](search.md#query-string-grammar) for the full grammar.

An unparseable string raises `QueryStringError` (a `ValueError`, from
`media_compost.querystring`). `parse_query(s)` and `serialize_query(tree)` are
exported if you want the tree itself.

### Condition objects

A query string is parsed into a tree of Pydantic condition models, and those
models are exported — so a query can be assembled instead of written. That is
worth doing when the values come from variables, because a value holding a
comma, a colon or a leading `!` has to be escaped to survive the string
grammar:

```python
from media_compost import QueryGroup, MetaCond, TagCond

lib.query(TagCond(name="portrait"))                    # one condition
lib.query([TagCond(name="portrait"), TagCond(name="cat")])   # a list is AND
lib.query(QueryGroup(op="or", children=[
    TagCond(name="cat"), TagCond(name="dog"),
]))
lib.query(QueryGroup(op="and", neg=True, children=[TagCond(name="lowres")]))
```

`QueryGroup` is `media_compost.query.Group`, renamed on export so it does not
collide with the tag-`Group` handle. `op` is `"and"` or `"or"`, `neg=True`
negates the whole group, and groups nest.

| Model | Matches |
| --- | --- |
| `TagCond(name, sign="pos", have=True, meta_tags=[])` | A tag, including tags implied by it and grants inherited from groups. With `meta_tags`, the condition stops asking about `name` and matches a tag by what the tag set marks it with — the `TAG:noflip` search |
| `MetaCond(name, mtype, op, value, tol=0.0)` | A metadata value. Numeric/date operators `>` `>=` `<` `<=` `=` `!=`; text `=` `!=` `~` (contains) `!~`. `tol` is the half-width a numeric `=`/`!=` accepts |
| `GroupCond(name, mode)` | Group membership by path, case-insensitively. `mode` is `has`/`hasnot` (in the group or any group under it, what the sidebar shows), or `only`/`notonly` (filed in the group itself) |
| `CaptionCond(mode, caption_kind="caption", caption_tags=[])` | Captions, or — with `caption_kind="instruction"` — instructions. Never both: one never matches the other |
| `LinkCond(direction, link_tags=[])` | Outgoing or incoming [links](item-properties.md), optionally narrowed by meta tags |
| `SubjectCond(name, have=True, date_from/date_to, age_from/age_to)` | A [subject](subjects-and-faces.md), optionally bounded by the assignment's date or their age in the picture |
| `PlaceCond(op, value, have=True)` | A [place](places.md), matched over the name of the item's places |
| `EventCond(name, have=True, date_from/date_to)` | An [event](events.md); the bound is on the event's own span and matches by overlap |
| `TakenCond(have=True, date_from/date_to)` | When the picture was taken, as a window overlap. Its bounds are the wider `YYYYMMDDHHMMSS` form the metadata index stores dates in — zeros again for what is unknown |
| `SimilarCond(uid, by="color", tol=None)` | Shares that item's palette (the `COLORLIKE:` search; `by` takes only `"color"`); `tol` is the bit distance between the two 56-bit colour signatures, defaulting to 2 |
| `ValueCond(name, op, value, unit="", have=True, tol=None)` | Carries a tag in the `name` namespace whose number satisfies the comparison (the `VALUE:` search; `tag_value_matches` is the rule) |

Subject and event dates are the app's partial form — `YYYYMMDD` with zeros
for what is unknown, so `19750000` is the whole of 1975. A `None` bound is
unbounded.

**A keyword none of them declares is an error, not a shrug.** `TagCond(name=…,
sign=…)` raises on a misspelled argument rather than dropping it, and the same
holds for a tree arriving as JSON over the API. A condition that quietly
ignores what you asked for answers a different question with no way to tell:
a group given `nodes` instead of `children` is an EMPTY group, and an empty
group matches the whole library.

`parse_query(s)` returns exactly these objects, which is the quickest way to
find the spelling of one: parse the string the search bar gave you and look at
what comes back. `serialize_query(tree)` goes the other way.

Conditions mean exactly what they mean in the app's search: tag matching
includes implied tags and group grants, subject and place conditions read the
same data, and group conditions use the same subtree semantics.

### Scope

Keyword arguments narrow what is searched, matching the app's own scopes:

```python
lib.query("portrait", groups=[lib.groups["Trips/Japan"]], kind="image",
          sort="name")
lib.trash                     # the trashed items
lib.hidden                    # the hidden ones
lib.pending                   # items with a machine's guess still waiting
```

| Argument | Meaning |
| --- | --- |
| `groups` | Only items in these groups (a `Group` handle or id, or a list of them), including subgroups |
| `ungrouped`, `untagged` | Only items in no group / with no tags |
| `trash`, `hidden`, `show_hidden` | Which lifecycle state to list |
| `kind` | `"image"`, `"video"` or `"sequence"` |
| `sequence`, `hide_sequenced` | Only a sequence's members / drop items that are in one |
| `pending`, `pending_kind` | Items awaiting review; `pending_kind` is `"tags"`, `"captions"` or `"faces"` |
| `sort` | `"recent"` (default), `"name"`, `"first"`, `"modified"`, `"resolution"`, `"taken"`, `"random"`, … as in the app |

### Working with the result

```python
q = lib.query("portrait")

len(q)                       # a COUNT where the query compiles to SQL whole;
                             # a condition with a residue evaluates the ids
bool(q)                      # is anything there (resolves the matching ids)
q.first()                    # the first item, or None
q.one()                      # exactly one, or an error
q.ids(); q.uids()            # lists; q.paths() is a generator
list(q[:20])                 # a slice of the matching ids

q.filter("cat")              # narrow further, returns a new ItemSet
q.exclude("blurry")
q.order_by("name")
for chunk in q.batches(500): ...
```

Iteration hydrates in windows: the matching *ids* are resolved up front, but
the item objects are built a window at a time, so walking a 50,000-item
library never holds 50,000 hydrated items.

### Prefetching

Reading a relation on an item loads it for that item. Over a long loop that is
one query per item per relation. `prefetch` bulk-loads them per window instead:

```python
for item in lib.query("portrait").prefetch("tags", "files", "subjects"):
    print(item.path, sorted(item.effective_tags))
```

Keys: `files`, `tags`, `captions`, `subjects`, `faces`, `text`, or `all`.
The default is `("files",)`, since `item.path` is what most scripts reach
for.

### Reading a whole result at once

Two things are shaped so awkwardly per item — a four-way join each, and for
tag groups four of them — that asking picture by picture is the difference
between a pass and an afternoon. Both answer for the entire result:

```python
result = lib.query("SUBJECT:alice")

for item_id, blocks in result.tag_groups().items():
    for block in blocks:                    # a GroupedTags each
        print(block.name, block.tags, block.meta_tags, block.subjects)

for item_id, by_tag in result.tag_boxes().items():
    for name, boxes in by_tag.items():
        print(name, [b.rect for b in boxes])
```

`tag_groups()` gives the tags in **placement order** — a group is a layout, so
the order somebody arranged is part of what it says. `tag_boxes()` gives the
boxes as STORED: geometry in the item's *reference frame*, and a range-only
box carrying a `time` and no `rect`. Map a rectangle through
`item.active_file.crop` to get the frame the stored pixels actually show.
`tag_boxes()` includes boxes of a tag whose assignment is negative — they
are keyed by name, and `item.tags` is what answers whether the tag applies;
`tag_groups()` is positive placements only.

`ungrouped_tags()` is `tag_groups()`'s companion: per item, the positive tags
placed in **no** group. It is not derivable from the groups — a tag can be
placed in one and still sit on the picture by the ungrouped route as well.

The same idea one item at a time is `item.tags.explain_all()`, which answers
`explain()` for every tag on the picture in one resolve rather than one per
name:

```python
for name, origin in item.tags.explain_all().items():
    if origin.implied_by and not origin.direct:
        print(f"{name} is only here because of {', '.join(origin.implied_by)}")
```

## Items

```python
item = lib.items["9f3c…"]       # by uid
item = lib.items[42]            # by database id
```

| Attribute | |
| --- | --- |
| `id`, `uid` | Database id; stable identity that names the on-disk folder |
| `name` ✎ | Display name |
| `kind` | `"image"`, `"video"`, `"sequence"` |
| `created_at`, `last_imported_at`, `updated_at` | |
| `hidden` ✎, `trashed` | |
| `width`, `height`, `duration` | Of the active file |
| `taken` ✎, `taken_effective`, `taken_source` | See [Dates](#dates-and-never) |
| `active_file` ✎ | Which stored file the item shows |
| `face_models` | Which detectors have already run on this item |

✎ = writable. Assigning writes and commits.

Methods: `rotate`, `hide`/`show`, `trash`/`restore`/`delete`, `merge_from`,
`add_caption`, `add_instruction`, `add_face`, `add_text`, `refresh`.

Collections: `files`, `tags`, `effective_tags`, `effective_neg_tags`,
`tag_groups`, `captions`, `instructions`, `groups`, `subjects`, `appearances`,
`faces`, `text_blocks`, `places`, `events`, `links`, `linked_by`,
`sequences`, `metadata`.

### Files on disk

There is no export step — you read the files where they are:

```python
item.path                     # Path to the active file's bytes, or None
item.paths                    # every stored file
item.image()                  # the active file as a PIL image
item.thumbnail()              # Path to the cached thumbnail
with item.open("rb") as fh: ...
```

The stored bytes are always in their final orientation, so `Image.open(item.path)`
and `item.image()` agree. (`file.rotation` records which way the bytes sit
relative to the item's first source file — it is provenance, not a transform
still to apply.)

A video offers `item.frames(fps=None, max_dim=None)`, an on-demand iterator of
`(index, timestamp_seconds, PIL.Image)` decoded straight from the file with
nothing written to the library:

```python
for index, timestamp, image in item.frames(fps=1.0, max_dim=1024):
    image.save(f"out/{item.uid}-{index:05d}.png")
```

`max_dim` caps the long side — ffmpeg downscales, never upscales, and the
aspect is kept, so a consumer that only wants a bucket-sized picture pays
neither the decode nor the scratch space of a 4K frame. A film ffmpeg cannot
read raises `MediaUnreadable`, which is its own class precisely so a walk over
a whole library can skip one broken file without catching everything.

Each stored file is a `File` handle: `path`, `image()`, `open()`, `width`,
`height`, `format`, `bytes`, `sha256`, `phash`, `frame_rate`, `rotation`,
`crop`, `is_active`, `is_derived`, `sources`, `artifacts`, plus `add_url`,
`add_source`, `split_out`, `delete`. `lib.file(id)` is the way to one from an
id you were handed rather than from its item.

### Deciding whether two pictures are the same one

`file.phash` is the perceptual hash the deduper compares, as the hex string
the library stores; `Phash.parse(file.phash)` is the comparable object. For
pixels that are *not* in the library — a frame you just sampled, a copy you
just derived — `Phash.of` gives you one of the same kind, and
`lib.phash_threshold` is the tolerance the importer itself uses, so your idea
of "the same picture" is the library's rather than a second one:

```python
from media_compost import Phash

kept = []
for _, _, frame in item.frames(fps=0.5, max_dim=768):
    h = Phash.of(frame)
    if not any(h.near(k, lib.phash_threshold) for k in kept):
        kept.append(h)
```

### Caching things you derive from a file

Anything generated from a file is a `FileArtifact` sitting in the item's own
folder — a depth map, a pose overlay, and equally a cached tensor or a
deliberately degraded copy. The name is **deterministic**, which is the whole
mechanism: the same three arguments always address the same bytes, so writing
and finding-again are the same call:

```python
f = item.active_file

art = f.find_artifact("degraded", model="jpeg-q30")
if art is None:
    art = f.add_artifact("degraded", jpeg_bytes, key="jpeg-q30", ext="jpg",
                         model="jpeg-q30", width=w, height=h)

# Something else writes the bytes — hand it the path, then index the result.
dst = f.artifact_path("latent", "sd15-512x512", "pt")
encode_into(dst)
f.record_artifact("latent", key="sd15-512x512", ext="pt", model="sd15",
                  parent=art)
```

`add_artifact` writes and records; `artifact_path` gives the absolute path
(creating the parent directory, nothing else), for a process that writes its
own bytes;
`record_artifact` then indexes what landed there, returning `None` if nothing
did and the existing handle if it is already known — so re-running over a
folder adds nothing. `parent=` nests one artifact under another, and deleting
the parent takes its children with it.

An `Artifact` reads `kind`, `model`, `rel_path`, `path`, `sha256`, `width`,
`height`, `bytes`, `format`, `stale`, `parent`, `file`, `item`, and deletes.

None of this writes history. An artifact a *model produced* is an event the
History shows; a cache is not an edit, and a materialization over a large
library would otherwise write six figures of entries saying it had warmed one.

### Pixels, without the library

Two ffmpeg operations are exported directly, because this package owns ffmpeg
discovery (a bundled binary, whatever is on `PATH`, or neither) and a second
copy of that in every consumer is exactly what the API exists to prevent:

```python
from media_compost import codec_roundtrip, encoder_available

if encoder_available("h264"):
    rough = codec_roundtrip(image, "h264", crf=32)
```

`codec_roundtrip` pushes a still through a video encoder and back, which is
how a picture is made to look like a frame grabbed off a low-bitrate stream —
the blocking comes with 4:2:0 chroma smear and the encoder's own ringing, and
no image codec reproduces that.

## Tags

Four layers, and you can stop at whichever answers your question.

```python
"portrait" in item.tags               # 1. direct positive tags — a set
item.tags.add("temple")
item.tags.remove("temple")
item.tags |= {"a", "b"}

item.tags.negative.add("blurry")      # 2. the sign

a = item.tags["portrait"]             # 3. the assignment
a.negative = True
a.boxes.add(0.1, 0.2, 0.3, 0.4)
a.pending = False

item.tag_groups["Hers"].tags.add("blue_eyes")   # 4. placements
```

`add` takes extras beyond the name: `negative=`, `group=`, `box=`, `pending=`.

`tag_groups[...]` takes a name and **gets-or-creates** — a per-item group is
a layout the item owns, and placing a tag in it is what brings it into being.
A name two groups here share raises `AmbiguousName` rather than picking one;
an int is still an id, and `.get(name)` is the read that never creates.

**What the item says gets the short name; what the library concludes gets the
long one.** `item.tags` is direct and editable; `item.effective_tags` and
`item.effective_neg_tags` are read-only frozensets including group grants and
implied tags. `item.tags.explain("dog")` answers where a tag came from —
direct, which groups granted it, what implied it, whether an override hides it.

Adding a tag mints it if it does not exist, exactly as the app's add field
does. Looking one up in the catalog does not:

```python
lib.tags["nope"]              # KeyError — a read must not write
lib.tags.create("portrait")
lib.tags.get_or_create("portrait")
```

A tag name the app would normalize differently raises `InvalidTagName` rather
than silently changing what you asked for (whitespace is what a name may not
hold: a space is refused outright, any other kind naming the form that would be
accepted). A colon is ordinary wherever it stands — `:d` and `d:` are two
tags. `normalize_tag(s)` is exported for deliberate normalization.

### The tag catalog

```python
tag = lib.tags["portrait"]
tag.comment = "head and shoulders"   # the one line shown beside the name
tag.name = "portraits"            # rename
tag.implies.add("person")         # tagging `portrait` now also means `person`
tag.alias_of = "portraits"
tag.merge_into(lib.tags["headshot"])
tag.delete()
tag.items                         # every item carrying it
tag.namespace, tag.basename       # "costume", "tiger" for `costume:tiger`
tag.subject, tag.place, tag.event # the record attached to it, if any
tag.meta_tag_counts               # pictures it has SOMEWHERE ELSE, per
                                  # meta tag: {"tumblr": 50, "twitter": 100}
tag.set_meta_tag_count("tumblr", 40_000)  # never added to a displayed count;
                                  # tie-ordering and training's
                                  # inverse-frequency balancing read it

# What the TAG SET says about the tag — the namespace a link's and a
# caption's meta tags share. It never reaches an item, so nothing about
# search, counts or export changes; `TAG:noflip` and a training run's
# meta-tag settings are what read it.
tag.meta_tags.add("noflip")
sorted(tag.meta_tags)
lib.tags.meta_map()               # every marked tag at once, in one query
```

## Groups

Groups are a tree. `parent` is writable and assigning it *moves* the group.

```python
g = lib.groups["Trips/2019/Japan"]     # by path
g = lib.groups.create("Japan", parent=lib.groups["Trips/2019"])
g.parent = lib.groups["Archive"]
g.children, g.descendants, g.items
g.icon, g.color
g.add(item); g.remove(item)
g.duplicate()
g.delete(assign_tags=True)
```

`g.tags` is the group's **tag grants** — the tags every item in the subtree
inherits. One assignment here tags a whole subtree, which is where most
inherited tags in a library come from.

A **smart group** carries a search instead of hand-picked members: its
query (the saved-search tag set — the same strings `lib.query` takes)
decides which items belong to it, kept up to date automatically after
library changes. It grants tags like any other group and sits anywhere in
the tree, and it refuses what would contradict the rule — `g.add(item)`
raises, and it cannot hold child groups. **Smart is an identity, chosen at
creation**: an ordinary group never becomes smart nor the reverse; an
empty rule is legal and holds nothing (the group has not said which items
yet).

```python
best = lib.groups.create("Best cats", smart_query="cat quality:9")
best.smart                 # True — and fixed for life
best.items                 # whatever the search matches right now
best.smart_query = "cat"   # re-filed immediately
```

## Subjects, places, events, faces

Each is a record attached to a tag, so assigning one is assigning that tag —
search, counts, training and export need nothing new.

```python
alice = lib.create_subject("Alice", comment="the tall one", since="1975")
item.tags.add(alice.tag.name)
alice.items                         # every picture she is in
alice.faces

tokyo = lib.create_place(name="Tokyo, Japan")
con = lib.create_event("Comic-Con 2014", start="2014-07-24", end="2014-07-27",
                       places=[tokyo])

lib.subjects.find("ali")            # substring, like the app's autocomplete
lib.subjects.one("Alice")           # AmbiguousName if two people share it
```

Faces are evidence on an item:

```python
face = item.add_face(0.3, 0.1, 0.2, 0.25)   # a hand-drawn face
face.name(alice)                            # who it is
face.subjects, face.models, face.det_score
face.move(0.31, 0.11, 0.2, 0.25)
face.unname(alice)                          # records the correction
face.crop()                                 # the cropped PIL image
```

Detection itself is a model run — enqueue it from the app. Everything
downstream of it is here.

## Detected text

What an OCR engine read off a picture, as a tree — a block holds lines, a
line holds words, as deep as the engine actually went. Like a face, a region
is evidence: a re-run refreshes *where* it is and never what a person said it
*says*.

```python
for block in item.text_blocks:            # top level, in reading order
    block.text, block.level, block.rect
    block.score                           # None when the engine has none
    block.models                          # every engine that read it
    for word in block.children:           # the finer levels, if any
        word.text, word.score

block = item.text_blocks[0]
block.text = "what it really says"        # a correction — marks it `edited`,
                                          # and no run may rewrite it after
block.dismissed = True                    # "not text"; absorbs the next
                                          # detection over the same box
block.quad                                # the engine's four points for a
                                          # rotated shape; () when upright
block.crop()                              # the strip as a PIL image

drawn = item.add_text(0.3, 0.1, 0.4, 0.08, text="typed by hand")
drawn.delete()                            # the answer for a drawn box —
                                          # a detected one is dismissed

item.text_models                          # engines that have READ this item
```

There is deliberately no `item.text` shortcut — a page's text is a rendering
decision (separator, dismissed regions in or out, children flattened or not),
so the one-liner is yours:

```python
"\n".join(b.text for b in item.text_blocks)
```

Reading itself is a model run — enqueue **Detect text** from the app.
`INFO:text_blocks>0` finds the items that have been read.

## Captions, instructions and links

```python
cap = item.add_caption("a woman in a red coat")
cap.text = "a woman in a red coat, smiling"
cap.tags.add("alt-text")            # meta tags — a separate namespace
cap.delete()

# An INSTRUCTION is a caption of the other kind: it says how this picture was
# made from others, and carries them in the order a model is shown them. It
# lives on the RESULT, so `item` here is what the edit produced.
ins = item.add_instruction("make it snow", [summer, reference])
ins.kind                            # "instruction"; a caption's is "caption"
ins.refs                            # [Item, Item] — in order
ins.refs = [reference, summer]      # the whole list, so this reorders
ins.meta_tags.add("edit")           # the same namespace a caption's tags use

item.captions                       # descriptions only
item.instructions                   # instructions only — the two never mix

link = item.links.add(other, kind="panel")
link.meta_tags.add("redraw")        # the same namespace again
link.other, link.kind
item.linked_by                      # the incoming direction
```

## Sequences

An ordered run of items — a chapter, a book, an animated GIF's frames. A
sequence is carried by a **container item** of its own, so it can be tagged,
grouped and searched like anything else in the grid:

```python
seq = lib.create_sequence(pages, name="Chapter 4")
seq.members                         # the items, in order — one entry per position
seq.members.reorder(new_order)      # the whole list, so this reorders
seq.remove([page])                  # take an item out (every occurrence)
seq.item                            # the container item; seq.item.tags works
seq.kind                            # how it came to be: archive | pdf | gif | manual
seq.delete()                        # removes the sequence, keeps the members

lib.sequences                       # every sequence
item.sequences                      # the ones this item is in
```

## Dates and `NEVER`

Dates in a library are partial by design — "1975" and "March 1975" are both
answers — so `PartialDate` carries the precision:

```python
from media_compost import PartialDate, NEVER

PartialDate.parse("2019-04")        # .year .month .day .precision .range()
item.taken = "2019-04"              # str, int, date or datetime all accepted
```

`item.taken` has three states, and Python has only one `None`:

```python
item.taken = "2019-04"   # somebody said when
item.taken = None        # nobody has said — fall back to EXIF, then events
item.taken = NEVER       # somebody looked and there is no answer; stop there
```

`item.taken_effective` and `item.taken_source` report what the app displays and
why (`"set"` — somebody typed it — plus `"exif"`, `"event"`, `"never"` for
"somebody looked and there is no answer", and `""` when nothing has spoken).

## Importing

Local paths, with `move=True` to take the file rather than copy it in:

```python
got = lib.import_file("/inbox/DSC_0001.jpg", move=True)
if got:
    got.item.groups.add(lib.groups["Trips/Japan"])
    got.file.add_url("https://example.com/DSC_0001.jpg")
```

There is no destination-group argument: the result carries the item, so put it
where you want it afterwards.

| Call | |
| --- | --- |
| `lib.import_file(path, *, move=False, **options)` | One file |
| `lib.import_bytes(data, name)` | Bytes you already have — a download, an archive reader |
| `lib.import_folder(path, **options)` | A folder, with the importer's folders-as-groups logic |
| `lib.import_all(sources, **options)` | Many sources as one run |
| `lib.importing(**options)` | A run for sources discovered one at a time |
| `lib.merge_library(folder)` | Merge another library folder's items into this one |

```python
from collections import deque
from media_compost import ImportBytes

pending, urls, tags = deque(), [], []

def sources():
    for body, name, url, when, site in downloads():
        pending.append((url, when, site))
        yield ImportBytes(data=body, name=name)

with lib.importing() as run:
    for got in run.add_many(sources()):
        url, when, site = pending.popleft()
        if not got:
            print("failed:", got.error)
            continue
        urls += [(f, url, when) for f in got.files]      # where the BYTES went
        tags += [(it, site) for it in got.all_items]     # what is true of the ITEMS
        if len(urls) >= 500:
            lib.add_file_urls(urls); urls.clear()
            lib.assign_tags(tags); tags.clear()
    lib.add_file_urls(urls)
    lib.assign_tags(tags)
```

An `ImportBytes` is a pure stand-in for a file — data plus a name, nothing
else — and where the bytes came from is recorded **off the result**, through
the two bulk ops:

| Call | |
| --- | --- |
| `lib.add_file_urls(rows)` | `(file, url, accessed_at)` triples — `add_url`'s rules per row (idempotent per file+url+time, offset-aware times stored as the UTC moment they name), one transaction and one revertible History entry per batch |
| `lib.assign_tags(pairs)` | `(item, tag name)` pairs — the tag-field rules per name (a leading `-` is the negative sign, an alias assigns its target, a name the catalog refuses is skipped), pairs the item already carries left alone, one transaction and one revertible History entry per batch |

A few hundred rows to a transaction costs about what recording inside the
importer would; the singular `file.add_url(...)` and `item.tags.add(...)`
stay the shape for one-offs. The two walks are the whole recipe — `files`
and `all_items` answer correctly whatever a source turns out to be, so
nothing reads the result's shape by hand.

An `ImportRun`'s `add` takes paths as well as `ImportBytes`, keeps one commit
rhythm and one write lease for the whole run and
writes one History entry when it closes, so it is much faster than a loop of
`import_file`. When the sources can be listed up front, **`run.add_many(sources)`
is faster still**: it reads, decodes and hashes upcoming images on worker
threads while the current one is stored, and yields the same per-source
results in order.

**`processes=True`** moves that half into worker *processes*, so it stops
competing with the importing thread for the GIL — measured over four crawl
archives, the serial import loop alone runs 0.9&nbsp;s where the same loop
under eight prefetch threads takes 1.7&nbsp;s, and the process pool gives
that time back (1.85&nbsp;s of thread pipeline becomes 1.4&nbsp;s warm). Two
things to know before reaching for it. Your script **must** have an
`if __name__ == "__main__":` guard: the pool is `spawn` (forking would fork
a live SQLite connection and the library's own background threads), and a
spawned worker re-imports your `__main__` — without the guard it re-runs
your import in every worker, which starts more workers. And it costs a
one-time ~0.4&nbsp;s pool start, so a handful of files gains nothing; it
earns its keep on a real run, and all the more wherever the main process is
already busy — a reader thread feeding the import, a large library whose
every import probes a bigger index.

The result is an `ImportResult` — exactly one per source, in order — and its
shape is **fixed at two levels** however deeply a source physically nests:

| Field | |
| --- | --- |
| `status` | An `ImportStatus` (a `str` subclass): `imported`, `alternative`, `duplicate`, `multi`, `skipped`, `ignored` (left out by the run's own size, shape or type filters) or `error` — each spelled out in the [reference](api/importing.md) |
| `item`, `file` | The one item/file standing for the source, when there is one: a picture's own, a book's sequence **container** (`item`, with `file` None) — the thing the library shows for a PDF or GIF |
| `entries` | One `ImportEntry` per file-shaped thing the source contained, **flat**: a zip of PDFs is one entry per PDF, a zip inside a zip flattens away, an unsupported member is a `skipped` entry named after itself |
| `stats` | Counts for the whole run |
| `error` | Why, when `status == "error"` |

Each `ImportEntry` carries its own `status`, `item`, `file`, `name` and
`children` — the pages of a book, the frames a video matched — and children
are always leaves. One content rule keeps the depth fixed: **a book inside a
book is a flat sibling entry**, never a member of the outer sequence.

Two derived walks answer the questions the entries exist for:

| Property | |
| --- | --- |
| `got.files` | Every stored file the source's **bytes** went into — the existing file for a duplicate, one per page, never a container (owns no file) and never a **derived** file (a matched video frame materialized onto an existing item) |
| `got.all_items` | Every **item** the source produced or landed on, deduplicated — created items, book containers, and the existing items a duplicate or matched frame reached |

`bool(result)` is False only on error, so `if got:` is the check to write.

**`move=True`** removes the source once the file is fully ingested — including
when the bytes turn out to be an exact duplicate, since the library provably
holds identical content and leaving the file behind defeats the point. A source
that failed to import is never removed.

## History

Every change is logged, and most can be undone:

```python
for change in lib.history[:20]:
    print(change.created_at, change.action, change.summary, change.username)

lib.history[0].revert()

mark = lib.history[0].id                     # note the newest id,
...                                          # do the risky thing, then
lib.history.revert(lib.history.since(mark))  # undo everything it logged
```

This is the safety net worth reaching for first: a script that mis-tagged
10,000 items is one loop away from being undone.

## Settings and stats

```python
lib.settings.subject_tag_prefix     # "subject:" — what the app mints
lib.settings.place_tag_prefix
lib.settings.event_tag_prefix
lib.settings.face_match_threshold

lib.stats                           # counts per entity: items, files, tags,
                                    # groups, subjects, faces, captions, ...
lib.metadata_names                  # everything queryable via INFO:
```

These prefixes decide what tags the app *invents*, so a script creating
subjects should read them rather than hardcode `subject:`.

## Maintenance

```python
lib.merge_library(folder) # fold another library's items and tag set in;
                          # its database is read directly (read-only), its
                          # file bytes are copied, existing uids are skipped.
                          # dry_run=True counts without writing. The source
                          # must be at this build's format — refused by name
                          # otherwise.
lib.reindex_metadata()    # re-read what EVERY FILE of every item says about
                          # itself, then rebuild each item's index from its
                          # active one; returns how many FILES it read.
                          # THE ONE SURVIVING REPAIR: a library from an older
                          # build has metadata for its active files alone, and
                          # a video's was never read at all. It never clears a
                          # value pinned to an item — no amount of re-reading
                          # bytes can produce one again.
lib.prune()               # sweep stray files in item folders
lib.empty_trash()
```

## Errors

```
MediaCompostError
├── LibraryError → LibraryVersionError, ReadOnlyError
├── NotFound (also a KeyError) → ObjectDeleted
├── AmbiguousName (also a LookupError)
├── ValidationError (also a ValueError) → InvalidTagName, InvalidDate
├── ConflictError → DuplicateName, GroupCycleError, InvalidLink
├── ImportFailed
├── MediaUnreadable (also an OSError)
└── UnsupportedOperation (also a ValueError)
```

`NotFound` subclasses `KeyError`, so catalogs behave like the mappings they
are. A handle whose row has been deleted raises `ObjectDeleted` on read and on
write, rather than returning a silently stale value — `item.exists` and
`bool(item)` probe without raising, and `item.refresh()` re-reads.

## Bulk edits

Every write on an `ItemSet` is one transaction, not one commit per item. The
log still records one event per item (per item *and tag* for the tag stamps)
— that is what makes each change revertible — but the History view groups a
consecutive run into a single row:

```python
q = lib.query("INFO:width<800")
q.add_tags("lowres")
q.remove_tags("hires")
q.add_to(lib.groups["Needs work"])
q.remove_from(lib.groups["Done"])
q.hide(); q.show()
q.trash(); q.restore(); q.delete()
```

Use these rather than a loop wherever they fit — over 50,000 items the
difference is thousands of commits, each taking and releasing the write
lease, against one.

## Worked examples

### A custom dataset export

Copy each matching image next to a `.txt` caption file of its tags — the layout
many trainers expect:

```python
import shutil
from pathlib import Path

from media_compost import open_library

out = Path("dataset")
out.mkdir(exist_ok=True)

with open_library("/path/to/library", mode="r") as lib:
    q = lib.query("portrait !lowres INFO:resolution>=1.0", kind="image")
    for item in q.prefetch("tags", "files"):
        if item.path is None:
            continue
        dest = out / f"{item.uid}{item.path.suffix}"
        shutil.copy2(item.path, dest)
        dest.with_suffix(".txt").write_text(", ".join(sorted(item.effective_tags)))
```

### Feeding a training pipeline

Skip the copy and stream items into your own loader — and mix in video frames,
since `frames()` decodes on demand:

```python
from media_compost import open_library

with open_library("/path/to/library", mode="r") as lib:
    for item in lib.query("SUBJECT:alice").prefetch("tags", "files"):
        caption = ", ".join(sorted(item.effective_tags))
        if item.kind == "video":
            for _i, _t, image in item.frames(fps=1.0):
                yield image, caption
        elif item.path:
            yield item.image().convert("RGB"), caption
```

### Tidying up after an import

```python
from media_compost import open_library

with open_library("/path/to/library", user="tidy-script") as lib:
    got = lib.import_folder("/inbox/japan-2019", move=True)
    print(f"{got.stats.imported} new, {got.stats.skipped_duplicate} duplicates")

    japan = lib.groups.get_or_create("Trips/Japan")
    with lib.transaction():
        for item in got.all_items:
            item.groups.add(japan)
            item.tags.add("unsorted")
```

If that turns out to be wrong, note the newest history id before you start
and revert everything logged after it — the watermark pattern from
[History](#history):

```python
mark = lib.history[0].id            # before the import
...
lib.history.revert(lib.history.since(mark))
```
