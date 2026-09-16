"""Reorientation detection at import: original -> derived relationships.

Only whole-image rotations and flips (and their combinations) are detected;
crops are deliberately not. A reorientation preserves pixel count, so the
pre-existing image is treated as the original and the newly-imported one as the
derived version.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy import func, select

from media_compost.db import File, Item, Relationship
from media_compost.importer import Importer, ImportOptions


def _photo(seed: int, size: tuple[int, int] = (1000, 1000)) -> Image.Image:
    """A deterministic image with several large, distinctly-textured shapes —
    distinct from other seeds so unrelated photos never match."""
    rng = np.random.default_rng(seed)
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.float32) + 15
    for _ in range(7):
        cx, cy = rng.integers(w // 6, w * 5 // 6), rng.integers(h // 6, h * 5 // 6)
        rw, rh = rng.integers(120, 240), rng.integers(120, 240)
        x0, x1 = max(0, cx - rw), min(w, cx + rw)
        y0, y1 = max(0, cy - rh), min(h, cy + rh)
        ax, ay = rng.uniform(-1, 1), rng.uniform(-1, 1)
        base = rng.integers(60, 255, 3)
        grad = xx * ax + yy * ay
        for c in range(3):
            region = base[c] * 0.5 + 0.4 * (grad % 256)
            img[y0:y1, x0:x1, c] = region[y0:y1, x0:x1]
    return Image.fromarray(np.clip(img, 0, 255).astype("uint8"))


def _count(session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def _originals(session) -> dict[str, str]:
    """Map each item's short name -> its original's short name (edit links)."""
    by_id = {it.id: it.name.rsplit(".", 1)[0]
             for it in session.execute(select(Item)).scalars()}
    out: dict[str, str] = {}
    for r in session.execute(
        select(Relationship).where(Relationship.kind == "edit")
    ).scalars():
        out[by_id[r.to_item_id]] = by_id[r.from_item_id]
    return out


def _import_order(lib, tmp_path: Path, names_to_imgs, order):
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    with db.session() as s:
        imp = Importer(s, store, cfg)
        for name in order:
            p = src / f"{name}.png"
            names_to_imgs[name].save(p, "PNG")
            imp.import_paths([p], ImportOptions(folders_as_groups=False))


def test_crops_are_not_linked(lib, tmp_path: Path):
    # A crop is a distinct new item with NO edit relationship — crop detection
    # was removed because it produced too many false links.
    A = _photo(5)
    w, h = A.size
    B = A.crop((w // 10, h // 10, w * 9 // 10, h * 9 // 10))  # centre crop
    _import_order(lib, tmp_path, {"A": A, "B": B}, ["A", "B"])
    cfg, db, store = lib
    with db.session() as s:
        assert _count(s, Item) == 2
        assert _count(s, Relationship) == 0


def _files_of_first_item(session) -> int:
    first = session.execute(select(Item).order_by(Item.id)).scalars().first()
    return session.execute(
        select(func.count()).select_from(File).where(File.item_id == first.id)
    ).scalar_one()


def test_rotation_folds_into_existing(lib, tmp_path: Path):
    # A rotation is folded into the pre-existing item's source files (a single
    # item with two files), not a separate linked item.
    A = _photo(7)
    Arot = A.rotate(90, expand=True)
    _import_order(lib, tmp_path, {"A": A, "Arot": Arot}, ["A", "Arot"])
    cfg, db, store = lib
    with db.session() as s:
        assert _count(s, Item) == 1
        assert _count(s, Relationship) == 0
        assert _files_of_first_item(s) == 2


def test_flip_folds_into_existing(lib, tmp_path: Path):
    A = _photo(11)
    Aflip = A.transpose(Image.FLIP_LEFT_RIGHT)
    _import_order(lib, tmp_path, {"A": A, "Aflip": Aflip}, ["A", "Aflip"])
    cfg, db, store = lib
    with db.session() as s:
        assert _count(s, Item) == 1
        assert _count(s, Relationship) == 0
        assert _files_of_first_item(s) == 2


def test_unrelated_images_are_not_linked(lib, tmp_path: Path):
    A = _photo(5)
    D = _photo(905)
    _import_order(lib, tmp_path, {"A": A, "D": D}, ["A", "D"])
    cfg, db, store = lib
    with db.session() as s:
        assert _count(s, Relationship) == 0


def test_same_size_different_photos_not_linked(lib, tmp_path: Path):
    """Two different photos of the same dimensions must never be linked as an
    edit, even if the crop-resistant hash nominates them: a same-size match can
    only be a rotate/flip, which the pixel check rejects here. This is the
    regression guard for the false crop links between similar same-size images."""
    from media_compost.dedup import canon_thumb, whole_image_edit

    A = _photo(5, size=(800, 600))
    D = _photo(905, size=(800, 600))
    # Directly assert the pixel classifier rejects the pair (independent of
    # whether the hash happens to nominate it in this synthetic set).
    assert whole_image_edit(canon_thumb(A), canon_thumb(D), 0.02) is None
    # And it accepts a genuine whole-image edit.
    assert whole_image_edit(
        canon_thumb(A), canon_thumb(A.rotate(180, expand=True)), 0.02
    ) == "rotate"

    _import_order(lib, tmp_path, {"A": A, "D": D}, ["A", "D"])
    cfg, db, store = lib
    with db.session() as s:
        assert _count(s, Relationship) == 0
