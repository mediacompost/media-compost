# Changelog

## Unreleased

### Features

- The wand's properties bar carries **Inpaint**, like the select and text
  tools': a patch of sky, a speech balloon's inside or a logo's background is
  picked up in one click, and painting it out no longer means changing tools.
- The library grid's **Show sequenced** toggle is now **Fold sequences**, on by
  default: a sequence's members give way to the sequence itself where both
  would be in the view, and stay where it would not — in a group holding the
  pages but not the chapter, or with sequences unticked in the media kinds.
- Shift + an arrow key in the preview leaves a sequence for the item beside
  it, instead of turning its pages one at a time.

### Fixes

- The image editor takes the keyboard back when you press on the picture.
  Typing in a properties-bar field — the wand's Grow, either Tolerance box, a
  brush size, a crop ratio — left the caret there for the rest of the session,
  whatever you did on the canvas afterwards, and every shortcut stands down
  over a field: Space stopped panning, M and W stopped switching tools, ⌘Z
  stopped undoing and Delete stopped filling.
- A sequence's repeated page is stepped where it stands: with the same picture
  at two positions, the grid's and the preview's arrow keys went to the item
  after its OTHER position.
- The sidebar's Quick Assign button reads a set's GROUPS as well as its tags:
  a set holding a group showed "Remove from N selected" before it had ever
  been applied, and the press then wrote only the tags.

## 1.0.1

- The project page on PyPI carries the README as its description.

## 1.0.0

First release
