# Tags

Tags are the library's tag set — short labels you assign to items — and the Tags tab is where you manage them: rename, merge, comment, connect, and import or export them in bulk.

## The Tags tab

Open the **Tags** tab from the main navigation. It is **one list**, and there is no page switcher over it: a row of tag set **pills** above — the library first, each imported [tag set](tag-sets.md) beside it — and a left column for narrowing what the pill holds. The page is "which tag set, and what is in it".

**Meta used to be a button of its own.** A meta tag is a name in the same tag set — a label on a NAME rather than on a picture — so it is the **Meta** row of the left column now, under Subjects, Places and Events, in the library's list and in a tag set's alike. Picking it shows the labels instead of the names, with the tag set pills still above them; picking anything higher in the column goes back. Meta rows are deliberately not counted in **Everything**: they are the other list a tag set holds, not a slice of the first.

**Faces used to be a button here too**, and is a tab of the main navigation now (`/faces`): answering "which crops are one person" is a screen you spend an afternoon in, not a slice of the tag table. See [Subjects and faces](subjects-and-faces.md#the-faces-tab).

**Subjects, Places, Events and Sets used to be sub-tabs of their own.** A subject, a place and an event are extra data ON a tag — same rows, same counts — so each of those lists was this list cut one way, and the cut is now a row in its left column (see [Subjects and faces](subjects-and-faces.md), [Places](places.md), [Events](events.md)). A tag **set** is a tag set the same list can be pointed at, so it is a pill above it, with the library as the first pill; see [Tag sets](tag-sets.md).

**The list is part of the address**, so you can bookmark it, reload it, and step back with the browser's Back button: the tag table is the plain `/tags`, the meta tags are `/tags/links`, and a tag set is `/tags/tagsets?set=7`. The retired sub-tab addresses (`/tags/subjects`, `/tags/places`, `/tags/events`) still land on the tag list narrowed to that kind, and `/tags/faces` and `/tags/rankings` land on the tag list rather than being redirected across to the tabs those moved to. The tab remembers how you left it — which list was open, its filters, search, and sort order — even after you visit the Library and come back. Switching lists by hand clears that list's filters, since they mean different things in each.

## The left column

Beside the list, a fixed head and two blocks say what it can be narrowed to. The head does not scroll — these are the rows you press to get back OUT of a category, and a way back that scrolls away is one you have to scroll back for:

- **Everything**, with what the whole tag set holds.
- **Subjects**, **Places** and **Events** — one row for each kind the library has any of. Picking one narrows the list AND changes the rows' shape: the record's own name leads and the tag drops to a subtitle beside what only that kind knows.
- **Uncategorized**, the names filed nowhere. It takes a drop too, which is how a name comes back OUT of a category.
- **Meta**, the labels on the names — the other list this pane leads to (above).

Then, in the scroller:

- **Categories** — a tree you author. **Filing is a drag**: carry the picked rows from the list onto a category and they are filed there, and the filing survives a rename. Categories nest, take an icon, and are **dragged to re-nest and reorder** among themselves: the top quarter of a row drops the carried category before it, the bottom quarter after it, the middle inside it. They are the same rows an imported set's categories are, edited by the same gesture.
- **Namespaces** — derived from the names, never authored: the text before a tag's first colon, listed where two or more names share it. Picking one flattens the list, since every row then shares the prefix.

The search box over the two blocks narrows **both** — categories and namespaces alike, each row marking the part that matched — and a block the needle has emptied loses its heading with its rows. It appears wherever there is a category or a namespace to hunt through, and stays while you are typing even when nothing matches.

Every pickable row is in ONE selection (a click picks one, ⌘ adds, shift takes the run, a press-and-drag paints), and several picked are the **union**: a category and a namespace together list the tags in either.

## How tags work

- A tag's name is a slug (`albert_einstein`, `red_dress`), and names are unique. Lowercase is the app's own convention: every tag field commits lowercase with underscores for spaces, though the API accepts mixed case (an import or an older library can carry it).
- A name may contain **colons** (`costume:tiger`, even `costume:hat:straw`). The part before the first colon is a namespace by convention only — search, counts and implications know nothing of it. The Items list does fold by it: a foldable parent row appears for every prefix two or more tags share, carrying the group's totals (the filter menu's **Laid out** section switches between *Grouped by namespace* and a *Flat list*). Typing `costume:` in a tag field narrows to that prefix, and the tags the app invents for subjects, places, and events use the prefixes set in [Settings → Tagging](settings.md) (`subject:`, `place:`, `event:` by default). A colon is an ordinary character wherever it stands, including at either end: `:d` and `d:` are two different tags, and both are spellings the booru tag sets use. Only **whitespace** is changed in a typed name, to underscores.
- A tag can be assigned **positively** ("this applies") or **negatively** ("this pointedly does not apply") on an item.
- An item can carry a tag **directly**, or **indirectly**: inherited from a library group whose tags flow down to its items, implied by another tag (see below), or — for a sequence container — carried by any of its members. Searches and counts include indirect assignments, so what you see in the table matches what a search returns.
- A tag can also be described at length by a [tag set](tag-sets.md) — an imported list of names with a sentence on each, kept apart from the library's own tags and offered in every tag field.
- Tags can carry a **comment** and a **description** — what the tag is, at two lengths. The comment is one line and rides wherever the name does: beside it in the tag table, as the secondary text in every tag autocomplete. It is what tells two similar tags apart (`einstein` — "physicist"). The description is the long form, with line breaks: what the tag covers, when to reach for it, what it is not. It appears nowhere by itself — a **?** after the name opens it, on hover or pinned by a click — so it can be paragraphs without crowding a list. Meta tags carry the same pair. A **subject, a place and an event carry no comment of their own**: each is extra data *on* a tag, so what it is in a line is that tag's — one field, one editor, and every list shows the same answer.
- A tag can also carry extra data that makes it a [subject](subjects-and-faces.md), a [place](places.md), or an [event](events.md) — a small person, pin, or calendar icon after the name marks it, and the icon's tooltip spells out the full name or address. Clicking the icon opens the list where that half of the tag is edited.

## Implications

Each tag can **imply** other tags. Assigning a tag implicitly assigns everything it implies, transitively: tagging an item `poodle` (which implies `dog`) makes it match a `dog` search as well.

- A tag may imply several tags at once — `poodle` can imply both `dog` and `pet`. Implications form a graph, not a tree.
- **Cycles are refused**: a tag cannot imply itself, directly or through a chain.
- Implication follows the **positive** assignment only. "Not a poodle" says nothing about dogs, so a negative assignment implies nothing.
- In the table, what a tag implies reads under its name as a grey subtitle (`→ dog, pet`).

## Aliases

An alias is a second name for an existing tag. Assigning a tag whose name matches an alias — anywhere in the app, whether picked from autocomplete or typed — always assigns the linked tag instead.

- An alias is shown with an arrow to its target (`old_name → new_name`); clicking the target jumps to that tag's row. Its count columns are blank, since an alias is never assigned directly. **Its row is nested under the tag it spells**, one indent past it — the shape a namespace's names have under their parent row — in every order, since an alias carries no number and no place of its own. One whose target the filter took away stays where it is, unindented: an indent under nothing would read as a child of whatever ended up above it.
- An alias carries **no comment and no description**. It is a second spelling of another tag, so what it means is that tag's to say — making a tag an alias clears the pair it had.
- When you create an alias, the destination is **picked, never typed into existence**: the field offers only real tags, and refuses a name that matches none.
- An alias can be neither side of an implication, and a name that already belongs to an existing tag cannot be added again — as a plain tag or as an alias.
- An alias's delete button appears when you hover its row.

## The tag table (Items)

**The library's names and an imported set's are ONE list.** The pills above the table are the tag sets — *Library* first, then every [tag set](tag-sets.md) — and picking one changes which tag set the same two columns are about. The same header band sorts it, the same left column files it, the same rows select, drag and search; what changes is the **columns** and the **verbs**.

The columns are the tag set's own: the library counts pictures three ways (**Positive**, **Implicit**, **Negative**), an imported set carries **Library** (how many pictures this library has under the name) and **Count** (what its file claimed). **Category** is drawn for both — every tag set files its names in a tree of its own — and stands down only where one leaf category is picked and every row would say the same thing.

The verbs are the tag set's own too. A library tag is renamed, merged, hidden from the autocomplete and deleted; a set's name is *advice*, so its row offers to **add the tag to the library** or to **make the library's tag say what the set says**, and its editor is the entry's (its description, its count, what it entails, what it says the tag IS).

The table shows each tag with its implications and **effective counts** of positive and negative assignments — the number of items the tag matches directly or indirectly, exactly what a search for it returns. An **Implicit** column between Positive and Negative shows how much of the positive count is indirect; it is sortable, blank when zero, and absent altogether while no tag in the library has an indirect assignment.

- **Clicking a count** jumps to the [Library](library.md) filtered to those items. A positive count filters on `tag`; a negative one on `-tag` (items where the tag is assigned negatively — distinct from `!tag`, which means *not positively tagged*). See [Search](search.md).
- **Selecting rows**: each row has a checkbox (with a select-all in the header), and clicking anywhere on a row's background selects it (⌘/Ctrl adds and removes, shift extends the range). Press and drag across rows to select a run of them; the row the drag starts on decides whether you are selecting or clearing.
- One **filter menu** holds every way the list narrows, in labeled sections: **What it names** (Any kind, Plain, Subjects, Places, or Events), **How it relates** (Any relation, Aliases, or Implications), **Laid out** (Grouped by namespace, or Flat list), **Pictures** (Names only, or **Representative items** — a strip of up to eight pictures carrying the tag under each row, the Subjects list's face strips for tags; hover one for a ✕ that says *not representative*, which is remembered until the tag leaves that picture and puts a random other in its place; click one for the preview overlay, which then steps through the tag's other representatives; double-click one to show it in the library), and **Narrowed to** (Everything, or **On no item** — tags with no assignments at all, with a count: a look before a delete). The button names whatever is currently narrowing ("Subjects · Aliases", "On no item (12)").
- Beside the hover pencil each plain tag row carries a **⋯ menu** — *Add subject*, *Add place* or *Add event* over that tag, or *Edit* the record it already is. All six open the **same tag editor** at the section they name (see below); Add arrives with it open and empty, its display name prefilled from the tag's basename. A right-click opens the same menu. **Right-clicking a selected row while several are selected** opens a menu for the whole selection instead — **Merge N…** and **Delete N**, the toolbar's own two actions with their counts; a right-click on an unselected row stays about that row and leaves the selection alone.
- A tag's pictures *somewhere else* (a booru, an archive, another machine) are counted **per meta-tag assignment** — "abc" can carry tumblr 50 beside twitter 100 — and each counted assignment's capsule behind the name shows its figure ("TUMBLR 50"). The counts come from the [CSV import](#csv-import-and-export)'s count column and are never added to a count the app displays; they break ties in the ordering of the tag autocomplete (equal library counts sort by the highest per-meta figure, the only order a freshly imported dump has), and hovering an autocomplete row's count lists them. Nothing joins them to a count: [training](training.md)'s inverse-frequency balancing could once measure a tag's rarity against them, under the name the tag-level offset left behind, and that option went with the offset. (The per-meta counts replaced a single tag-level "count offset", which could not say where a number came from.)

## Creating and editing tags

- The **Add** button creates a new tag or an alias.
- **Hovering a row reveals a pencil** that opens the tag editor — the one place a tag's name, comment, description, implications, and aliases are edited:
  - **Name.** Renaming updates every item carrying the tag directly; when the tag has assignments, the field says so ("On save, all N items carrying this tag are updated.").
  - **Comment** — the one line shown beside the name.
  - **Description** — the long form, with line breaks; a **?** beside the name opens it wherever the tag is listed.
  - **Implies**, as a list with a remove button on each and an autocomplete to add more. A tag that doesn't exist yet is created on the spot. Implication rows select with the usual gestures, and with two or more selected a **Remove N** button appears.
  - **Meta tags** — what the *tag set* says about this tag (see below). The same list, with an autocomplete over the meta-tag namespace; each row carries a small count field for that assignment's figure ("no count" while empty — see the per-meta counts above).
  - **Aliases** — the tag's other names, as the same kind of list; removing one deletes that alias.
- Under a rule, three sections say **what the tag is**: **Subject**, **Place** and **Event**. Each is a row with a **+** until the tag is one of those, and its fields under it once it is; the **✕** in an open section's header takes the record away while the tag stays. A tag may be more than one of them.
  - **Subject** — the display name and the exists-since date.
  - **Place** — the one-line name, the coordinates with an offline world map beside them, and the place it is **inside**.
  - **Event** — the display name, the **From** and **To** partial dates, the **places** it was at (picked from the library's own, with a **New** beside the field that opens this editor a level down — a venue is a place and a place is a tag) and what it is **part of**.
- While the tag's name is still the slug the record's display name derives, typing into that display name **rewrites the tag name in front of you** (with the [namespace prefix](settings.md) its kind is given); typing into the name field yourself stops it.
- Nothing in the editor is applied until **Save**; Cancel leaves the tag exactly as it was. The editor's subtitle counts the assignments (`6 positive (3 implicit) · 0 negative`).

## Merging tags

Renaming a tag onto a name that already exists is not an error — it is a **merge**, and the save button becomes **Merge…**. Confirming moves everything the tag carries onto the other: every item assignment (with its tag groups, boxes, and time ranges), what it implies and what implies it, the library groups that assign it, its aliases, and its meta tags. A checkbox on the confirmation decides what happens to the old name: kept as an **alias** of the target (the default), or deleted.

With **two or more mergeable rows selected** — an alias does not count — a **Merge N** button appears next to Delete. The target may be one of the selected tags, any other existing tag, or a name that does not exist yet (it is created). The same keep-as-aliases checkbox applies.

Every item's change is recorded as its own event, so a merge shows in [History](history.md) and can be undone there — or immediately from the same undo toast a deletion gets (see below), which after a merge reads "Merged → ‹target›" (or "Merged ‹old› → ‹new›" from the editor).

## Deleting tags and the undo toast

With one or more rows selected, a **Delete N** button appears. Deleting a tag also removes it from every item it is assigned to — with a confirmation in that case. Deleting a subject's, place's or event's identity tag deletes that record with it, which the button's tooltip says whenever the selection holds one. A selection of any size is deleted in one request per few thousand rows, so even a freshly imported dump of tens of thousands of tags is gone in seconds; the button reads "Deleting…" while it works.

After a deletion or a merge, a **toast** in the accent color appears at the bottom of the window — "Deleted 3", with an **Undo** button and a small ✕. It does not time out; it stays until dismissed. Undo puts the tags back **whole**: every item assignment with its sign, tag groups, boxes and time ranges, implications in both directions, the library groups that assigned it, the aliases that pointed at it, and its meta tags. Having undone, the toast reads "The deletion was undone" (or "The merge was undone") and offers **Redo**, and the two keep swapping for as long as you press the button.

## CSV import and export

Importing lives in the toolbar's **Add** menu — adding by hand and adding from a file are the same intent at two scales — and **Export** keeps a button of its own; both lead the toolbar whatever is selected, with the selection's Delete and Merge growing to their right. The two speak the same five file shapes, so what the export writes imports back unchanged. The [Subjects](subjects-and-faces.md), [Places](places.md), and [Events](events.md) lists offer the same pair — the records are rows of the same Tags file — with the export dialog opened narrowed to their own kind:

- **Tags** — the tag table: name (required), comment and description, plus optional count columns on export. The file can also carry the **subject, place, and event records** a tag holds, field by field — Subject, Subject since; Place, Place parent, Place latitude, Place longitude; Event, Event parent, Event start, Event end — so what the export writes imports back as the same records (a tag can be more than one of them). Dates travel in the app's own partial form, `YYYYMMDD` with zeros for what is unknown (`19750000` is "1975"); coordinates as decimal degrees, the pair together or not at all. (A file from an older export still maps: the old "Place address" / "Place inside" / "Event inside" headers are recognised.)
- **Aliases** — one pair per row: the alias and the tag it stands for.
- **Implications** — one pair per row: the tag and one tag it entails.
- **Meta assignments** — one row per assignment: a tag, one [meta tag](#meta-tags-on-a-tag) on it, and that assignment's count (empty where there is none). Its own file for the same reason the two above are: a tag carries any number of them.
- **Meta tags** — the meta-tag table: name, comment, description, and the Links / Captions / Tag groups counts.

**Import** picks a `.csv` file (comma, semicolon, tab, or pipe delimiters are auto-detected) and opens a column-mapping overlay. The file's shape is guessed from its header and switchable; header names pre-guess the column mapping, and a preview shows the first mapped rows. The subject, place, and event records are one collapsible group each, with the column that **names** the thing mapped right on the group's row and the rest of its fields behind the chevron. Rows missing a required value are skipped, missing tags are created (including an alias's target), and existing tags are updated rather than duplicated. Names are normalized as they are read — "tiny giant" is imported as `tiny_giant`, and the preview shows that rather than what was typed into somebody else's spreadsheet. (Case is kept, deliberately: the API accepts mixed case precisely because an import can carry it.) The tag table itself imports in **batches** — one request and one transaction per two thousand rows, the "Mark every tag with" names riding along in each — so a booru dump of tens of thousands of tags lands in seconds, each creation and each mark still logged as its own revertible event. A row that lands is complete: its fields, its count and its marks arrive in the same transaction (the subject, place and event records it carries are written in a second pass, a few rows at a time). A row the API refuses is reported and skipped while the rest of the file goes on; a row refused because another write held the library for a moment is simply retried. Closing the dialog mid-import stops the run — the rows already in flight land, nothing further starts, and what was imported stays imported.

Everything about the **count** is one group of the same shape: the **Count** column dropdown sits on the group's own row, and behind its chevron wait the two settings that only mean something once a column is picked:

- **Skip rows under a count of** — a booru dump is tens of thousands of tags, most of them used twice, and this is how you take the useful end of it.
- **Store the count on** (don't store) — a **meta tag**, usually the site the dump came from. Named, the count is saved on that meta tag's *assignment* (which the import also puts on every counted tag), so "abc" can carry tumblr 50 beside twitter 100 — which one tag-level number never could; empty, the count is only read by the minimum. A second row, **If an assignment has a count**, then picks the count's own conflict policy for an assignment that already carries one — *Keep the number it has*, *Replace it with the file's*, *Keep the smaller number* or *Keep the larger number* (a newer dump replaces; merged crawls of one site usually keep the larger). Its own policy, read from none of the text-field rules below; an assignment with no count yet always takes the file's number, since there is nothing to compare.

Two more settings are facts about the whole file rather than columns in it, so each is a field and not a mapping:

- **Where the library already says something** — the last row of the mapping panel, a three-way choice over every mapped text column, the subject, place and event fields included: *Fill in the gaps only* (the default — the file only fills in what the library has not said), *Update what the file maps* (every mapped column of every tag the file names takes the file's value), or *Match the file exactly* (the same, and a column the file leaves empty clears the library's value). Importing over a library you have curated does not quietly rewrite your own words unless you ask it to.
- **Mark every tag with**, in a **Counts and marks** section after the count group — meta tags put on every tag the file names, **tags the library already has included** ("these are all characters", "none of these should be flipped"). The names are picked from a list of the meta tags you already have, with a *Create* row for a name none of them matches — a typo here would mint a meta tag and put it on every tag in the file, so look before taking that row.

The **Aliases**, **Implications**, and **Meta assignments** shapes take a **Split several values on** setting. Empty, a cell is one value — the shape the export writes. Set it to `,` and a cell reading `x, y, z` becomes three rows against the same tag, so a file that lists a tag's aliases in one field imports as it reads. Several rows for one tag combine, a pair the file names twice is imported once, and nothing already in the library is removed: these imports only ever add.

**Export** lets you tick which columns the table files carry and **drag them into order** — that order is the file's column order, and both it and which columns are ticked are remembered between exports (a **Reset order** button appears in the footer once the order has been dragged off the default). A **Which tags** filter narrows the Tags file to one kind — all tags, subjects, places, or events — and is pre-set to the list the Export button was pressed on. Everything starts ticked; the Subject, Place and Event groups drag as whole blocks by their own line, and their columns drag within them. While the Meta list is showing, only the meta-tag shape is offered on both sides.

## Meta tags

**Meta tags** are the free-form labels on item links, on captions, on a single item's tag groups — and on the library's own **tags**. They are a separate namespace from item tags — no aliases, no implications — and are managed under the **Meta** row of the left column:

- Instead of positive/negative counts, each meta tag shows one count per carrier: **Links**, **Captions**, **Tag groups** and **Tags**, each its own sortable column.
- The **Add** button opens the same dialog the pencil does, with nothing filled in — a meta tag is a name, a comment and a description, and the inline strip this replaced could take only the name. Deleting a row removes the tag from every carrier that used it.
- A meta tag is **not deleted automatically** when its last use is removed — it stays in the list with all counts at zero so it can be reused. The **On no item** filter narrows to exactly those.
- Names are normalized to lowercase with underscores for spaces, like item tag names.
- Hovering a row reveals a pencil that opens the meta-tag editor — name, comment and description, with a subtitle spelling out the carriers ("3 links · 1 caption · 0 tag groups · 2 tags"). Renaming rewrites the tag on every link, caption, tag group and tag at once, and the field says how many carriers that is before you save.
- **Renaming onto an existing name is a merge**: every carrier of the old name carries the new one instead, and the old name goes (meta tags have no aliases). With two or more rows selected, a **Merge N** button folds them into one target — one of them, another meta tag, or a new name.
- Each rename is recorded in [History](history.md) and can be reverted there.

**A tag set has meta tags of its own.** Its left column carries the same row, and what it lists are the labels that tag set puts on its own names — a set that knows `hatsune_miku` is a `character` is saying something a library would otherwise have to be told once per name. An entry's **Meta tags** field says which ones it carries; a label the set does not know yet is made with the save, the way an implied name is. They travel in the [tag-set file](tag-sets.md), and the door carries them over — as ordinary, revertible assignments, with the set's comment and description for a label the library has not heard of — at the one moment it creates the library's tag. What the library already says about a label of that name is left alone, and the two tag sets never see each other's: a set's labels are its own advice until a name of its is assigned.

### Meta tags on a tag

A meta tag on a **tag** says something about the tag rather than about any
picture carrying it: `noflip` (mirroring this would be wrong), `character`,
`from a booru`. It never reaches an item, so search counts, training prompts
and export see no new tag — what changes is what can be asked about the
tag set itself.

- They are added and removed in the **tag editor**, which is where a subject, a
  place and an event are edited too — each of those is extra data *on* a tag, so
  it is that tag's list.
- They show as small capsules behind the name in the **Items**, **Subjects**,
  **Places** and **Events** lists and in every tag **autocomplete** row (the
  counted ones first there, their figures compacted — "tumblr 1.2k"), and
  nowhere on a picture: a capsule on a picture's tag row would read as a label
  on the picture. A row shows as many as fit — measured, at least one — and
  counts the rest (`+10`, whose tooltip lists them all); the name always keeps
  its full width, and the capsules give way before it.
- [`TAG:noflip`](search.md) finds every picture carrying a tag marked that way
  — the same required/excluded capsules `CAPTION:` and `LINK:` use.
- A [training](training.md) run can name tags by what they are marked with
  instead of one by one: never mirror the pictures carrying such a tag, always
  include or always exclude those tags from prompts, and gate a degraded copy
  on them. The rule is then stated once here, and a tag added later carries it
  automatically.
- The [tag CSV](#csv-import-and-export) has a **Meta assignments** shape (one
  row per assignment), and the tag import can put a set of meta tags on every
  tag it touches — existing ones included.

## Related pages

- [Tag sets](tag-sets.md) — imported tag lists that advise the autocomplete
- [Subjects and faces](subjects-and-faces.md) — people and face detection
- [Places](places.md) — locations
- [Events](events.md) — time spans and venues
- [Search](search.md) — the query syntax tags feed into
- [Item properties](item-properties.md) — assigning tags to items
