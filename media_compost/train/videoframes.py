"""Videos as training images: sample a video's frames, drop the repeats.

A video item is not one picture, so training normally skips it. With
``TrainingConfig.video.include`` on, this turns each matched video into a run
of ordinary images — extracted into the job's own folder while the dataset is
materialized, and thrown away with the run.

Two things make the result usable rather than merely large:

* **Sampling.** Every frame of a film is tens of thousands of near-identical
  pictures. One frame every N seconds (or every Nth frame) is the interval.
* **Deduplication.** A shot held for five seconds is ONE picture, not five, and
  a title card or a black frame can hold for a minute. Each kept frame is
  perceptually hashed and a new frame that matches one already kept from the
  same video is dropped — the same hash and threshold the importer dedups
  images with, so "the same picture" means the same thing here as everywhere.

And one thing keeps it from being paid for twice: **the frames are cached**.
Sampling a feature film is minutes of decoding, and a job is materialized
again whenever it starts without a resume point — a pause during the
extraction itself, a run that died before its first checkpoint, a finished job
continued with more steps. What a video's frames are made of is written beside
them (:data:`STAMP`): the file they came from, its size and mtime, and the
sampling settings. A stamp that still matches is the answer; anything else —
a moved interval, a re-encoded film, an interrupted extraction, which writes
no stamp at all — samples the video again.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from media_compost import Phash

#: What a video's extracted frames are written beside, so a later run can tell
#: whether they are still the frames it would extract.
STAMP = "frames.json"

#: Bumped when the frames on disk stop meaning what this module would write
#: now — a different file name, encoding or sampling rule. An old stamp then
#: simply fails to match and the video is sampled again, which is the whole
#: recovery: these are scratch files, and re-deriving them is never wrong.
CACHE_VERSION = 1


@dataclass
class Frame:
    """One kept frame: where it was written, and when it happens."""
    path: Path
    time: float
    width: int
    height: int


def sample_fps(every: float, unit: str, frame_rate: Optional[float]) -> float:
    """Frames per second to sample at, for an interval in seconds or frames.

    A frame interval needs the video's own rate; without a probed one, 25 fps
    is the same fallback :func:`media.iter_video_frames` uses.
    """
    step = max(float(every), 1e-6)
    if unit == "frames":
        fr = frame_rate or 25.0
        if fr <= 0:
            fr = 25.0
        return max(fr / step, 1e-6)
    return 1.0 / step


def cache_key(item, *, every: float, unit: str, dedupe: bool,
              threshold: int, max_dim: int) -> dict:
    """Everything the extracted frames are a function of.

    The FILE is named by its path, size and mtime rather than by its id: a
    file can be rewritten in place (a rotation, a re-encode) and an id that
    survived that would hand the run the old film's frames. Same reasoning as
    `media`'s probe cache, which is keyed on the stat for exactly this.
    """
    path = getattr(item, "path", None)
    size = mtime = -1.0
    if path is not None:
        try:
            st = Path(path).stat()
            size, mtime = st.st_size, st.st_mtime
        except OSError:
            pass
    return {
        "v": CACHE_VERSION,
        "path": str(path or ""),
        "size": int(size),
        "mtime": round(float(mtime), 3),
        "every": float(every),
        "unit": str(unit),
        "dedupe": bool(dedupe),
        # Only where it decides something: with dedup off no frame is ever
        # compared, and a library whose threshold moved would otherwise
        # re-extract every film for a number nothing read.
        "threshold": int(threshold) if dedupe else 0,
        "max_dim": int(max_dim),
    }


def cached(out_dir: Path, key: dict) -> Optional[list[Frame]]:
    """The frames already in ``out_dir``, or None to sample the video again.

    None for every kind of doubt: no stamp (an extraction that was
    interrupted writes none), a stamp made of something else, or a frame the
    stamp names that is not on disk any more.
    """
    try:
        data = json.loads((out_dir / STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("key") != key:
        return None
    out: list[Frame] = []
    try:
        for row in data.get("frames") or []:
            path = out_dir / str(row["name"])
            if not path.is_file():
                return None
            out.append(Frame(path=path, time=float(row["time"]),
                             width=int(row["width"]),
                             height=int(row["height"])))
    except (KeyError, TypeError, ValueError):
        return None
    return out


def _write_stamp(out_dir: Path, key: dict, frames: list[Frame]) -> None:
    """Record what these frames are, so the next run can reuse them.

    Written LAST and only for a complete extraction: a partial run of frames
    with a stamp over it would read as the whole film.
    """
    try:
        (out_dir / STAMP).write_text(json.dumps({
            "key": key,
            "frames": [{"name": f.path.name, "time": f.time,
                        "width": f.width, "height": f.height}
                       for f in frames],
        }), encoding="utf-8")
    except OSError:
        # A cache that cannot be written is a cache that misses next time,
        # which is slow rather than wrong.
        pass


def extract(
    item,
    out_dir: Path,
    *,
    every: float,
    unit: str,
    dedupe: bool,
    threshold: int,
    max_dim: int = 0,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> list[Frame]:
    """Sample one video ``item`` into ``out_dir`` and return the frames kept.

    Frames are written as JPEG: they are a scratch copy of an already
    lossy-compressed stream, and a 1080p PNG each would cost ten times the disk
    for nothing. ``max_dim`` caps the long side (ffmpeg downscales, never
    upscales) — a frame only has to cover the largest training bucket.

    ``threshold`` is the library's own `phash_threshold`, and `Phash` its own
    hash, so "the same picture" means here exactly what it means to the
    importer rather than being a second rule that can drift from it.

    Frames already sampled from this video with these settings are REUSED —
    see the module docstring. Anything else starts from an empty folder: a
    stale extraction is removed rather than written over, or one changed
    setting would leave the frames of two samplings side by side and the run
    would train on both.
    """
    key = cache_key(item, every=every, unit=unit, dedupe=dedupe,
                    threshold=threshold, max_dim=max_dim)
    have = cached(out_dir, key)
    if have is not None:
        if on_progress is not None:
            on_progress(len(have), len(have))
        return have
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = sample_fps(every, unit, item.active_file.frame_rate)
    kept: list[Frame] = []
    seen: list[Phash] = []
    scanned = 0
    stopped = False
    for _i, t, im in item.frames(fps, max_dim=max_dim or None):
        scanned += 1
        if should_stop is not None and should_stop():
            stopped = True
            break
        if dedupe:
            h = Phash.of(im)
            if any(h.near(prev, threshold) for prev in seen):
                continue
            seen.append(h)
        fp = out_dir / f"f{len(kept):06d}.jpg"
        im.save(fp, "JPEG", quality=95, subsampling=0)
        kept.append(Frame(path=fp, time=t, width=im.width, height=im.height))
        if on_progress is not None:
            on_progress(len(kept), scanned)
    if not stopped:
        _write_stamp(out_dir, key, kept)
    return kept


def covers(
    spans: list[tuple[float, Optional[float]]], when: float, tol: float = 0.0
) -> bool:
    """Whether any of a timed tag's ranges covers the moment ``when``.

    ``tol`` widens each range by half a sampling interval at both ends, which
    is what makes a SINGLE-MOMENT tag (a range with no end — one frame of the
    film) reach the sampled frame nearest to it. Without it a tag placed at
    12.30 s would simply never appear in a dataset sampled at 1 s.
    """
    return any(
        (a - tol) <= when <= ((b if b is not None else a) + tol)
        for a, b in spans
    )
