# Places

A place is where a picture is — location data attached to a tag, so assigning a place is assigning its tag and search, counts, and facets need nothing new.

## What a place is

A place record on a tag can carry a **name**, a **coordinate pair**, and
the place it is **inside**. What the place *is*, in a line and at length, is
its identity tag's [comment and description](tags.md).

**The name is one free text field**, and it is the only text a place
carries. One field says everything a structured address would, refuses
nothing, and allows "the corner of the old market" or "Bob's house" as
readily as a street and a postcode.

## Inside

A place can be **inside** another: Tokyo Tower in Tokyo in Japan. One optional
parent each, set in the place form, and the Places list draws the result as a
tree you can collapse.

**Assigning a place assigns everything above it.** That is not a second
mechanism — a place is a tag, so putting Tokyo Tower inside Tokyo writes an
ordinary [implication](tags.md#implications) between their two tags, and
search, counts, facets, training and export need to know nothing new. A
picture at Tokyo Tower answers a search for `tokyo` because it genuinely
carries that tag.

## The place form

The form reads in that order: the **name** first — labelled that way
so that "Bob's house" reads as welcome as a street address, and it is
**required**, since it is the whole of what a place says and what its tag is
derived from — then the comment and description that say what it is, then the
**coordinates**, the identity **tag**, the **parent** it is inside, and last
the tag's [meta tags](tags.md#meta-tags).

Coordinates can be pasted from a map, and are drawn on a small world map
beside the field — always shown, greyed out until the numbers are a real
position. The outline ships with the app (fetched from its own bundle the
first time a map is drawn) and the marker is plotted from the numbers, with no
tile service involved. Emptying the field and saving takes the pair off the
place.

The parent autocompletes over the places you already have, and offers to
**make one** from what you typed — the alternative is leaving the form to add
the parent and coming back.

A place with no coordinates is an **abstract place** — "Bob's House", a line
and nothing else. It is assignable and searchable like any other place; it
simply cannot be put on a map.

## Places on an item

In the sidebar ([item properties](item-properties.md)), **Places** is a tab of its own, between Subjects and [Events](events.md) (⌘-click the tabs to keep several open at once):

- One row per place, with its short form (the name, or its tag where there is none, up to the first comma; the tooltip carries the whole line).
- Above the places, the item's own **coordinates** — where this picture was taken. Type a pair, or leave it **Automatic** (a coordinate somebody kept on the item answers first, then the file's own GPS); "It has no coordinates" is a third answer of its own, which is how a wrong fix off a borrowed camera is removed rather than merely replaced. They are drawn on a small world map that expands on click, and the row's subtitle names an automatic source ("from the file's own coordinates") — what you typed gets no subtitle.
- A ⋯ menu on the row: **Edit place…** (which says plainly that a place is shared, since editing it changes every item that carries it, and which opens the [tag editor](tags.md) at its Place section), a search for every picture at it (**Find every picture with this**, plus **Add to the search** while a search is already active), and removing it from this item.
- An adder that autocompletes existing places or opens the form for a new one.
- Under those rows, a **Suggested** heading gathers the offers: the venues implied by the item's [events](events.md), and the place the photo's own file names (below) — see [Events](events.md#suggestions) for how accepting and dismissing work.

## The place a photo's own file names

Import **never creates a place** — a crawl of random downloads would fill the Places list with strangers' coordinates. What a photo's metadata says about where it was taken is indexed like everything else it says about itself, and stays visible and searchable (`INFO:location`, `INFO:gps_lat`):

- **Named location text** (XMP/IPTC sub-location, city, state, country) is offered as a **suggestion** in the item's Places section, marked *Written in the file itself* — the address on one line, finest first. Accepting it creates the place (or reuses the one already called exactly that, giving it the file's coordinates if it had none) and assigns its tag, which is minted from the finest component with the [place prefix](settings.md#prefixes) (`place:shibuya`); declining makes the offer stay away. Nothing happens until you answer.
- **Bare GPS coordinates** are a fact about the *picture*, not a place: the item's own coordinates read them directly (the map in the sidebar), and no place row is minted for them at all.

## The Places list

The **Places** list — the [Tags tab](tags.md)'s Items list narrowed to Places, which is where its own sub-tab went — shows each place's name with its tag's comment, the `?` that opens its description and its meta-tag capsules beside it, its coordinates underneath, its identity tag, and its picture count, with the same row selection, ⋯ / right-click menu and deletion behavior as the other lists. Deleting a place from here keeps its tag on the pictures (the confirmation says so); deleting the identity **tag** in the Tags list takes the place with it.

An **Unnamed** filter narrows to the places that carry no identity tag — ones an older library minted from bare GPS pins and brought across in a merge. **Naming an unnamed place** — filling in its Name in the edit form, which the tag is then derived from — mints its tag and moves every pinned item onto it.

## Searching by place

Search matches over the location data of the tags an item carries:

- `PLACE:Shibuya` — the name of a place the item is at contains that; `PLACE=Tokyo` — it is exactly that.
- **The name is all this matches.** To ask for one particular place, search its **tag** (`tokyo`), which is what an item actually carries — that is exact, and it also finds the sequence containers whose pages were taken there.
- A place **inside** another needs nothing special: the child implies the parent, so searching for `tokyo` finds the pictures taken at Tokyo Tower.
- `PLACE:` — has a location at all; `!PLACE:` — has none.

The query builder has a **Place** row for the same thing (is at / is not at · is / contains · the value). Both it and the search field complete values from **what your library actually holds** — a city nobody has tagged is never offered. See [Search](search.md).

## Related pages

- [Tags](tags.md) — the tag system places are built on
- [Subjects and faces](subjects-and-faces.md) and [Events](events.md) — the other kinds of data on a tag
- [Import](import.md) — what a file says about where it was taken is indexed there, and offered here
