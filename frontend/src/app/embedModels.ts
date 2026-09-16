// The one line each embedder's dropdown row carries beside its name — WHAT
// KIND OF LIKENESS it measures, which is the only thing a person picking one
// needs and the model names cannot say. Keyed by the registry FAMILY, not the
// model id, so a variant added later inherits its family's line. One module,
// because two dialogs offer the choice (the import overlay's index option and
// the Tag batch chooser) and two hand-written copies would drift.
//
// The wording is deliberately about STRENGTHS: DINOv2's self-supervised
// features excel at fine visual likeness (style, linework, composition),
// while CLIP's language-aligned features group by what a picture DEPICTS.
export const EMBED_STRENGTHS: Record<string, string> = {
  DINOv2: "visual likeness — style & composition",
  CLIP: "subject matter — what is shown",
};

// (There used to be an `embedOptionLabel` here, joining the two with a dash
//  for a native `<option>`, which cannot carry a second line. Both dialogs
//  use `EmbedModelPicker` now, where the strength is a SUBTITLE — which is
//  what it is, and it was the least readable part of the longest row in the
//  dialog as a suffix.)
