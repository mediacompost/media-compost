# Events

An event is what was happening when a picture was taken — a time span and venues attached to a tag, so assigning an event is assigning its tag and search, counts, and facets need nothing new.

## What an event is

Like a [subject](subjects-and-faces.md) or a [place](places.md), an event is extra data on a tag. The record adds:

- A **name** with its spaces and capitals — "San Diego Comic-Con 2014" is not a slug. Required: it is what the event IS, and what its tag is derived from. (What the event is, in a line and at length, is its identity tag's [comment and description](tags.md) — the same one-home rule subjects and places follow.)
- A **span of days** — two partial dates, so a year, a month, or a full date all work. Leaving the second date empty means the event was the one day (or year) the first names. A span that ends before it starts is refused.
- The **places** it was at. An event's places must be **named** places, picked from the library — the venue field completes from the Places list, and a name it does not know (or the **New** button beside it) opens the place form so the venue can be made on the spot and chipped in. They are what makes the suggestions below possible.
- The event it is **part of**: Day 1 of NY Comic Con 2026, which is part of Summer 2026. One optional parent each — the field can create the parent it is given — and **assigning the day assigns everything it is part of** — the same mechanism a [place's parent](places.md#inside) uses, an ordinary tag implication between the two identity tags. The Events list draws the result as a collapsible tree. (An `EVENT:` search reads the event's *own* assignments only, so a picture tagged with the day answers `EVENT:` for the day and a plain tag search for the parent, but not `EVENT:` for the parent.)
- Its identity **tag**, derived from the name with the [event prefix](settings.md#prefixes) (`event:san_diego_comic_con_2014`) unless you type one — an existing tag no other event owns is adopted — and the tag's [meta tags](tags.md#meta-tags).

## Creating and editing events

The **Events** list — the [Tags tab](tags.md)'s Items list narrowed to Events, which is where its own sub-tab went — lists every event — as a tree, children under what they are part of — with its venues under the name, the span, the identity tag, and the picture count, each sortable. A hover pencil opens the edit form; the list's **Add** menu makes a new event with the same form, and so does committing a name the sidebar's *Add an event…* field does not know. A plain tag can become an event after the fact from the Items list's ⋯ menu (**Add event…**), which opens the form over that tag.

Deleting an event keeps its tag — the pictures were still taken at whatever it was. (The API can take the tag with it; the app never does, and when the event is on any picture its confirmation says the tag is kept.) The other way round, deleting an event's identity **tag** in the Tags list deletes the event with it.

## Suggestions

An event knows where it was, so it **offers** its venues: a picture carrying `event:san_diego_comic_con_2014` gets the convention center and the hotel shown in its **Places** section under a *Suggested* heading — dashed and muted so they never read as assigned, each naming the event that prompted it, each with a tick and a cross. They are never assigned automatically, because half of a week is spent somewhere else. (The same heading also carries the place a photo's own file names — see [Places](places.md#the-place-a-photos-own-file-names).)

The same works in reverse: a picture whose **capture date** falls inside an event's span gets that event offered in its **Events** section, saying which date put it there. Where no capture date is indexed and the picture carries no event, the section says so rather than showing nothing.

- **Accepting** a suggestion is nothing special: it assigns the tag, and is logged and undone like any other tagging.
- **Dismissing sticks.** A dismissal is recorded per picture and per thing, and it survives everything: editing the event's venue list cannot resurrect it, and a second event at the same venue does not ask again. It is *not* a negative tag — it says only "stop offering this", and the place stays a perfectly good thing to assign by hand later. Every dismissal is in [History](history.md) and can be undone there, which is the only way one comes back.

## When the picture was taken

"When" sits at the top of the Events section, because "when" and "what was happening" are the same question asked two ways. It has **three answers**, and the sidebar says where an automatic one came from ("from the file's EXIF data", "from the event below"); a date you typed carries no label — that it is yours shows in the menu, where *Automatic* sits unticked:

1. What somebody **typed** — an override.
2. The capture date **from the file** (EXIF).
3. The span of the **events the picture carries** — a photograph from a convention that ran January 5–10 was taken then, which is the most anyone can say and is enough to find it. A search reads the whole span; the sidebar's row shows the earliest day an event it carries began.

A picture with a date of its own never inherits one from its events — that is the point of having typed it. The precision is whatever you write: "2020" is a year, "March 2020" a month, "5 March 2020 14:30" a minute (a time only counts after a full date — after a month or a year alone it is dropped), and a search reads each as the window it is.

The ⋯ menu sets or changes the date. It also offers **"It has no date"** — an answer, not the lack of one, which is what stops a scanned print's scanner date from being read as a real capture date. Once you have said either, picking **Automatic** falls back to the file and the events again. Typing a date never touches the file's own metadata, so a re-index can never throw a typed date away.

## Searching

### By event

- `EVENT:` — was the picture at some event at all.
- `EVENT:event:san_diego_comic_con_2014` — names one, by its tag.
- `EVENT:@2014` / `EVENT:@2014..2016` — bounds the event's **own** span, not when the picture says it is from (that is what `TAKEN:` reads).

The match is an **overlap**: an event running December 30, 2014 to January 2, 2015 answers both years, because it did. A bound only narrows, so an event nobody dated satisfies none. `EVENT:` reads the events assigned to the picture itself, not the ones those imply — a day's picture answers for the day, and for the convention it is part of only through a plain tag search.

### By capture date

- `TAKEN:` — does anything say when the picture was taken.
- `TAKEN:@2020-01-01..2020-01-07` — bounds it. A partial date works too: `@2020` is the whole year, and a time is written after a `T` (`@2020-03-05T14:30`).
- `!TAKEN:` — nothing dates the picture, including the ones you have said have no date.

The match is an overlap, like `EVENT:` — a week-of-January window finds a picture dated only "2020", and one from a convention running January 5–10 — while a picture that says January 8 outside the window is left out, because the specific answer beats the inherited one.

See [Search](search.md) for the full query syntax.

## Related pages

- [Tags](tags.md) — the tag system events are built on
- [Places](places.md) — the venues events point at
- [Subjects and faces](subjects-and-faces.md) — dating people in pictures
- [Item properties](item-properties.md) — the sidebar's Events section
- [History](history.md) — undoing assignments and dismissals
