"""Archive extraction must confine members to its own temp dir.

Archives are the one import format that routinely comes from third parties,
and ``tmp / member_name`` trusts the name: ``../../x`` walks out of the temp
dir and an absolute name replaces it outright. ``media._member_dest`` is the
sanitizer; these tests hold it to ``ZipFile.extract``'s semantics — hostile
names land harmlessly INSIDE the dir rather than aborting the archive.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from media_compost import media


def _inside_extraction_dir(dest: Path) -> bool:
    return any(p.name.startswith("mc_arc_") for p in dest.parents)


def test_member_dest_confines_hostile_names(tmp_path: Path):
    tmp = tmp_path / "x"
    assert media._member_dest(tmp, "a/b.png") == tmp / "a" / "b.png"
    assert media._member_dest(tmp, "../../evil.png") == tmp / "evil.png"
    assert media._member_dest(tmp, "/etc/passwd") == tmp / "etc" / "passwd"
    assert media._member_dest(tmp, "a/../../../b.png") == tmp / "a" / "b.png"
    assert media._member_dest(tmp, "..\\..\\evil.png") == tmp / "evil.png"
    assert media._member_dest(tmp, "./x.png") == tmp / "x.png"
    # A name with nothing left is unextractable, not an escape.
    assert media._member_dest(tmp, "../..") is None
    assert media._member_dest(tmp, "/") is None


def test_iter_archive_zip_slip_stays_inside(tmp_path: Path):
    zpath = tmp_path / "hostile.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("ok.txt", b"fine")
        zf.writestr("../../escape.txt", b"evil")
        zf.writestr("/abs.txt", b"evil")
        zf.writestr("..", b"")  # nothing left after sanitizing -> skipped

    seen: dict[str, Path] = {}
    for name, dest in media.iter_archive(zpath):
        seen[name] = dest
        # Every extracted file really exists, inside the extraction dir.
        assert dest.is_file()
        assert _inside_extraction_dir(dest), dest

    assert set(seen) == {"ok.txt", "../../escape.txt", "/abs.txt"}
    # The traversal name was confined, not honored.
    assert seen["../../escape.txt"].name == "escape.txt"
    assert not (tmp_path.parent / "escape.txt").exists()
    assert not Path("/abs.txt").exists()
