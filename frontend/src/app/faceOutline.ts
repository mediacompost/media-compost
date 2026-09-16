/**
 * A face outline is an ELLIPSE, everywhere one is drawn.
 *
 * The box behind it is still a rectangle — that is what a detector returns and
 * what `ItemTagBox`/`Face` store — but a head is not rectangular, and over a
 * crowded manga panel four rectangles read as panel borders while four ovals
 * read as faces. It is only the outline that changes: the geometry, the crops
 * cut from it, and everything that reasons about overlap are untouched.
 *
 * One constant rather than `borderRadius: "50%"` typed at each site, because
 * the sites are three files apart and a face that is an oval in the annotator
 * and a rectangle in the sidebar's hover preview is two features wearing one
 * name.
 */
export const FACE_OUTLINE_RADIUS = "50%";

/*
 * There is no corner constant any more. A ✕ used to sit on the annotator's
 * ring at its 45° point, because an ellipse has no corner for one to hang off
 * — and that was the answer to the wrong question: a control that follows the
 * outline is a target that moves with every head it belongs to. It now sits in
 * the row under the oval, directly after the name, where the face's other
 * answer already is.
 */
