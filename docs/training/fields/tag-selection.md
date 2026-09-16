## Tag selection

### Always include

Tags listed here bypass the random subset pick: if the image has the tag, the prompt gets it.

The point is honesty about things the model would otherwise learn silently. If a third of your images carry a watermark and the word never appears in a prompt, the model concludes watermarks are simply part of how these pictures look — and paints them into everything. Naming it every time attaches the concept to the word instead, and you can then suppress it at generation time.

Same reasoning for anything that is present but not wanted: a signature, a logo, a heavy filter. A tag is never forced onto an image that does not have it.

### Always include tags marked

The rule above, named by what the library says ABOUT a tag rather than by the tag. Any tag marked with one of these meta tags bypasses the random pick — again only where the image actually has it.

A meta tag put on “watermark”, “signature” and “logo” once means every run treats them that way, including runs written before the third of them existed. The two lists are unioned, so naming a tag here and above is simply the same instruction twice.

### Exclude

Tags removed from every prompt before it is used, while staying on your items.

Two common cases. Housekeeping tags that describe your workflow rather than the picture (“check-later”, “scan”, quality ratings) teach the model nothing and dilute the prompt. And when you are training a concept behind a trigger word, excluding the plain tag for that concept keeps the meaning attached to the trigger instead of leaking into the everyday word.

### Exclude tags marked

The same, one level up: any tag the library marks with one of these meta tags is stripped from every prompt.

This is the one to reach for when the exclusions are a KIND of tag rather than a list of them. Quality ratings, scan notes, the booru's own housekeeping words — mark them “noprompt” in the Tags tab and every run drops them, instead of every job carrying a list that has to grow with the vocabulary.

It is not the same as a skipped tag GROUP below. This one is about the tag wherever it appears; that one is about a grouping on one item, and a tag placed in an excluded group and also somewhere else survives it.

### Skip tag groups tagged

Per-item tag groups are how a library keeps what a picture shows apart from notes about it — a “Notes” group holding “to redraw” and “bad scan”, a group for someone else's tags you have not checked. Those words are useful in the library and wrong in a prompt.

Marking the group with a meta tag and naming it here is what makes that separation reach training, without maintaining a parallel exclude list of individual tags that grows every time you add one.

Two details keep it honest. A tag placed in an excluded group AND somewhere else — another group, or ungrouped — stays, because it reaches the item by a route you did not exclude. And a broader tag that was only implied by dropped tags is dropped too: excluding a group holding “poodle” would otherwise leave “dog” in the prompt.

### Min tags per prompt

The fewest tags a prompt may contain. Together with the maximum it defines the random subset drawn on every visit; leaving both empty simply uses all of an image’s tags every time.

A floor is worth setting when some images carry very few tags — a one-word prompt trains that word against the entire picture, background and all, which is a fast way to teach the model something you did not mean.

### Max tags per prompt

The most tags a prompt may contain. This is the more useful of the two limits: showing the model a different handful each visit forces it to learn what each word contributes on its own, instead of memorising one long fixed list as a single unit.

It also keeps prompts within the model’s attention span — very long tag lists get progressively less attention toward the end, so 20 tags do not teach twice as much as 10. Something in the range of 8–20 is a common choice for heavily tagged libraries.

### Pick probability

When a random subset of an image's tags goes into each prompt, uniform picking mirrors your library's imbalance: a tag on 400 images is learned 400× more often than one on 5, and the rare tag never really takes.

'Balance rare tags' weights the draw by 1/frequency, so across the whole run every tag gets roughly comparable exposure. Use it when your dataset has a long tail you actually care about. It only changes WHICH tags are picked — see 'Weight loss by tag rarity' for the other lever, which changes how much each image counts.

### Frequency measured in

Rarity is relative to some population, and this picks which one.

“Training data” counts only the images this job selected, so balancing works within the set you are actually training on — usually what you want. “Whole library” counts every item you own, which makes a tag that is common in your dataset but rare overall still count as rare. That is occasionally useful when the training set is a deliberate slice of a much larger, differently balanced collection.

### Weight loss by tag rarity

Pick probability changes which tags make it into a prompt. This changes how much a whole image counts once it is there: images whose tags are rare get a bigger say in each weight update, common ones a smaller one.

The multiplier is clamped between ×0.25 and ×4 so no single oddity can dominate a run. It is the right lever when the imbalance is in your images rather than in your tagging — five pictures of one character against four hundred of another. The two can be combined, but turn one on at a time so you can see what each did.

### Skip partially matching tags

Booru-style tagging often carries a general tag alongside a specific one: “shirt” next to “white shirt”, “hair” next to “long hair”. In a prompt the pair is redundant, and worse, it teaches the model that the two words travel together — after which asking for “shirt” tends to give you a white one.

With this on, whenever a picked tag is a whole-word subset of another picked tag, the general one is dropped and a different tag is drawn in its place. The prompt keeps its length and gains a word that actually carries information.

### Shuffle tag order

Randomises the order of the tags in each prompt.

Position carries weight: words near the front get more attention than words near the end. With a fixed order, whatever your tagging tool happens to list first is systematically learned harder — and the model also picks up the order itself as a pattern, so prompts written differently at generation time work less well. Shuffling averages both effects out over the run. Leave it on unless you have a specific reason not to.

### Caption dropout

Occasionally hands the model an image with NO prompt at all. That sounds pointless, but guidance (the CFG scale at generation time) works by comparing a prompted prediction against an unprompted one — so the unprompted path has to stay healthy.

Without any dropout, fine-tuning slowly degrades that path and generations get stiff and over-cooked at normal CFG values. 0.05–0.1 is the usual insurance; much higher just wastes steps.

### Tag separator

The string put between tags when the prompt is assembled. Comma + space is what nearly every image model was trained on and what people type at generation time, so it is almost always the right answer.

Change it only to match an unusual prompt convention — and if you do, remember that generation prompts should then use the same convention to get the same behavior.

### Group tags by tag group

A per-item tag group is usually about one thing in the picture — Alice's hair and dress, Bob's hat. Flattened into one comma list, the model is left to work out which adjective belongs to whom, and in a busy image it often gets it wrong.

With this on, the tags the random pick chose are laid out per group, in the order the pick produced, so shuffling still applies within a block. Tags in no group lead, because they describe the scene the groups sit inside. A tag that is in two groups is written under the first one — the same tag twice reads as emphasis and teaches nothing.

### Label each block with

Puts something in front of each group's tags, so a block reads “Alice: blonde hair, dress” instead of “blonde hair, dress”.

The group's NAME is right when your groups are named for what they show. The SUBJECTS it is about are usually better: a group called “front figure” is bookkeeping, while the subject on it is “Alice” — the word you would actually type at generation time.

A group with no subjects gets no label at all under that choice, rather than quietly falling back to its name.

### Between groups

The string between one group's block and the next. A newline is the default because it is what makes the blocks read as separate statements rather than one longer list.

If your prompts are consumed somewhere that cannot carry line breaks, a distinctive string such as “ | ” works too — just use the same convention when you write generation prompts.

### Write tags as an alias

Your library's aliases are the other words for one thing — “cat”, “kitty”, “feline”. Assigning any of them stores the canonical name, so every prompt says the same word and the model learns to answer to that word alone; at generation time the others do less, or nothing.

With this above 0, each picked tag is sometimes written as one of its aliases instead. The roll happens per tag per visit, so one image seen twice reads differently and the whole vocabulary is spread across the run rather than one alias being chosen per tag and then repeated.

Only the PROMPT changes. Tag matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all keep using the canonical name — so this cannot skew any of them. A tag with no aliases is always written as itself, and 0 is exactly what every run did before this setting existed.

### Write tags as

A tag's comment is the one line beside its name in the Tags tab — “one girl in the picture” for `1girl`, “from below, looking up at the subject” for `from_below`. A booru vocabulary is compact for the people typing it and opaque to a text encoder; the comment is the same idea in words the encoder can read.

“Their name” is what every run did: the tag as it is spelled. “Their comment” writes the comment in place of the name wherever a picked tag has one, and “Name and comment” writes the name with the comment in brackets after it, so the model learns both spellings of one thing. A tag with no comment is written as its name whatever this says.

Only the PROMPT changes. Matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all stay keyed on the tag's name, exactly as with aliases — and the comment is read from the library when the dataset is built, so editing a comment later changes the next run, not this one.

### Underscores to spaces

Tag vocabularies from booru sites write phrases with underscores — “looking_at_viewer”. The text encoder has no idea what that is; as plain words it does.

With this on, underscores become spaces in the training prompt, so the model learns ordinary English it can also understand when you type it later. Turn it off if you are deliberately training the underscore vocabulary itself, e.g. to match an existing anime model’s prompt style. Everything else — tag matching, always/exclude lists, frequency balancing — keeps using the raw tag names.
