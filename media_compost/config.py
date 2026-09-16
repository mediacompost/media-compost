"""Runtime configuration: data locations and tunable thresholds.

All paths derive from a single data directory, overridable via the
``MEDIA_COMPOST_DATA`` environment variable so tests and the CLI can point at a
scratch location.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Image formats we accept and keep during import. Everything else is discarded
# (e.g. when extracting an archive). Extensions are lowercase, without the dot.
IMAGE_EXTS: frozenset[str] = frozenset(
    {"jpg", "jpeg", "png", "webp", "bmp", "gif", "tif", "tiff", "heic", "heif",
     # Pillow >= 11.2 bundles libavif in its wheels, so AVIF decodes with no
     # extra dependency; a build without it reports "cannot read image" per
     # file rather than failing the app, like any other undecodable file.
     "avif"}
)
VIDEO_EXTS: frozenset[str] = frozenset(
    {"mp4", "mov", "m4v", "avi", "mkv", "webm"}
)
# Comic-book archives: cbz is a zip, cbr is a rar. Imported like other archives
# but their pages are additionally marked as an ordered sequence.
COMIC_EXTS: frozenset[str] = frozenset({"cbz", "cbr"})
ARCHIVE_EXTS: frozenset[str] = frozenset({"zip", "7z"}) | COMIC_EXTS
# A PDF is imported like a comic archive: every page becomes an ordinary image
# item and the pages become an ordered sequence. It is a CONTAINER of pictures
# in exactly the way a cbz is — the only difference is that its pages have to
# be rendered rather than unpacked, which is `media.iter_pdf_pages`' job.
PDF_EXTS: frozenset[str] = frozenset({"pdf"})

# GIF IS AN IMAGE FORMAT HERE AND NEVER A VIDEO ONE. It used to be in both
# sets — a multi-frame GIF imported as a video item — and a browser will not
# play a GIF in a `<video>` element, so the one thing that produced was an item
# whose preview overlay, annotator and video editor were all a black rectangle.
# An animated GIF is a BOOK OF PICTURES instead (`classify` answers "gif", and
# `Importer._import_gif` unpacks it like a PDF); a single-frame one is an
# ordinary picture, as it always was. Two other readers keyed off the old
# membership and were wrong for a still GIF because of it: `files.get_thumb`
# ran ffmpeg over it to find "a representative frame", and `jobs._only_pictures`
# dropped it from every AI action.


def _default_data_dir() -> Path:
    env = os.environ.get("MEDIA_COMPOST_DATA")
    if env:
        return Path(env).expanduser().resolve()
    # Repo-local ./_data by default (single-user local app). The underscore is
    # this project's mark for a directory a program writes rather than a
    # person; see the repository's .gitignore.
    #
    # ONE ANSWER, AND IT IS NOT CONDITIONAL. This was briefly a two-branch
    # rule that adopted a `./data` from an older build, and the branch is
    # deliberately gone: which library a bare run opens should not depend on
    # what happens to be sitting in the working directory. A library made
    # before the rename is opened by naming it — `--data-dir` or
    # `MEDIA_COMPOST_DATA` — or by renaming the folder.
    return (Path.cwd() / "_data").resolve()


@dataclass(frozen=True)
class Config:
    """What a LIBRARY needs, and nothing a server does.

    The app's extra knobs — who is calling, whether training is offered, the
    color-reference store — live on ``media_compost.ui.config.UiConfig``, a
    subclass this module never names. The split is by owner: a script reading
    a library through the public API constructs this class and should not be
    asked to care about HTTP authentication.
    """

    data_dir: Path = field(default_factory=_default_data_dir)

    # Perceptual-hash Hamming distance at or below which two images may be
    # treated as the same item (added as alternative versions rather than new
    # items). Tuned for the 256-bit hash above; a match must additionally pass
    # ``dedup_verify`` before the images are actually merged.
    #
    # STILL 10, deliberately — see ``dedup_verify_mse_far`` for the 2026-09
    # round that started by lowering it to 8 and measured its way back. This
    # is the NOMINATOR, and the house rule for it is "reduce collisions
    # instead of missing duplicates": it is allowed to be generous, because
    # the gate prunes and the pixel check decides.
    phash_threshold: int = 10

    # Require a secondary pixel/histogram check to agree before merging two images
    # that are within ``phash_threshold`` (reduces false-positive merges of
    # structurally similar but different images).
    dedup_verify: bool = True
    # Normalized mean-squared-error bound (0..1) for the secondary check; the
    # pair is only merged when their downscaled-RGB MSE is at or below this.
    #
    # 0.006, down from the 0.020 it was until 2026-09. 0.020 was 12.6x the
    # worst a genuine re-encode measured (0.00159, across 3600 degradations of
    # 240 pictures — JPEG down to q5, WebP q10, palette quantisation, rescales
    # from 1/16 to 4x, down-then-up round trips, four resamplers), so it was
    # tolerating far more than it had to and turning almost nothing away.
    # Not tighter than 0.006: what sits between it and 0.020 is a copy whose
    # pixel VALUES have moved globally — a gamma or brightness shift — and
    # that is an edit rather than "the same picture at another size or
    # encoding", which is all this rule claims to fold.
    dedup_verify_mse: float = 0.006

    # AND AT THE EDGE OF THE NEIGHBOURHOOD, THE PIXELS MUST AGREE FAR BETTER.
    # Past ``dedup_verify_near`` bits of Hamming distance the hash has almost
    # stopped being evidence, so the pixel check has to carry the decision on
    # its own; this is the bound it carries it with.
    #
    # The whole of a real report: manga pages that are the same artwork with
    # the speech bubbles TRANSLATED were folding onto one item. Ground truth
    # was one 209-page chapter held in both Japanese and English, aligned page
    # by page — two genuine false folds, and BOTH sit at Hamming exactly 10,
    # while every one of the remaining 203 translated pairs is at 12 or more.
    # So the failure lived entirely in the last band the threshold admits.
    #
    # The obvious fix — lower ``phash_threshold`` to 8 — was tried first and
    # measured worse. That band is also where a DEGENERATE picture's own
    # re-encode lands: the two-file fixture in `tests/ui/test_metadata_pins.py`
    # is one image re-saved at JPEG q95, and it comes back 10 bits away. What
    # separates it from a translated page is not the hash at all, it is the
    # pixels — 0.0000027 against 0.00125 and 0.00396, a factor of 450. Cutting
    # the nominator threw that fold away with the bad ones (81.8% of genuine
    # re-encodes kept -> 79.9%); cutting the FAR bound instead keeps 81.6% and
    # rejects both false folds.
    #
    # 0.001 is anchored rather than tuned: 0.000753 is the worst a genuine
    # re-encode measures anywhere the hash is still confident (Hamming <= 6),
    # 0.00125 is the nearest false fold, and this is essentially the
    # geometric middle of the two. It costs the ~11% of Hamming-9/10 genuine
    # re-encodes whose pixels disagree more than that — all of them
    # nearest-neighbour resamples, i.e. pictures already visibly damaged.
    dedup_verify_mse_far: float = 0.001
    # The distance up to which ``dedup_verify_mse`` applies. Genuine
    # re-encodes measured p99 0.00058 at Hamming <= 6 and 0.00161 at 8-10, so
    # this is where the hash's own evidence visibly thins out.
    dedup_verify_near: int = 8

    # Detect whole-image reorientations (90/180/270° rotations, horizontal/
    # vertical flips, and their combinations) during import and record an
    # original->derived "edit" Relationship. Crops are deliberately NOT detected:
    # crop-resistant hashing produced too many false links, so only pixel-exact
    # reorientations are recognized now.
    edit_detect: bool = True
    # Normalized MSE bound for confirming a rotation/flip via the
    # orientation-invariant pixel check. A reorientation is pixel-*exact*, so its
    # downscaled MSE is ~1e-6; different photos measure >= ~0.008 even at their
    # best-matching orientation. This bound sits well between the two, so it is
    # far tighter than ``dedup_verify_mse`` (which tolerates rescale/recompression
    # for near-dup *merging*, a looser task).
    edit_mse: float = 0.004

    # (There used to be a `video_match_fps` here, the rate the frame index was
    # SAMPLED at. Every frame of a video is hashed now — one row per run of
    # identical hashes — so there is no rate to set; `importer._new_run` says
    # why sampling could not be made to work.)

    # Longest edge (px) of generated grid thumbnails.
    thumb_size: int = 512

    def verify_mse(self, distance: int) -> float:
        """The pixel bound a candidate at Hamming ``distance`` must meet.

        ONE definition, because three call sites verify a near-duplicate (the
        importer, the library merge and a captured still) and a rule spelled
        three times is a rule that drifts. The further the hashes are apart,
        the more the pixels have to agree — at the edge of the neighbourhood
        the hash barely narrows anything, so the pixel check is the whole of
        the decision. A caller that genuinely does not know the distance
        passes the widest one, which is the conservative reading.
        """
        return (self.dedup_verify_mse if distance <= self.dedup_verify_near
                else self.dedup_verify_mse_far)

    def __post_init__(self) -> None:
        # The band index guarantees completeness only to
        # `dedup_index.MAX_BANDED_THRESHOLD`, and there is no scan fallback
        # past it any more — a larger threshold would silently probe past the
        # guarantee and MISS matches, so it is refused at load rather than
        # clamped (a clamp answers a different question than was asked).
        from .dedup_index import MAX_BANDED_THRESHOLD

        if not 0 <= self.phash_threshold <= MAX_BANDED_THRESHOLD:
            raise ValueError(
                f"phash_threshold must be between 0 and "
                f"{MAX_BANDED_THRESHOLD} (the band index guarantees "
                f"completeness no further); got {self.phash_threshold}")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "media.db"

    @property
    def items_dir(self) -> Path:
        """Per-item folders: ``items/<uid[:2]>/<uid>/`` holds an item's source
        files and its artifacts."""
        return self.data_dir / "items"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def backup_dir(self) -> Path:
        """Where the library is copied aside before a schema upgrade
        (``migrations.backup``). Created on demand — not part of
        ``ensure_dirs``, since most opens never need it."""
        return self.data_dir / "backups"

    @property
    def import_stage_dir(self) -> Path:
        """Where an in-memory import (``ImportBytes``) is staged as a real file
        before the readers see it. Inside the data dir on purpose: the stage is
        then on the same filesystem as the item folders it is copied into.
        Created on demand — not part of ``ensure_dirs``."""
        return self.data_dir / "tmp" / "import"

    @property
    def render_stage_dir(self) -> Path:
        """Where a video render writes before its file is MOVED into the item
        folder. Inside the data dir for the same-filesystem reason above, and
        here it is the whole point: the finished render is renamed into place
        (`os.replace`-style), and a temp on another volume — the system /tmp,
        with the library on a NAS or an external disk — turns that rename
        into a second full copy of a multi-gigabyte file. Created on demand.
        """
        return self.data_dir / "tmp" / "render"

    def ensure_dirs(self) -> None:
        # NOT the training directory: it belongs to `media_compost.train`,
        # which may not be installed, and a library that never trains has no
        # business growing an empty folder for it. The trainer makes its own.
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)


def ext_of(name: str) -> str:
    """Lowercase extension without the leading dot ('' if none)."""
    _, _, ext = name.rpartition(".")
    return ext.lower() if ext and ext != name else ""


# Process-wide default; callers may construct their own Config for tests.
config = Config()
