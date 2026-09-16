"""Importer + dedup behavior."""

from __future__ import annotations

import io

import pytest
from pathlib import Path

from sqlalchemy import func, select

from PIL import Image

from media_compost.config import Config
from media_compost.db import (Database, File, FileMetadata, FileName, Group,
                              GroupParent, Item, ItemGroup)
from media_compost.dedup import phash_to_int
from media_compost.importer import Importer, ImportOptions
from media_compost.media import normalize_format
from media_compost.storage import ItemStore


def _count(session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_dedup_exact_and_near(lib, images: Path):
    cfg, db, store = lib
    with db.session() as s:
        imp = Importer(s, store, cfg)
        stats = imp.import_paths([images], ImportOptions(folders_as_groups=False))

    with db.session() as s:
        # a + b are new items; a_copy is exact dup (skipped); a_small is a near
        # dup added as an alternative version of a.
        assert _count(s, Item) == 2, stats.as_dict()
        assert _count(s, File) == 3  # a, a_small, b
        assert stats.imported == 2
        assert stats.skipped_duplicate == 1
        assert stats.added_alternative == 1

        # The item with two files should have the larger (400x300) active.
        a_item = s.execute(
            select(Item).join(File, File.item_id == Item.id)
            .where(File.width == 400)
        ).scalars().first()
        assert a_item.active_file.width == 400


def test_reimport_is_idempotent(lib, images: Path):
    cfg, db, store = lib
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=False)
        )
    with db.session() as s:
        imp = Importer(s, store, cfg)
        stats = imp.import_paths([images], ImportOptions(folders_as_groups=False))
        assert stats.imported == 0
        assert stats.added_alternative == 0
        assert _count(s, Item) == 2


def test_folders_become_nested_groups(lib, tmp_path: Path):
    from tests.core.conftest import make_image

    cfg, db, store = lib
    root = tmp_path / "shoot"
    (root / "day1").mkdir(parents=True)
    (root / "day2").mkdir()
    make_image(root / "day1" / "x.png", seed=3)
    make_image(root / "day2" / "y.png", seed=4)

    with db.session() as s:
        imp = Importer(s, store, cfg)
        imp.import_paths([root], ImportOptions(folders_as_groups=True))

    with db.session() as s:
        names = set(s.execute(select(Group.name)).scalars().all())
        assert {"shoot", "day1", "day2"} <= names
        # Each image assigned to its folder group.
        assert _count(s, ItemGroup) == 2
        # Source filenames keep the relative import path (root folder included).
        fnames = set(s.execute(select(FileName.name)).scalars().all())
        assert {"shoot/day1/x.png", "shoot/day2/y.png"} <= fnames


def test_a_run_can_have_a_group_of_its_own(lib, tmp_path: Path):
    """`new_group` is a box for THIS import, inside "where it goes"."""
    from tests.core.conftest import make_image

    cfg, db, store = lib
    root = tmp_path / "shoot"
    (root / "day1").mkdir(parents=True)
    make_image(root / "day1" / "x.png", seed=3)

    with db.session() as s:
        shelf = Group(name="Shelf")
        s.add(shelf)
        s.flush()
        Importer(s, store, cfg).import_paths([root], ImportOptions(
            parent_group_id=shelf.id, new_group=True,
            new_group_name="Batch 1", folders_as_groups=True))
        s.commit()

    with db.session() as s:
        by_name = {g.name: g for g in s.execute(select(Group)).scalars()}
        assert {"Shelf", "Batch 1", "shoot", "day1"} <= set(by_name)
        # The box is INSIDE the shelf, and the folder tree is inside the box.
        def parent_of(name):
            return s.execute(select(GroupParent.parent_group_id).where(
                GroupParent.group_id == by_name[name].id)).scalar_one_or_none()
        assert parent_of("Batch 1") == by_name["Shelf"].id
        assert parent_of("shoot") == by_name["Batch 1"].id


def test_the_run_group_is_LAZY_like_a_folders(lib, tmp_path: Path):
    """A run that imports nothing leaves no empty box behind — the rule
    `test_empty_folders_create_no_group` states one level down. An import
    whose every file is a duplicate is the ordinary way to reach this."""
    from tests.core.conftest import make_image

    cfg, db, store = lib
    root = tmp_path / "shoot"
    root.mkdir()
    make_image(root / "x.png", seed=3)
    opts = dict(new_group=True, new_group_name="Batch 1")

    with db.session() as s:
        Importer(s, store, cfg).import_paths([root], ImportOptions(**opts))
        s.commit()
    with db.session() as s:
        assert "Batch 1" in {g.name for g in s.execute(select(Group)).scalars()}

    # A SECOND library, where the same run imports nothing at all.
    empty = tmp_path / "nothing"
    empty.mkdir()
    with db.session() as s:
        Importer(s, store, cfg).import_paths([empty], ImportOptions(
            new_group=True, new_group_name="Batch 2"))
        s.commit()
    with db.session() as s:
        assert "Batch 2" not in {g.name
                                 for g in s.execute(select(Group)).scalars()}


def test_an_unnamed_run_group_is_named_ONCE_for_the_whole_run(lib, tmp_path: Path):
    """The default is a timestamp, so a name computed per SOURCE would
    scatter one import over several boxes at a minute boundary."""
    from tests.core.conftest import make_image
    from media_compost.importer import default_run_group_name

    cfg, db, store = lib
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    make_image(a, seed=3)
    make_image(b, seed=4)
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [a, b], ImportOptions(new_group=True))
        s.commit()
    with db.session() as s:
        made = [g.name for g in s.execute(select(Group)).scalars()]
        assert len(made) == 1, made
        assert made[0].startswith("Imported "), made
        assert _count(s, ItemGroup) == 2


def test_empty_folders_create_no_group(lib, tmp_path: Path):
    """A folder with no importable files must not spawn a group (lazy groups)."""
    from tests.core.conftest import make_image

    cfg, db, store = lib
    root = tmp_path / "shoot"
    (root / "has_img").mkdir(parents=True)
    (root / "empty").mkdir()          # no files at all
    (root / "junk").mkdir()
    (root / "junk" / "notes.txt").write_text("nothing importable")
    make_image(root / "has_img" / "x.png", seed=3)

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [root], ImportOptions(folders_as_groups=True)
        )

    with db.session() as s:
        names = set(s.execute(select(Group.name)).scalars().all())
        assert {"shoot", "has_img"} <= names
        # The empty / junk-only folders never got a group.
        assert "empty" not in names
        assert "junk" not in names


def _make_zip(zpath: Path, tmp_path: Path, seeds: list[int]) -> None:
    """Build a .zip archive of images (one per seed) at ``zpath``."""
    import zipfile

    from tests.core.conftest import make_image

    zpath.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath, "w") as z:
        for i, seed in enumerate(seeds):
            img = tmp_path / f"_z{seed}.png"
            make_image(img, seed=seed)
            z.write(img, f"page{i:02d}.png")


def test_archive_sequence_placed_at_parent_level(lib, tmp_path: Path):
    """With folders-as-groups + archive-sequences, the archive's pages go into
    the archive's own group, but the sequence *item* sits one level up — in the
    group of the folder that contains the archive."""
    cfg, db, store = lib
    chapter = tmp_path / "chapter"
    _make_zip(chapter / "book.zip", tmp_path, seeds=[41, 42, 43])

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [chapter], ImportOptions(folders_as_groups=True,
                                     archives_as_groups=True,
                                     archive_sequences=True)
        )

    with db.session() as s:
        gid = {n: i for i, n in s.execute(select(Group.id, Group.name)).all()}
        assert "chapter" in gid and "book.zip" in gid
        # The sequence container lives in the "chapter" group (the archive's
        # parent), not in the "book.zip" archive group.
        container = s.execute(select(Item).where(Item.kind == "sequence")).scalars().one()
        cont_groups = set(s.execute(
            select(ItemGroup.group_id).where(ItemGroup.item_id == container.id)
        ).scalars().all())
        assert gid["chapter"] in cont_groups
        assert gid["book.zip"] not in cont_groups
        # The pages themselves live in the archive group.
        page_groups = set(s.execute(
            select(ItemGroup.group_id).join(Item, Item.id == ItemGroup.item_id)
            .where(Item.kind == "image")
        ).scalars().all())
        assert page_groups == {gid["book.zip"]}


def test_root_level_archive_sequence_joins_its_pages_group(lib, tmp_path: Path):
    """An archive at the root level has no level to sit at — so the sequence
    joins the group its own pages are in rather than none at all.

    Reported as a bug in exactly this shape: a PDF dropped on its own put its
    pages in a "book.pdf" group and left the sequence ungrouped, which reads
    as an import that lost the book."""
    cfg, db, store = lib
    zpath = tmp_path / "book.zip"
    _make_zip(zpath, tmp_path, seeds=[51, 52])

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [zpath], ImportOptions(folders_as_groups=True,
                                   archives_as_groups=True,
                                   archive_sequences=True)
        )

    with db.session() as s:
        gid = {n: i for i, n in s.execute(select(Group.id, Group.name)).all()}
        container = s.execute(select(Item).where(Item.kind == "sequence")).scalars().one()
        cont_groups = s.execute(
            select(ItemGroup.group_id).where(ItemGroup.item_id == container.id)
        ).scalars().all()
        assert cont_groups == [gid["book.zip"]]


def test_a_root_level_archive_with_no_group_at_all_stays_ungrouped(lib, tmp_path: Path):
    """The fallback is to the group that EXISTS, not to inventing one: with
    no archive group and no folder above it there is nothing to join."""
    cfg, db, store = lib
    zpath = tmp_path / "book.zip"
    _make_zip(zpath, tmp_path, seeds=[61, 62])

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [zpath], ImportOptions(folders_as_groups=True,
                                   archives_as_groups=False,
                                   archive_sequences=True)
        )

    with db.session() as s:
        assert s.execute(select(Group)).scalars().all() == []
        assert s.execute(select(ItemGroup)).scalars().all() == []


def test_sequence_grouping_says_which_half_joins_the_groups(lib, tmp_path: Path):
    """A book is two things at once — the item the library shows and the
    pages inside it — and which of them somebody wants in their groups is a
    real choice, so it is one."""
    cfg, db, store = lib
    chapter = tmp_path / "chapter"
    _make_zip(chapter / "book.zip", tmp_path, seeds=[81, 82])

    def grouped(which: str) -> tuple[set, set]:
        d = tmp_path / f"lib_{which}"
        c2 = Config(data_dir=d)
        db2, store2 = Database(c2), ItemStore(c2)
        with db2.session() as s:
            Importer(s, store2, c2).import_paths(
                [chapter], ImportOptions(folders_as_groups=True,
                                         archives_as_groups=True,
                                         archive_sequences=True,
                                         sequence_grouping=which))
            s.commit()
        with db2.session() as s:
            names = {i: n for i, n in s.execute(select(Group.id, Group.name)).all()}
            out = []
            for kind in ("sequence", "image"):
                out.append({names[g] for g in s.execute(
                    select(ItemGroup.group_id)
                    .join(Item, Item.id == ItemGroup.item_id)
                    .where(Item.kind == kind)).scalars().all()})
            return out[0], out[1]

    # Each half keeps its own LEVEL — the option says whether it joins at all.
    assert grouped("both") == ({"chapter"}, {"book.zip"})
    assert grouped("container") == ({"chapter"}, set())
    assert grouped("members") == (set(), {"book.zip"})


def test_archives_not_as_groups_puts_pages_in_parent(lib, tmp_path: Path):
    """With archives_as_groups off, an archive's pages land in the archive's
    parent group (the folder that contains it) — no group named after the zip."""
    cfg, db, store = lib
    chapter = tmp_path / "chapter"
    _make_zip(chapter / "book.zip", tmp_path, seeds=[71, 72, 73])

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [chapter],
            ImportOptions(folders_as_groups=True, archives_as_groups=False),
        )

    with db.session() as s:
        names = {n for (n,) in s.execute(select(Group.name)).all()}
        assert "chapter" in names
        assert "book.zip" not in names  # no archive group was created
        gid = {n: i for i, n in s.execute(select(Group.id, Group.name)).all()}
        page_groups = set(s.execute(
            select(ItemGroup.group_id).join(Item, Item.id == ItemGroup.item_id)
            .where(Item.kind == "image")
        ).scalars().all())
        assert page_groups == {gid["chapter"]}


def test_reimport_refreshes_filename_date(lib, images: Path):
    """Re-importing an existing image bumps its source-filename timestamp, so a
    newest-import sort can float it back to the top."""
    cfg, db, store = lib
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=False)
        )
    with db.session() as s:
        before = s.execute(
            select(FileName.created_at).where(FileName.name == "src/a.png")
        ).scalar_one()

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=False)
        )
    with db.session() as s:
        after = s.execute(
            select(FileName.created_at).where(FileName.name == "src/a.png")
        ).scalar_one()
    assert after >= before


def test_reimport_refreshes_last_imported_only(lib, images: Path):
    """Re-importing an image refreshes the item's ``last_imported_at`` (drives the
    "Recently Imported" sort) but never touches ``created_at`` (the immutable
    "First Import Date")."""
    cfg, db, store = lib
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=False)
        )
    with db.session() as s:
        it = s.execute(select(Item)).scalars().first()
        created_before, imported_before = it.created_at, it.last_imported_at

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=False)
        )
    with db.session() as s:
        it = s.get(Item, it.id)
        assert it.created_at == created_before          # first-seen never changes
        assert it.last_imported_at >= imported_before   # bumped by the re-import


def test_normalize_format_mpo():
    # Multi-picture-object JPEGs report as MPO; surface them as plain JPEG.
    assert normalize_format("MPO") == "jpeg"
    assert normalize_format("JPEG") == "jpeg"
    assert normalize_format("PNG") == "png"
    assert normalize_format(None) == ""


def _make_cbz(dst: Path, tmp_path: Path, names: list[str]) -> Path:
    import zipfile

    from tests.core.conftest import make_image

    pages = tmp_path / f"pages_{dst.stem}"
    pages.mkdir(exist_ok=True)
    for i, nm in enumerate(names):
        make_image(pages / nm, seed=200 + i, size=(200, 300))
    with zipfile.ZipFile(dst, "w") as zf:
        for nm in names:
            zf.write(pages / nm, nm)
    return dst


def test_archive_reimport_does_not_duplicate_sequence(lib, tmp_path: Path):
    """Re-importing the same archive (same name + same pages) refreshes the
    existing sequence instead of creating a second one (task: archive dedup)."""
    from media_compost.db import Sequence, SequenceItem

    cfg, db, store = lib
    cbz = _make_cbz(tmp_path / "book.cbz", tmp_path, ["p1.png", "p2.png"])

    with db.session() as s:
        stats1 = Importer(s, store, cfg).import_paths([cbz], ImportOptions())
        s.commit()
    assert stats1.sequences_created == 1

    with db.session() as s:
        before = s.get(
            Item,
            s.execute(select(Sequence.item_id)
                      .where(Sequence.kind == "archive")).scalar_one(),
        ).last_imported_at

    with db.session() as s:
        stats2 = Importer(s, store, cfg).import_paths([cbz], ImportOptions())
        s.commit()

    with db.session() as s:
        # Still exactly one sequence (and one container item), no second copy.
        assert stats2.sequences_created == 0
        assert _count(s, Sequence) == 1
        seq = s.execute(select(Sequence).where(Sequence.kind == "archive")).scalars().one()
        assert _count(s, SequenceItem) == 2
        # The container's import date was refreshed by the re-import.
        assert s.get(Item, seq.item_id).last_imported_at >= before


def test_active_file_promoted_to_higher_quality(lib, tmp_path: Path):
    """A near-dup re-import becomes the active source when it's better quality:
    same resolution but a lossless (PNG) format beats the lossy (JPEG) original."""
    from PIL import Image

    from tests.core.conftest import make_image

    cfg, db, store = lib
    base = make_image(tmp_path / "base.png", seed=3, size=(400, 300))
    with Image.open(base) as im:
        rgb = im.convert("RGB")
        jpg = tmp_path / "a.jpg"
        rgb.save(jpg, "JPEG", quality=95)
        png = tmp_path / "a.png"
        rgb.save(png, "PNG")

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [jpg], ImportOptions(folders_as_groups=False)
        )
        s.commit()
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [png], ImportOptions(folders_as_groups=False)
        )
        s.commit()

    with db.session() as s:
        assert stats.added_alternative == 1  # PNG folded in as an alternative
        item = s.execute(select(Item)).scalars().one()
        active = s.get(File, item.active_file_id)
        assert normalize_format(active.format) == "png"  # lossless now active


def test_edited_active_file_not_overridden_by_reimport(lib, tmp_path: Path):
    """An import never overrides a user's edit: when the active file is an
    edited/derived version, a higher-quality near-dup re-import folds in as an
    alternative but the edit stays active."""
    from PIL import Image

    from tests.core.conftest import make_image

    cfg, db, store = lib
    base = make_image(tmp_path / "base.png", seed=5, size=(400, 300))
    with Image.open(base) as im:
        rgb = im.convert("RGB")
        jpg = tmp_path / "a.jpg"
        rgb.save(jpg, "JPEG", quality=95)
        png = tmp_path / "a.png"
        rgb.save(png, "PNG")

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [jpg], ImportOptions(folders_as_groups=False)
        )
        s.commit()
        item = s.execute(select(Item)).scalars().one()
        active = s.get(File, item.active_file_id)
        active.is_derived = True  # pretend the active source is an edit
        edited_id = active.id
        s.commit()

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [png], ImportOptions(folders_as_groups=False)
        )
        s.commit()

    with db.session() as s:
        item = s.execute(select(Item)).scalars().one()
        # The lossless PNG would normally be promoted, but the edit wins.
        assert item.active_file_id == edited_id


def test_a_later_import_matches_files_earlier_imports_stored(lib, tmp_path: Path):
    """Near-dup matching reads the band-key COLUMNS, so a file stored by any
    earlier import — a different Importer, an out-of-band writer — is a
    candidate at once: there is no per-process index to prime, no signature
    to go stale, and nothing to share between import jobs."""
    from PIL import Image

    from tests.core.conftest import make_image

    cfg, db, store = lib
    a = make_image(tmp_path / "a.png", seed=8, size=(320, 240))
    c = make_image(tmp_path / "c.png", seed=44, size=(320, 240))
    with Image.open(a) as im:
        im.convert("RGB").save(tmp_path / "a.jpg", "JPEG", quality=95)
    with Image.open(c) as im:
        im.convert("RGB").save(tmp_path / "c.jpg", "JPEG", quality=95)

    # 1. One import stores a.png; a LATER one folds its near-dup JPEG.
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [a], ImportOptions(folders_as_groups=False)
        )
        s.commit()
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [tmp_path / "a.jpg"], ImportOptions(folders_as_groups=False)
        )
        s.commit()
    assert stats.added_alternative == 1

    # 2. c.png arrives through yet another importer; its near-dup still folds.
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [c], ImportOptions(folders_as_groups=False)
        )
        s.commit()
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [tmp_path / "c.jpg"], ImportOptions(folders_as_groups=False)
        )
        s.commit()
    assert stats.added_alternative == 1


def test_reorientation_detection_folds_rotation_into_item(lib, tmp_path: Path):
    """Reorientation detection always runs on import (there is no per-import
    opt-out): a rotated copy of an existing image is folded into that item's
    source files (not a separate linked item), while an unrelated image stays
    its own item."""
    from PIL import Image
    from media_compost.db import File, Item, Relationship
    from tests.core.conftest import make_image

    cfg, db, store = lib
    a = make_image(tmp_path / "a.png", seed=11)
    Image.open(a).rotate(90, expand=True).save(tmp_path / "a_rot.png", "PNG")
    b = make_image(tmp_path / "b.png", seed=77)  # unrelated
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [a, tmp_path / "a_rot.png", b],
            ImportOptions(folders_as_groups=False),
        )
        s.commit()
    with db.session() as s:
        # Two items: the folded rotation shares "a"'s item, so only a + b remain.
        assert s.execute(select(func.count()).select_from(Item)).scalar_one() == 2
        # No edit relationships are created — the reorientation is a file, not a
        # linked derived item.
        assert s.execute(
            select(func.count()).select_from(Relationship)
            .where(Relationship.kind == "edit")
        ).scalar_one() == 0
        # The first item now owns two source files (the original + its rotation).
        first = s.execute(select(Item).order_by(Item.id)).scalars().first()
        files = s.execute(
            select(File).where(File.item_id == first.id).order_by(File.id)
        ).scalars().all()
        assert len(files) == 2
        # The pristine first file is the orientation reference (0°, no mirror);
        # the folded rotation records its angle relative to it.
        assert (files[0].rotation, files[0].mirrored) == (0, False)
        assert files[1].rotation in (90, 270) and files[1].mirrored is False


def test_all_eight_dihedral_copies_fold_onto_the_original(lib, tmp_path: Path):
    """Every whole-image reorientation (four rotations x optional mirror, PIL's
    transpose set) plus a plain re-encode folds into the original's item as an
    alternative source file — never a second item, never an edit relationship."""
    from PIL import Image
    from media_compost.db import Relationship
    from tests.core.conftest import make_image

    cfg, db, store = lib
    a = make_image(tmp_path / "a.png", seed=23)
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [a], ImportOptions(folders_as_groups=False)
        )
        s.commit()

    transforms = [
        Image.Transpose.ROTATE_90,
        Image.Transpose.ROTATE_180,
        Image.Transpose.ROTATE_270,
        Image.Transpose.FLIP_LEFT_RIGHT,
        Image.Transpose.FLIP_TOP_BOTTOM,
        Image.Transpose.TRANSPOSE,
        Image.Transpose.TRANSVERSE,
    ]
    copies = []
    with Image.open(a) as im:
        rgb = im.convert("RGB")
        for i, op in enumerate(transforms):
            p = tmp_path / f"a_t{i}.png"
            rgb.transpose(op).save(p, "PNG")
            copies.append(p)
        # The identity re-encode (a JPEG of the same pixels) folds in too,
        # via the plain near-dup path.
        p = tmp_path / "a_reenc.jpg"
        rgb.save(p, "JPEG", quality=95)
        copies.append(p)

    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            copies, ImportOptions(folders_as_groups=False)
        )
        s.commit()

    assert stats.imported == 0, stats.as_dict()
    assert stats.added_alternative == 8, stats.as_dict()
    with db.session() as s:
        # Still one item; all copies are source files of it.
        assert _count(s, Item) == 1
        item = s.execute(select(Item)).scalars().one()
        files = s.execute(
            select(File).where(File.item_id == item.id).order_by(File.id)
        ).scalars().all()
        assert len(files) == 9
        # No edit relationships — a reorientation is a file, not a linked item.
        assert s.execute(
            select(func.count()).select_from(Relationship)
            .where(Relationship.kind == "edit")
        ).scalar_one() == 0
        # The original stays the orientation reference; each reoriented copy
        # records a real reorientation relative to it.
        assert (files[0].rotation, files[0].mirrored) == (0, False)
        reoriented = [
            f for f in files[1:]
            if int(f.rotation or 0) % 360 != 0 or f.mirrored
        ]
        assert len(reoriented) == 7  # all but the identity re-encode


def test_frame_rows_written_out_of_band_are_matched_at_once(lib, tmp_path: Path):
    """The frame probe reads `video_frames` directly, so rows another session
    wrote are candidates with nothing to reload — the whole-table reload a
    single-file upload used to pay is simply gone."""
    from media_compost.db import VideoFrame

    cfg, db, store = lib
    from tests.core.conftest import make_image

    img = make_image(tmp_path / "x.png", seed=31)
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [img], ImportOptions(folders_as_groups=False)
        )
        s.commit()

    # Frame rows appear out-of-band (as another import would create them),
    # matching x.png's own hash at the picture's own aspect.
    with db.session() as s:
        item = s.execute(select(Item)).scalars().one()
        f = s.execute(select(File)).scalars().one()
        s.add(VideoFrame(video_item_id=item.id, video_file_id=f.id,
                         timestamp=1.0, phash=f.phash,
                         width=f.width, height=f.height))
        s.commit()

    with db.session() as s:
        f = s.execute(select(File)).scalars().one()
        imp = Importer(s, store, cfg)
        from media_compost.dedup import phash_to_int
        hits = imp._match_video_frames(phash_to_int(f.phash),
                                       f.width, f.height)
        assert list(hits.values()) == [[1.0]]


# ---- PDFs: a container of pictures, like a comic archive --------------------

def _make_pdf(path: Path, pages: int = 3) -> Path:
    """A PDF of visibly DIFFERENT pages, written with Pillow so the test needs
    nothing the library does not already depend on. Different because the
    import is a real import: flat pages of one colour dedup onto each other,
    which is the importer being right rather than the PDF reader being wrong."""
    from PIL import Image, ImageDraw

    ims = []
    for i in range(pages):
        im = Image.new("RGB", (300, 400), (250, 250, 250))
        d = ImageDraw.Draw(im)
        for k in range(i + 1):
            d.rectangle([20 + k * 30, 20 + k * 40, 120 + k * 45, 220 + k * 30],
                        fill=(20 + 70 * k, 40 * i, 200 - 50 * k))
        ims.append(im)
    ims[0].save(path, save_all=True, append_images=ims[1:])
    return path


def test_a_pdf_imports_as_one_image_item_per_page_and_a_sequence(lib, tmp_path: Path):
    """A PDF is an archive of pictures as far as this library is concerned, so
    it goes through the same `_ingest_image` every other picture does — dedup,
    hashing, thumbnails and all — and its pages become a reading order."""
    import pytest

    from media_compost import media
    from media_compost.db import Sequence, SequenceItem

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    _make_pdf(src / "manual.pdf", pages=3)
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.commit()
    assert stats.errors == []
    with db.session() as s:
        pages = s.execute(select(Item).where(Item.kind == "image")).scalars().all()
        assert len(pages) == 3
        # Real stored pictures, not placeholders.
        for p in pages:
            f = s.get(File, p.active_file_id)
            assert f is not None and f.format == "webp" and (f.width or 0) > 0
        seq = s.execute(select(Sequence)).scalars().one()
        assert seq.kind == "pdf" and seq.name == "manual.pdf"
        members = s.execute(
            select(SequenceItem.item_id)
            .where(SequenceItem.sequence_id == seq.id)
            .order_by(SequenceItem.position)
        ).scalars().all()
        # In PAGE order: the names are zero-padded, so the natural sort the
        # sequence builder uses puts page 10 after page 9 rather than after 1.
        assert members == [p.id for p in sorted(pages, key=lambda x: x.name)]
        assert [p.name for p in sorted(pages, key=lambda x: x.name)] == [
            "manual-0001.webp", "manual-0002.webp", "manual-0003.webp"]


def test_every_pdf_page_is_written_LOSSLESSLY(tmp_path: Path):
    """A page is the only copy of itself the library will ever have, so the
    import may not throw pixels away — and it does not have to. Lossless WebP
    beats PNG on BOTH axes on every document measured (0.42-0.45x the bytes on
    vector pages, 0.70-0.88x on scans, at 30-60 ms against 41-101 ms), which is
    what made the old rule — PNG for a flat page, JPEG for a photographic one,
    decided by counting colours — unnecessary as well as lossy.

    Asserted against the RENDERER's own bitmap: the page is rasterized a
    second time here, with the same scale `iter_pdf_pages` uses, and the file
    it wrote has to decode to exactly that. `lossless=True` is one keyword that
    can be dropped in an edit without anything else changing, and every other
    symptom of dropping it (bytes, timings) is a judgement call rather than a
    test.
    """
    import pytest
    from PIL import Image, ImageChops, ImageDraw

    from media_compost import media

    import numpy as np
    import pypdfium2 as pdfium

    # The two kinds the old heuristic split on, so both are covered: flat
    # vector-ish drawing, and noise no lossy encoder can keep.
    flat = Image.new("RGB", (600, 800), (255, 255, 255))
    d = ImageDraw.Draw(flat)
    d.rectangle([40, 40, 560, 400], outline=(0, 0, 0), width=3)
    d.ellipse([80, 450, 500, 760], outline=(0, 0, 0), width=3)
    rng = np.random.default_rng(3)
    photo = Image.fromarray(
        rng.integers(0, 256, size=(800, 600, 3), dtype=np.uint8))

    def rendered(pdf: Path, i: int) -> Image.Image:
        """The bitmap `iter_pdf_pages` starts from, made the same way."""
        doc = pdfium.PdfDocument(str(pdf))
        try:
            page = doc[i]
            w, h = page.get_size()
            scale = media.PDF_PAGE_PX / max(1.0, max(w, h))
            im = page.render(scale=scale).to_pil()
            return im if im.mode == "RGB" else im.convert("RGB")
        finally:
            doc.close()

    for name, page in (("flat", flat), ("photo", photo)):
        pdf = tmp_path / f"{name}.pdf"
        page.save(pdf)
        with media.iter_pdf_pages(pdf) as pages:
            for i, (_n, path) in enumerate(pages):
                assert path.suffix == ".webp", name
                with Image.open(path) as im:
                    im.load()
                    assert im.format == "WEBP"
                    written = im.convert("RGB")
                assert ImageChops.difference(
                    written, rendered(pdf, i)).getbbox() is None, name


# ---- animated GIFs: a run of pictures, not a film -------------------------

def _make_gif(path: Path, frames: int = 4, *, size=(160, 120)) -> Path:
    """An animated GIF of visibly DIFFERENT frames.

    Different because the import is a real import: two identical frames dedup
    onto one item, which is the importer being right — and is asserted on its
    own below."""
    from PIL import Image, ImageDraw

    ims = []
    for i in range(frames):
        im = Image.new("RGB", size, (250, 250, 250))
        d = ImageDraw.Draw(im)
        d.rectangle([10 + i * 25, 10, 70 + i * 15, 100],
                    fill=(20 + 60 * i, 200 - 45 * i, 90 + 30 * i))
        ims.append(im)
    ims[0].save(path, save_all=True, append_images=ims[1:], duration=80, loop=0)
    return path


def test_an_animated_gif_imports_as_one_image_item_per_frame_and_a_sequence(
        lib, tmp_path: Path):
    """It used to import as a VIDEO item, and a browser plays no GIF in a
    `<video>` — so the preview overlay, the annotator and the video editor
    were each a black rectangle. As frames it is what the library already
    holds: ordinary pictures, in the order they play."""
    from media_compost.db import Sequence, SequenceItem

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    _make_gif(src / "spin.gif", frames=4)
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.commit()
    assert stats.errors == []
    with db.session() as s:
        # No video item, and no GIF file stored whole.
        assert _count(s, Item) == 5  # 4 frames + the sequence container
        assert s.execute(
            select(Item).where(Item.kind == "video")).scalars().all() == []
        frames = s.execute(
            select(Item).where(Item.kind == "image")).scalars().all()
        assert len(frames) == 4
        for f_item in frames:
            f = s.get(File, f_item.active_file_id)
            # Real stored pictures, in the format `encode_lossless` chooses.
            assert f is not None and f.format == "webp" and (f.width or 0) > 0
        seq = s.execute(select(Sequence)).scalars().one()
        assert seq.kind == "gif" and seq.name == "spin.gif"
        members = s.execute(
            select(SequenceItem.item_id)
            .where(SequenceItem.sequence_id == seq.id)
            .order_by(SequenceItem.position)
        ).scalars().all()
        # In PLAY order: the names are zero-padded, so the natural sort the
        # sequence builder uses puts frame 10 after frame 9 rather than after 1.
        in_order = sorted(frames, key=lambda x: x.name)
        assert members == [x.id for x in in_order]
        assert [x.name for x in in_order] == [
            "spin-0001.webp", "spin-0002.webp", "spin-0003.webp",
            "spin-0004.webp"]


def test_a_repeated_gif_frame_is_ONE_item_held_at_two_positions(
        lib, tmp_path: Path):
    """A GIF that holds a drawing on screen writes that frame several times.
    Those are one picture, and a sequence may repeat a member — so the item
    count follows the DRAWINGS while the sequence keeps every frame's slot."""
    from PIL import Image, ImageDraw

    from media_compost.db import Sequence, SequenceItem

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    ims = []
    for i in (0, 1, 0, 1):
        im = Image.new("RGB", (120, 90), (250, 250, 250))
        ImageDraw.Draw(im).rectangle([10 + i * 40, 10, 60 + i * 30, 80],
                                     fill=(200 * i, 60, 180 - 90 * i))
        ims.append(im)
    ims[0].save(src / "blink.gif", save_all=True, append_images=ims[1:])
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.commit()
    assert stats.errors == []
    with db.session() as s:
        frames = s.execute(
            select(Item).where(Item.kind == "image")).scalars().all()
        assert len(frames) == 2
        seq = s.execute(select(Sequence)).scalars().one()
        members = s.execute(
            select(SequenceItem.item_id)
            .where(SequenceItem.sequence_id == seq.id)
            .order_by(SequenceItem.position)
        ).scalars().all()
        assert len(members) == 4 and members[0] == members[2]


def test_a_single_frame_gif_is_still_an_ordinary_picture(lib, tmp_path: Path):
    """One frame is a picture, not a book of one. It also has to stay OUT of
    the video half of the app: `files.get_thumb` used to run ffmpeg over it
    looking for a representative frame, and `jobs._only_pictures` dropped it
    from every AI action, both off GIF's old `VIDEO_EXTS` membership."""
    from PIL import Image, ImageDraw

    from media_compost.config import VIDEO_EXTS
    from media_compost.db import Sequence

    assert "gif" not in VIDEO_EXTS

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    im = Image.new("RGB", (140, 100), (240, 240, 240))
    ImageDraw.Draw(im).ellipse([20, 20, 100, 80], fill=(30, 120, 200))
    im.save(src / "logo.gif")
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.commit()
    assert stats.errors == []
    with db.session() as s:
        item = s.execute(select(Item)).scalars().one()
        assert item.kind == "image"
        f = s.get(File, item.active_file_id)
        # Its OWN bytes, untouched — this one was imported, not rendered.
        assert f.format == "gif"
        assert s.execute(select(Sequence)).scalars().all() == []


def test_an_animated_gif_UPLOADED_AS_BYTES_takes_the_same_path(
        lib, tmp_path: Path):
    """`classify` reads the frame count off the file and the prefetch has only
    a NAME, so an animated gif reached `prepare_source` as an ordinary image —
    and its bundle carries the whole file's sha256. Consumed by the first
    frame, that would store the GIF's identity on one of its pictures."""
    from media_compost.db import Sequence
    from media_compost.importer import ImportBytes, prepare_source

    cfg, db, store = lib
    gif = _make_gif(tmp_path / "wave.gif", frames=3)
    src = ImportBytes(name="wave.gif", data=gif.read_bytes())
    assert prepare_source(src) is None

    with db.session() as s:
        imp = Importer(s, store, cfg)
        imp.begin_run(ImportOptions(folders_as_groups=False))
        imp.add_source(src, ImportOptions(folders_as_groups=False),
                       prepared=prepare_source(src))
        stats = imp.finish_run()
    assert stats.errors == []
    with db.session() as s:
        assert len(s.execute(
            select(Item).where(Item.kind == "image")).scalars().all()) == 3
        assert s.execute(select(Sequence)).scalars().one().kind == "gif"
        # Nothing carries the GIF's own digest: the frames are their own files.
        import hashlib
        whole = hashlib.sha256(gif.read_bytes()).hexdigest()
        assert s.execute(
            select(File).where(File.sha256 == whole)).scalars().all() == []


def test_pdf_bytes_are_recognised_without_a_filename():
    """`sniff_ext` is what an in-memory import leans on when the name carries
    no usable extension; a PDF has to be one of the answers or it lands as
    "unrecognized file type"."""
    from media_compost import media

    assert media.sniff_ext(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n") == "pdf"


def test_a_match_on_a_HIDDEN_or_TRASHED_item_is_reported(lib, tmp_path: Path):
    """Folding onto something the grid does not show is still folding.

    The import reports success and the picture is nowhere to be found — it is
    inside a hidden item or one somebody threw away, which reads exactly like
    an import that dropped files. Nothing here is repaired automatically:
    un-hiding somebody's hidden item and restoring their Trash are both
    decisions. The run names the files instead.
    """
    from PIL import Image

    from media_compost.db import TrashedItem
    from tests.core.conftest import make_image

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    a = make_image(src / "a.png", seed=1, size=(400, 300))
    b = make_image(src / "b.png", seed=2, size=(400, 300))
    with db.session() as s:
        Importer(s, store, cfg).import_paths([a, b], ImportOptions())
        s.commit()

    with db.session() as s:
        by_name = {i.name: i for i in
                   s.execute(select(Item)).scalars().all()}
        by_name["a.png"].hidden = True
        s.add(TrashedItem(item_id=by_name["b.png"].id))
        s.commit()

    # The same bytes (the exact-duplicate path) and a SCALED copy of the second
    # (the near-dup alternative path) — both landings are reported. Scaled from
    # the file rather than re-drawn: `make_image` places its shapes modulo the
    # size, so the same seed at another size is a different picture.
    with Image.open(b) as im:
        im.resize((200, 150)).save(tmp_path / "b-small.png", "PNG")
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [a, tmp_path / "b-small.png"], ImportOptions())
        s.commit()

    assert stats.imported == 0, stats.as_dict()
    assert stats.skipped_duplicate == 1 and stats.added_alternative == 1
    assert sorted(stats.hidden_matches) == [("a.png", "hidden"),
                                            ("b-small.png", "trashed")]
    # …and it rides out to the job, which is what the file list reads.
    assert sorted(stats.as_dict()["hidden_matches"]) == [
        ["a.png", "hidden"], ["b-small.png", "trashed"]]


def test_an_ordinary_match_reports_nothing(lib, tmp_path: Path):
    """The warning is about invisibility, not about matching: re-importing a
    picture the library shows is the ordinary case and says nothing."""
    from tests.core.conftest import make_image

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "a.png", seed=3, size=(400, 300))
    with db.session() as s:
        Importer(s, store, cfg).import_paths([src], ImportOptions())
        s.commit()
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths([src], ImportOptions())
        s.commit()
    assert stats.skipped_duplicate == 1
    assert stats.hidden_matches == []


def test_import_tags_land_on_created_items_and_kinds(lib, tmp_path: Path):
    """`ImportOptions.tags` goes on everything the run creates — sequence
    containers included — and the per-kind lists on their kinds. Through the
    ordinary assignment door, so an alias or a refused score name cannot
    derail a finished import; and a re-import creates nothing, so it tags
    nothing."""
    from media_compost.db import ItemTag, Tag
    from media_compost.testing import make_image

    cfg, db, store = lib
    src = tmp_path / "tagged"
    src.mkdir()
    make_image(src / "one.png", seed=101, size=(64, 48))
    _make_cbz(src / "book.cbz", tmp_path, ["p1.png", "p2.png"])
    opts = ImportOptions(folders_as_groups=False,
                         tags=["batch", "  Two Words  "],
                         tags_image=["pic"], tags_sequence=["book"])
    with db.session() as s:
        Importer(s, store, cfg).import_paths([src], opts)
    with db.session() as s:
        def items_with(name):
            tag = s.execute(select(Tag).where(Tag.name == name)
                            ).scalars().first()
            if tag is None:
                return set()
            return {iid for (iid,) in s.execute(
                select(ItemTag.item_id).where(ItemTag.tag_id == tag.id))}

        images = {i.id for i in s.execute(select(Item)).scalars()
                  if i.kind == "image"}
        seqs = {i.id for i in s.execute(select(Item)).scalars()
                if i.kind == "sequence"}
        assert len(images) == 3 and len(seqs) == 1
        # The base tags cover everything created, normalized like a tag field.
        assert items_with("batch") == images | seqs
        assert items_with("two_words") == images | seqs
        # The per-kind lists stay with their kinds.
        assert items_with("pic") == images
        assert items_with("book") == seqs

    # A "-" prefix is the NEGATIVE sign, not part of the name.
    src2 = tmp_path / "signed"
    src2.mkdir()
    make_image(src2 / "neg.png", seed=202, size=(64, 48))
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [src2], ImportOptions(folders_as_groups=False,
                                  tags=["-blurry", "keep"]))
    with db.session() as s:
        from sqlalchemy import select as sel
        row = s.execute(select(ItemTag).join(Tag).where(
            Tag.name == "blurry")).scalars().one()
        assert row.negative is True
        assert s.execute(select(Tag).where(
            Tag.name == "-blurry")).scalars().first() is None

    # A re-import creates nothing, but by default (`tags_existing`) the tags
    # still land on the items it MATCHED — a re-import of a folder is how a
    # batch gets a tag after the fact.
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False, tags=["again"]))
    with db.session() as s:
        tagged = s.execute(
            select(ItemTag).join(Tag).where(Tag.name == "again")
        ).scalars().all()
        assert len(tagged) > 0

    # With the option OFF, a run that creates nothing tags nothing.
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False, tags=["never"],
                                 tags_existing=False))
    with db.session() as s:
        assert s.execute(select(Tag).where(Tag.name == "never")
                         ).scalars().first() is None


def test_an_in_place_pixel_rewrite_moves_the_band_keys_with_the_hash(
    lib, tmp_path: Path
):
    """`fileops` can rewrite a file's bytes UNDER ITS OWN ROW (an in-place
    rotation), which reassigns `File.phash`. The band-key columns travel in
    the SAME flush (the `before_flush` listener's dirty branch), so the
    probe answers for the picture that is actually stored — the in-memory
    index this replaced went on nominating the pre-rotation hash until an
    invalidation channel told it otherwise, and the thumb LRU (keyed by
    (id, phash) now) was stale in exactly the same way.
    """
    from PIL import Image

    from media_compost import fileops
    from media_compost.dedup import phash_to_int
    from media_compost.dedup_index import find_best_file
    from tests.core.conftest import make_image

    cfg, db, store = lib
    a = make_image(tmp_path / "a.png", seed=23, size=(320, 240))

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [a], ImportOptions(folders_as_groups=False))
        s.commit()

    with db.session() as s:
        f = s.execute(select(File)).scalars().one()
        before = f.phash
        fileops.rotate_active_file(s, store, f, 90, in_place=True)
        s.commit()
        s.refresh(f)
        after = f.phash
        # The premise: same row, a different picture.
        assert before != after
        # The probe already answers for the new hash and not the old.
        assert find_best_file(s, phash_to_int(after), 0) == f.id
        assert find_best_file(s, phash_to_int(before), 0) is None

    # End to end: the same rotated picture at another size is ONE item.
    with db.session() as s:
        f = s.execute(select(File)).scalars().one()
        with Image.open(store.path_of(s, f)) as im:
            im.resize((int(im.width * 0.95), int(im.height * 0.95))).save(
                tmp_path / "a_rot_small.png")
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [tmp_path / "a_rot_small.png"],
            ImportOptions(folders_as_groups=False))
        s.commit()
    assert stats.added_alternative == 1
    assert stats.imported == 0
    with db.session() as s:
        assert _count(s, Item) == 1


# --- the prefetch bundle, and what a worker PROCESS may leave out of it ------
#
# `prepare_source` computes the whole CPU-heavy half of a still-image import,
# and `ImportRun.add_many` may run it in another process — where the decoded
# picture cannot come back (4.7 MB pickled against ~10 KB for everything
# else). These hold the invariant that makes that safe: a bundle WITHOUT the
# pixels must import to exactly what a bundle WITH them imports to.


def test_a_prepared_bundle_carries_the_expensive_answers(tmp_path: Path):
    from media_compost.importer import ImportBytes, prepare_source
    from media_compost.testing import make_jpeg_with_exif

    src = make_jpeg_with_exif(tmp_path / "a.jpg", seed=3)
    pre = prepare_source(src)
    assert pre is not None
    # The three things the serial half used to need full pixels for on EVERY
    # picture. Each is what makes the decode droppable, so each is asserted.
    assert len(pre.dihedral) == 8, "the 8 orientation pHashes"
    assert pre.dihedral[0] == phash_to_int(pre.phash), "identity comes first"
    assert pre.canon is not None and pre.canon.shape == (48, 48)
    assert any(mv.name == "camera_make" for mv in pre.meta_values or []), \
        "the EXIF read, so index_file_metadata need not re-read the file"
    assert len(pre.rgb32) == 3 * 32 * 32, \
        "the near-dup verifier's incoming side (RGB now — see norm_rgb), " \
        "so a fifth of a crawl's imports stops re-decoding the file on " \
        "the serial thread"

    # And bytes answer identically to the same file on disk — the crawler
    # path never has a file when the prefetch runs.
    from_bytes = prepare_source(ImportBytes(data=src.read_bytes(), name="a.jpg"))
    assert from_bytes is not None
    assert from_bytes.digest == pre.digest
    assert from_bytes.phash == pre.phash
    assert tuple(from_bytes.dihedral) == tuple(pre.dihedral)
    assert [(m.name, m.raw) for m in from_bytes.meta_values or []] == \
           [(m.name, m.raw) for m in pre.meta_values or []]


def test_a_bundle_WITHOUT_the_decoded_image_imports_to_the_same_library(
    lib, tmp_path: Path
):
    """The whole reason a prefetch may run in another process.

    `without_image` is what crosses the pipe; the serial half then decodes
    the file again for the few branches that still need pixels. If those two
    libraries ever differ, the process path is silently importing something
    else.
    """
    from media_compost.importer import prepare_source
    from media_compost.testing import make_image, make_jpeg_with_exif

    src = tmp_path / "src"
    src.mkdir()
    paths = [make_image(src / f"p{i}.png", seed=i) for i in range(6)]
    paths.append(make_jpeg_with_exif(src / "cam.jpg", seed=11))
    # A near-duplicate and a rotation, so the two branches that DO still want
    # the pixels (the pixel verify, the orientation record) are exercised.
    Image.open(paths[0]).resize((200, 150)).save(src / "small.png")
    Image.open(paths[1]).transpose(Image.Transpose.ROTATE_90).save(src / "rot.png")
    paths += [src / "small.png", src / "rot.png"]

    def run(data_dir: Path, slim: bool):
        cfg = Config(data_dir=data_dir)
        db, store = Database(cfg), ItemStore(cfg)
        with db.session() as s:
            imp = Importer(s, store, cfg)
            imp.begin_run(ImportOptions(folders_as_groups=False))
            for p in paths:
                pre = prepare_source(p)
                if pre is not None and slim:
                    pre = pre.without_image()
                imp.add_source(p, ImportOptions(folders_as_groups=False),
                               prepared=pre)
            imp.finish_run()
            s.commit()
        with db.session() as s:
            return sorted(
                (f.sha256, f.phash, f.color_key, f.color_sig, f.width,
                 f.height, f.format, f.item.kind,
                 # The orientation record is what the rotate/flip fold
                 # writes — the branch that reads the bundle's canon thumb
                 # now, so a wrong thumb would show up exactly here.
                 int(f.rotation or 0), bool(f.mirrored),
                 tuple(sorted(
                     (m.name, m.raw) for m in s.execute(
                         select(FileMetadata).where(
                             FileMetadata.file_id == f.id)).scalars())))
                for f in s.execute(select(File)).scalars()
            )

    full = run(tmp_path / "full", slim=False)
    assert any(r[8] or r[9] for r in full), \
        "the rotation branch must actually fire, or the orientation " \
        "columns are compared between two libraries that never wrote them"
    assert full == run(tmp_path / "slim", slim=True)


def test_hash_collision_storms_are_gated_not_capped(lib, tmp_path: Path):
    """Hash-nominated candidates are pruned by the stored ASPECT RATIO —
    never by a count, and no longer by colour: every survivor still gets its
    pixel check, so a collision storm cannot cost a genuine match (the
    owner's rule: reduce collisions, don't miss duplicates). The colour gate
    that sat beside the aspect one was removed after measuring 0% pruning on
    real content, so a colour-far decoy is CHECKED now — this test is what
    says that out loud."""
    import random

    from tests.core.conftest import make_image
    from media_compost.colorkey import color_signature
    from media_compost.dedup import compute_phash_image
    from media_compost.importer import dihedral_phashes
    from media_compost.media import load_rgb_with_info

    cfg, db, store = lib
    src = make_image(tmp_path / "orig.png", seed=41, size=(320, 240))
    rotated = tmp_path / "rot.png"
    with Image.open(src) as im:
        im.transpose(Image.Transpose.ROTATE_90).save(rotated)

    with db.session() as s:
        imp = Importer(s, store, cfg)
        stats = imp.import_paths([src], ImportOptions(folders_as_groups=False))
        assert stats.imported == 1

        turned_rgb = load_rgb_with_info(rotated)[1]
        probes = dihedral_phashes(
            turned_rgb, phash_to_int(compute_phash_image(turned_rgb)))
        csig = color_signature(turned_rgb)[1]
        rnd = random.Random(3)

        def perturbed() -> str:
            h = probes[rnd.randrange(len(probes))]
            for pos in rnd.sample(range(256), rnd.randrange(2, 6)):
                h ^= 1 << pos
            return f"{h:064x}"

        # Three kinds of decoy, all nominated by the hash probes. Their
        # stored files do not exist, so a pixel check on one reads as
        # "cannot decode" — which is exactly how the count below tells a
        # gated (never opened) candidate from a checked one.
        far_sig = csig ^ 0x3FF          # 10 bits away — colour never gates
        decoys = (
            # aspect fits, colour is far: CHECKED (colour cannot prune)
            [((320, 240), far_sig) for _ in range(6)]
            # aspect fits neither orientation: gated out
            + [((1000, 100), None) for _ in range(30)]
            # both fit: CHECKED, however many there are — that is the no-cap
            # half of the rule
            + [((240, 320), csig) for _ in range(5)]
        )
        for i, ((w, h), sig) in enumerate(decoys):
            it = Item(uid=f"d{i:06d}", name=f"decoy {i}", kind="image")
            s.add(it)
            s.flush()
            s.add(File(item_id=it.id, number=1, path="files/1.png",
                       sha256=f"decoy{i}", width=w, height=h, bytes=1,
                       format="png", phash=perturbed(), color_sig=sig))
        s.flush()
        s.commit()

    with db.session() as s:
        imp = Importer(s, store, cfg)
        checked = []
        orig = Importer._decode_thumb

        def spy(self, f):
            checked.append(f)
            return orig(self, f)

        Importer._decode_thumb = spy
        try:
            stats = imp.import_paths([rotated],
                                     ImportOptions(folders_as_groups=False))
        finally:
            Importer._decode_thumb = orig
        # Found through the decoys: folded into the original's item...
        assert stats.added_alternative == 1 and stats.edit_links == 1
        # ...with every aspect-passing candidate checked (six colour-far
        # decoys, five look-alikes, the genuine original) and the thirty
        # aspect-gated ones never decoded. (+2 slack: the verify path and
        # the orientation record read thumbs of their own.)
        assert 12 <= len(checked) <= 14, len(checked)


# ---- everything supported imports from inside an archive ---------------------


def _zip_of(zpath: Path, members: "dict[str, bytes]") -> Path:
    import zipfile

    zpath.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return zpath


def _png_bytes(tmp_path: Path, seed: int) -> bytes:
    from tests.core.conftest import make_image

    return make_image(tmp_path / f"_m{seed}.png", seed=seed).read_bytes()


def _gif_bytes(tmp_path: Path, seed: int) -> bytes:
    from PIL import Image as PILImage

    frames = []
    for i in range(3):
        im = PILImage.new("RGB", (160, 120))
        px = im.load()
        for y in range(120):
            for x in range(160):
                px[x, y] = ((x * (i + 2) + seed) % 256, (y * (i + 3)) % 256,
                            (x * y + i * 97) % 256)
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=80, loop=0)
    return buf.getvalue()


def test_every_supported_format_imports_from_inside_an_archive(
        lib, tmp_path: Path):
    """An archive member goes to the branch its own kind calls for — a zip
    holding a GIF, a nested zip of images and a text file imports the GIF as
    a book, flattens the nested zip's pictures into entries of their own,
    and reports the text file as a skipped entry by name (hidden junk
    excepted). It used to import only the loose pictures: a zip of books
    imported NOTHING, near-silently."""
    from media_compost.db import Sequence
    from media_compost.library.importing import import_run

    cfg, db, store = lib
    zpath = _zip_of(tmp_path / "mixed.zip", {
        "loop.gif": _gif_bytes(tmp_path, 5),
        "inner.zip": _zip_of(
            tmp_path / "_inner.zip",
            {"x.png": _png_bytes(tmp_path, 61),
             "y.png": _png_bytes(tmp_path, 62)}).read_bytes(),
        "plain.png": _png_bytes(tmp_path, 63),
        "notes.txt": b"nothing importable",
        "__MACOSX/loop.gif": b"junk",
        ".DS_Store": b"junk",
    })

    from media_compost import open_library

    lib2 = open_library(cfg.data_dir)
    with lib2:
        with lib2.importing(folders_as_groups=False) as run:
            got = run.add(zpath)
        by_status = {}
        for e in got.entries:
            by_status.setdefault(str(e.status), []).append(e)
        # The GIF is a book entry with its frames as children.
        (book,) = by_status["multi"]
        assert book.name == "loop.gif"
        assert book.item.kind == "sequence" and len(book.children) == 3
        # The nested zip's pictures and the loose one are flat entries.
        imported = by_status["imported"]
        assert sorted(e.name for e in imported) == [
            "inner.zip/x.png", "inner.zip/y.png", "plain.png"]
        assert all(e.file is not None for e in imported)
        # The text file is a visible skip; the junk is not.
        (skip,) = by_status["skipped"]
        assert skip.name == "notes.txt" and skip.file is None
        # One sequence in the library: the GIF's. The zips made none.
        assert lib2._session.query(Sequence).count() == 1


def test_a_book_inside_a_book_is_a_flat_sibling(lib, tmp_path: Path):
    """A cbz containing a nested zip of pictures: the comic's sequence holds
    only its DIRECT pages, and the nested pictures become entries of their
    own — the rule that keeps the result's depth fixed at entries+children."""
    from media_compost.db import Sequence, SequenceItem
    from media_compost import open_library

    cfg, db, store = lib
    cbz = _zip_of(tmp_path / "book.cbz", {
        "p01.png": _png_bytes(tmp_path, 71),
        "p02.png": _png_bytes(tmp_path, 72),
        "extras.zip": _zip_of(
            tmp_path / "_extras.zip",
            {"bonus.png": _png_bytes(tmp_path, 73)}).read_bytes(),
    })
    lib2 = open_library(cfg.data_dir)
    with lib2:
        with lib2.importing(folders_as_groups=False) as run:
            got = run.add(cbz)
        (book,) = [e for e in got.entries if str(e.status) == "multi"]
        assert [c.name for c in book.children] == ["p01.png", "p02.png"]
        flat = [e for e in got.entries if str(e.status) == "imported"]
        assert [e.name for e in flat] == ["extras.zip/bonus.png"]
        s = lib2._session
        seq = s.query(Sequence).one()
        assert s.query(SequenceItem).filter(
            SequenceItem.sequence_id == seq.id).count() == 2, \
            "the bonus picture is not a page of the comic"


def test_archives_nested_too_deep_are_skipped_by_name(lib, tmp_path: Path):
    """Depth `_ARCHIVE_DEPTH_MAX` guards hostile nesting: the member past it
    is recorded as skipped rather than opened."""
    from media_compost import open_library

    cfg, db, store = lib
    z3 = _zip_of(tmp_path / "_l3.zip", {"deep.png": _png_bytes(tmp_path, 81)})
    z2 = _zip_of(tmp_path / "_l2.zip", {"l3.zip": z3.read_bytes()})
    z1 = _zip_of(tmp_path / "_l1.zip", {"l2.zip": z2.read_bytes()})
    z0 = _zip_of(tmp_path / "outer.zip", {"l1.zip": z1.read_bytes()})
    lib2 = open_library(cfg.data_dir)
    with lib2:
        with lib2.importing(folders_as_groups=False) as run:
            got = run.add(z0)
        skipped = [e for e in got.entries if str(e.status) == "skipped"]
        assert skipped and "too deep" in skipped[0].error
        assert not [e for e in got.entries if str(e.status) == "imported"]


# ---- the minimum-resolution gate ----


def test_minimums_skips_small_pictures(lib, tmp_path: Path):
    """A picture under the minimum is not imported at all — not stored, not
    folded into a near-duplicate, not counted as a duplicate that refreshes
    something's dates. The SHORTER side decides, so a wide, short banner is
    small however many pixels across it is."""
    from tests.core.conftest import make_image

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "big.png", seed=1, size=(800, 600))
    make_image(src / "small.png", seed=2, size=(320, 240))
    make_image(src / "banner.png", seed=3, size=(2000, 100))
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False, min_short_edge=400))
    assert stats.imported == 1
    assert stats.ignored == 2
    with db.session() as s:
        names = {f.name for f in s.execute(select(FileName)).scalars().all()}
        assert names == {"src/big.png"}


def test_minimums_off_by_default(lib, tmp_path: Path):
    """Zero is the default and means "import whatever you are given"."""
    from tests.core.conftest import make_image

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "tiny.png", seed=4, size=(64, 48))
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
    assert stats.imported == 1 and stats.ignored == 0


def test_minimums_keeps_a_sequence_whole(lib, tmp_path: Path):
    """A book is judged by its LARGEST page and kept whole: one page over the
    minimum brings the small ones with it, because a chapter with holes in it
    is not what a page filter was asked for."""
    import zipfile

    from tests.core.conftest import make_image

    cfg, db, store = lib
    pages = tmp_path / "pages"
    pages.mkdir()
    make_image(pages / "p01.png", seed=11, size=(200, 150))   # under
    make_image(pages / "p02.png", seed=12, size=(900, 700))   # over
    make_image(pages / "p03.png", seed=13, size=(200, 150))   # under
    cbz = tmp_path / "book.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        for nm in ("p01.png", "p02.png", "p03.png"):
            zf.write(pages / nm, nm)
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [cbz], ImportOptions(folders_as_groups=False, min_short_edge=400))
    assert stats.imported == 3 and stats.ignored == 0
    from media_compost.db import Sequence, SequenceItem

    with db.session() as s:
        seq = s.execute(select(Sequence)).scalars().one()
        assert s.execute(
            select(func.count()).select_from(SequenceItem)
            .where(SequenceItem.sequence_id == seq.id)).scalar_one() == 3


def test_minimums_skips_a_whole_small_sequence(lib, tmp_path: Path):
    """…and a book with no page over the minimum is skipped WHOLE — one
    skipped entry for the book, no pages, no sequence, no group."""
    import zipfile

    from media_compost import open_library
    from tests.core.conftest import make_image

    cfg, db, store = lib
    pages = tmp_path / "small"
    pages.mkdir()
    for i in (1, 2):
        make_image(pages / f"p0{i}.png", seed=20 + i, size=(200, 150))
    cbz = tmp_path / "thumbs.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        for i in (1, 2):
            zf.write(pages / f"p0{i}.png", f"p0{i}.png")
    lib2 = open_library(cfg.data_dir)
    with lib2:
        with lib2.importing(folders_as_groups=False,
                            min_short_edge=400) as run:
            got = run.add(cbz)
        assert str(got.status) == "ignored"
        assert [str(e.status) for e in got.entries] == ["ignored"]
        assert run.stats.ignored == 1
        assert run.stats.imported == 0
        s = lib2._session
        assert _count(s, Item) == 0
        assert _count(s, Group) == 0


def test_minimums_judges_a_plain_archives_members_one_by_one(
        lib, tmp_path: Path):
    """A plain archive is NOT a book: its members become items of their own,
    so each answers the gate itself."""
    import zipfile

    from tests.core.conftest import make_image

    cfg, db, store = lib
    pages = tmp_path / "loose"
    pages.mkdir()
    make_image(pages / "big.png", seed=31, size=(900, 700))
    make_image(pages / "small.png", seed=32, size=(200, 150))
    zpath = tmp_path / "mixed.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(pages / "big.png", "big.png")
        zf.write(pages / "small.png", "small.png")
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [zpath], ImportOptions(folders_as_groups=False,
                                   min_short_edge=400))
    assert stats.imported == 1 and stats.ignored == 1


def test_a_move_import_leaves_a_skipped_file_where_it_is(lib, tmp_path: Path):
    """The gate never takes the source: a move-import deletes what it stored,
    and it stored nothing here."""
    from tests.core.conftest import make_image

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    small = make_image(src / "small.png", seed=41, size=(100, 80))
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False, move=True,
                                 min_short_edge=400))
    assert small.exists()


def test_minimums_measures_a_pdfs_pages_without_rendering_them(
        lib, tmp_path: Path):
    """A PDF page is rendered at a size the app chooses, so the gate asks
    `media.pdf_page_sizes` — arithmetic on the page box — rather than
    rendering the document twice. Above the rendered short side the whole
    document is skipped; below it, every page comes in."""
    from media_compost import media

    cfg, db, store = lib
    pdf = _make_pdf(tmp_path / "doc.pdf", pages=2)
    sizes = media.pdf_page_sizes(pdf)
    assert len(sizes) == 2
    short = max(min(w, h) for w, h in sizes)
    # …and that is what the pages really come out at.
    with media.iter_pdf_pages(pdf) as rendered:
        assert [Image.open(p).size for _n, p in rendered] == sizes

    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [pdf], ImportOptions(folders_as_groups=False,
                                 min_short_edge=short + 1))
    assert stats.imported == 0 and stats.ignored == 1

    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [pdf], ImportOptions(folders_as_groups=False,
                                 min_short_edge=short))
    assert stats.imported == 2 and stats.ignored == 0


def test_the_three_minimums_are_each_a_minimum_to_clear(lib, tmp_path: Path):
    """Resolution, shortest edge and longest edge are three separate
    thresholds — the Storage page's prune rule read the other way round — and
    a file must clear EVERY one that is set. A 2000x100 banner is 0.2 MP with
    a long edge of 2000: which of the three is set decides what happens to
    it."""
    from tests.core.conftest import make_image

    cfg, db, store = lib

    def run(name: str, size: "tuple[int, int]", **limits) -> int:
        src = tmp_path / f"src_{name}"
        src.mkdir(exist_ok=True)
        make_image(src / f"{name}.png", seed=abs(hash(name)) % 500, size=size)
        with db.session() as s:
            st = Importer(s, store, cfg).import_paths(
                [src / f"{name}.png"],
                ImportOptions(folders_as_groups=False, **limits))
        return st.ignored

    # Megapixels: 0.2 MP is under half a megapixel, over a tenth.
    assert run("mp_under", (2000, 100), min_megapixels=0.5) == 1
    assert run("mp_over", (2000, 100), min_megapixels=0.1) == 0
    # The long edge passes what the short edge fails, on the same picture.
    assert run("edges_a", (2000, 100), min_long_edge=1000) == 0
    assert run("edges_b", (2000, 100), min_short_edge=200) == 1
    # Set together they are ANDed: clearing one is not enough.
    assert run("both", (2000, 100), min_long_edge=1000, min_short_edge=200) == 1


def test_the_aspect_range_is_a_range_and_knows_which_way_up(lib, tmp_path: Path):
    """`min_aspect`/`max_aspect` bound width/height from either side, and each
    end stands alone. Orientation-aware on purpose: a 2000x100 banner and a
    100x2000 column are the same shape to a long/short rule and opposite
    answers here."""
    from tests.core.conftest import make_image

    cfg, db, store = lib

    def run(name: str, size: "tuple[int, int]", **limits) -> int:
        src = tmp_path / f"asp_{name}"
        src.mkdir(exist_ok=True)
        make_image(src / f"{name}.png", seed=abs(hash(name)) % 500, size=size)
        with db.session() as s:
            st = Importer(s, store, cfg).import_paths(
                [src / f"{name}.png"],
                ImportOptions(folders_as_groups=False, **limits))
        return st.ignored

    # A banner is 20:1 wide, a column 1:20 tall.
    assert run("wide_out", (2000, 100), max_aspect=2) == 1
    assert run("wide_in", (2000, 100), min_aspect=0.5) == 0
    assert run("tall_out", (100, 2000), min_aspect=0.5) == 1
    assert run("tall_in", (100, 2000), max_aspect=2) == 0
    # Both ends together are the range: a square clears it, either extreme
    # does not.
    assert run("square", (800, 800), min_aspect=0.5, max_aspect=2) == 0
    assert run("wide_both", (2000, 100), min_aspect=0.5, max_aspect=2) == 1
    # The bound is inclusive at its own value (2:1 is not "over 2").
    assert run("exact", (1000, 500), max_aspect=2) == 0
    # It is ANDed with the minimums, like every other filter here.
    assert run("with_min", (1000, 500), max_aspect=2, min_short_edge=800) == 1


def test_a_sequence_passes_when_ANY_page_clears_the_minimums(lib, tmp_path: Path):
    """"Kept whole" is asked page by page, not of one "largest" page: with
    three thresholds there is no single largest, since the page with the most
    pixels need not be the one with the longest short edge."""
    import zipfile

    from tests.core.conftest import make_image

    cfg, db, store = lib
    pages = tmp_path / "mixed_pages"
    pages.mkdir()
    # p01 has the most pixels; p02 has the longest SHORT edge. Only p02 can
    # clear a short-edge minimum, and it is not the "largest" page.
    make_image(pages / "p01.png", seed=61, size=(4000, 100))
    make_image(pages / "p02.png", seed=62, size=(600, 600))
    cbz = tmp_path / "mixed.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        for nm in ("p01.png", "p02.png"):
            zf.write(pages / nm, nm)
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths(
            [cbz], ImportOptions(folders_as_groups=False, min_short_edge=500))
    assert stats.imported == 2 and stats.ignored == 0


def test_ignore_kinds_leaves_whole_file_types_alone(lib, tmp_path: Path):
    """The four buckets partition what an import can be handed: a loose
    picture, a film, a book (PDF / animated GIF / comic archive) and an
    archive that scatters. Ignoring one leaves it where it is."""
    import zipfile

    from tests.core.conftest import make_image

    cfg, db, store = lib
    src = tmp_path / "mixed"
    src.mkdir()
    make_image(src / "loose.png", seed=71, size=(600, 500))
    _make_pdf(src / "book.pdf", pages=2)
    pages = tmp_path / "cbz_pages"
    pages.mkdir()
    for i in (1, 2):
        make_image(pages / f"p0{i}.png", seed=80 + i, size=(500, 700))
    make_image(pages / "inside.png", seed=95, size=(500, 700))
    with zipfile.ZipFile(src / "comic.cbz", "w") as zf:
        for i in (1, 2):
            zf.write(pages / f"p0{i}.png", f"p0{i}.png")
    with zipfile.ZipFile(src / "loose.zip", "w") as zf:
        zf.write(pages / "inside.png", "inside.png")

    def run(ignore):
        cfg2 = Config(data_dir=tmp_path / f"data_{'_'.join(ignore) or 'all'}")
        db2, store2 = Database(cfg2), ItemStore(cfg2)
        with db2.session() as s:
            return Importer(s, store2, cfg2).import_paths(
                [src], ImportOptions(folders_as_groups=False,
                                     ignore_kinds=tuple(ignore)))

    # Everything: the loose picture, the zip's member, and two books of two.
    every = run([])
    assert (every.imported, every.sequences_created, every.ignored) == (6, 2, 0)

    # A book is a PDF, a GIF or a comic — the plain zip still scatters.
    no_books = run(["sequence"])
    assert (no_books.imported, no_books.sequences_created,
            no_books.ignored) == (2, 0, 2)

    # …and the plain archive is the fourth bucket, not the third.
    no_zips = run(["archive"])
    assert (no_zips.imported, no_zips.sequences_created,
            no_zips.ignored) == (5, 2, 1)

    # A PAGE of a book is not judged by the type filter, or ignoring images
    # would hollow out the comic — but a plain archive's member is an item of
    # its own and answers for itself.
    no_pictures = run(["image"])
    assert (no_pictures.imported, no_pictures.sequences_created,
            no_pictures.ignored) == (4, 2, 2)


def test_an_ignored_file_says_which_reason(lib, tmp_path: Path):
    """Both reasons are `ignored` — the run was told not to take these — and
    the entry says which; neither is the `duplicate` the library already
    holds nor the `skipped` it cannot read."""
    from media_compost import open_library
    from tests.core.conftest import make_image

    cfg, db, store = lib
    small = make_image(tmp_path / "small.png", seed=91, size=(100, 90))
    big = make_image(tmp_path / "big.png", seed=92, size=(900, 800))
    lib2 = open_library(cfg.data_dir)
    with lib2:
        with lib2.importing(folders_as_groups=False, min_short_edge=400,
                            ignore_kinds=("video",)) as run:
            got = run.add(small)
        assert str(got.status) == "ignored"
        assert "minimum size" in got.entries[0].error
        with lib2.importing(folders_as_groups=False,
                            ignore_kinds=("image",)) as run:
            got2 = run.add(big)
        assert str(got2.status) == "ignored"
        assert "file type" in got2.entries[0].error
        # And the SHAPE is a third reason: size and aspect are different
        # questions, so a run that left something out says which answered.
        with lib2.importing(folders_as_groups=False, max_aspect=1.0) as run:
            got3 = run.add(big)
        assert str(got3.status) == "ignored"
        assert "aspect-ratio" in got3.entries[0].error


# ---- the folder walk's look-ahead -------------------------------------------


def _folder_of(tmp_path, n=12):
    src = tmp_path / "pics"
    src.mkdir()
    sub = src / "sub"
    sub.mkdir()
    for i in range(n):
        into = sub if i % 3 == 0 else src
        im = Image.new("RGB", (120, 90), (250, 250, 250))
        # Distinct pixels per file, or they all fold onto one item and the
        # comparison is between two libraries of one picture.
        for x in range(30):
            for y in range(20):
                im.putpixel((x + i, y + (i * 3) % 20),
                            ((i * 37) % 256, (i * 91) % 256, (i * 13) % 256))
        im.save(into / f"p{i:03d}.png")
    return src


def _imported(cfg, store, db, src, window):
    from media_compost import importer as imp_mod

    old = imp_mod.Importer._PREFETCH_WINDOW
    imp_mod.Importer._PREFETCH_WINDOW = window
    try:
        with db.session() as s:
            imp = Importer(s, store, cfg)
            imp.import_paths([src], ImportOptions())
            return [
                (i.id, i.name, f.sha256, f.phash, f.width, f.height)
                for i, f in s.execute(
                    select(Item, File).join(File, File.item_id == Item.id)
                    .order_by(Item.id)).all()
            ]
    finally:
        imp_mod.Importer._PREFETCH_WINDOW = old


def test_hashing_AHEAD_imports_exactly_what_hashing_IN_LINE_does(tmp_path):
    """The per-source arithmetic moves to workers; nothing else does.

    Order is the sorted walk's either way — what is submitted ahead is only
    submitted, and each file is still imported when the loop reaches it — so
    the item IDS have to line up with the same names, not merely the same set
    of names.
    """
    src = _folder_of(tmp_path)

    def run(tag, window):
        cfg = Config(data_dir=tmp_path / tag)
        cfg.ensure_dirs()
        db = Database(cfg)
        try:
            return _imported(cfg, ItemStore(cfg), db, src, window)
        finally:
            db.engine.dispose()

    serial = run("serial", 0)
    ahead = run("ahead", 4)
    assert len(serial) == 12
    assert serial == ahead


def test_the_look_ahead_pool_does_not_outlive_the_run(tmp_path):
    """`finish_run` shuts it down. A pool per import that nobody joins is a
    thread leak in a server that imports all day."""
    import threading

    src = _folder_of(tmp_path, n=6)
    cfg = Config(data_dir=tmp_path / "data")
    cfg.ensure_dirs()
    db = Database(cfg)
    try:
        before = threading.active_count()
        with db.session() as s:
            imp = Importer(s, ItemStore(cfg), cfg)
            imp.import_paths([src], ImportOptions())
            assert imp._pool is None, "finish_run left the pool open"
        assert threading.active_count() <= before
    finally:
        db.engine.dispose()


@pytest.mark.parametrize("as_sequence", [False, True])
def test_macos_zip_litter_is_skipped_before_it_reaches_a_decoder(
        lib, tmp_path: Path, as_sequence: bool):
    """A macOS zip carries `__MACOSX/._page.jpg` beside every page — an
    AppleDouble resource fork wearing the picture's own extension. By
    extension it classifies as an IMAGE, and the junk rule used to be asked
    only of members of NO supported kind, so each fork reached the decoder
    and reported "cannot read image ._page.jpg" (629 lines for six Viz
    volumes). The rule is asked of the NAME, first, whatever the kind — as a
    plain archive and as a sequence alike."""
    from media_compost import open_library

    cfg, db, store = lib
    zpath = _zip_of(tmp_path / "volume.zip", {
        "001.jpg": _png_bytes(tmp_path, 81),
        "__MACOSX/._001.jpg": b"\x00\x05\x16\x07" + b"\x00" * 60,
        "__MACOSX/._002.png": b"\x00\x05\x16\x07" + b"\x00" * 60,
        "._003.jpg": b"\x00\x05\x16\x07" + b"\x00" * 60,
    })
    lib2 = open_library(cfg.data_dir)
    with lib2:
        with lib2.importing(folders_as_groups=False,
                            archive_sequences=as_sequence) as run:
            got = run.add(zpath)
        errors = list(run.stats.errors) if hasattr(run, "stats") else []
        assert not errors, errors
        assert not got.error, got.error
        if as_sequence:
            (book,) = got.entries
            assert str(book.status) == "multi"
            names = [c.name for c in book.children]
        else:
            names = [e.name for e in got.entries]
        assert names == ["001.jpg"], names
        assert all("._" not in n and "__MACOSX" not in n for n in names)


def test_pdf_pages_and_archive_members_are_hashed_ahead(tmp_path, monkeypatch):
    """A PDF's pages and an archive's members go through the run's
    look-ahead pool like a folder's files: every one arrives at the ingest
    with its bundle (`prepare_source_slim` ran for each, off the serial
    thread), and the items are the same as before."""
    import zipfile

    from PIL import Image

    from media_compost import importer as imod
    from tests.core.conftest import make_image
    from media_compost.config import Config
    from media_compost.db import Database, Item
    from media_compost.storage import ItemStore

    monkeypatch.setattr(imod.Importer, "_PREFETCH_WINDOW", 2)
    seen: list = []
    real = imod.prepare_source_slim

    def counting(source):
        seen.append(str(source))
        return real(source)
    monkeypatch.setattr(imod, "prepare_source_slim", counting)

    pics = [make_image(tmp_path / f"p{i}.png", seed=i, size=(120, 90))
            for i in range(3)]
    pdf = tmp_path / "book.pdf"
    ims = [Image.open(p).convert("RGB") for p in pics]
    ims[0].save(pdf, "PDF", save_all=True, append_images=ims[1:])
    cbz = tmp_path / "book.cbz"
    others = [make_image(tmp_path / f"q{i}.png", seed=10 + i, size=(120, 90))
              for i in range(3)]      # not the PDF's pictures, or they fold
    with zipfile.ZipFile(cbz, "w") as zf:
        for i, p in enumerate(others):
            zf.write(p, f"page-{i}.png")

    cfg = Config(data_dir=tmp_path / "lib")
    db, store = Database(cfg), ItemStore(cfg)
    with db.session() as s:
        imp = imod.Importer(s, store, cfg)
        imp.import_paths([pdf], ImportOptions(folders_as_groups=False))
        # (the PDF itself is offered to the pool as any top-level source is;
        # its pages are the three .webp files)
        assert sum(".webp" in p for p in seen) == 3
        seen.clear()
        imp.import_paths([cbz], ImportOptions(folders_as_groups=False))
        assert sum("page-" in p for p in seen) == 3
        s.commit()
        # 3 pages + container, 3 members + container: same as the serial
        # path made
        from sqlalchemy import select, func
        assert s.execute(select(func.count(Item.id))).scalar() == 8
