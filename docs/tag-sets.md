# Tag sets

A **tag set** is an imported tag list — names, a sentence on what each one means, an optional popularity count, other spellings, what a tag entails, and nestable categories — kept **apart from the library's own tags**. Importing a set of 10,000 names adds nothing to the [Tags](tags.md) table and puts nothing on a picture. It is advice: the names are *offered* in every tag field, and what the set says about a name is shown beside it.

**The library is written only by an assignment.** Picking a set-only name creates that tag exactly as typing it would — and nothing else is copied out of a set. A tag the library already has is never re-described by one.

## What a set does

Every **enabled** set feeds the tag autocomplete, in three ways:

- **A name the library already has** is the library's own row, wearing the set's **capsule** behind the name — dashed and quieter than a [meta tag](tags.md#meta-tags-on-a-tag)'s, reading the set's name and the set's count ("BOORU 5M") — in every list and every suggestion.
- **A name the library lacks** appears as a suggestion of its own, ranked after every *used* library tag at the same match position and, among set-only rows, by the set's count. Picking it creates the tag.
- **A set's alias** is offered with an arrow to its canonical, and picking it — or typing it raw — assigns the canonical. A tag set's aliases are the set's own; they are not [library aliases](tags.md#aliases) and nothing is written until a name is assigned.

The **?** after a name in any tag list or autocomplete opens what the sets say about it: the description of the set you read most recently, a strip of set names to switch between when several describe the tag, and under it the category that set files the tag in ("people › female"), **the one-liner the set says the tag should carry, and what it says the tag IS** — a subject with its date, a place with its coordinates and what it is inside, an event with its span. That last is there because the popover is often the only place a name is met: a half-typed word in a field, a row in an autocomplete. A set that has written no prose but knows the name is a person opens a `?` all the same.

**A description can carry links.** `[text](https://…)` opens in a new window; `[text](#other_tag)` is a link to another tag of the same set, and following one opens *that* tag's description in the same popover behind a **Back** button. Either way an **In the set** button jumps to the tag where its set files it — the Tags tab, that set's pill, that entry. (`scripts/link_tagset_descriptions.py` in the source tree is what put the links into the shipped sets: it links a word that matches an entry's name exactly *and* looks like a tag rather than English — one holding an underscore, a digit or punctuation — never the tag the description is about, and only the first mention of each.) The set you switch to moves to the front for every tag, per user — in the *next* popover, so the strip never reorders under your hand.

**An empty tag field browses the sets.** Focus a tag field with nothing typed and, instead of nothing, it shows the enabled sets' **category trees**: the sets (skipped when only one is enabled), then a set's categories with how many tags each holds, then a category's own tags. `→` opens the highlighted row, `←` (and Escape) goes back one level, Enter on a tag assigns it. The [quick tag field (T)](library.md#quick-tag-from-the-keyboard-t) shows the tree over an empty line and offers the last five lines you applied above it.

## Where sets live

Two places, for two errands:

- **The pencil at the end of the pill row** (Tags tab) opens the list: every set with a switch, its entry count, a **drag handle** to reorder it and a ⋯ menu — *Duplicate*, *Export*, *Delete* — with *Properties…* as a button of its own beside it. An **Add** menu in its footer is where a new one comes from (below). The **library's own set is pinned at the top** with none of those: it cannot be hidden from itself, moved off the front or deleted — its rows are the library's tags — and the one thing it shares with the rest is that it exports as an ordinary tag-set file. The **built-in sets** are rows like any other, with a *Built-in* chip and no *Delete* (below). Everything applies at once; there is no Save. (This was a section of Settings → Tagging until 2026-09. Settings is for preferences, and a tag set is library content.) Whether a set is enabled is **library-global** (which sets feed everyone's autocomplete is a fact about the shared library); the order you prefer to read descriptions in is **yours**.
- **The Tags tab's Items list** is where a set's content is read and written — the page the rest of this describes. A set is a **pill** above that list rather than a sub-tab beside it, and the LIBRARY is the first pill: its own tag set, its own categories, and an export of its own (see [The library as a set](#the-library-as-a-set)).

A set's **name is unique**, and the dialogs refuse a taken name before the server does. A set travels across a [library merge](cli.md) by key; the destination's copy wins.

## Making a set

The sets are a row of **pills** — one per set, with its entry count, and *Hidden* on a set that is switched off. Making one is **a press in a menu, not a form**: the **Add** button in the manage overlay's footer lists

- **New empty set**,
- **Import from file…** — a set's **JSON** export, or a **CSV** (a booru dump), which always becomes a **new set**, named in its own dialog.

Both makers **name the set themselves** (*New set*, or the first *New set 2*, *New set 3*… that is free), because the server refuses a duplicate name and a refusal is not what pressing a menu entry asked for. Renaming is the row's **Properties**, one line below where the row appears.

## The sets that ship with the app

Five lists come with Media Compost — **Booru**, **Characters**, **Photography**, **Cinematography**, **Documents and screens** — and each one is a **row of the tag set list** in every library, wearing a *Built-in* chip. They are **switched off** to begin with: a list of a hundred thousand names is not something to put in everybody's tag fields uninvited, and nothing of a built-in is written into the library until you turn it on. Turning one on writes its entries; the big ones take a few seconds, and the footer says so while it writes.

A built-in is **read-only**. You cannot rename it, add or remove an entry, or delete it — it is the app's list, not yours, and *Duplicate* is the copy that is. What you *can* set is everything that is a fact about **this library** rather than about the file: whether it is switched on, where it sits in the list, and the two switches in **Properties…** — *Offer alias spellings* and *Create implied tags*. It exports like any other set, switched on or not.

Its **pill** above the list is a pill like any other set's, with a struck-through pencil at the end to say its list is read and not edited — a built-in is a tag set, not a third kind of thing on that row.

Its entry list is **read**, and that is the only difference: the names, their descriptions, their categories and what they imply are all there, the search, the filters and the sorts are the same, and every way from a row into the library — **Add to library**, **Tag in library**, **Parent hierarchy** — is exactly why you would open one. What is missing is everything that would write the *set*: no Add, no pencil, no category verbs, no dragging a row onto a category, no Delete.

**An update is offered, never taken.** When a new version of Media Compost ships a different version of a list — more names, better descriptions — a built-in you have switched on grows an **Update available** chip, and *Update* appears at the top of its ⋯ menu. Nothing rewrites it on its own: that would be a hundred thousand rows written while you wait for the window to open, on a launch you only meant to be a launch. A built-in you have never switched on simply takes the current version whenever you do. (Updating replaces the set's entries with the ones this build ships and cannot be undone — what it replaces is the previous release's file, which is no longer on the machine.)

*(They were **templates** listed in the Add menu for a round — owner decision 2026-09, reversed. One press made a copy frozen at the file it came from, so a set nobody could keep up to date sat in a menu rather than in the list it belongs in. If you made a set from one of those, it becomes the built-in on the next open — same entries, same switch, same place — and it reads as behind, so the update that makes it the current list is yours to press.)*

The built-in **Booru** list is about 700 of the general tags almost every picture library needs, in the booru spelling so a generated tag lands on the same name, each with a sentence on what it means and the popularity count from the list it was drawn from: how many people are in the picture, their age, hair, eyes, face and ears; expression and gaze; posture, arms, hands and what two people do together; clothing by kind with the common colour variants; the setting, objects, food, furniture and animals; framing and angle; effects, lighting, quality, text, medium and colour. Nothing in it names a franchise, a person, a place or an event, and nothing in it is sexual.

The built-in **Characters** list is the one that does name people: 102,215 characters from the danbooru tag list, each with the **display name** spelled properly (`hatsune_miku` is "Hatsune Miku"), the other spellings the sites use for it as aliases, its **franchise** as the tag's comment, and that franchise's own tag as an implication — so tagging a picture `hatsune_miku` says `vocaloid` too. Every character entry says **this name is somebody**, so assigning one makes a **subject** in your library with the display name already on it, rather than a bare tag.

The **8,653 franchises** are entries of the same set, so what a character implies is a name the set describes rather than a bare word: a franchise carries what kind of thing it is as its comment (*Video Game*, *Manga*, *Toy*, *VTuber*, or *Franchise* where the wiki names more than one medium), its parent franchise as its own implication, and the wiki's first sentence as its description. A franchise is **not** somebody — the display name is a subject's, a place's or an event's to carry — so the tag is the name you see. **The tree is the franchises, and a franchise is one place.** Opening *Vocaloid* finds the `vocaloid` tag itself and everybody in it; opening *Nintendo ▸ Pokemon* finds the franchise, its individual games and its whole cast. Nothing in the tree says character-or-franchise — that is the **Subjects** row in the sidebar and the *Is a* filter, which read the record rather than the shelf — and nothing splits a cast by how big a part somebody has. **A category exists only where at least three names are under it**: a franchise with one character is not a folder, it is a row whose comment already says which franchise it belongs to. Everything with five or more danbooru posts is in it.

Each set's verbs are in the list behind the pencil — **Properties…** as a button, then a **⋯** with **Duplicate**, **Export** (the JSON file the import reads) and **Delete**; a built-in has no Delete, and gains **Update** while one is available. Renaming is a field in Properties, not a row of its own. The open set is in the address (`/tags/tagsets?set=7`), so a reload comes back to it.

## Categories

The left column is the set's **category tree** — a browsing aid and a filter, nothing more. Two fixed rows lead it: **Everything** and **Uncategorized**. Under a rule come the categories, each with its icon and **how many entries it holds, its sub-categories' included** — which is exactly what clicking it lists. A **search field** narrows the tree to the matching categories and their ancestors while it is live.

- **Add category** is over the tree; a category's ⋯ (and its right-click) edits it, adds one inside it, hides it, or deletes it — **everything under it goes with it**, and the entries of the whole branch stay, uncategorized. The question says how many categories that is.
- The dialog holds the category's **name**, an **icon** from a small palette, its **parent** — offered as the tree, indented, never as a flat list of paths — and whether it is [hidden from the autocomplete](#hiding-a-category).
- **A category row drags** — the whole row — before or after another, or *into* it, to reorder and re-nest the tree. While a drop hangs over a row the line starts at the depth the drop would land at, and the category it would land inside wears a ring.
- **Several categories select at once**, and **the list is the union of what they hold**: ⌘/Ctrl-click adds and removes, shift extends the run, and a plain click picks one alone — *show me this one* — as it always did. Picking a category and one inside it lists each entry once. A plain click on the only picked category lets it go, which is the way back to *Everything*. With any picked, a **Delete N** button appears beside Add category, and a right-click on a picked row opens a menu for the **whole selection**: hide or show them all, or delete them. A right-click on an unpicked row stays about that row and leaves the selection alone.

### Hiding a category

A category can be **hidden from the autocomplete** (the switch in its dialog; a hidden category's row wears a crossed-out eye). Hiding takes the category, everything under it and every tag in that subtree out of the tag fields — out of the ranked suggestions, out of their aliases, and out of the browse tree — for a set that is otherwise fully enabled. It is the way to keep the half of a big imported list this library never wants offered without deleting rows you may want back.

It is **not** a deletion and not the set's own *Hide*:

- The entries stay listed and editable here, and an **export still carries them** (the file writes a `hidden` key on the category).
- **A tag the library already has is unaffected.** That suggestion is the library's own row, which no tag set has ever had a say in — so hiding a category stops it *offering* names, never stops you using tags you already have.

## Entries

**A set's names are listed by the [Tags tab's own table](tags.md#the-tag-table-items), the one the library's names are listed by.** Picking the set's pill changes which tag set the table is about; everything else — the header band, the left column with its categories and namespaces, the search, the filters, the selection, the drag onto a category, the windowing — is the same code doing the same thing. What is the set's own is the two count columns (**Library** and **Count**) and what a row offers.

It is **paged and windowed**: a 250,000-entry dump is a list like any other, and the search, the category filter and the sort are the server's.

The list is the [items tag list](tags.md#the-tag-table-items)'s shape — a select-all checkbox and the **Tag**, **Category** and **Count** headings on the header band, a checkbox per row — and each row reads: the tag name, the **?** with its description, what it entails after a `→`, the category it sits in (over the whole set) and the count. All three headings sort; **Count descending is the default**, the popular tags first being what a list of a dump is read for, and the name breaks every tie. A count nobody gave and an entry in no category sort last either way.

**A set's other spellings are rows of the list**, exactly as the library's aliases are rows of its own: an alias has its own checkbox, its own selection, its own place in every order, and it reads `1male → 1boy` — the name, an arrow, the name it stands for, which is a link to it. It carries nothing else, because everything else on a row belongs to the tag and an alias's tag is the one it points at: no description, no count, no records, and no pencil. It is **filed where its entry is**, so a category holds every name for the tags in it. Under the file's own order, under Count and under Category it stands directly beneath the name it spells; sorted **by name** it stands where its own name puts it. Its ⋯ menu is the three things there are to do with a spelling: show the tag it stands for, point it at another one, delete it — deleting takes the spelling and leaves the tag. (They used to be drawn *inside* their entry's row, which was the one thing the two lists said differently about the same fact.)

- **Add entry** is a menu: *Add entry…* (the dialog) or *Import from CSV…*, which adds a file's rows to the set on screen.
- The dialog holds the **tag**, its **description**, an optional **count**, its **category**, its **aliases** and what it **implies** — the last two as space-separated lists — and, under a rule, what the set says the **library's tag** should be: a comment, and whether the name is a subject, a place or an event (see [what an entry says the tag is](#what-an-entry-says-the-tag-is)).
- **Rows select** like every other tag list's: click, ⌘/Ctrl-click to toggle, shift-click for a range, press and drag across several. A **Delete N entries** button appears over the list while any are picked, and a right-click on a picked row is about the **whole selection**; on an unpicked one it is about that row.
- **Filter** narrows to entries carrying *aliases*, *implied tags*, or (both ticked) both. The button lights while either is on, so a short list is never a mystery.
- **The Category cell is a way into the tree**: each name of the trail a row shows is clickable, and clicking one picks that category in the sidebar — which is what narrows the list. A branch that was collapsed opens to show it.
- **An implied tag is a way to that tag**: the names after the `→` are links, and clicking one lands on that entry of the same set. A row whose implied tags do not fit one line **wraps onto a second** rather than cutting them off — the list is what the row is for.
- **Drag entries onto a category to move them.** A *picked* row is the drag source (dragging an unpicked row still paints a selection, as the list has always done), and what travels is the whole selection: drop it on a category to file it there, or on **Uncategorized** to take it out of the one it is in.

### What an entry implies

An entry can name the tags it **entails**, beside its other spellings. Nothing happens in the library until the entry's name is **assigned for the first time**: the tag is created, and so are the names it implies, linked as ordinary [library implications](tags.md#implications) — each its own [History](history.md) event you can undo. A tag the library already has keeps the implications it has; the set does not add to them.

Two things the app settles for you, because they cannot mean anything:

- **An entry never implies itself** — neither its own name nor one of its own aliases, both of which assign the very same tag. Such a name is dropped where it is written: in the dialog, in an imported file, in a CSV.
- **A ring cannot become library implications.** `a → b → c → a` is a loop, and the library refuses to close one, so one edge of the ring has to go. The walk starts at the name you actually assigned and works outward, so `a → b` and `b → c` are made and the edge back to `a` — the one furthest from what you asked for — is the one dropped. All three tags still land on the picture; only the last link is not recorded.

An implied name may of course be a tag the library has never heard of: creating it is the point. If it names something another entry of the same set calls an alias, the **canonical** is what gets implied — the same redirect assigning the name would take.

### What an entry is labelled with

A set has **meta tags** of its own — labels it puts on its own names, listed under **Meta tags** in the left column beside the categories. A meta tag says something about the NAME rather than about any picture: `character`, `noflip`, `from a booru`. An entry's **Meta tags** field says which ones it carries, space-separated, and a label the set does not know yet is made with the save, the way an implied name is; the list's own **Add meta tag…** is where one gets a comment and a description before anything carries it.

They reach the library through the same door the implications do, at the same one moment: assigning the entry's name for the first time creates the tag and puts the labels on it, each an ordinary [meta assignment](tags.md#meta-tags-on-a-tag) you can undo. A label the library has never heard of arrives with the set's words for it; one it already knows keeps its own. A tag the library already had hears nothing — the rule everywhere a set meets an answer that is already there.

The two tag sets stay apart: what a set calls a `character` is that set's advice, and renaming or deleting a label in one list never reaches the other.

### Syncing what the library missed

The door speaks once, and only when it is creating the tag. That is deliberate — a set may not re-describe a library that already has an answer — but it leaves two ordinary situations where the set says something the library never hears: a tag that was already in the library when the set arrived, and an entry given an `implies` after its tag had gone into use.

The list says so. An implied name the library does not entail is drawn **struck through**: the entry claims it, nothing has acted on it. A name the library has never heard of is not struck through — it is unassigned, not behind — and neither is one the library reaches through a chain of its own, which already behaves as the set says.

The **⋯ menu → Tag in library**, on a row or on the selection, is where it gets made true — the same one verb that writes the comment and the records, since the door writes all of it at one moment:

- **Add missing info** adds what the set says and touches nothing else. Whatever else the tag entails was somebody's own decision, or another set's.
- **Replace with the set's** makes the tag's implications exactly what the sets say — every direct implication they do not name is removed first. This is how you follow a set that has *dropped* an implication, rather than only adding to it.

Both are made of the ordinary logged primitives, so a sync appears in [History](history.md) edge by edge and undoes. A name the library does not have is **skipped**, never created: an unassigned entry is not out of step with anything, and a set of seventeen thousand names would otherwise be a way to fill the catalog by accident. So is a name no enabled set speaks for — under *Replace*, silence would otherwise read as "remove everything".

A row for a name the library has never heard of offers **Add to library** instead — until the tag exists there is nothing for the set's advice to be about. That goes through the same door an assignment does, so the tag arrives with what its set says about it: an alias name creates the canonical tag, and the entry's implied names are minted with it.

The list can be narrowed to exactly these rows: the filter menu's **The library → Missing implied tags**. It lists an entry only where BOTH tags are in the library and only the link between them is missing — a gap whose implied name the library has never heard of is an entry talking about a tag nobody uses, and syncing that is a way to fill the catalog from a dump rather than a repair. The row still strikes the name through, because the library really does not entail it. It is answered by walking the entries the library actually has names for rather than the whole set, and remembered for as long as the library has not moved, so paging through the narrowed list costs nothing more.

A branch whose implications are [switched off](#the-file) shows none of this: its entries keep their implied names, and the list does not draw them at all, because nothing will ever act on them. Neither does a hidden set — its advice is not in force, so nothing can be out of step with it.

### What an entry says the tag is

Beside all that, an entry can say what the name **is**. The description is the set's own words about it and stays in the set; these are advice about the **library's own tag**:

- a **comment** — the one-liner the tag should wear in the Tags tab;
- a **subject** — this name is somebody: a person, a character, a band, a cat. A display name (where it differs from the tag) and a since-date;
- a **place** — what it is called (an address, or "Bob's house" — the [Places](places.md) list's own field, labelled **Name** for that reason), optionally coordinates, optionally the place it is **inside**;
- an **event** — a name and a span of days, optionally the event it is **part of**.

A tag set knows these things, and without them a library is told twice: once by importing the list, once by typing the same facts into [Subjects](subjects-and-faces.md), [Places](places.md) and [Events](events.md). They reach the library the way `implies` does — **through the one door**, when the name is first assigned and the tag is created — and what they make are **ordinary records**: a comment on the tag, a Subject, a Location, an Occasion, each its own [History](history.md) event to undo. A tag set holds no records of its own.

**What the library already says wins.** A tag that carries a comment is not re-described; one that is already somebody is not made into a second person.

A **parent** — a place's, an event's — is named by that one's own tag, and at the door **the whole hierarchy above it is made with it**: assigning `shibuya` for the first time makes the place *and* Tokyo, and Japan above that. A place standing in nothing is not what the set said. Containment is an implication between the identity tags, so assigning the child then assigns its parents too; a ring the set describes (`a` in `b` in `a`) loses the edge furthest from the name that was assigned, exactly as the implications do.

**The one it is inside is picked from the set's own places** (and an event's from its own events): the field holds a tag name, because that is what a parent is named by everywhere here, but a tag name is not what anybody knows the place as — so typing into it searches this set's entries of that kind and the rows read as the place, its name with the tag behind it. A name the set does not have yet can be **made here**, as an entry of this set marked as that kind: going away to add `japan` before `tokyo` can be filed in it is the errand that stops anybody building a hierarchy at all.

**The Implies field completes from this set.** An implication points at another entry of the same tag set far more often than not, and a name typed from memory into a plain box is how a set comes to entail `1girls` where it meant `1girl`; the suggestions are about the word under the caret, so a half-typed list stays a list. A name the set does not have yet is **made in it** when the entry is saved — the hierarchy of a tag set is built out of its own rows, and leaving the dialog to add the parent first is the errand that stops anybody building one. (A name the set already knows as an *alias* is left alone: it is that entry, said differently.)

In the dialog the **comment sits with the name**, directly under it — the description below is the set's own paragraph, and putting a paragraph between a name and its one-line gloss read as two unrelated fields. The three records follow, each a **row with a + until the name is one of these** and its fields under it once it is. There is nothing to fold: the two states are the answer itself, and the ✕ in a section's header is how a record is taken away. On the entry's row the comment reads as secondary text straight after the name, and each record as a small glyph after it — both **dimmed where the library's tag does not have it yet**, the strikethrough on the implied names one kind of advice along.

**A set of people is read as people.** The filter menu's **Is a** section ticks *Subject*, *Place* and *Event* in any combination (several is the union — the entries that are *either*), and the sidebar draws a row for each kind the set has any of, under **Everything** with its count. Narrowed to exactly one kind the rows change shape: **the record's own name leads**, and the tag and its other spellings drop to the subtitle beside the record's own facts — the date, the coordinates, what it is inside — in the words the library's own [Subjects](subjects-and-faces.md), [Places](places.md) and [Events](events.md) lists use. It is the **library's** record that leads, which is why a set's entry keeps its tag as the name until the tag is one the library has: a set is advice, and what *it* says the name is called reads in the **?** and in the row's dimmed glyphs, where it is plainly the set talking. (The ordinary rows are unchanged either way: there the tag is the name.)

The same two situations the implications have apply here, and the same answer: a tag that was already in the library, or an entry given a record after its tag went into use, says something nothing ever heard. The **⋯ menu → Tag in library** writes it, and it writes **all** of it — what the name entails, the line it carries, and what it is — because the door applies all of it at one moment and two menu entries made you choose between two halves of one thing. *Add missing info* leaves everything the library has; *Replace with the set's* overrides it (and makes the implications exactly what the sets name), filling in the fields an existing record is missing rather than deleting and rewriting it, since a record somebody edited is an answer. A name the library does not have is **skipped**, never created.

**Parents are their own verb.** Following one mints that tag and its own parent above it, so over a selection of four hundred rows it fills the catalog rather than describing what was picked — which is why the sync above leaves them alone and **⋯ → Parent hierarchy** (*Add missing info* / *Replace with the set's*) is offered separately, and only on rows whose place or event sits inside another.

The filter menu's **Comment and records → Missing comment or record** narrows to the rows that are behind; with *Missing implied tags* it is the union — anything the library has not caught up with.

## The file

**Export** writes the set as JSON, and **Import from file…** reads it back. The document is the set as an outline: its name and description; its categories nested by `children` (with an `icon` and `hidden` where they are set); and its entries, each with `name`, `description`, `count`, `category`, `aliases`, `implies` and `meta` (the labels it carries) — plus `comment` and the `subject` / `place` / `event` objects where the set says what the tag is (a place's line is its `name`, like a subject's and an event's). An **empty** record is still a record: `"subject": {}` says "this name is a person", which is the whole of what a tag set often knows, so that key is written even when it holds nothing. A top-level `meta_tags` block carries the labels the file has a comment or a description for; the rest arrive on the entries, the way a category trail does. Every key is written only where there is something to say, so most of a real file is one line per tag and a round trip changes nothing.

An entry's **`category` is the list of names down to it** — `["people", "count"]`, not `people/count`. That is what lets a category be *called* `and/or`: there is no separator for a name to collide with, and the app draws the trail with chevrons between the names rather than joining it into a string.

**The category tree is not written down. It is what the entries say it is**: reading them in order and creating each trail's missing levels builds the whole thing, parents and order together. `categories` survives as a **flat list of what the entries cannot say** — a category's `icon`, `hidden`, `aliases` or `implications`; a category that holds no entries, which would otherwise not exist (a row that is only a `path` means exactly that); and a `position`, for a parent whose children somebody reordered by hand, written then for all of them at once. The whole key is omitted when the entries already say everything, which is the usual case: **the shipped sets write no `categories` at all**, because their entries are emitted grouped by category in the authored outline's order, so the tree they imply *is* that outline. Several hundred categories, spelled nowhere.

**Aliases and implications can be turned off** — for the whole set, or for one branch. The set's two switches are in **⋯ → Properties…** beside *Hidden*; a category's are in its own dialog and are three-state (*Default*, which takes whatever the category above it says with the set's own switch at the root, or an answer of its own). A set whose aliases are off offers none of its other spellings and none of them redirect; one whose implications are off mints nothing when a name is assigned. Neither removes a row: the entries keep their aliases and their implications, the Sets tab lists them, and an export carries them. Both travel in the file, since whether a tag set's alias spellings and entailments are advice worth taking is a fact about the tag set.

What is deliberately *not* in the file: whether the set is enabled, its position, every id — and its key and version. Those are facts about one installation, not about the set: the key says which set *this* library filed the tag set under (a second copy of one file is `booru-2`), and the version is a counter this library bumps as you edit. A file read from disk takes its key from its **filename**.


Importing into an **existing** set adds what it lacks; importing as a **new** set makes one from the whole file.

## CSV import

The **CSV import** takes a booru dump or any sheet with a tag column. Comma, semicolon, tab and pipe delimiters are detected; the header is guessed (name, description, count, category, aliases, implies) and corrected in the dialog, with a **preview table** showing the first rows as they will land.

- **A minimum count** — offered once a count column is mapped — leaves out every row under it. A dump lists every tag ever used once, and the useful end of it is where the counts are; a row with no count stays.
- A row with a **blank or repeated name** is skipped, and names are normalized as they are read.
- A **category is kept exactly as the file spells it** (no site's numbering is built in), and the categories a file names are created along the way. One cell has to hold the whole trail, so here — and only here — a `/` separates two category names: `people/girls` files the tag two levels down. A category whose own name holds a slash is made in the Sets tab or in a tag-set file instead.
- Importing **into an existing set** asks what an entry the set already has should do: keep what it says, take the file's non-empty fields, or become the file's row. A new set is empty, so it is not asked.
- The rows go in **chunks** with a Stop between them, each chunk its own revertible write.

## History

Every edit here is an ordinary [History](history.md) entry and reverts: making, renaming, hiding and duplicating a set; adding, editing, moving and deleting a category; adding, editing and deleting an entry; and an import, which reverts as one step while it is small enough to snapshot. **Deleting a set is the one thing History cannot undo** — its categories and entries go with it, and the dialog says so. The library's own tags are untouched by any of it.

## Related pages

- [Tags](tags.md) — the library's own tag set, which a set only ever advises
- [Settings](settings.md) — where sets are switched on and off
- [Library](library.md) — the tag fields a set feeds
- [History](history.md) — undoing what an edit did


## The library as a set

**The library is the first pill**, and it is a tag set in every way but its
names: its list is the [Items list](tags.md), its categories are
ordinary categories, it has properties of its own — and it **exports**.

Its pill's ⋯ offers **Export**, which writes the same format-2 file an
imported set exports. Every tag becomes an entry carrying what the library
knows about the name:

- its **description** (the long form) and its **comment** (the one-liner),
- its other **spellings** — an alias is a spelling of its target here, never
  an entry of its own,
- what it **implies**, as names,
- the **category** it is filed in, as a trail,
- and what it **IS**: its subject, place or event, with that record's own
  fields.

A ranking's minted score names are left out: they are derived from judgments
no file can carry, and a hundred `quality:N` rows are noise in every library
but the one that made them.

Imported into another library the file is a set like any other — **advice**,
written into that library only when one of its names is assigned. That is the
point of it: a tag set somebody built by hand is worth carrying to the next
library, and the [tag CSV](tags.md) knows nothing about categories,
descriptions or records.

The library's set row is **lazy**: a library that has never filed a tag in a
category has never needed one, and the pill is drawn all the same.
