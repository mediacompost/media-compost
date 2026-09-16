## Caption or instruction selection

### Only instructions tagged

Items often carry more than one caption: a one-line description and a paragraph, a translation, a machine draft someone approved. They are not interchangeable, and a run that mixes them teaches the model to answer the same picture in several different registers.

Meta tags are how a caption is labeled in the library — “long”, “alt text”, “German” — so naming one here picks that kind of caption throughout the dataset without touching the captions themselves. An item whose captions are all filtered out simply trains with no caption text, exactly as an item with no captions does.

### An item with several captions

Items often carry more than one caption — a short one and a long one, a translation, a machine draft somebody approved.

ONE AT RANDOM gives the item a single visit each pass and draws a different caption each time, so the whole set is seen across a long run and an item counts once however many ways it has been described.

EVERY CAPTION gives it one visit per caption, so all of them are used every pass — and an item with ten is therefore seen ten times, which is usually an accident of tooling rather than a claim that the picture matters ten times as much.

EVERY CAPTION, SHARED is that with the accident removed: each caption still gets its visit, and together they carry one item's worth of gradient.

### Skip instructions tagged

The other half of the same lever, and usually the easier one to maintain: rather than name every kind of caption you want, name the few you do not.

The common cases are captions kept for a purpose other than training — a note to yourself, a source credit, an unreviewed machine draft — and captions in a language the model was not trained on. Excluding wins over including, so a caption carrying both an included and an excluded tag is left out.
