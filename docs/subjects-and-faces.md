# Subjects and faces

A subject is who or what a picture is *of* — a person, an animal, a building — and faces are the detected evidence of where in a picture somebody appears.

## What a subject is

A subject is not a second catalog beside the tags: it is **extra data on a tag**. Assigning a subject to an item assigns that tag; its picture count is that tag's count, and search, facets, aliases, and training all work with nothing new. What the subject record adds is what a tag alone cannot say:

- **A display name** — "Albert Einstein", with spaces and capitals. The tag keeps its slug (`subject:albert_einstein`, with the prefix the [Tagging settings](settings.md) give app-invented tags), and you never have to type it.
- **Two people can share a name.** Tag names are unique, so two people called Michael Jordan could never both be `subject:michael_jordan`. As subjects they share a display name and are told apart by their identity tag's comment ("basketball" / "actor"); their slugs differ quietly, and the second is offered as `subject:michael_jordan_2`.
- **An identity with no name at all.** A detected face cluster is somebody before anyone knows who — and a tag cannot be nameless. Such a subject has no tag until it is named; naming it mints the tag and back-fills it onto every picture the identity was already known to be in, as one undoable step.

Each subject may also carry an **Exists since** date — born, built, founded, released. It is a **partial date**: `1975`, `July 1999`, and `14 March 1879` are all valid, at different precisions. Its job is to turn a year into an age and back.

### Dates and ages on assignments

Each assignment of a subject to an item can carry a **date and an age**, and either derives the other from the since-date as you type. The date lives on the assignment, not on the item — which is what lets two people in one photo carry two different ages, and makes a collage of pictures from different years describable.

## Face detection

Media Compost ships two detectors, because a library often mixes drawn art and photographs:

- **Illustrated faces (YOLOv8 + Magi)** — for drawn art, anime, and manga. A YOLOv8 detector finds the face and Magi's character embedder describes it, so drawn faces get clustering and name suggestions too.
- **Photographic faces (InsightFace)** — for photographs, with descriptors that power clustering and suggestions.

Face descriptors are computed and compared entirely on your machine.

You can run detection from several places:

- **At import** — enable the *Detect faces* option in the [import](import.md) dialog and pick a detector; detection runs as one background job over the images the import created.
- **From the sidebar** — the *Detect* section in [item properties](item-properties.md) offers face detection for an image, and for a sequence whose members are stills (a comic chapter is detected page by page, as one job with a progress bar).
- **From the annotator** — the Subjects tab in the [annotation editor](annotation-editor.md) carries the same button, and while it is open the faces are outlined on the picture; you can also draw a face box by hand there.
- **Over a whole group** — right-click a group in the Library's group tree and pick a detector under its *Detect* section: the run covers everything in the group, items that detector has already looked at are skipped, and the menu reports how many were.

The app remembers which detectors have already run over an item — the Detect menus **tick** them, so a second run is a choice rather than a guess. Re-running detection is always safe, and running the *other* detector over the same picture is a normal next step in a mixed library:

- A detection that matches a known face refreshes its geometry and descriptor only — who it is never changes.
- A face the run did not find is left alone (it may have been drawn by hand).
- A dismissed face absorbs its detection, so the same false positive is not offered again.
- A face found by several detectors becomes one face, credited to both ("Illustrated faces (YOLOv8 + Magi) + InsightFace").
- A hand-drawn face can never be removed by a later run.

### Faces in the sidebar

Detected faces appear as a list in the **Subjects** tab of [item properties](item-properties.md): the crop, which detector found it ("Detected by …", or "added by hand"), and a hover that outlines the face in the whole picture. A row's title says how many people are on the face ("1 person", "3 people") — the names themselves are in the person rows beneath, so the face row does not repeat them — and only an unnamed one asks "Who is this?". Clicking the title opens the name field — which is also how a second name is added to a face.

A row's ⋯ menu offers one way out, and where the face came from picks it: a **detected** face is dismissed ("not a face"), which is the answer that sticks — a dismissal absorbs the next detection over the same box. A face somebody **drew by hand** is deleted instead ("added by hand", says the row): nothing ever detected it, so there is nothing to stop offering. The same menu holds **Reset the box** while a detected face's rectangle has been moved or resized by hand in the [annotator](annotation-editor.md) (the detector's own rectangle is kept aside, and later runs refresh that rather than the edit) and **Remove the outline** while the face carries a whole-figure outline.

A face you dismissed is not thrown away: it shows grayed out behind a link at the bottom of the section, where you can restore it ("it is a face after all") or delete it for good.

## Naming faces, guesses, and suggestions

**Naming a face assigns that subject's tag to the item** — that connection is the point, since the tag is what search, training, and export read. The subjects you named most recently come first in every name autocomplete.

Once a subject has confirmed faces, the app can **suggest** names for new ones:

- A guess shows as "Alice?" with its score ("87%") beside it, a tick and a cross. In face-crop strips, a guessed crop wears an **amber border**.
- A guess assigns the tag too, but **pending** — search, training, and export leave it alone until somebody agrees.
- The **tick accepts** the guess (the tag becomes a real assignment). The **cross rejects** it, takes the pending tag back off, and **records the refusal**: no later run will offer the same wrong name for that face again. Naming the face as somebody else records the refusal too.
- **Dating a guess accepts it** — writing an age onto a face is agreeing it is that person.
- A suggestion never overwrites a name you gave by hand; only your confirmed answers feed the suggestion pool. A guess is withheld when the best match does not clearly beat the runner-up — two people alike enough to tie get no name.
- Suggestions are made at the end of a detection run, and again the moment you name a face or a cluster by hand: the lookalike unnamed faces get their guesses right away.
- How alike is "alike enough" is a setting: **Settings → Faces → Minimum face similarity**, a slider from 30 to 99%. See [Settings](settings.md). It is one knob for both detectors — each descriptor space reads it at its own scale, so it never needs calibrating per model.

Items with unanswered face guesses appear under the **Pending → Faces** scope in the Library sidebar, so reviewing them is a queue you can work through.

## The Faces tab

**Which crops are one person** is its own tab in the main navigation
(`/faces`), and it is **two columns**: every cluster as a row down the left —
its cover crop, its name or *Unknown*, how many faces it holds and how many
of those are still a machine's guess — and the picked cluster's crops in the
grid beside it. A search field narrows the rows by name; the **S / M / L**
control sizes the crops.

It used to be two lists inside the Subjects sub-tab: people with their crops
under them, then the clusters nobody had named. The question a person is
answering is the same for both — is this one person, and who — and two lists
meant carrying a crop from one to the other to say so.

**Which cluster is open is simply which row is picked**, so the crops on the
right are that cluster's as it is *now*: answer something and the grid
follows, without a place to navigate back to.

### Naming

The **empty name slot is a control**, not a placeholder. Pressing it — on the
row, or on the heading over the crops — opens *Who is this?* over the subjects
you already have, most recently named first, and takes free text for somebody
new. Naming mints the subject where there is no such person yet and puts its
tag on every picture the cluster's faces sit on — one action, one undo.

### Selecting

Both columns select like the library's grid: a plain click picks one and drops
the rest; **⌘/Ctrl** adds and removes; **shift** takes the run; **dragging
across** paints, picking up everything the pointer crosses — or putting it
down again, when the drag starts on something already picked.

**A crop drags onto a cluster row**, which is how a face is moved by hand: a
picked crop carries the whole selection, an unpicked one goes alone (the
library grid's rule). Dropped on a row with a person, it is assigned to them;
dropped on a nameless one, the two are merged. A **cluster row drags onto
another row** too — the merge that says these are all one person, whoever
they are.

A row's **⋯** (and its right-click) holds **Who is this? / Change who this
is**, **Merge**, **Show tag** — which goes to that tag's row in the tag list —
**Not faces** and **Delete**, each speaking for the whole selection when the
row is part of one.

### Grouping and narrowing the crops

Over the grid sits a row of **capsules, one per tag the crops carry**, with a
verb in front of them saying what ticking one does: **Group by** (a section
per combination the crops carry), **Filter** (only the crops carrying every
ticked tag) or **Exclude** (drop every crop carrying any of them). It is one
row tall until its chevron opens it, and the ticked capsules lead the list.

Beside it, the grid's own filter menu: **Show** (every face, or only the ones
with a guess waiting), the **Might be the same person** row below (see next),
and **Grouped by** — **Age** (sections "AGE 12", "AGE 16", with the undated
last, since "nobody said" is not a point on the scale), **Sequence**, or
nothing.

The cluster list has a filter menu of its own: **Show** — *Everyone*,
*Named*, *Unnamed*, *Unknown* or *With a guess waiting*, each with its count —
and **Found by**, one row per detector that has looked at these faces.

### The right-click menu

Right-clicking a crop opens a menu. If the crop is **picked**, the menu is
about the whole selection and says so; if it is not, it speaks only of that
crop and leaves the selection alone.

It looks first, then changes: **Show in library** and **Preview** (the whole
picture with this face outlined), offered for one face only, then a rule.
Where a picked crop carries a machine's guess, **Accept the guess** and
**Reject the guess** come first among the changes. Then **Set the date or
age** (one named crop — the date belongs to the appearance, and saying it
agrees with a guess), **Not this person**, **Not a face**, and
**Delete this face**.

**"This is someone else" is offered where there is no name to reject** — a
crop in a cluster nobody has named. It asks *who*: the subjects you already
have, a name nobody has used yet, and the two answers no name can stand for
as buttons of their own — **Unnamed** (somebody with no name, below) and
**Nobody yet**, which splits the crops off as a cluster waiting for one. On a
crop that *has* a name the one-click reject is the verb instead, and the
undo bar it raises carries **Say who** — the same dialog, one press away —
because taking a name off is only half an answer.

**And the correction is evidence about the rest.** Having moved crops out, the
ones left behind are scored against both sides, and any that look more like
what left are offered over the crops as **These look more like the ones you
moved**, with a **Move them too**. Nothing is written until you press it, and
the offer goes when the cluster is closed.

**Accepting keeps the selection** — the crops do not move, the guess simply
stops being one — and everything else there takes them out of the list and
drops it.

### Might be the same person

**An open cluster gets one row of what looks most like it**, over its grid of
crops (and switched off from the grid's filter menu): as many cards as fit at the grid's own size, each with its likeness
in the bottom-right corner. "Is this the same person as that one" lives in
the descriptors, and the only way to ask it was to scroll a grid of crops
and remember.

- **A card is a crop, or a whole unanswered cluster.** A cluster nobody has
  answered is offered as one card — its cover crop, with how many crops it
  holds in the bottom-left corner — because "this cluster of twelve might be
  them" is one question, not twelve; a cluster of one is simply a face. A
  *named* person's crops are still offered one by one: they are answered,
  and the question about them is which of them is wrong.
- **No threshold.** Every neighbour is offered however unlike, because a
  cutoff hides exactly the near-misses this is for; the score says how alike
  and you decide. It is on the same scale the **Minimum face similarity**
  setting uses, not a raw number from whichever detector found the face —
  the two detectors' bands do not even overlap.
- **Which clusters are offered depends on what is open.** A *named* cluster
  is offered the unanswered ones; folding two named people together is a
  different verb in a different place, and offering it here would put it one
  click from every drill-in. An *Unknown* or *Unnamed* one is offered
  everything, since the answer may be either.
- **The row selects like the grid**: click, ⌘/Ctrl-click, shift for a run,
  press-and-drag to paint. One selection at a time — picking in the row
  clears the grid's picks and picking in the grid clears the row's — and
  the bar above then carries **Add to this cluster** and **Not this person**
  over whatever is picked.
- **Space previews what is picked**, and the preview walks it: an offered
  cluster opens on its first crop and ← → step through every crop of it,
  each on the picture it came from. **Double-clicking a card goes to its
  cluster** — its row is picked, opened and scrolled into view.
- **✚ adds it** — a whole cluster's crops at once — and **✕ is "not this
  person"**, which sticks: the pair is out of the row for good and another
  neighbour takes its place. It is the same statement a split writes, so it
  is in History and undoes from there.
- **The row is there only when it has something in it**, and a cluster
  embedded by a detector that produced no descriptors — or by a different
  one — has no neighbours to offer, which is honest rather than empty.

### Somebody with no name

**A cluster nobody has answered is *Unknown*** — the question this page is
for. Most of a library of a television series is background characters,
though, and inventing `unknown_person_3` for each of them puts junk in the
catalog and in every prompt an export writes. So there is a second answer:
the name field's suggestion list leads with an **Unnamed** row (*somebody
with no name*), and taking it says this is a person the library is not going
to name.

It takes the cluster out of the queue and puts it in the answered list,
drawn as **Unnamed**. **Each cluster answered this way stays its own
person** — unlike picking a real subject, marking two clusters Unnamed does
not fold them together, because two background characters are two people
(and naming one later must not name the other). Pressing the word opens the
name field again, so a background character who turns out to have a name is
one click from having it.

The same row is in the annotator's **Who is this?** field, for one face at a
time.

### What is not here

A subject's comment, since-date, meta tags, description and delete are facts
about a **name**, not about a crop, so they live on that tag's row in the
[Tags tab](tags.md) — narrowed to **Subjects**, where the display name leads
and the tag and since-date read as its subtitle. A row's **Show tag** goes
straight there.


## Editing and deleting a subject

The pencil on row hover opens the **tag editor** with its **Subject** section in front — there is no subject dialog of its own, since a subject is extra data on a tag: the tag's name, comment, description, implications and [meta tags](tags.md#meta-tags-on-a-tag) above, the display name and exists-since in the section. While the tag is still the slug the display name derives, typing a new display name rewrites the tag name with it, in view. Two subjects may share a display name — their slugs quietly differ. When **creating** a subject, a typed tag another subject already owns is refused, and one no subject owns is **adopted** rather than minted beside. When **editing**, giving one an identity tag that already exists is offered as a **merge**: the identity tags merge through the ordinary [tag merge](tags.md), and where that tag was another subject's the two subjects merge with it, so every picture's change is recorded separately and the whole thing reverts. Selecting several rows in the list offers the same **Merge** in one go.

- **Deleting a subject keeps its tag** — the pictures are still of something.
- **Deleting the tag deletes the subject** with it, the way every identity tag takes its record. The list's *Without a tag* filter finds the nameless identities an unnamed cluster is held by, and anything a merge brought in without one.

## Tag groups about a subject

A picture with two people wants two groups of tags — hers and his. While dragging tags in [item properties](item-properties.md), a **drop zone per subject** appears beside the "new group" zone (one for each subject on the item that has no group yet); dropping there creates the group already bound to that identity, and the group header carries the subject as a chip (which is also how the binding is removed). The grouped tags are still the item's tags; "Alice with blonde hair" is deliberately not searchable.

## Multiple people on one face

One face can be **several people at once** — a drawn head can be both the character and the actor who plays them, each with an age of its own, and one manga page can hold the same character twice at two ages. Naming a face **adds** a person to it; the cross on a person row in the sidebar takes that one name off, while the crop menu's "Not this person" takes every name off the picked faces. This is why the face strips list such a face under each of its people. The other way round, one person can be on a picture more than once — the sidebar numbers the rows "(1)", "(2)" after the name, a grip drags them into order, and dropping one onto a face card or into the loose zone puts the appearance at that face or takes it off one.

## Searching by subject

The tag already finds the pictures — `albert_einstein` works like any tag. The `SUBJECT:` condition exists for what a tag cannot express:

- `SUBJECT:alice@1921` — Alice in a picture from 1921; `SUBJECT:alice@1910..1920` for a range. A bare year like `@2014` means the whole year.
- `SUBJECT:alice#12` — Alice at age 12; `SUBJECT:alice#10..14` for a range.
- `SUBJECT:` — has any subject at all.

Either half of a state derives from the other where the since-date allows it, so typing a picture's year answers an age search too. **Every appearance counts**: a picture matches `SUBJECT:alice#12` if any of Alice's appearances in it — at a face or at none — says so, so a page holding her at six and at twelve answers both. A bound only narrows: a picture where nobody dated the assignment or a face cannot satisfy "aged 10 to 14", because the honest answer is that we do not know.

See [Search](search.md) for the full query syntax.

## Related pages

- [Tags](tags.md) — the tag system subjects are built on
- [Places](places.md) and [Events](events.md) — the other two kinds of data on a tag
- [Annotation editor](annotation-editor.md) — drawing and naming faces on the picture
- [Item properties](item-properties.md) — the sidebar's Subjects tab, people and faces together
