"""Per-item file storage plus a thumbnail cache.

Every item owns a folder ``items/<uid[:2]>/<uid>/`` (sharded by the uid's first
two hex chars) holding its source files (``files/<number>.<ext>``), its
generated artifacts (``artifacts/<file-number>-<kind>[-<model>].<ext>``) and its
generated artifacts. ``File.path`` / ``FileArtifact.path`` are stored
relative to that item folder.

Thumbnails live under ``thumbs/<file_id>.webp`` outside the item folders — they
are regenerable and not part of the library's portable data.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from .config import Config


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _slug(text: str) -> str:
    """Filesystem-safe lowercase token (used for artifact kind/model names)."""
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _norm_ext(ext: str) -> str:
    return (ext or "").lstrip(".").lower() or "bin"


class ItemStore:
    def __init__(self, cfg: Config):
        self.config = cfg
        cfg.ensure_dirs()

    # ---- paths ----

    def item_dir(self, uid: str) -> Path:
        return self.config.items_dir / uid[:2] / uid

    def file_path(self, uid: str, rel_path: str) -> Path:
        """Absolute path of an item-folder-relative file/artifact path."""
        return self.item_dir(uid) / rel_path

    def path_of(self, session, row) -> Path:
        """Absolute path for a ``File``/``FileArtifact`` row (both carry an
        ``item_id`` and an item-folder-relative ``path``)."""
        from .db import Item

        item = session.get(Item, row.item_id)
        if item is None or not row.path:
            raise FileNotFoundError(f"no stored bytes for row {row.id}")
        return self.file_path(item.uid, row.path)

    # ---- writing source files ----

    def file_target(self, uid: str, number: int, ext: str) -> tuple[Path, str]:
        """(absolute, item-relative) destination for source file ``number``.

        Creates the parent folder; used directly by callers that produce their
        output with an external tool (ffmpeg writes the clip file itself).
        """
        rel = f"files/{number}.{_norm_ext(ext)}"
        dst = self.item_dir(uid) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        return dst, rel

    def write_file(self, uid: str, number: int, ext: str, *,
                   data: bytes | None = None, src: Path | None = None) -> str:
        """Store a source file's bytes as ``files/<number>.<ext>``; returns the
        item-relative path. Atomic (tmp + ``os.replace``). Exactly one of
        ``data`` (bytes) or ``src`` (a file to copy) must be given.

        Always a COPY. An import asked to MOVE its sources removes them
        itself, once the whole file has been ingested — the readers after this
        point (the hash, the thumbnail, the EXIF) still need the original, and
        taking it here fails the import that asked for it.
        """
        dst, rel = self.file_target(uid, number, ext)
        self._atomic_write(dst, data=data, src=src)
        return rel

    def write_bytes_at(self, uid: str, rel_path: str, data: bytes) -> None:
        """Overwrite an existing stored file/artifact in place (atomic).

        Used by in-place edits (rotate a derived file / its artifacts) where the
        row keeps its path and only the pixels change.
        """
        dst = self.file_path(uid, rel_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(dst, data=data)

    def write_artifact(self, uid: str, file_number: int, kind: str, ext: str,
                       data: bytes, model: str = "") -> str:
        """Store an artifact's bytes as
        ``artifacts/<file-number>-<kind>[-<model>].<ext>`` (flat, next to
        ``files/``); returns the item-relative path. Appends ``-2``, ``-3`` … if
        the name is already taken (several artifacts may share kind+model).
        """
        stem = f"{file_number}-{_slug(kind)}"
        if model:
            stem += f"-{_slug(model)}"
        adir = self.item_dir(uid) / "artifacts"
        adir.mkdir(parents=True, exist_ok=True)
        ext = _norm_ext(ext)
        name, n = f"{stem}.{ext}", 2
        while (adir / name).exists():
            name = f"{stem}-{n}.{ext}"
            n += 1
        self._atomic_write(adir / name, data=data)
        return f"artifacts/{name}"

    @staticmethod
    def _atomic_write(dst: Path, data: bytes | None = None,
                      src: Path | None = None) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
        os.close(fd)
        try:
            if data is not None:
                Path(tmp).write_bytes(data)
            elif src is not None:
                shutil.copyfile(src, tmp)
            else:
                raise ValueError("write needs data or src")
            os.replace(tmp, dst)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ---- moving / removing ----

    def move_file(self, src_uid: str, dst_uid: str, old_rel: str,
                  new_rel: str) -> None:
        """Physically move a stored file/artifact between item folders (used by
        merge/split, which re-parent File rows)."""
        src = self.file_path(src_uid, old_rel)
        dst = self.file_path(dst_uid, new_rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            os.replace(src, dst)

    def remove_file(self, uid: str, rel_path: str) -> None:
        self.file_path(uid, rel_path).unlink(missing_ok=True)

    def remove_artifacts_for(self, uid: str, file_number: int) -> None:
        """Delete every on-disk artifact belonging to source file ``number``
        (their filenames start with ``<number>-``)."""
        adir = self.item_dir(uid) / "artifacts"
        if adir.is_dir():
            for p in adir.glob(f"{file_number}-*"):
                p.unlink(missing_ok=True)

    def remove_item(self, uid: str) -> None:
        """Delete an item's whole folder (files and artifacts)."""
        shutil.rmtree(self.item_dir(uid), ignore_errors=True)
        # Drop the two-char shard folder too once it's empty.
        try:
            self.item_dir(uid).parent.rmdir()
        except OSError:
            pass

    # ---- thumbnails ----

    def thumb_path(self, file_id: int, sha256: str) -> Path:
        """Thumbnail cache path, keyed by file id AND a content-hash prefix,
        sharded as ``thumbs/<xx>/`` by the id's low byte.

        Keying by id alone is fragile: SQLite reuses rowids (and a rebuilt DB
        reassigns them wholesale), so a leftover ``<id>.webp`` could be served
        for a *different* file's id. With the content hash in the name, a thumb
        can only ever be found for the exact bytes it was generated from —
        anything stale is simply a cache miss (and pruned later).

        Sharded because one flat folder of every thumbnail in a large library
        makes each ``drop_thumb`` glob (and every cache-miss stat) walk a
        directory of hundreds of thousands of entries. ``file_id % 256`` keys
        the shard so a file's thumbs are all in ONE subfolder, whatever their
        content hash — which is what lets ``drop_thumb`` glob only that shard."""
        return (self.config.thumbs_dir / f"{file_id % 256:02x}"
                / f"{file_id}-{(sha256 or 'x')[:16]}.webp")

    def ensure_thumb(self, file_id: int, sha256: str, src: Path) -> Path:
        """Generate (if missing) and return the thumbnail for a stored file.

        The file's stored bytes are already in their final orientation (a rotated
        source file holds rotated pixels), so the thumbnail is a plain downscale
        with no rotation applied."""
        out = self.thumb_path(file_id, sha256)
        if out.exists():
            return out
        with Image.open(src) as im:
            return self._write_thumb(out, im)

    def ensure_thumb_from_image(self, file_id: int, sha256: str,
                                im: Image.Image) -> Path:
        """Generate (if missing) a thumbnail from an already-loaded image.

        Used for videos, whose source bytes aren't a still image the
        thumbnailer can open directly (a representative frame is extracted).
        """
        out = self.thumb_path(file_id, sha256)
        if out.exists():
            return out
        return self._write_thumb(out, im)

    def set_thumb_from_image(self, file_id: int, sha256: str,
                             im: Image.Image) -> Path:
        """Write the thumbnail from ``im``, REPLACING whatever is cached.

        `ensure_thumb_from_image` answers "make one if there is none", which is
        what every generated thumbnail wants. This one is for the deliberate
        act — somebody choosing which frame of a film represents it — where the
        existing thumbnail is exactly the thing being replaced.
        """
        return self._write_thumb(self.thumb_path(file_id, sha256), im)

    def _write_thumb(self, out: Path, im: Image.Image) -> Path:
        # Preserve transparency (WEBP supports an alpha channel) so images with
        # transparent regions keep it in their thumbnail — the UI paints a
        # checkerboard behind them rather than baking one into the file. Opaque
        # images are flattened to RGB as before.
        has_alpha = im.mode in ("RGBA", "LA") or (
            im.mode == "P" and "transparency" in im.info
        )
        im = im.convert("RGBA") if has_alpha else im.convert("RGB")
        im.thumbnail(
            (self.config.thumb_size, self.config.thumb_size),
            Image.Resampling.LANCZOS,
        )
        # Write atomically (temp file + rename): the same file id's thumbnail can
        # be generated concurrently (the grid, sidebar and hover previews request
        # it via different URLs), and a half-written .webp reads as a broken image
        # until something re-triggers generation. os.replace is atomic, so readers
        # only ever see a complete file.
        out.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".webp")
        os.close(fd)
        try:
            # Encoder effort 2, not 4: the same bytes (31 KB a 512 px thumb,
            # measured over 60 crawl pictures) in 19 ms instead of 25, and a
            # thumbnail is made on demand, in the request that first shows it.
            im.save(tmp, "WEBP", quality=82, method=2)
            os.replace(tmp, out)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return out

    def drop_thumb(self, file_id: int) -> None:
        """Remove every cached thumbnail of this file id (any content hash —
        an in-place edit leaves the old content's thumb behind otherwise).
        Only the id's own shard is globbed; the shard key is the id, so every
        thumbnail of the file lives there."""
        shard = self.config.thumbs_dir / f"{file_id % 256:02x}"
        if shard.is_dir():
            for p in shard.glob(f"{file_id}-*.webp"):
                p.unlink(missing_ok=True)

    # ---- pruning ----

    def prune_all(self, session, on_progress=None) -> int:
        """Remove on-disk data no longer referenced by the database: stray files
        inside item folders (e.g. bytes orphaned by a rolled-back import
        savepoint), whole folders of items that no longer exist, and thumbnails
        of deleted files. Returns the number of files/folders removed.

        Normal deletes clean up directly (``remove_item``/``remove_file``); this
        is the safety net behind ``prune-storage``.

        ``on_progress(removed, where)`` — optional — is called as the sweep
        moves: ``removed`` is the running total and ``where`` the item shard,
        folder or thumbnail shard being looked at, both library-relative so a
        caller can print them. It is called per FOLDER rather than per file
        (a caller wanting a slower line throttles), and it reports the two
        catalog reads before the sweep as well, which on a large library is
        where the first seconds go with nothing else to show for them.
        """
        from sqlalchemy import select

        from .db import File, FileArtifact, Item

        def report(removed: int, where: str) -> None:
            if on_progress is not None:
                on_progress(removed, where)

        report(0, "reading the item list…")
        uid_by_id = {
            i: u for i, u in session.execute(select(Item.id, Item.uid)).all()
        }
        # Item-relative path STRINGS per uid, from streamed column selects —
        # not one big set of absolute Path objects, whose per-entry cost is
        # what made this sweep's memory scale with the library's file count.
        referenced: dict[str, set[str]] = {}
        report(0, "reading the file list…")
        for model in (File, FileArtifact):
            for iid, rel in session.execute(
                select(model.item_id, model.path)
                .where(model.path.is_not(None))
                .execution_options(yield_per=2000)
            ):
                uid = uid_by_id.get(iid)
                if uid and rel:
                    referenced.setdefault(uid, set()).add(rel)

        removed = 0
        live_uids = set(uid_by_id.values())
        root = self.config.items_dir
        for shard in root.iterdir() if root.is_dir() else []:
            if not shard.is_dir():
                continue
            for folder in shard.iterdir():
                if not folder.is_dir():
                    continue
                report(removed, f"items/{shard.name}/{folder.name}")
                if folder.name not in live_uids:
                    shutil.rmtree(folder, ignore_errors=True)
                    removed += 1
                    continue
                keep = referenced.get(folder.name, set())
                for p in folder.rglob("*"):
                    if (p.is_file()
                            and p.relative_to(folder).as_posix() not in keep):
                        p.unlink(missing_ok=True)
                        removed += 1
            try:
                shard.rmdir()   # drop an emptied shard folder
            except OSError:
                pass

        # Thumbs are named ``<xx>/<file_id>-<sha16>.webp`` — keep one only when
        # a file row with that exact id AND content hash still exists. Anything
        # else (stale content, deleted files, legacy names) goes — including
        # files sitting directly under thumbs/ from the old flat layout, which
        # nothing will ever look up again (it is a regenerable cache).
        report(removed, "reading the thumbnail list…")
        live_thumbs = {
            f"{fid}-{(sha or '')[:16]}"
            for fid, sha in session.execute(
                select(File.id, File.sha256).execution_options(yield_per=2000))
        }
        thumbs = self.config.thumbs_dir
        for entry in thumbs.glob("*") if thumbs.is_dir() else []:
            if entry.is_file():
                # Old flat layout — the sharded lookup never finds these.
                entry.unlink(missing_ok=True)
                removed += 1
            elif entry.is_dir():
                report(removed, f"thumbs/{entry.name}")
                for t in entry.glob("*"):
                    if t.is_file() and t.stem not in live_thumbs:
                        t.unlink(missing_ok=True)
                        removed += 1
                try:
                    entry.rmdir()   # drop an emptied shard folder
                except OSError:
                    pass
        return removed
