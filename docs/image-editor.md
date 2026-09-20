# Image Editor

The image editor is a Photoshop-style editor for retouching library images — selections, painting, transforms, cropping, adjustments, and AI-assisted cleanup. It is the **Edit** half of the item window, an overlay that opens over the library. (Unlike the rest of the app, this window is deliberately English-only — its tag set is Photoshop's, and it does not follow the [language setting](settings.md).)

## Opening the editor

Click **Edit image** in the sidebar (or use the grid's context menu). The item window opens with the address as a parameter on the view behind it (`?item=<ids>&mode=edit`), so reloading brings it back; a **mode switch** at the left of the header flips the current tab between **Edit** and **Annotate** (the [annotation editor](annotation-editor.md)) — leaving Edit with unsaved changes asks first. Opening several images at once shows **one tab per image** across the top; tabs size to their full names, a star (`*`) marks a tab with unsaved changes, and the tab bar's bottom line disappears under the active tab. With a single image the strip is hidden — the header's ✕ is the way out.

## Layout

- The **header** holds the mode switch, the item's name (with the buffer's current size underneath) and its **file-number chip** (see [Editing older versions](#editing-older-versions)), the theme menu, the **Save** split-button, and the window's ✕.
- **Undo/Redo** and the **Image** and **Selection** menus float over the picture's top-left corner, in their own pills — they act on the picture, so they live over it.
- A compact **tool palette** floats below them at the left edge: selection and painting tools first, the hand and zoom tools at the bottom, and the two **color swatches** in their own panel beneath the tools. Hovering a tool shows its name immediately as a tooltip.
- A **tool properties bar** sits centered at the top; it carries only controls. The active tool's name and a one-line hint live in the **help bar** at the bottom left.
- The area around the image is a solid background; the transparency **checkerboard** shows only within the image's bounds, so its size and edges are always visible.
- **Zoom to fit** respects the floating bars — the fitted image is never covered by the palette or the top and bottom bars.

**Pen input is pressure-sensitive**: with a stylus, each brush or erase stamp scales its size and strength by pen pressure (a mouse always paints at full pressure).

**Tool shortcuts are spring-loaded**: a quick tap switches tools for good, while *holding* a tool's key uses that tool only while pressed — releasing returns to the previous tool.

**The editor opens on the tool you last used**, across pictures and across sessions: a tool is the job in hand — cropping a batch of scans, painting out a batch of logos — and the editor is opened once per picture.

### Theme

The theme toggle is a menu with **Default**, **Light**, and **Dark**. Default follows the main app's mode (and keeps following it); Light and Dark hold this window at that mode regardless — useful for judging an image against the opposite background. The choice persists across sessions.

## Zoom and pan

- The scroll wheel zooms. Along an axis where the picture overflows the view it **pivots on the cursor**, so the point under it stays put; along one where the picture still fits it grows about its own centre, so a picture zoomed up and back down lands exactly where it was. A wheel over the picture is the picture's whatever is held down: `Ctrl`/`Cmd` + scroll, and a trackpad pinch, zoom the image, and the browser's own page zoom is refused — so a slipped modifier cannot leave the app at 110%.
- The **zoom tool** clicks to zoom in a step on the clicked point, `Alt`-clicks to zoom out, and drags a box to fill the view with that area.
- **Fit** and **100%** buttons also re-center the image. **100% means one image pixel per device pixel** — on a HiDPI/retina display the percentage is measured in device pixels, so 100% is true actual size.
- The **hand tool** (`H`) pans. Holding `Space` temporarily switches any tool to the hand, and dragging with the **middle mouse button** pans from any tool.

## Selections

The **selection tool** offers two shapes — rectangle and circle — and four modes — replace, extend, subtract, intersect — in its properties bar. `Shift` temporarily extends, `Option`/`Alt` subtracts, and **`Shift`+`Alt` intersects** — keeping only what the new shape and the old selection have in common (Clip Studio Paint's pairing). Intersecting when nothing is selected leaves nothing, which is what intersecting with nothing means. **The control follows the keys**: hold a modifier and the lit button moves to the mode that press would use, so you can check the keys where the setting already is. Once a drag starts it locks — the mode was decided at the press, and from then on those keys mean the shape instead — and a lasso built from clicks keeps its mode until the outline closes. Press them **after** the drag has begun and they shape the box instead: `Option`/`Alt` draws it out from its centre, `Shift` constrains it to a square — a circle in the ellipse style, which draws inside the same rectangle — and holding both gives a square centred where you pressed. It is the same two keys doing Photoshop's two jobs each, told apart by whether they were already down when you pressed — and a key you held at the press is spent on the mode only until you let it go: release it mid-drag and press it again and it shapes the box like any other, so a selection begun with `Shift` can still be squared and one begun with `Alt` can still be drawn from its centre. The mode itself never changes mid-drag. A square takes the larger of the two distances and still grows the way you dragged. The active selection is outlined with animated **marching ants** (a 1 px dashed line that stays 1 px at any zoom), and the dimmed unselected area keeps a pixel-sharp edge. Box selections snap to whole pixel edges.

The **lasso** (`L`) is its own tool beside it, with the same properties and the same modes: drag to draw freehand, or click to place corners (double-click, a click on the first corner, or `Enter` closes the outline; `Escape` throws it away). It was a third shape inside the selection tool, which put the one gesture that is genuinely different behind a shape picker.

- **Invert** turns the selection inside out; **Clear** removes it. Both are enabled only while a selection exists.
- Dragging from the selection's **outline** moves the selection mask itself without touching pixels (the cursor shows *move* over the outline), and the move is undoable like every other selection change.
- Clicking anywhere without dragging removes the selection.
- The `Delete` key fills the selection with the background color (transparency by default).
- The bar's **Crop** button crops the image to the selection's bounding box.
- **Fill** fills the whole selection with the foreground color; **Inpaint** fills it from its surroundings (see [Inpainting](#inpainting)).

### The wand tool

The **wand** (`W`) selects the contiguous area of similar color under the click, with its own **Tolerance** slider and a replace / add / remove / intersect control (`Shift`, `Alt` and `Shift`+`Alt` override it for one click). Clicking inside the current selection in replace mode clears it. **Keep the button down and drag to adjust the tolerance live** — right/up widens the selection, left/down narrows it — and the tolerance you release at becomes the tool's new setting. Both tolerances and the wand's Grow are **remembered between sessions**.

Beside the tolerance is a **Grow** field, in whole pixels: a positive number pads what the wand found, a negative one eats into it. It is for the hairline a flood stops short of at a soft or anti-aliased edge — select the sky, grow by two, and the fringe goes with it. It applies to the **new area alone**, so adding to a selection grows only the part being added and leaves what was already selected exactly as it stands. While you are dragging the tolerance you see the raw find, and the padding is applied when you let go — the drag is for judging the tolerance, which the unpadded area shows more honestly. (To grow the whole selection instead, use **Grow selection…** in the Selection menu; that dialog remembers its own amount, and **Shrink selection…** remembers a separate one.)

**Blur selection…**, beside them, blurs the *selection* rather than the picture: it softens the mask's own edge by N pixels, spreading it both ways. Everything done afterwards fades out across that band instead of stopping at a visible seam, which is what makes it useful before an inpaint — the filled area meets the original gradually. It remembers its own amount as well.

### The text tool

The **Select text** tool (`T`) turns what an OCR engine has read on this picture into selections: it outlines the text boxes, and clicking one — or sweeping a band over several, with the marquee's modifiers — selects those exact regions (rotated text becomes exact quadrilaterals), ready to fill, inpaint, or transform. Its bar switches between word boxes and whichever other levels the reading holds (character, line, block), carries **All text** and **Clear** buttons and its own **Inpaint** split-button, and offers the reading engines for a file that hasn't been read yet — a run's progress shows right there.

## Move and transform

Dragging a selection's **outline** moves the selection mask; lifting the *pixels* goes through **Transform** (or paste), which floats them into a movable layer — the hand tool and held `Space` only ever pan, Photoshop-style.

The **Transform** button (in the selection bar, and in the floating-selection bar while a float is not yet in transform mode) shows a bounding box:

- **Corner handles scale** — the opposite corner stays fixed, `Shift` keeps the aspect ratio, `Alt`/`Option` scales about the center.
- **Mid-edge handles** move just that edge; a top handle **rotates**; dragging inside **moves**. While un-rotated, moves and resizes snap to whole pixels so content never blurs.
- **Apply** (or `Enter`) bakes the result in and re-selects it; **Cancel** (or `Escape`) discards it — and `⌘Z` during a move or transform cancels it the same way.
- A **Keep original** toggle switches to copy mode: the source pixels stay in place and applying bakes a duplicate at the new position.
- **Flip H / Flip V** mirror the content and **Rotate Left / Rotate Right** quarter-turn it; flips survive further resizing.
- Switching tools or saving applies a pending transform automatically.

### Clipboard

`⌘/Ctrl+C` copies the selected pixels, `⌘/Ctrl+X` cuts them, and `⌘/Ctrl+V` pastes the clipboard as a new floating selection in transform mode, centered in the viewport. The clipboard lives for the editor's session and carries across its tabs.

## Painting tools

### Brush

Paints the foreground color; the brush shape is previewed as an outlined circle under the cursor. With a selection active, the brush affects only the selected area. Size, hardness and opacity are set in the properties bar. **The size slider is logarithmic** — the same for the erase and blur tools — so each doubling takes the same length of track: the quarter points are 1, 4, 14, 53 and 200 px, and picking a 3 px tip is as easy as picking a 150 px one. The number field beside it is still plain pixels — **Opacity is the foreground colour's alpha**, the same number the colour picker shows, so the two always agree: paint at 40% and the swatch is 40% too — each slider has an editable number field, and every such field accepts **simple arithmetic** (`500+10` commits as 510). One pass lays the tip down in full: the centre of a stroke reaches the colour's own opacity at any hardness, and hardness decides only how wide the soft edge is. Crossing your own stroke within one stroke does not darken it — the colour's alpha is the opacity for the whole stroke, so a 50%-alpha colour paints a 50% stroke however many times it doubles back. (It used to build up like an airbrush instead, which meant a soft brush could never get past about a third of the colour: measured, 32.5% at the default hardness of 80, and 100% only at a hardness of 100.)

### Erase

The **erase tool** (`E`) has its own size and hardness. With no background color set it erases to transparency; with one set it paints the background color. `Delete`/`Backspace` likewise fills the selection (or the whole image) with the background color.

### Blur

The **blur tool** works like the brush but applies a gaussian blur inside the soft brush circle; its Strength slider sets the radius, repeated strokes blur further, and a selection clips it. **Only the pixels under the brush are averaged** — brushing along the edge of one colour never drags the colour beside it in, however strong the blur.

### Fill (paint bucket)

The **fill tool** flood-fills the contiguous area of similar color under the cursor with the foreground color, governed by a **Tolerance** slider. With a selection active the fill is confined to it. Like the wand, **dragging with the button held adjusts the tolerance live**, and the whole drag is one undo step.

## Crop

The **crop tool** drags out a rectangle with handles: corners resize (the opposite corner stays fixed), mid-edge handles move one edge, a stalked top handle **rotates** (synced with the Angle field, clamped to ±45°), and dragging inside moves it. An un-rotated crop is limited to the image bounds; a rotated one may reach past a corner, and whatever falls outside the picture is filled with transparency.

- **Ratio** limits the crop to a fixed width-to-height shape — **Original** (the picture's own, spelled out as `Original (3:2)`), `1:1`, `3:2`, `2:3`, `4:3`, `3:4`, `16:9`, `9:16`, `5:4`, `4:5`, **Free**, or **Custom…**, which reveals two fields beside the menu seeded from the rectangle on screen and taking a ratio (`16 : 9`) or a size (`1920 : 1080`), reshaping the crop as you type. Picking one reshapes the rectangle already on screen (keeping its centre) as well as constraining the next drag; a locked rectangle **stops at the edge of the picture** rather than being squashed out of shape, and an edge handle moves the other pair of edges with it. The shape is held in the crop's own frame, so it survives the Angle field: a rotated `16:9` crop still produces a `16:9` picture.
- **To Selection** sets the crop rectangle to the current selection's bounding box — with a ratio locked, to the largest rectangle of that shape inside it.
- Clicking the image without dragging clears the crop rectangle.
- The **Crop** button or `Enter` performs the crop; `Escape` clears the pending rectangle.
- **Duplicate & Crop** opens the cropped region as a pending **New crop** tab (marked unsaved) — the new item is only created when that tab is first saved; discarding the tab creates nothing.

## Colors

The palette carries two swatches: the **foreground** color (used when adding — brush, fill) and the **background** color (used when removing — erase, `Delete`). The background is transparent by default; picking a fully transparent color (alpha 0) resets it.

Clicking a swatch opens a custom **color picker** popover anchored beside it: a saturation/value square, hue and alpha sliders, editable values in RGB, HSL, HSV, or hex (8-digit hex carries alpha), and a **Recent colors** row remembered across sessions. Every change applies live. **The pipette's picks join that row too**, one per pick — a drag across the picture records the colour it ended on, not every colour it crossed.

Colors carry **alpha**: a color's alpha is the stroke's opacity cap, and erasing replaces the area with the background color at its own alpha — never a blend with the old pixels.

## Adjustments

**Image → Adjustments…** opens a small panel over the top right of the canvas — not a modal, so you can keep panning and zooming while judging the change. Four sliders — **brightness**, **contrast**, **saturation**, **hue** — preview live on the full-resolution image; double-click a slider to return it to neutral. **Reset**, **Cancel**, and **OK** (applies everything as one undoable step). With a selection active, the adjustment applies to the selection only, and the panel says so.

## Blur

**Image → Blur…** opens the same panel with one slider on it: **Radius**, a gaussian blur of the picture, previewed live and applied as one undoable step. With a selection active it blurs the selection only — reading the pixels around it, so the blurred patch doesn't darken towards its own edge — and the panel says so. The panel opens at the radius you last used and shows it straight away; **Reset** takes it to 0, **Cancel** puts the picture back.

This is not the Selection menu's [**Blur selection…**](#the-selection-menu), which softens the *selection's* edge and changes no pixel of the picture.

## Sharpen

**Image → Sharpen…** is the same panel again, with **Amount** (per cent — 100 adds the picture's own detail back once over) and **Radius** (the size of the detail being lifted; small, because sharpening a photograph means its texture). It is an unsharp mask: the picture minus a blurred copy of itself *is* the detail, so adding that back is what "sharper" means. Live preview, one undoable step, the selection only where there is one — and double-clicking the Radius puts it back to its default rather than to zero, a radius having no neutral.

## Background color

**Image → Apply background color** puts the background color *behind* the picture: opaque pixels are untouched and transparency becomes the color, with half-transparent pixels blending — so a soft-edged cut-out lands on it cleanly rather than with a fringe. With a selection active it fills only there. It is undoable like any other edit.

If the background color is transparent there is nothing to put behind anything, so the action **asks**: the background swatch's own picker opens with a line saying what the color is for, and the fill happens when you close it on a color. Closing it without picking one does nothing.

## Inpainting

**Inpaint** fills the selected area from the surrounding image with a LaMa AI model, removing unwanted content and replacing it with a plausible continuation. It runs from the **Inpaint** button in the bar of every tool that makes a selection — the marquee and lasso (next to Fill), the text tool, and the **wand**, which is where a patch of sky, a speech balloon's inside or a logo's background is picked up in one click — or from the Selection menu; only the selected pixels change, and the result is undoable.

**A partly-selected pixel is partly filled**, so **Blur selection…** is the answer to a seam you can still see: soften the mask's edge first and the fill meets the original gradually instead of at a line. The model's own tone is corrected against the pixels around the hole, so a fill dropped into a sky, a wall or a screentone sits at the tone of what surrounds it.

Two models are available (the Inpaint button's dropdown picks one): **Photo** (big-lama) for photographic content and **Anime / illustration** (a line-art and screentone fine-tune of it) for illustrations, manga, and line art. A variant is greyed until its weights are downloaded in [Settings → Actions](settings.md).

## The Image menu

- **Rotate left / Rotate right**.
- **Image size…** — resample to a new size with aspect-linked fields.
- **Canvas size…** — grow with transparency or trim, with a 3×3 anchor grid; the image is never scaled.
- **Apply background color** — see [Background color](#background-color).
- **Adjustments…** — see [Adjustments](#adjustments).
- **Blur…** — see [Blur](#blur).
- **Sharpen…** — see [Sharpen](#sharpen).
- **Upscale**, **Colorize**, **Remove artifacts**, **Remove screen tones** and **Remove background** — five submenus side by side, each listing that action's AI models and greying the ones not yet set up (or leaving them out, under the [hide-unready setting](settings.md#ai-actions)); results replace the buffer and are undoable. The Colorize submenu includes the example-based manga model, which opens the reference picker right inside the editor.
- **Remove screen tones** converts manga screentones into smooth greyscale gradients: two neural **OpenComic descreen** models (**Compact**, near-instant, and **Lite**, a touch cleaner) plus **Descreen (FFT)**, a download-free classical filter whose one extra trick is restraint — a page with no detectable screentone only gets a gentle smoothing.

## The Selection menu

- **Select text / Select watermark** run the detectors on the current buffer and turn the found regions into the selection (rotated text becomes exact quadrilaterals) — ready to fill, inpaint, or transform.
- **Inpaint selection** — the two LaMa models as separate rows (see [Inpainting](#inpainting)).
- **Fill selection**, **Grow / Shrink selection…** (a dialog asks for the amount in pixels, expressions allowed), **Invert selection**, **Transform selection** (lifts the selected pixels straight into transform mode), **Crop to selection** (crops immediately), and **Clear selection** — all disabled until a selection exists.

## Saving and closing

- **Save** (or `⌘/Ctrl+S`) saves the buffer **as a new file on the item** — the file you edited is kept intact as a prior version, and the new one becomes the item's active file, so thumbnails update immediately everywhere. The button is enabled only while the buffer actually differs from the last saved state — undoing every change back to it disables Save again.
- The Save button's **chevron** menu offers **Save to a new item** (the edit becomes a standalone item, linked back to this one and carrying its tags, captions, and the rest — the original is left entirely alone) and **Revert to saved** (throws away unsaved edits — itself undoable).
- The window's **✕** in the header — or a tab's own ✕ — closes, guarding unsaved edits with a save/discard/cancel prompt. Switching the mode to Annotate is guarded the same way. With several tabs open the header's ✕ asks the same question `Escape` does: close the **window** or just this **tab**.
- **`Escape` steps down before it closes**: it first cancels an active transform, then clears a pending crop rectangle, then clears the selection — only then does it start closing. With several tabs open it asks whether to close the **window** or just the **tab**, and then guards unsaved changes. Closing the browser tab itself falls back to the browser's native unsaved-changes confirmation.

## Editing older versions

The header's **file-number chip** (`#N`) lists the item's image files (a video file on the same item is left out) — number, name or edit action, dimensions, and an "active" marker on the item's active file. Selecting one loads that file into the editor (guarding unsaved edits first), so an older or alternate version can be edited directly; saving still adds a new file to the item, based on the file that was loaded.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `H` | Hand tool (pan) |
| `M` / `L` | Select (marquee) / Lasso |
| `E` | Erase tool |
| `W` | Wand tool |
| `T` | Select-text tool |
| `Space` (hold) | Temporarily switch to the hand tool |
| Middle-drag | Pan from any tool |
| `Shift` / `Alt` | Extend / subtract selection (while selecting) |
| `⌘/Ctrl+Z` | Undo (cancels an active move/transform) |
| `⌘/Ctrl+Shift+Z` or `⌘/Ctrl+Y` | Redo |
| `⌘/Ctrl+C` / `X` / `V` | Copy / cut / paste selection |
| `Enter` | Apply transform · perform crop |
| `Escape` | Cancel transform · clear crop rect · clear selection · then close |
| `Delete` / `Backspace` | Fill selection (or image) with the background color |
| `⌘/Ctrl+S` | Save |

Every tool has a shortcut — hover its palette button to see it — and holding any tool key uses that tool only while pressed.

## See also

- [Annotation editor](annotation-editor.md) — tag bounding boxes are created there, not here
- [Video editor](video-editor.md)
- [Item properties](item-properties.md) — where edits appear as file versions
- [Settings](settings.md) — model downloads for inpainting, upscaling, and colorizing
