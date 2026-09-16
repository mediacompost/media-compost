"""Media helpers: probing images, extracting video frames, reading archives.

Keeps every third-party format dependency (Pillow, pillow-heif, ffmpeg, py7zr)
behind small functions so the importer stays readable.
"""

from __future__ import annotations

import io
import json
from collections import OrderedDict
import os
import re
import shutil
import subprocess
import contextlib
import tempfile
import threading
from fractions import Fraction
from functools import lru_cache
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator, Optional, Sequence

from PIL import ExifTags, Image

from .config import (ARCHIVE_EXTS, COMIC_EXTS, IMAGE_EXTS, PDF_EXTS,
                     VIDEO_EXTS, ext_of)

# Register HEIC/HEIF support with Pillow.
try:  # pragma: no cover - depends on system libs
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # noqa: BLE001
    pass


class MediaError(Exception):
    pass


class Canceled(MediaError):
    """The caller asked for the run to stop. A subclass of MediaError so
    an `except MediaError` still catches it, and its own type so a caller
    can tell "stopped on purpose" from "failed"."""


@dataclass
class ImageInfo:
    width: int
    height: int
    format: str  # normalized lowercase, e.g. "jpeg", "png"


def megapixel_label(width: int, height: int) -> str:
    """``"0.6 MP"`` — the ONE way a resolution is rendered for the user.

    Done in integers on purpose. Formatting ``w * h / 1e6`` as a float rounds
    the binary approximation of the value, and different rounding rules (or
    rounding twice — once to two decimals for the API, once to one for the
    display) let the same image read as 0.6 MP in one place and 0.7 MP in
    another. `mpLabel` in the frontend's `format.ts` mirrors this exactly, so
    the grid and the metadata list can never disagree.
    """
    tenths = (width * height + 50_000) // 100_000     # round half up
    return f"{tenths // 10}.{tenths % 10} MP"


def normalize_format(fmt: str | None) -> str:
    """Lowercase Pillow's format label, mapping quirks to their common name.

    Pillow reports multi-picture JPEGs (the ``.jpg`` files many phones and
    cameras produce) as ``MPO``; surface those as plain ``jpeg`` so the UI shows
    "JPEG" like any other JPEG rather than a confusing "MPO".
    """
    f = (fmt or "").lower()
    return "jpeg" if f == "mpo" else f


def load_rgb_with_info(src, name: str = "") -> tuple[ImageInfo, Image.Image]:
    """Decode ``src`` **once**, returning its info and a loaded RGB image.

    The importer uses this so a new image is decoded a single time for both its
    metadata and its perceptual hash. ``src`` is a path or a binary file object
    (the importer's prefetch decodes in-memory bytes without staging them
    first); ``name`` is the filename the format falls back to when the decoder
    does not report one, defaulting to the path's own. Raises MediaError if
    the file can't be decoded.
    """
    label = str(name or getattr(src, "name", "") or src)
    try:
        with Image.open(src) as im:
            fmt = normalize_format(im.format) or ext_of(Path(label).name).lower()
            rgb = im.convert("RGB")  # forces the (single) decode
        return ImageInfo(rgb.width, rgb.height, fmt), rgb
    except Exception as exc:  # noqa: BLE001
        raise MediaError(f"cannot read image {Path(label).name}: {exc}") from exc


def image_size(src) -> Optional[tuple[int, int]]:
    """``(width, height)`` without decoding the picture, or None if it cannot
    be read at all.

    Pillow opens lazily — the header is parsed and the pixels are not — which
    is what makes this affordable as a GATE: the import's minimum resolution
    asks it of every picture before anything else happens to one, including
    the hash. The numbers are the RAW ones, exactly as `load_rgb_with_info`
    reports them (neither applies the EXIF orientation), so the gate and the
    stored file can never disagree about how big the picture is.
    """
    try:
        with Image.open(src) as im:
            return int(im.width), int(im.height)
    except Exception:  # noqa: BLE001 - an unreadable file is not a size
        return None


def pdf_page_sizes(path: Path) -> list[tuple[int, int]]:
    """The size every page would be RENDERED at, without rendering one.

    `iter_pdf_pages` scales each page so its longer side is `PDF_PAGE_PX`, so
    the answer is arithmetic on the page box — which is what lets the import's
    minimum resolution judge a PDF for the pixels it is about to store rather
    than by rendering the document twice. A document that cannot be opened
    answers with an empty list; the import then goes ahead and fails (or not)
    where it always did.
    """
    import pypdfium2 as pdfium

    out: list[tuple[int, int]] = []
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception:  # noqa: BLE001 - the import reports it in its own place
        return out
    try:
        for i in range(len(doc)):
            page = doc[i]
            w, h = page.get_size()
            page.close()
            scale = PDF_PAGE_PX / max(1.0, max(w, h))
            out.append((max(1, round(w * scale)), max(1, round(h * scale))))
    finally:
        doc.close()
    return out


def exif_datetime_iso(value: str) -> Optional[str]:
    """Parse an EXIF datetime string (``YYYY:MM:DD HH:MM:SS``, or just a date)
    into ISO-8601, or None when it doesn't look like a datetime. The frontend
    reformats this per the user's date/time preferences."""
    m = re.match(r"\s*(\d{4})\D(\d{2})\D(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", value or "")
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{y}-{mo}-{d}T{h}:{mi}:{s}"
    m = re.match(r"\s*(\d{4})\D(\d{2})\D(\d{2})", value or "")
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}T00:00:00"
    return None


def _fmt_exif(value: object) -> str:
    """Best-effort readable string for an EXIF value."""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            value = value.hex()
    text = str(value).strip().replace("\x00", "")
    return text[:120]


# A typed metadata value indexed for search. ``num`` holds numeric values and
# dates (as a sortable ``YYYYMMDDHHMMSS`` number, timezone-free and directly
# comparable); ``text`` holds text values; ``raw`` is the display string.
@dataclass
class MetaValue:
    name: str
    mtype: str  # "numeric" | "text" | "date"
    num: Optional[float]
    text: Optional[str]
    raw: str


# EXIF tag name -> (catalog name, type). Only genuinely static, useful fields;
# derived/intrinsic numerics (dimensions, resolution) are handled live elsewhere.
_EXIF_INDEX: dict[str, tuple[str, str]] = {
    "Make": ("camera_make", "text"),
    "Model": ("camera_model", "text"),
    "LensModel": ("lens", "text"),
    "Software": ("software", "text"),
    "Artist": ("artist", "text"),
    "Copyright": ("copyright", "text"),
    "ImageDescription": ("description", "text"),
    "ISOSpeedRatings": ("iso", "numeric"),
    "FNumber": ("aperture", "numeric"),
    "ExposureTime": ("exposure_time", "numeric"),
    "FocalLength": ("focal_length", "numeric"),
    "FocalLengthIn35mmFilm": ("focal_length_35mm", "numeric"),
    "ExposureBiasValue": ("exposure_bias", "numeric"),
    # The last four are ENUM CODES, and they are indexed as the integers the
    # file holds — `Flash` is a bitfield, `Orientation` is 1..8. Decoding them
    # to words would put an English string into the search index, where it
    # could never be translated and would change what an existing query
    # matches; the Info tab decodes them for DISPLAY instead
    # (`frontend/src/app/metaEnums.ts`). `Orientation` is honestly a fact about
    # the FILE rather than the picture — this library stores pixels already in
    # their orientation, `File.rotation`/`mirrored` being the truth — which is
    # exactly the kind of thing per-file metadata is for.
    "MeteringMode": ("metering_mode", "numeric"),
    "Flash": ("flash", "numeric"),
    "WhiteBalance": ("white_balance", "numeric"),
    "Orientation": ("orientation", "numeric"),
    "DateTimeOriginal": ("date_taken", "date"),
    "DateTime": ("date_modified", "date"),
}

# Canonical metadata name -> the label the Info tab shows. Keyed by the CATALOG
# name, not the EXIF tag: a video's `camera_make` comes from a QuickTime atom
# and never sees an EXIF tag at all, so the label has to hang off the answer
# rather than off where it was read. A name with no entry shows as itself.
_META_LABEL: dict[str, str] = {
    "camera_make": "Make",
    "camera_model": "Model",
    "lens": "Lens",
    "software": "Software",
    "artist": "Artist",
    "copyright": "Copyright",
    "description": "Description",
    "title": "Title",
    "mode": "Mode",
    "iso": "ISO",
    "aperture": "Aperture",
    "exposure_time": "Exposure time",
    "focal_length": "Focal length",
    "focal_length_35mm": "Focal length (35 mm)",
    "exposure_bias": "Exposure bias",
    "metering_mode": "Metering mode",
    "flash": "Flash",
    "white_balance": "White balance",
    "orientation": "Orientation",
    "date_taken": "Date taken",
    "date_modified": "Date modified",
    "codec": "Codec",
    "audio_codec": "Audio codec",
    "audio_channels": "Audio channels",
    "has_audio": "Has audio",
}


def meta_label(name: str) -> str:
    """The Info tab's label for a canonical metadata name."""
    return _META_LABEL.get(name, name)


#: Display order, taken from `_EXIF_INDEX`'s own insertion order — which is
#: what `read_image_metadata` used to impose by iterating the EXIF tags. A name
#: that is not an EXIF field at all (a video's codec, `mode`) sorts after them
#: by its position in `_META_LABEL`, and anything unknown sorts last.
def _meta_order_table() -> dict[str, int]:
    order: dict[str, int] = {}
    for name in [v[0] for v in _EXIF_INDEX.values()] + list(_META_LABEL):
        order.setdefault(name, len(order))   # FIRST mention wins
    return order


_META_ORDER = _meta_order_table()


def meta_order(name: str) -> tuple[int, str]:
    """Sort key for a metadata name in the Info tab."""
    return (_META_ORDER.get(name, len(_META_ORDER)), name)


def date_sortkey(value: str) -> Optional[float]:
    """An EXIF datetime as a sortable, timezone-free ``YYYYMMDDHHMMSS`` number
    (date-only -> ``HHMMSS`` = 0), or None when unparseable. The frontend's date
    picker serializes to the same form, so both sides compare identically."""
    iso = exif_datetime_iso(value)
    if not iso:
        return None
    digits = re.sub(r"\D", "", iso)  # YYYYMMDDHHMMSS
    return float(digits) if digits else None


def _exif_num(value: object) -> Optional[float]:
    """Best-effort float for a numeric EXIF value (handles IFDRational, tuples)."""
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    try:
        return float(value)  # IFDRational / int / str all support float()
    except (TypeError, ValueError):
        return None


#: What the three readers below accept: a file on disk, or the bytes
#: themselves. Each of them opens the picture ONCE and takes nothing else off
#: the disk, so bytes already in memory serve exactly as well — which is what
#: lets the importer read a file's metadata index from a prefetched body,
#: before it has been staged, on a worker or in another process.
ImageInput = "Path | bytes"


def _image_input(source):
    """Something `Image.open` accepts, from either a path or raw bytes.

    A FRESH `BytesIO` per call, deliberately: the readers each open the
    picture independently, and one shared stream would be sitting at its end
    by the second of them.
    """
    if isinstance(source, (bytes, bytearray)):
        return io.BytesIO(source)
    return source


def typed_image_metadata(path: "Path | bytes") -> list[MetaValue]:
    """Typed, indexable metadata for a still image (a subset of EXIF), for the
    import-time metadata index. Never raises; unreadable files yield nothing.

    Takes the bytes as well as a path (see `ImageInput`)."""
    out: list[MetaValue] = []
    try:
        with Image.open(_image_input(path)) as im:
            # The pixel mode (RGB/RGBA/L/…) is an enumerated text filter present
            # on every image, no EXIF needed. The container format is NOT
            # indexed here: it lives on `File.format`, so it is served intrinsic
            # (see metadata_catalog) and can't go stale when the active file
            # changes.
            if im.mode:
                out.append(MetaValue("mode", "text", None, im.mode, im.mode))
            try:
                exif = im.getexif()
            except Exception:  # noqa: BLE001
                exif = None
            # Merge the base IFD with the Exif sub-IFD (0x8769), where the camera
            # fields — ISO, aperture, focal length, DateTimeOriginal — actually
            # live; iterating the base dict alone would miss them. No early
            # return on an EXIF-less file: the location text below is XMP/IPTC,
            # which plenty of files carry with no EXIF at all.
            merged = dict(exif) if exif else {}
            try:
                if exif:
                    merged.update(exif.get_ifd(ExifTags.IFD.Exif))
            except Exception:  # noqa: BLE001
                pass
            for tag_id, value in merged.items():
                tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                spec = _EXIF_INDEX.get(tag)
                if spec is None:
                    continue
                name, mtype = spec
                raw = _fmt_exif(value)
                if not raw:
                    continue
                if mtype == "text":
                    out.append(MetaValue(name, "text", None, raw, raw))
                elif mtype == "date":
                    key = date_sortkey(raw)
                    if key is not None:
                        out.append(MetaValue(name, "date", key, None, raw))
                else:  # numeric
                    num = _exif_num(value)
                    if num is not None:
                        out.append(MetaValue(name, "numeric", num, None, raw))
    except Exception:  # noqa: BLE001
        return out
    # WHERE the file says it was taken, indexed like anything else it says
    # about itself. The importer used to consume these directly — minting
    # places and tags nobody asked for, which a crawl of random web images
    # turned into a Places list full of strangers' coordinates. Indexed, the
    # facts stay searchable (`INFO:gps_lat`, `INFO:location`), the Info tab
    # shows them, and the Places section can OFFER them; only accepting one
    # creates anything.
    gps = read_gps(path)
    if gps is not None:
        out.append(MetaValue("gps_lat", "numeric", gps[0], None,
                             f"{gps[0]:.6f}"))
        out.append(MetaValue("gps_lon", "numeric", gps[1], None,
                             f"{gps[1]:.6f}"))
    line = location_line(read_location_text(path))
    if line:
        out.append(MetaValue("location", "text", None, line, line))
    # De-dup by name (first wins), matching the one-row-per-(item,name) index.
    seen: set[str] = set()
    deduped: list[MetaValue] = []
    for mv in out:
        if mv.name not in seen:
            seen.add(mv.name)
            deduped.append(mv)
    return deduped


def read_gps(path: "Path | bytes") -> Optional[tuple[float, float]]:
    """Where a photo says it was taken, from its EXIF GPS IFD.

    Pillow-only (no new dependency): the GPS block is a sub-IFD of the base
    EXIF, stored as degrees/minutes/seconds rationals plus a hemisphere letter.
    Returns None for anything that has no usable pair — which is most files.

    Takes the bytes as well as a path (see `ImageInput`).
    """
    try:
        with Image.open(_image_input(path)) as im:
            exif = im.getexif()
            gps = exif.get_ifd(0x8825) if exif else None
    except Exception:  # noqa: BLE001 - a broken header is not an error here
        return None
    if not gps:
        return None

    def dms(value) -> Optional[float]:
        try:
            d, m, sec = (float(x) for x in value)
        except (TypeError, ValueError):
            return None
        return d + m / 60 + sec / 3600

    lat, lon = dms(gps.get(2)), dms(gps.get(4))
    if lat is None or lon is None:
        return None
    if str(gps.get(1) or "N").upper().startswith("S"):
        lat = -lat
    if str(gps.get(3) or "E").upper().startswith("W"):
        lon = -lon
    if abs(lat) > 90 or abs(lon) > 180 or (lat == 0 and lon == 0):
        return None
    return round(lat, 6), round(lon, 6)


# The XMP/IPTC properties that name a place, mapped to our component kinds.
# `country_name` is the spelled-out name (the record stores a 2-letter code, so
# the importer resolves it); the rest are our own kinds.
_XMP_LOCATION = {
    "photoshop:Country": "country_name",
    "Iptc4xmpCore:CountryCode": "country",
    "photoshop:State": "admin1",
    "photoshop:City": "city",
    "Iptc4xmpCore:Location": "district",
}
_IPTC_LOCATION = {
    (2, 101): "country_name", (2, 100): "country", (2, 95): "admin1",
    (2, 90): "city", (2, 92): "district",
}


def location_line(text: dict[str, str]) -> str:
    """`read_location_text`'s answer as ONE address line, in the order an
    address reads: the finest component first, the country last. The one rule
    for turning a file's location fields into the single text field a place
    has — the suggestion, the accept and the search all read this spelling."""
    return ", ".join(
        v for v in (text.get("district"), text.get("city"),
                    text.get("admin1"),
                    text.get("country_name") or text.get("country"))
        if v)


def read_location_text(path: "Path | bytes") -> dict[str, str]:
    """The place a photo NAMES in its metadata — city, state, country.

    Photo software has written these for twenty years (XMP `photoshop:City` and
    the older IPTC records), and they are the only location text that can be
    turned into a place without a geocoder.

    The XMP half reads the RAW packet rather than `Image.getxmp()`: that needs
    `defusedxml`, and running an XML parser over five known property names in
    untrusted files buys nothing. A property is written either as an attribute
    or as an element, so both spellings are matched.
    """
    out: dict[str, str] = {}
    try:
        with Image.open(_image_input(path)) as im:
            xmp = im.info.get("XML:com.adobe.xmp") or im.info.get("xmp") or ""
            if isinstance(xmp, bytes):
                xmp = xmp.decode("utf-8", "replace")
            for prop, name in _XMP_LOCATION.items():
                m = (re.search(rf'{prop}="([^"]*)"', xmp)
                     or re.search(rf"<{prop}[^>]*>(?:\s*<rdf:Alt>\s*<rdf:li[^>]*>)?"
                                  rf"([^<]*)", xmp))
                if m and m.group(1).strip():
                    out[name] = m.group(1).strip()
            try:
                from PIL import IptcImagePlugin

                iptc = IptcImagePlugin.getiptcinfo(im) or {}
            except Exception:  # noqa: BLE001 - optional, and often absent
                iptc = {}
            for key, name in _IPTC_LOCATION.items():
                raw = iptc.get(key)
                if isinstance(raw, (bytes, bytearray)):
                    value = bytes(raw).decode("utf-8", "replace").strip()
                    if value:
                        out.setdefault(name, value)
    except Exception:  # noqa: BLE001 - a broken header is not an error here
        return out
    return {k: v for k, v in out.items() if v}


def _multi_frame(src) -> bool:
    try:
        with Image.open(src) as im:
            return getattr(im, "n_frames", 1) > 1
    except Exception:  # noqa: BLE001 - undecodable is an answer, not an error
        return False


def is_animated(path: Path) -> bool:
    """True for a multi-frame GIF/WEBP file."""
    return _multi_frame(path)


def is_animated_bytes(data: bytes) -> bool:
    """:func:`is_animated` for bytes that are not a file yet.

    An uploaded GIF reaches `prepare_source` as bytes with a name, and
    `classify` reads the FRAME COUNT to tell an animation from a picture —
    which it cannot do from a name. Without this the prefetch prepared an
    animated GIF as a still and the first frame of the sequence would have
    consumed that bundle, taking the whole file's sha256 as its own.
    """
    return _multi_frame(io.BytesIO(data))


def classify(path: Path) -> str:
    """One of: 'image', 'video', 'archive', 'pdf', 'gif', 'other'.

    'gif' is an ANIMATED gif and means "a book of pictures" — the same kind
    of answer 'pdf' is, and the reason it is not simply 'image'. A
    single-frame gif is a picture and answers 'image'. Reads the file, so a
    caller holding only a NAME (the bytes import's prefetch) gets 'image' for
    every gif and must ask :func:`is_animated_bytes` itself.
    """
    ext = ext_of(path.name)
    if ext in PDF_EXTS:
        return "pdf"
    if ext in ARCHIVE_EXTS:
        return "archive"
    if ext == "gif":
        return "gif" if is_animated(path) else "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    return "other"


# Container magic numbers, for bytes that arrive without a usable filename.
# Images are sniffed by Pillow instead (it knows far more formats than a table
# here would); a video is deliberately not sniffed at all — telling one MP4-ish
# container from another needs the demuxer, and `classify` keys off the
# extension anyway, so a video must arrive named.
_ARCHIVE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "zip"),
    (b"Rar!\x1a\x07", "cbr"),  # rar is only imported as a comic archive
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"%PDF-", "pdf"),
)


def sniff_ext(data: bytes) -> str:
    """A supported file extension for in-memory bytes, or '' if unrecognized.

    Used when bytes are imported under a name that carries no extension (or a
    wrong one): `classify` and the readers below key off the extension, so the
    staged file needs one that matches its actual contents. Only extensions the
    importer accepts are returned — an AVIF, say, sniffs as '' rather than as a
    name the import would then reject one step later.
    """
    for magic, ext in _ARCHIVE_MAGIC:
        if data.startswith(magic):
            return ext
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = normalize_format(im.format)
    except Exception:  # noqa: BLE001 - unrecognized is an answer, not an error
        return ""
    if fmt == "jpeg":
        return "jpg"
    if fmt == "tiff":
        return "tif"
    # 'gif' lands here and is right either way: `classify` re-reads the frame
    # count to decide whether it is a picture or a book of them.
    return fmt if fmt in IMAGE_EXTS else ""


# ---- pdf ----

#: How many pixels across a rendered page is, at most. A PDF page is vector
#: art with no resolution of its own, so one has to be chosen; this is about a
#: 200 dpi A4, which is what a scanned page of the same document would be and
#: enough for the text in a comic or a manual to be read at full zoom.
PDF_PAGE_PX = 1700

#: The effort libwebp spends on a lossless page, as Pillow's `method` and
#: `quality`. BOTH are effort here — under `lossless=True` neither touches
#: fidelity, and every setting was verified to round-trip bit-identical — so
#: the only question is where the knee is, and it is at the bottom: measured
#: over three documents, method 0 is within 3-8% of the size method 1 reaches
#: for a quarter to an eighth of the time, and method 6 spends five to twelve
#: SECONDS a page to save another 2%.
_WEBP_EFFORT = dict(lossless=True, method=0, quality=0)

#: The formats a picture this app RENDERS is written in — WebP where it can be
#: held exactly, PNG where it cannot. Not a picture somebody IMPORTED: that
#: keeps its own bytes and its own format, untouched.
LOSSLESS_EXT = "webp"
FALLBACK_EXT = "png"
#: The LAST resort, for the few modes neither of the other two can hold at all
#: — CMYK and 32-bit float, which PNG refuses outright (the old code, which
#: only ever called `save(buf, "PNG")`, raised on them). Already an accepted
#: import format, so nothing downstream learns a new one.
DEEP_EXT = "tiff"

#: WebP's hard limit, per side. Past it libwebp raises rather than truncating —
#: which a 4x upscale of a large picture really can reach.
WEBP_MAX_DIM = 16383

#: The modes WebP holds EXACTLY, and how to hand them over. RGB and RGBA are
#: native; greyscale is widened to RGB, which changes no value and is worth it
#: (measured on a real grey page: 3 KB as PNG, 0.03 KB as lossless WebP).
#:
#: EVERYTHING ELSE STAYS PNG, and the reason is that WebP does not refuse it —
#: it silently converts. A 16-bit depth map saved "losslessly" comes back with
#: its 0-65520 range crushed to 0-255, and a CMYK scan comes back a different
#: colour, with nothing raised and nothing said. That is the one failure this
#: whole change exists to avoid, so the gate is a list of what is known to
#: survive rather than a list of what is known to break.
#:
#: `P` is exact through RGB and is still on the PNG side: a palette is what PNG
#: is best at, and converting one measured 1.10x here. `1` likewise.
_WEBP_MODES = {"RGB": None, "RGBA": None, "L": "RGB", "LA": "RGBA"}


def encode_lossless(img: "Image.Image") -> tuple[str, bytes]:
    """A rendered picture, encoded for storage without losing a value.

    Returns ``(extension, bytes)`` — the extension because the answer is not
    always the same one, and a caller that assumed it would be is a caller that
    writes `.webp` over PNG bytes. Three rungs: WebP where it is exact, PNG
    where it is not, TIFF for the few modes PNG cannot hold either.

    ONE definition, because several places materialize a picture this library
    has MADE rather than been given — a PDF page, a still captured from a film,
    the frame the importer keeps beside a matched picture, a rotation, an
    editor save, every AI job's output — and "what format do our own renders
    get" has to have one answer or they drift. They all wrote PNG; lossless
    WebP is both smaller and faster than PNG on everything measured here (see
    `_WEBP_EFFORT`), so it is the answer wherever it is exact, and PNG is the
    answer wherever it is not (see `_WEBP_MODES`).
    """
    mode = img.mode
    if mode in _WEBP_MODES and max(img.size) <= WEBP_MAX_DIM:
        widen = _WEBP_MODES[mode]
        out = img.convert(widen) if widen else img
        buf = io.BytesIO()
        out.save(buf, "WEBP", **_WEBP_EFFORT)
        return LOSSLESS_EXT, buf.getvalue()
    buf = io.BytesIO()
    try:
        img.save(buf, "PNG")
    except OSError:
        # PNG cannot write CMYK or 32-bit float. Asked rather than tabled,
        # because "which modes can PNG hold" is Pillow's answer to give and a
        # list here would drift from it.
        buf = io.BytesIO()
        img.save(buf, "TIFF", compression="tiff_lzw")
        return DEEP_EXT, buf.getvalue()
    return FALLBACK_EXT, buf.getvalue()


def encode_matching(img: "Image.Image", ext: str | None) -> bytes:
    """Re-encode ``img`` in the format ``ext`` already names.

    For a picture that is being rewritten AT ITS OWN PATH — rotating an
    artifact in place. `encode_lossless` picks the best format, which is the
    wrong question here: the path is fixed, so WebP bytes under a `.png` name
    would be a file that lies about itself. Falls back to `encode_lossless`
    for a format this cannot write (nothing produces one today), rather than
    guessing.
    """
    e = (ext or "").lower()
    buf = io.BytesIO()
    if e in ("webp", LOSSLESS_EXT):
        out = img
        widen = _WEBP_MODES.get(img.mode, "keep")
        if widen == "keep":
            return encode_lossless(img)[1]
        if widen:
            out = img.convert(widen)
        out.save(buf, "WEBP", **_WEBP_EFFORT)
        return buf.getvalue()
    if e == "png":
        img.save(buf, "PNG")
        return buf.getvalue()
    return encode_lossless(img)[1]


def pdf_page_count(path: Path) -> int:
    """How many pages ``path`` has; 0 for a document that cannot be opened."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception:  # noqa: BLE001 - the import reports the failure itself
        return 0
    try:
        return len(doc)
    finally:
        doc.close()


#: The last document opened by `render_pdf_page`, kept open for the next
#: page of the same file: one per process, keyed on path and mtime.
_PDF_OPEN: dict = {}
#: PDFium IS NOT THREAD-SAFE: two pages rendering at once on the import's
#: THREAD pool (a small document, or `MEDIA_COMPOST_IMPORT_THREADS=1`)
#: took the process down without a word. One render at a time per
#: process; the hashing that follows each page still overlaps. A process
#: pool has a lock per process and never waits on it.
_PDF_RENDER_LOCK = threading.Lock()


def render_pdf_page(path: Path, index: int, out_dir: Path) -> Path:
    """Render page ``index`` (0-based) of ``path`` to a lossless WebP in
    ``out_dir`` and return its path, named ``<stem>-0001.webp`` and so on
    (zero-padded so the natural sort the sequence builder uses puts page 10
    after page 9). Every page scaled so its longer side is `PDF_PAGE_PX`.

    A plain function of (file, page) so that a POOL can render pages
    ahead — the import's look-ahead workers (`importer._render_and_prepare`)
    — each process keeping the document open across its pages.
    """
    import pypdfium2 as pdfium

    key = (str(path), path.stat().st_mtime_ns)
    with _PDF_RENDER_LOCK:
        doc = _PDF_OPEN.get(key)
        if doc is None:
            for old in list(_PDF_OPEN.values()):
                try:
                    old.close()
                except Exception:  # noqa: BLE001
                    pass
            _PDF_OPEN.clear()
            doc = pdfium.PdfDocument(str(path))
            _PDF_OPEN[key] = doc
        page = doc[index]
        try:
            w, h = page.get_size()
            scale = PDF_PAGE_PX / max(1.0, max(w, h))
            bitmap = page.render(scale=scale)
            try:
                im = bitmap.to_pil()
            finally:
                bitmap.close()
        finally:
            page.close()
    if im.mode != "RGB":
        im = im.convert("RGB")
    stem = path.stem or "page"
    out = out_dir / f"{stem}-{index + 1:04d}.{LOSSLESS_EXT}"
    im.save(out, "WEBP", **_WEBP_EFFORT)
    return out


@contextlib.contextmanager
def iter_pdf_pages(path: Path):
    """Render every page to a lossless WebP, yielding ``(page_name, path)``.

    A CONTEXT MANAGER over a temporary directory, and it has to be: a page
    must exist as a file for as long as its caller reads it. `render_pdf_page`
    is the per-page half; the importer drives that one directly, ahead, on
    its workers, and this is the serial spelling for everything else.
    """
    def pages(tmp: Path):
        for i in range(pdf_page_count(path)):
            out = render_pdf_page(path, i, tmp)
            yield out.name, out
            out.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="mc_pdf_") as td:
        yield pages(Path(td))


def archive_member_count(path: Path) -> int:
    """How many files an archive holds, without extracting one — what sizes
    the import's look-ahead pool (`importer.Importer._prefetch_pool`). 0
    when the archive cannot be listed; the import then reports the failure
    where it always did."""
    ext = ext_of(path.name)
    try:
        if ext in ("zip", "cbz") or zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                return sum(1 for i in zf.infolist() if not i.is_dir())
        if ext == "cbr":
            import rarfile

            with rarfile.RarFile(path) as rf:
                return sum(1 for i in rf.infolist() if not i.is_dir())
        if ext == "7z":
            import py7zr

            with py7zr.SevenZipFile(path, mode="r") as zf:
                return sum(1 for e in zf.list() if not e.is_directory)
    except Exception:  # noqa: BLE001
        return 0
    return 0


@contextlib.contextmanager
def iter_gif_frames(path: Path):
    """Write every frame of an animated GIF, yielding ``(frame_name, path)``.

    `iter_pdf_pages`' shape exactly, and for the same reason: the caller
    imports each frame as an ordinary file through `_ingest_image`, so a frame
    must exist on disk for the length of that — and it gets the dedup, the
    hashing, the colour keys and the thumbnails every other picture gets. A
    frames-in-memory variant would be a second ingest path.

    Frames are COMPOSITED, not the raw sub-rectangles a GIF stores: Pillow
    applies the disposal method while it seeks forward, so what is written is
    what a viewer would show at that moment. Alpha is kept only where the
    frame actually has any — a GIF's palette is a container detail, and an
    opaque frame has nothing to gain from an alpha channel.

    Names are `<stem>-0001.<ext>`, zero-padded so the natural sort the
    sequence builder uses puts frame 10 after frame 9. The extension comes
    from :func:`encode_lossless`, which is the one place that decides how a
    picture this app renders is stored.
    """
    def frames(tmp: Path):
        from PIL import ImageSequence

        with Image.open(path) as im:
            stem = path.stem or "frame"
            for i, frame in enumerate(ImageSequence.Iterator(im)):
                rgba = frame.convert("RGBA")
                lo, _hi = rgba.getchannel("A").getextrema()
                out_im = rgba if lo < 255 else rgba.convert("RGB")
                ext, data = encode_lossless(out_im)
                out = tmp / f"{stem}-{i + 1:04d}.{ext}"
                out.write_bytes(data)
                yield out.name, out
                # Stored by now (`ItemStore` has copied the bytes into the
                # item's folder), so it can go: a 500-frame GIF should not
                # hold 500 renders in a temp directory to no purpose.
                out.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix="mc_gif_") as td:
        yield frames(Path(td))


# ---- video ----

def _ffmpeg_exe() -> str:
    override = os.environ.get("MEDIA_COMPOST_FFMPEG", "").strip()
    if override:
        return override
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"  # fall back to system binary


@dataclass
class VideoInfo:
    duration: float | None  # seconds
    frame_rate: float | None  # fps
    bitrate: int | None  # bits/sec
    width: int | None
    height: int | None


@lru_cache(maxsize=1)
def _ffprobe_exe() -> str:
    """The ffprobe binary, looked for where an ffmpeg actually is.

    This used to be the bare string ``"ffprobe"``, i.e. "assume a system
    ffmpeg install put one on PATH". That assumption is what makes the app's
    video support silently half-work on a machine that has no system ffmpeg —
    which is the DEFAULT state on Windows, where nothing installs one and the
    `imageio-ffmpeg` wheel we fall back to for ffmpeg bundles no ffprobe.

    Every probe is written best-effort, so nothing raises: a video imports
    with no duration, no frame rate, no audio or subtitle TRACKS at all (the
    picker lists nothing), no rotation and no colorimetry — so an HDR film is
    never tone-mapped. It looks like a library that has forgotten how to read
    videos rather than like a missing dependency.

    Resolution order: an explicit override, then next to whatever ffmpeg we
    resolved (a real install ships the pair in one directory, so honouring
    MEDIA_COMPOST_FFMPEG / IMAGEIO_FFMPEG_EXE finds its ffprobe too), then
    PATH. The bare name remains the last resort, so behaviour where one IS on
    PATH is unchanged."""
    override = os.environ.get("MEDIA_COMPOST_FFPROBE", "").strip()
    if override:
        return override
    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    beside = Path(_ffmpeg_exe()).parent / exe
    if beside.is_file():
        return str(beside)
    found = shutil.which("ffprobe")
    return found or "ffprobe"


def probe_video(path: Path) -> VideoInfo:
    """Return duration/fps/bitrate/dimensions via ffprobe (best-effort).

    Falls back to a first-frame probe for dimensions if ffprobe is unavailable;
    unknown fields come back as None.
    """
    width = height = None
    duration = frame_rate = None
    bitrate = None
    cmd = [
        _ffprobe_exe(), "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,bit_rate,duration",
        "-show_entries", "format=duration,bit_rate",
        "-of", "json", str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            data = json.loads(proc.stdout or "{}")
            streams = data.get("streams") or [{}]
            s = streams[0]
            fmt = data.get("format") or {}
            width = int(s["width"]) if s.get("width") else None
            height = int(s["height"]) if s.get("height") else None
            fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/0"
            try:
                frame_rate = float(Fraction(fr)) if fr not in ("0/0", "") else None
            except (ZeroDivisionError, ValueError):
                frame_rate = None
            dur = s.get("duration") or fmt.get("duration")
            duration = float(dur) if dur else None
            br = s.get("bit_rate") or fmt.get("bit_rate")
            bitrate = int(br) if br else None
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    if width is None or height is None:
        # Dimensions fallback: decode the first frame.
        try:
            first = extract_frame(path, 0.0)
            width, height = first.width, first.height
        except MediaError:
            pass
    return VideoInfo(duration, frame_rate, bitrate, width, height)


# Container/stream tag -> (catalog name, type), lowercased keys. Deliberately
# the SAME catalog names `_EXIF_INDEX` uses, so `INFO:camera_make=Apple` answers
# for a photograph and for the video shot beside it — a search is about the
# picture, not about which demuxer read it.
_VIDEO_TAG_INDEX: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("com.apple.quicktime.make", "make"), "camera_make", "text"),
    (("com.apple.quicktime.model", "model"), "camera_model", "text"),
    (("com.apple.quicktime.software", "encoder"), "software", "text"),
    (("com.apple.quicktime.author", "artist", "author"), "artist", "text"),
    (("copyright",), "copyright", "text"),
    (("comment", "description"), "description", "text"),
    (("title",), "title", "text"),
)


def _video_capture_date(tags: dict) -> Optional[str]:
    """A video's capture time as a LOCAL wall clock string, or None.

    The trap this exists for: ffprobe's ``creation_time`` is UTC
    (``2024-06-01T14:30:00.000000Z``) and ``exif_datetime_iso``'s regex matches
    it happily, ignoring the trailing ``Z``. Every EXIF ``DateTimeOriginal`` in
    this library is local wall-clock and ``date_sortkey`` is documented as
    timezone-free, so taken at face value a film shot at 14:30 in Berlin indexes
    two hours before the photograph taken beside it — and a ``TAKEN:`` window
    straddling midnight puts them on different days, silently.

    ``com.apple.quicktime.creationdate`` is preferred because it is written in
    LOCAL time with the offset appended (``2024-06-01T14:30:00+0200``): the wall
    clock in it is already the answer, so the offset is simply DROPPED rather
    than added — the arithmetic that looks right here is the bug, and it moves
    every video by its own timezone. Bare ``creation_time`` is UTC with no
    offset to recover, so it is a fallback and is wrong by however far the
    camera was from Greenwich; nothing in the file can say by how much.
    """
    stamped = (tags.get("com.apple.quicktime.creationdate") or "").strip()
    if stamped:
        m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})",
                     stamped)
        if m:
            y, mo, d, h, mi, s = m.groups()
            return f"{y}:{mo}:{d} {h}:{mi}:{s}"
        return stamped
    return (tags.get("creation_time") or "").strip() or None


def probe_video_full(path: Path) -> tuple[VideoInfo, list[MetaValue]]:
    """``probe_video``'s answer PLUS the container's indexable metadata, from
    ONE ffprobe call.

    Separate from ``probe_video`` rather than widening it, because that command
    carries ``-select_streams v:0`` — which is what guarantees ``streams[0]`` is
    the video. Dropping it in place would make a file whose first stream is
    audio read width and height as None in all five of its other callers; here
    the video stream is picked by ``codec_type`` explicitly instead.

    Best-effort throughout: no ffprobe, or a container with no tags, simply
    yields fewer values.
    """
    info = VideoInfo(None, None, None, None, None)
    out: list[MetaValue] = []
    cmd = [
        _ffprobe_exe(), "-v", "error", "-show_entries",
        "stream=index,codec_type,codec_name,width,height,avg_frame_rate,"
        "r_frame_rate,bit_rate,duration,channels"
        ":format=duration,bit_rate"
        ":format_tags",
        "-of", "json", str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(proc.stdout or "{}") if proc.returncode == 0 else {}
    except (OSError, ValueError, json.JSONDecodeError):
        data = {}
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    vid = next((s for s in streams if s.get("codec_type") == "video"), None)
    aud = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if vid is not None:
        width = int(vid["width"]) if vid.get("width") else None
        height = int(vid["height"]) if vid.get("height") else None
        fr = vid.get("avg_frame_rate") or vid.get("r_frame_rate") or "0/0"
        try:
            frame_rate = float(Fraction(fr)) if fr not in ("0/0", "") else None
        except (ZeroDivisionError, ValueError):
            frame_rate = None
        dur = vid.get("duration") or fmt.get("duration")
        br = vid.get("bit_rate") or fmt.get("bit_rate")
        info = VideoInfo(
            float(dur) if dur else None, frame_rate,
            int(br) if br else None, width, height,
        )
    if info.width is None or info.height is None:
        try:
            first = extract_frame(path, 0.0)
            info = VideoInfo(info.duration, info.frame_rate, info.bitrate,
                             first.width, first.height)
        except MediaError:
            pass

    tags = {str(k).lower(): v for k, v in (fmt.get("tags") or {}).items()}
    seen: set[str] = set()
    for keys, name, mtype in _VIDEO_TAG_INDEX:
        if name in seen:
            continue
        for key in keys:
            raw = _fmt_exif(tags.get(key)) if tags.get(key) is not None else ""
            if raw:
                out.append(MetaValue(name, mtype, None, raw, raw))
                seen.add(name)
                break
    stamp = _video_capture_date(tags)
    if stamp:
        key = date_sortkey(stamp)
        if key is not None:
            out.append(MetaValue("date_taken", "date", key, None, stamp))
    if vid is not None and vid.get("codec_name"):
        codec = str(vid["codec_name"])
        out.append(MetaValue("codec", "text", None, codec, codec))
    # "Has audio" was an ffprobe subprocess on every render of the Info tab.
    # Read once here, and searchable for the first time as a side effect.
    has = "Yes" if aud is not None else "No"
    if streams:
        out.append(MetaValue("has_audio", "text", None, has, has))
    if aud is not None:
        if aud.get("codec_name"):
            ac = str(aud["codec_name"])
            out.append(MetaValue("audio_codec", "text", None, ac, ac))
        if aud.get("channels"):
            ch = int(aud["channels"])
            out.append(MetaValue("audio_channels", "numeric", float(ch), None,
                                 str(ch)))
    return info, out


def _iter_boxes(f, start: int, end: int) -> Iterator[tuple[str, int, int]]:
    """Yield ``(type, payload_start, payload_end)`` for the ISO-BMFF boxes in
    ``[start, end)``. Stops at the first malformed header."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            return
        size = int.from_bytes(head[:4], "big")
        typ = head[4:8].decode("latin-1")
        hdr = 8
        if size == 1:  # 64-bit extended size
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = int.from_bytes(ext, "big")
            hdr = 16
        elif size == 0:  # extends to the end of the container
            size = end - pos
        if size < hdr or pos + size > end:
            return
        yield typ, pos + hdr, pos + size
        pos += size


def _mp4_track_edits(path: Path) -> Optional[dict[int, float]]:
    """Per-track edit-list shift in seconds, keyed by stream index.

    A ``trak``'s ``edts/elst`` maps its own media timeline onto the movie's:
    the shift is the leading empty edit's duration (a delay) minus the media
    time the first real edit starts at. Adding it to a sample's raw media
    timestamp gives the time it is presented at — which is what a ``<video>``
    element's ``currentTime`` counts, so it is the timeline a WebVTT cue has
    to be written on.

    Returns ``None`` when the file isn't an ISO-BMFF container with a ``moov``
    (so callers can tell "not an MP4" from "an MP4 with no edits"). Every trak
    is listed, most of them with 0.0.
    """
    out: dict[int, float] = {}
    found = False
    try:
        with path.open("rb") as f:
            size = path.stat().st_size
            for typ, ms, me in _iter_boxes(f, 0, size):
                if typ != "moov":
                    continue
                found = True
                movie_ts = 600
                for btyp, bs, be in _iter_boxes(f, ms, me):
                    if btyp != "mvhd" or be - bs < 20:
                        continue
                    f.seek(bs)
                    head = f.read(20)
                    # v1 widens the two times before the timescale field.
                    movie_ts = int.from_bytes(head[16:20] if head[0] == 1 else head[12:16], "big") or 600
                for ti, (_t, ts, te) in enumerate(
                    (b for b in _iter_boxes(f, ms, me) if b[0] == "trak")
                ):
                    media_ts, edits = 0, []
                    for btyp, bs, be in _iter_boxes(f, ts, te):
                        if btyp == "mdia":
                            for mtyp, mms, mme in _iter_boxes(f, bs, be):
                                if mtyp == "mdhd" and mme - mms >= 20:
                                    f.seek(mms)
                                    h = f.read(28)
                                    media_ts = int.from_bytes(
                                        h[20:24] if h[0] == 1 else h[12:16], "big")
                        elif btyp == "edts":
                            for etyp, es, ee in _iter_boxes(f, bs, be):
                                if etyp == "elst":
                                    edits = _parse_elst(f, es, ee)
                    out[ti] = _edit_shift(edits, movie_ts, media_ts)
                break
    except (OSError, ValueError):
        return out if found else None
    return out if found else None


def _parse_elst(f, start: int, end: int) -> list[tuple[int, int]]:
    """``[(segment_duration, media_time)]`` from an ``elst`` box; media_time is
    ``-1`` for an empty edit."""
    f.seek(start)
    data = f.read(end - start)
    if len(data) < 8:
        return []
    version = data[0]
    count = int.from_bytes(data[4:8], "big")
    wide = version == 1
    step = 20 if wide else 12
    out: list[tuple[int, int]] = []
    off = 8
    for _ in range(count):
        if off + step > len(data):
            break
        n = 8 if wide else 4
        dur = int.from_bytes(data[off:off + n], "big")
        mt = int.from_bytes(data[off + n:off + 2 * n], "big", signed=True)
        out.append((dur, mt))
        off += step
    return out


def _edit_shift(edits: list[tuple[int, int]], movie_ts: int, media_ts: int) -> float:
    """Seconds to add to a raw media timestamp to get its presentation time."""
    if not edits or not media_ts or not movie_ts:
        return 0.0
    delay = 0.0
    for dur, mt in edits:
        if mt < 0:  # empty edit: pure delay on the movie timeline
            delay += dur / movie_ts
            continue
        return delay - mt / media_ts
    return delay


def _mp4_track_names(path: Path) -> dict[int, str]:
    """Per-track names from an MP4/MOV's ``trak/udta`` boxes, keyed by stream index.

    ffprobe surfaces a track's title as a stream tag only where the container
    carries one there (MKV's ``title``). QuickTime-style files instead keep it
    in the track's own ``udta`` box — a raw ``name`` atom, or the 3GPP ``titl``
    (version/flags + packed language, then a NUL-terminated UTF-8 string) — and
    the mov demuxer maps neither. Streams leave that demuxer in ``trak`` order,
    so a ``trak``'s position inside ``moov`` IS its stream index.

    Best-effort: any malformed box ends the walk and whatever was found so far
    is returned.
    """
    names: dict[int, str] = {}
    try:
        with path.open("rb") as f:
            size = path.stat().st_size
            for typ, ms, me in _iter_boxes(f, 0, size):
                if typ != "moov":
                    continue
                for ti, (ttyp, ts, te) in enumerate(
                    (b for b in _iter_boxes(f, ms, me) if b[0] == "trak")
                ):
                    for utyp, us, ue in _iter_boxes(f, ts, te):
                        if utyp != "udta":
                            continue
                        for ntyp, ns, ne in _iter_boxes(f, us, ue):
                            if ntyp == "name":
                                f.seek(ns)
                                raw = f.read(ne - ns)
                            elif ntyp == "titl" and ne - ns > 6:
                                f.seek(ns + 6)  # version/flags + language
                                raw = f.read(ne - ns - 6)
                            else:
                                continue
                            text = raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()
                            # A raw ``name`` wins over ``titl`` (both usually
                            # carry the same string; ``name`` needs no decoding).
                            if text and (ntyp == "name" or ti not in names):
                                names[ti] = text
                break
    except (OSError, ValueError):
        return names
    return names


def probe_tracks(path: Path) -> list[dict]:
    """Return the media streams (tracks) inside a container, best-effort.

    Each entry is ``{index, kind, codec, detail, language, meta}`` where ``kind``
    is video/audio/subtitle/data, ``detail`` is a short human summary, and
    ``meta`` is an ordered list of ``{label, value}`` rows (dimensions, frame
    rate, bitrate, channels, …) for a per-track breakdown. Unknown fields are
    omitted. Returns an empty list if ffprobe is unavailable.
    """
    cmd = [
        _ffprobe_exe(), "-v", "error", "-show_entries",
        "stream=index,codec_type,codec_name,width,height,avg_frame_rate,"
        "r_frame_rate,bit_rate,channels,channel_layout,sample_rate,duration"
        ":stream_tags=language,title,filename,mimetype,DURATION"
        ":stream_disposition=default",
        "-of", "json", str(path),
    ]
    out: list[dict] = []
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    streams = data.get("streams") or []
    # A track's duration differs from the file's when it is meaningfully shorter
    # (e.g. a partial subtitle) — worth surfacing. The file duration is the
    # longest track.
    durs = [_stream_duration(s) for s in streams]
    max_dur = max(durs, default=0.0)
    # QuickTime-style containers keep a track's name where ffprobe doesn't look.
    udta_names = (
        _mp4_track_names(path)
        if streams and not any((s.get("tags") or {}).get("title") for s in streams)
        else {}
    )
    for si, s in enumerate(streams):
        kind = s.get("codec_type") or "data"
        codec = s.get("codec_name") or "?"
        meta: list[dict] = []

        def add(label: str, value: str | None) -> None:
            if value:
                meta.append({"label": label, "value": value})

        if kind == "video":
            if s.get("width") and s.get("height"):
                add("Dimensions", f"{int(s['width'])} × {int(s['height'])}")
            fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/0"
            try:
                fps = float(Fraction(fr)) if fr not in ("0/0", "") else None
            except (ZeroDivisionError, ValueError):
                fps = None
            if fps:
                add("Frame rate", f"{fps:.2f} fps")
        elif kind == "audio":
            if s.get("channels"):
                ch = int(s["channels"])
                layout = s.get("channel_layout")
                # ffprobe qualifies some layouts (e.g. "5.1(side)"); drop the
                # parenthetical so it doesn't nest inside our own brackets.
                if layout:
                    layout = layout.split("(")[0].strip() or layout
                add("Channels", f"{ch} ({layout})" if layout else f"{ch} ch")
            if s.get("sample_rate"):
                add("Sample rate", f"{int(s['sample_rate'])} Hz")
        elif kind == "attachment":
            # Usually embedded fonts in an MKV — surface their name and type.
            tags = s.get("tags") or {}
            add("File", tags.get("filename"))
            add("Type", tags.get("mimetype"))
        # (A track's title is surfaced as its own field / header, not a meta row.)
        br = s.get("bit_rate")
        if br:
            try:
                kbps = int(br) // 1000
                # A subtitle stream reports 0 kbps — not worth a row.
                if kbps > 0:
                    add("Bitrate", f"{kbps} kbps")
            except (TypeError, ValueError):
                pass
        lang = (s.get("tags") or {}).get("language")
        lang = lang if lang and lang.lower() != "und" else None
        add("Language", lang)
        # Only show a track's duration when it is meaningfully shorter than the
        # file (a >1 s gap — sub-second container padding isn't worth a row).
        dur = durs[si]
        if dur > 0 and max_dur - dur > 1.0:
            add("Duration", _fmt_duration(dur))
        out.append({
            "index": int(s.get("index", len(out))),
            "kind": kind,
            "codec": codec,
            "title": (s.get("tags") or {}).get("title") or udta_names.get(si) or None,
            # This track plays/shows by default (MKV/MP4 default disposition).
            "default": bool((s.get("disposition") or {}).get("default")),
            # A compact one-line summary (used where space is tight); the same
            # values expanded into rows live in ``meta``.
            "detail": " · ".join(m["value"] for m in meta if m["label"] != "Language"),
            "language": lang,
            "meta": meta,
        })
    return out


def _stream_duration(s: dict) -> float:
    """Seconds for one ffprobe stream: the numeric ``duration`` field, else the
    MKV ``DURATION`` tag (``HH:MM:SS.mmm``), else 0."""
    d = s.get("duration")
    try:
        if d is not None:
            return float(d)
    except (TypeError, ValueError):
        pass
    tag = (s.get("tags") or {}).get("DURATION")
    if tag:
        try:
            h, m, sec = tag.split(":")
            return int(h) * 3600 + int(m) * 60 + float(sec)
        except (ValueError, AttributeError):
            return 0.0
    return 0.0


def _fmt_duration(seconds: float) -> str:
    # Keep one decimal of seconds: track durations often differ by under a
    # second (container padding), and rounding to whole seconds hid exactly the
    # difference the duration row exists to show.
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m}:{s:04.1f}"


#: A BMP file header: ``BM``, the total file size, four reserved bytes and the
#: pixel offset. The size is what makes a stream of them readable one at a time.
_BMP_HEADER = 14


class _Unprobed:
    """The type of `UNPROBED`; a class so it reprs itself in a signature."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "UNPROBED"


#: "Nobody has worked out this file's colour conversion yet." Distinct from
#: `None`, which is the real answer *this file needs no conversion* — so a
#: caller that has already paid for `color_filter_for` can pass the answer in,
#: including when the answer is "nothing to do".
#:
#: It is an argument rather than a cache because a cache here would have to be
#: keyed on the path, and a path's CONTENT changes under this app: `fileops`
#: rewrites a file's bytes in place when it rotates one, and the server is a
#: process that runs for weeks. An argument cannot go stale.
UNPROBED = _Unprobed()


def _scale_filter(max_dim: int, flags: str = "") -> str:
    """Fit within ``max_dim``x``max_dim``, never upscaling, aspect preserved.

    ``flags`` names the scaler. **The frame SCAN must not pass one**: its
    downscale feeds `compute_phash_image`, so changing the resampling changes
    every scanned frame's hash and with it which frames match the library —
    swscale's default is what every stored `VideoFrame` was hashed through.
    A thumbnail has no such contract, and passes ``lanczos`` to stand in for
    the `Image.thumbnail` LANCZOS it replaced.
    """
    m = int(max_dim)
    return (f"scale='min({m},iw)':'min({m},ih)'"
            ":force_original_aspect_ratio=decrease"
            + (f":flags={flags}" if flags else ""))


def _read_bmp_stream(stdout, path: Path):
    """Yield RGB images from a pipe of concatenated BMPs.

    A BMP carries its own size and its own length, which is what lets several
    of them share one pipe with no framing of our own — see
    `iter_video_frames` for why the frames travel as BMP at all.
    """
    while True:
        head = stdout.read(_BMP_HEADER)
        if len(head) < _BMP_HEADER:
            return
        if head[:2] != b"BM":
            raise MediaError(f"ffmpeg produced no frames for {path.name}")
        size = int.from_bytes(head[2:6], "little")
        rest = stdout.read(size - _BMP_HEADER)
        with Image.open(io.BytesIO(head + rest)) as im:
            yield im.convert("RGB")


def iter_video_frames(
    path: Path, frame_rate: float | None = None,
    sample_fps: float | None = None,
    max_dim: int | None = None,
    color_filter: str | None | _Unprobed = UNPROBED,
) -> Iterator[tuple[int, float, Image.Image]]:
    """Yield ``(index, timestamp_seconds, RGB image)`` for the video's frames.

    By default every frame is extracted. Pass ``sample_fps`` to instead sample at
    a fixed rate (e.g. 2 fps) — hugely faster for scanning a video against the
    library, since consecutive frames are near-identical and an image that
    actually appears is on screen far longer than a fraction of a second.
    Timestamps are derived from the sampling rate (or ``frame_rate`` for the
    every-frame path; probed if not given, default 25).

    Pass ``max_dim`` to have ffmpeg **downscale** each frame to fit within a
    ``max_dim``×``max_dim`` box (never upscaling, aspect preserved). The
    perceptual hash and the pixel verification both work on tiny images, so
    scanning a large video for matches doesn't need — and is much faster without
    — full-resolution decoding of every sampled frame; the few frames that
    actually match are re-extracted at full resolution by the caller.

    **THE FRAMES COME DOWN A PIPE, ONE BMP EACH.** This used to write the whole
    run into a temp directory as PNGs and then read them back, which is two
    costs the caller pays for nothing: PNG is where the time goes, and a film
    at its own frame rate is 34 000 files on disk before the first of them is
    looked at — so nothing could be hashed until the last one had been
    written. Measured on a real 24-minute episode at 256 px: the PNG path
    spent 22 s on 2 863 sampled frames, and this one spends 23 s hashing all
    34 300 of them. Twelve times the frames for the same wall clock, and one
    frame in memory rather than a directory on disk.

    BMP rather than raw ``rgb24``: a raw pipe has no frame boundaries, so the
    reader must know the scaled size up front — which we do not, because the
    scale filter's output depends on the display aspect and on any rotation
    ffmpeg applies for us. A BMP carries its own size and its own length, and
    encoding one is a memcpy (verified byte-identical to the PNG path).
    """
    cmd = [_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(path)]
    filters: list[str] = []
    # HDR first, before anything samples or scales: these frames are hashed
    # against the library, and a screenshot somebody took of an HDR film
    # was tone-mapped by whatever showed it — so a hash taken off the raw
    # PQ values is a hash of a different picture and matches nothing. Same
    # chain the single-frame capture uses, so the two agree.
    hdr = color_filter_for(path) if isinstance(color_filter, _Unprobed) \
        else color_filter
    if hdr:
        filters.append(hdr)
    if sample_fps and sample_fps > 0:
        filters.append(f"fps={sample_fps}")
        step = 1.0 / sample_fps
    else:
        fr = frame_rate or probe_video(path).frame_rate or 25.0
        if fr <= 0:
            fr = 25.0
        cmd += ["-vsync", "0"]
        step = 1.0 / fr
    if max_dim and max_dim > 0:
        filters.append(_scale_filter(max_dim))
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-f", "image2pipe", "-vcodec", "bmp", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, bufsize=1 << 20)
    assert proc.stdout is not None
    try:
        for i, im in enumerate(_read_bmp_stream(proc.stdout, path)):
            yield i, i * step, im
        if proc.wait() != 0:
            err = (proc.stderr.read() if proc.stderr else b"").decode(
                "utf-8", "replace").strip()
            raise MediaError(f"ffmpeg failed on {path.name}: {err}")
    finally:
        # A caller that stops early (an importer that has found what it wanted,
        # or simply an exception) must not leave a decode running: the pipe
        # fills, ffmpeg blocks on the write and the process is never reaped.
        if proc.poll() is None:
            proc.kill()
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
        proc.wait()


#: The transfer functions that mean HIGH DYNAMIC RANGE — PQ (HDR10, and the
#: Dolby Vision profiles that carry a PQ base layer) and HLG. ffprobe reports
#: each under two spellings depending on the container.
_HDR_TRANSFERS = {
    "smpte2084", "smpte-st-2084", "st2084",       # PQ
    "arib-std-b67", "arib_std_b67",               # HLG
}


def is_hdr_transfer(transfer: str | None) -> bool:
    """Does this ffprobe ``color_transfer`` mean the picture is HDR?"""
    return (transfer or "").strip().lower() in _HDR_TRANSFERS


#: What ffprobe said about a file's video stream, keyed by FILE VERSION —
#: the path plus its size and modification time.
#:
#: These are facts about the ENCODING (how the colour is tagged, whether the
#: pixel format carries alpha) and they cost an ffprobe each: ~35 ms, twice,
#: on every still captured from a film — half of what taking one cost on a
#: 1.1 GB file. Nothing about them can change while the bytes do not.
#:
#: KEYED ON THE STAT, not on the path: a path's contents DO change here —
#: `fileops` rewrites a file in place to rotate it — so a path-only cache
#: would go on describing the file that used to be there. A stat is ~10 µs
#: against a 35 ms probe, and it is what makes the answer safe to keep.
#: Bounded, because a library has more films than a process needs to remember.
_STREAM_PROBES: "OrderedDict[tuple, dict]" = OrderedDict()
_STREAM_PROBE_MAX = 64


def _stream_fields(path: Path) -> dict:
    """The video stream's colour tags and pixel format, from ONE ffprobe.

    One call rather than two: `color_filter_for` and `video_has_alpha` are
    both questions about the same stream, and asked separately they were two
    subprocesses reading the same header.
    """
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is not None and key in _STREAM_PROBES:
        _STREAM_PROBES.move_to_end(key)
        return _STREAM_PROBES[key]
    cmd = [
        _ffprobe_exe(), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=color_transfer,color_primaries,pix_fmt",
        "-of", "json", str(path),
    ]
    out: dict = {}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            streams = json.loads(proc.stdout or "{}").get("streams") or []
            out = streams[0] if streams else {}
    except Exception:  # noqa: BLE001 — an unreadable stream says nothing
        out = {}
    if key is not None:
        _STREAM_PROBES[key] = out
        while len(_STREAM_PROBES) > _STREAM_PROBE_MAX:
            _STREAM_PROBES.popitem(last=False)
    return out


def _colorimetry(path: Path) -> tuple[str | None, str | None]:
    """The video stream's ``(transfer, primaries)`` tags; None where untagged.

    "unknown" is ffprobe's word for a stream that says nothing, and it means
    exactly what a missing tag means, so both come back as None — and NOTHING
    is converted on a guess.
    """
    s = _stream_fields(path)

    def tag(name: str) -> str | None:
        v = (s.get(name) or "").strip().lower()
        return None if v in ("", "unknown", "unspecified") else v

    return tag("color_transfer"), tag("color_primaries")


def _has_zscale() -> bool:
    """Is this ffmpeg built with libzimg (the ``zscale`` filter)?

    Cached for the process: it is a subprocess that lists every filter, and the
    answer cannot change while we run. `_ffmpeg_exe` may resolve to the bundled
    imageio binary (which has zimg) or to whatever ``ffmpeg`` is on PATH (which
    may not), so it has to be asked rather than assumed.
    """
    global _ZSCALE
    if _ZSCALE is None:
        try:
            proc = subprocess.run(
                [_ffmpeg_exe(), "-hide_banner", "-filters"],
                capture_output=True, text=True)
            _ZSCALE = " zscale " in (proc.stdout or "")
        except Exception:  # noqa: BLE001
            _ZSCALE = False
    return _ZSCALE


_ZSCALE: bool | None = None
_ALPHA_FMTS: frozenset | None = None


def _alpha_pix_fmts() -> frozenset:
    """The pixel formats that carry an alpha channel, asked of ffprobe.

    Asked rather than tabled: 67 of ffprobe's 267 formats carry the flag
    here, and a hand-kept list is one that silently misses the next format
    (or wrongly matches by name — `gray` contains an "a" and `pal8` does
    not, and pal8 IS one). Cached for the process like `_has_zscale`, and an
    unreadable answer is the empty set, which reads as "no alpha anywhere"
    — the direction every caller already handles, since it is today's
    behaviour.
    """
    global _ALPHA_FMTS
    if _ALPHA_FMTS is None:
        try:
            proc = subprocess.run(
                [_ffprobe_exe(), "-v", "error", "-show_pixel_formats",
                 "-of", "json"],
                capture_output=True, text=True)
            fmts = json.loads(proc.stdout or "{}").get("pixel_formats") or []
            _ALPHA_FMTS = frozenset(
                f["name"] for f in fmts
                if (f.get("flags") or {}).get("alpha"))
        except Exception:  # noqa: BLE001
            _ALPHA_FMTS = frozenset()
    return _ALPHA_FMTS


def video_has_alpha(path: Path) -> bool:
    """Does this video's stream carry an alpha channel?

    A video CAN: qtrle and ProRes 4444 in a .mov, VP8/VP9 with
    ``yuva420p`` in WebM, an AV1 alpha layer — stickers, motion graphics,
    anything rendered over transparency. The answer is the stream's
    ``pix_fmt`` held against ffprobe's own alpha flag, so a new format is
    covered the day ffprobe knows it.
    """
    fmt = (_stream_fields(path).get("pix_fmt") or "").strip()
    return bool(fmt) and fmt in _alpha_pix_fmts()

#: HDR → SDR, as one filter chain: linearize the PQ/HLG signal (with 100 nits
#: — SDR white — as 1.0), move the primaries to BT.709, roll the highlights
#: back into range, and re-encode to the BT.709 transfer an ordinary PNG is
#: read with.
#:
#: **`mobius`, not `hable`.** The widely-copied HDR→SDR recipe uses hable, and
#: measured against ground truth here it darkens the WHOLE picture, shadows and
#: midtones included: on a clip round-tripped from a real SDR source, a band
#: whose true mean is 107 came back at 72, and 148 came back at 97. Mobius is
#: built for exactly this trade — it leaves in-range values alone and only
#: degrades what is above the range — and on the same clip reproduced those
#: bands at 108 and 147, touching only the top one (251 → 213), which is the
#: highlight roll-off that is the point of tone mapping. `clip` is more
#: faithful still on content that never exceeds the range, and blows out
#: anything that does, which real HDR always does.
_HDR_TO_SDR = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=mobius,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)


#: Primaries that already ARE what a PNG is read with. Everything else the
#: stream names has to be converted, or the picture's most saturated colours
#: come out as different colours.
_SRGB_PRIMARIES = {"bt709", "srgb", "iec61966-2-1"}


def color_filter_for(path: Path) -> str | None:
    """The colour conversion this file's frames need, or None for none.

    Two things, and both are about the fact that a PNG carries no colour
    information at all — every viewer reads one as sRGB, so whatever comes out
    of ffmpeg has to already BE sRGB:

    * **HDR** (PQ or HLG) is tone-mapped down to BT.709. This is the loud one:
      without it the PQ-encoded values land unconverted in the file and a still
      captured from an HDR film looks nothing like the frame the player was
      showing (measured on a clip converted from a known SDR source, mean 97
      against the original's 185 — the player reads the stream's tags and tone
      maps, so the still has to do the same).
    * **Primaries** that are not BT.709 are converted to it. Quiet by
      comparison — on a real BT.470BG file here it moves the average pixel by
      0.05/255 — but it reaches 23 on the saturated ones, which is the pixels
      it is about.

    NOT the matrix or the range: ffmpeg already reads the stream's own and
    converts YUV → RGB accordingly, verified byte-identical on a BT.709 clip
    small enough that swscale's old guess-from-height heuristic would have
    called it BT.601. There is nothing to fix there and a filter that redid it
    could only introduce a rounding difference.

    None when the stream says NOTHING (ffprobe's "unknown"): a file with no
    tags is assumed BT.709 by everything that reads it, including the player
    we are trying to match, and converting from a guess is how a picture that
    was right becomes wrong.

    None, too, when ffmpeg has no ``zscale`` (libzimg): the frame is then
    extracted the plain way, which is imperfect — and no frame at all is worse.
    """
    transfer, primaries = _colorimetry(path)
    hdr = is_hdr_transfer(transfer)
    wide = primaries is not None and primaries not in _SRGB_PRIMARIES
    if not hdr and not wide:
        return None
    if not _has_zscale():
        return None
    # Tone mapping ends at BT.709 primaries itself, so it covers both.
    return _HDR_TO_SDR if hdr else "zscale=p=bt709,format=yuv420p"


def extract_frame(path: Path, timestamp: float, *,
                  max_dim: int | None = None,
                  color_filter: str | None | _Unprobed = UNPROBED,
                  keep_alpha: bool = False,
                  ) -> Image.Image:
    """Extract a single frame at ``timestamp`` seconds as an RGB image.

    ``keep_alpha`` returns RGBA instead — WHEN the stream carries alpha and
    no colour conversion runs — and exists for exactly one caller: the
    captured STILL, which becomes a real item stored losslessly. Everything
    else here wants RGB (a hash, a thumbnail, a dimensions probe), and for a
    transparent video the RGB reading is not merely flattened, it is wrong:
    a fully transparent pixel comes back as whatever colour sat under it,
    so a red-on-transparency sticker gained a bright green field nobody had
    ever seen on screen. Two format changes make it work: the BMP below
    cannot say alpha at all (ffmpeg writes a 32bpp BMP with a
    BITMAPINFOHEADER, which has no alpha mask, so Pillow reads it as RGBX),
    so the alpha frame travels as uncompressed TIFF; and the ``convert``
    keeps the mode. An HDR or wide-gamut stream keeps the RGB path even
    when asked — the colour filter ends in ``format=yuv420p``, so there is
    no alpha left on that road, and colour-correct beats transparent for
    the case (which barely exists) of a stream that is both.

    An **HDR** source is tone-mapped down to BT.709/SDR first. Without that the
    PQ- or HLG-encoded values land unconverted in a picture that carries no
    colour information at all, so every viewer reads them as sRGB — which is
    why a still captured from an HDR film came out looking nothing like the
    frame the player had just been showing (measured on a clip converted from a
    known SDR source: mean 97 against the original's 185). The player reads the
    stream's tags and tone-maps; the still has to do the same thing itself.

    ``color_filter`` is that conversion, for a caller that has already worked
    it out — `color_filter_for` is an `ffprobe` of its own (~42 ms), and the
    importer needs the answer once per video and then uses it for the
    thumbnail, the scan and every matched frame.

    ``max_dim`` has **ffmpeg** downscale the frame (never upscaling, aspect
    preserved) instead of returning it at full resolution. For a caller that
    only wants a thumbnail that is the whole saving: a 1920x1080 frame no
    longer has to be encoded, piped and decoded at full size just to be
    resized afterwards — 205 ms to 58 ms measured on a 1080p file. A caller
    that keeps the frame as a picture in its own right (a captured still) must
    NOT pass one.

    **THE FRAME COMES BACK AS BMP, NOT PNG.** It is a pipe between two
    processes on one machine, so the compression buys nothing and costs real
    time: measured full-res, PNG 127 ms against BMP 46 ms, for a
    pixel-identical image — encoding a BMP is a memcpy. WebP was measured too,
    since it is what a thumbnail is finally STORED as, and it is the wrong
    answer in both forms: lossless is 5.5x slower than PNG (696 ms) and
    lossy q90 is no faster than PNG while no longer being the frame that was
    decoded. `iter_video_frames` reached the same conclusion for the same
    reason; this is that fix at the single-frame call site.
    """
    cmd = [
        _ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, timestamp):.3f}", "-i", str(path),
        "-frames:v", "1",
    ]
    filt = color_filter_for(path) if isinstance(color_filter, _Unprobed) \
        else color_filter
    chain = [f for f in (filt, _scale_filter(max_dim, "lanczos")
                         if max_dim and max_dim > 0 else "") if f]
    if chain:
        cmd += ["-vf", ",".join(chain)]
    alpha = keep_alpha and not filt and video_has_alpha(path)
    if alpha:
        cmd += ["-pix_fmt", "rgba", "-f", "image2", "-c:v", "tiff",
                "-compression_algo", "raw", "-"]
    else:
        cmd += ["-f", "image2", "-c:v", "bmp", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise MediaError(f"ffmpeg frame extract failed on {path.name}: {err}")
    im = Image.open(io.BytesIO(proc.stdout))
    return im.convert("RGBA" if alpha else "RGB")


def extract_frames(path: Path, wanted: "Sequence[tuple[int, float]]", *,
                   color_filter: str | None | _Unprobed = UNPROBED,
                   ) -> dict[int, Image.Image]:
    """Extract several frames of one video at once: ``{frame_index: image}``.

    ``wanted`` is ``(frame_index, timestamp)`` pairs — the index as
    `iter_video_frames` counts them. The timestamp is carried for the caller's
    records; the SELECTION is by index, and that is the point of this function
    rather than an optimisation of it.

    **A SEEK RETURNS THE WRONG FRAME AND THIS DOES NOT.** ``extract_frame``
    formats its ``-ss`` to three decimals, so on a 23.976 fps file frame 90
    (t=3.7537...s) is asked for as 3.754 and ffmpeg answers with frame 91 —
    reproduced here, and it is why the frame materialized beside a matched
    picture could be one frame off the frame that actually matched it.
    Selecting by index is exact, at any frame rate, variable ones included,
    where multiplying a timestamp by a nominal rate is a guess.

    It is also far cheaper in the plural, which is how the importer needs it:
    nine matched frames of a 9.5 s clip took 1731 ms one seek at a time and
    165 ms in one pass, byte-identical (9/9). What one pass costs is one
    decode — 117 ms for that clip, 739 ms for a 76 s one — so for a SINGLE
    frame a seek would still have been quicker (205 ms). That trade is
    declined deliberately: a frame this returns is one somebody keeps, and
    two accuracies depending on how many were asked for is worse than the
    half-second.

    ``select`` comes FIRST in the chain: dropping frames before tone-mapping
    them is both cheaper and harmless — the conversion is per frame — and
    ``n`` then counts the decoder's own output, which is what
    `iter_video_frames` counts with ``-vsync 0``.
    """
    if not wanted:
        return {}
    filt = color_filter_for(path) if isinstance(color_filter, _Unprobed) \
        else color_filter
    order = sorted({int(i) for i, _ts in wanted})
    expr = "+".join(f"eq(n\\,{i})" for i in order)
    chain = [f for f in (f"select='{expr}'", filt) if f]
    cmd = [
        _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vf", ",".join(chain), "-vsync", "0",
        "-f", "image2pipe", "-vcodec", "bmp", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, bufsize=1 << 22)
    assert proc.stdout is not None
    out: dict[int, Image.Image] = {}
    try:
        for idx, im in zip(order, _read_bmp_stream(proc.stdout, path)):
            out[idx] = im
        if proc.wait() != 0:
            err = (proc.stderr.read() if proc.stderr else b"").decode(
                "utf-8", "replace").strip()
            raise MediaError(f"ffmpeg failed on {path.name}: {err}")
    finally:
        # Same reason as `iter_video_frames`: a caller that stops early must
        # not leave a decode blocked on a full pipe and never reaped.
        if proc.poll() is None:
            proc.kill()
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
        proc.wait()
    return out


#: The video encoders a codec round-trip may ask for. Probed once per process,
#: like `_has_zscale` and for the same reason: `_ffmpeg_exe` may resolve to the
#: bundled imageio binary (which has both) or to whatever is on PATH (which may
#: have neither), and naming a missing encoder fails the whole invocation.
_ENCODERS: set[str] | None = None


def has_encoder(name: str) -> bool:
    """Whether this ffmpeg can encode with ``name`` (e.g. ``libx265``)."""
    global _ENCODERS
    if _ENCODERS is None:
        try:
            proc = subprocess.run(
                [_ffmpeg_exe(), "-hide_banner", "-encoders"],
                capture_output=True, text=True)
            # Lines look like " V....D libx264   H.264 ...": the encoder name is
            # the second field.
            found = set()
            for line in (proc.stdout or "").splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] and not parts[0].startswith("-"):
                    found.add(parts[1])
            _ENCODERS = found
        except Exception:  # noqa: BLE001
            _ENCODERS = set()
    return name in _ENCODERS


#: Codec key -> the ffmpeg encoder that implements it.
CODEC_ENCODERS = {"h264": "libx264", "h265": "libx265"}


def codec_roundtrip(img: Image.Image, codec: str, crf: int) -> Image.Image:
    """Push one still through a video encoder and decode it back.

    This is what makes a picture look like a frame grabbed off a low-bitrate
    stream rather than a re-saved JPEG: the DCT blocking comes with the chroma
    smear of 4:2:0 subsampling and the encoder's own ringing, which no image
    codec reproduces.

    Two details are not optional. The intermediate goes through a real file in
    a temp directory rather than a pipe — an mp4 muxer needs to seek back and
    patch its header, so writing one to stdout either fails or needs the
    fragmenting flags, and the codebase's other ffmpeg writers already work
    this way. And `yuv420p` halves the chroma planes, so it refuses an odd
    width or height: the scale filter rounds both down to even, and the result
    is padded back to the original size afterwards, because every caller here
    relies on a degraded picture keeping its dimensions.
    """
    encoder = CODEC_ENCODERS.get(codec)
    if not encoder:
        raise MediaError(f"unknown codec {codec!r}")
    if not has_encoder(encoder):
        raise MediaError(
            f"this ffmpeg has no {encoder} encoder, so {codec} degradation "
            f"cannot run on this machine")
    rgb = img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "PNG")
    with tempfile.TemporaryDirectory(prefix="mc_degrade_") as tmp:
        clip = Path(tmp) / "v.mp4"
        enc = subprocess.run([
            _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "image2pipe", "-c:v", "png", "-i", "-",
            "-frames:v", "1", "-c:v", encoder, "-crf", str(int(crf)),
            "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(clip),
        ], input=buf.getvalue(), capture_output=True)
        if enc.returncode != 0 or not clip.is_file():
            err = enc.stderr.decode("utf-8", "replace").strip()
            raise MediaError(f"{encoder} encode failed: {err}")
        dec = subprocess.run([
            _ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-i", str(clip), "-frames:v", "1", "-f", "image2", "-c:v", "png",
            "-",
        ], capture_output=True)
    if dec.returncode != 0 or not dec.stdout:
        err = dec.stderr.decode("utf-8", "replace").strip()
        raise MediaError(f"{encoder} decode failed: {err}")
    out = Image.open(io.BytesIO(dec.stdout)).convert("RGB")
    if out.size != rgb.size:
        # The even-dimension rounding above cost at most one row or column.
        out = out.resize(rgb.size, Image.LANCZOS)
    return out


_VTT_CUE = re.compile(
    r"^((?:\d+:)?\d{2}:\d{2}\.\d{3})\s*-->\s*((?:\d+:)?\d{2}:\d{2}\.\d{3})(.*)$"
)


def _vtt_seconds(stamp: str) -> float:
    parts = stamp.split(":")
    sec = float(parts[-1]) + int(parts[-2]) * 60
    return sec + (int(parts[-3]) * 3600 if len(parts) > 2 else 0)


def _vtt_stamp(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rest = divmod(ms, 3600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def shift_vtt(text: str, seconds: float) -> str:
    """Move every cue in a WebVTT document by ``seconds``.

    Cues that end at or before zero are dropped (they play before the video
    starts); one straddling zero is clamped. Cue settings after the timings and
    everything else in the file are left alone.
    """
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        m = _VTT_CUE.match(line.strip())
        if m:
            start = _vtt_seconds(m.group(1)) + seconds
            end = _vtt_seconds(m.group(2)) + seconds
            skipping = end <= 0
            if skipping:
                # Drop the cue's payload too, up to the next blank line.
                if out and out[-1] and not _VTT_CUE.match(out[-1].strip()):
                    out.pop()  # its cue identifier line
                continue
            out.append(f"{_vtt_stamp(start)} --> {_vtt_stamp(end)}{m.group(3)}")
            continue
        if skipping:
            if line.strip() == "":
                skipping = False
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def extract_subtitle_vtt(path: Path, stream_index: int) -> str:
    """Extract one subtitle stream (by absolute ffmpeg stream index) as WebVTT
    text, which is the only subtitle format an HTML5 ``<video>`` can render —
    embedded ASS/SRT tracks in an MKV/MP4 are otherwise invisible in the player.

    Edit lists are applied HERE rather than by ffmpeg. Its mov demuxer rebases
    an edited subtitle track so that the first sample surviving the edit starts
    at zero, which for a track whose first sample is the long empty gap before
    the first line moves every cue by the length of that gap — measured at
    11.13 s on a real file, i.e. wildly out of sync with the picture. Reading
    the raw media timestamps and applying the track's own ``elst`` offset gives
    the times a spec-conforming player shows, which is what the ``<video>``
    element's ``currentTime`` counts in.
    """
    edits = _mp4_track_edits(path)
    cmd = [_ffmpeg_exe(), "-hide_banner", "-loglevel", "error"]
    if edits is not None:  # an MP4/MOV — take the raw timeline, shift it below
        cmd += ["-ignore_editlist", "1"]
    cmd += ["-i", str(path), "-map", f"0:{int(stream_index)}", "-f", "webvtt", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise MediaError(f"subtitle extract failed on {path.name}: {err}")
    vtt = proc.stdout.decode("utf-8", "replace")
    shift = (edits or {}).get(int(stream_index), 0.0)
    return shift_vtt(vtt, shift) if shift else vtt


def keyframe_times(path: Path, limit_seconds: float | None = None) -> list[float]:
    """Every video keyframe's timestamp, from the container's packet index.

    Packets, not frames: `-show_packets` reads the index and never decodes, so
    this is cheap even on a feature-length film, where `-show_frames` would
    decode the lot. Best-effort — an empty list means "cannot tell", and the
    caller then re-encodes rather than guessing.
    """
    cmd = [
        _ffprobe_exe(), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0",
    ]
    if limit_seconds is not None:
        cmd += ["-read_intervals", f"%{limit_seconds + 1:.3f}"]
    cmd.append(str(path))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    out: list[float] = []
    for line in proc.stdout.splitlines():
        ts, _, flags = line.partition(",")
        if "K" not in flags:
            continue
        try:
            out.append(float(ts))
        except ValueError:
            continue
    out.sort()
    return out


def _near(values: list[float], t: float, tol: float) -> bool:
    return any(abs(v - t) <= tol for v in values)


def cuts_are_keyframe_aligned(path: Path, cuts: list[tuple[float, float]],
                              tol: float) -> bool:
    """Can these cuts be taken WITHOUT re-encoding?

    Only when every range starts on a keyframe. A copy always starts at one —
    ffmpeg cannot begin a stream mid-GOP — so a start that is not one is
    silently moved back to the previous keyframe, and the saved video then
    begins somewhere the person did not choose. Avoiding a re-encode is worth
    a lot; it is not worth shifting a cut behind their back.
    """
    if not cuts:
        return False
    keys = keyframe_times(path)
    if not keys:
        return False
    return all(_near(keys, a, tol) for a, _ in cuts)


def _progress_seconds(line: str) -> float | None:
    """How far ffmpeg has got, in seconds, from one `-progress` line.

    `out_time_us` and `out_time` only. **NOT `out_time_ms`**, which despite its
    name carries MICROseconds — a long-standing ffmpeg quirk, and reading it as
    milliseconds makes every render report 100% within a second of starting,
    which is exactly what the progress bar did until this said so.
    """
    key, _, value = line.strip().partition("=")
    value = value.strip()
    if key == "out_time_us":
        try:
            n = float(value)
        except ValueError:
            return None
        return n / 1_000_000.0 if n >= 0 else None
    if key == "out_time":
        # `HH:MM:SS.microseconds`, and "N/A" before the first frame lands.
        parts = value.split(":")
        if len(parts) != 3:
            return None
        try:
            h, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            return None
        total = h * 3600 + m * 60 + sec
        return total if total >= 0 else None
    return None


def run_ffmpeg_progress(cmd: list[str], total_seconds: float, *,
                        on_progress=None, should_cancel=None) -> None:
    """Run an ffmpeg command, reporting progress and honouring a cancel.

    `-progress pipe:1` makes ffmpeg emit `key=value` lines as it goes, which is
    the only honest source of "how far in" — the alternative is parsing the
    human-readable status line it writes to stderr, whose format is not a
    contract. `should_cancel` is polled between those lines and the process is
    killed, so a cancelled render stops within a second rather than at the end.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        bufsize=1,
    )
    canceled = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if should_cancel is not None and should_cancel():
                canceled = True
                proc.kill()
                break
            done = _progress_seconds(line)
            if done is not None and on_progress is not None and total_seconds > 0:
                on_progress(max(0.0, min(1.0, done / total_seconds)))
    finally:
        err = ""
        try:
            if proc.stderr is not None:
                err = proc.stderr.read() or ""
        except Exception:  # noqa: BLE001
            err = ""
        proc.wait()
    if canceled:
        raise Canceled("render canceled")
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg failed: {err.strip()[-600:]}")


#: DO NOT CARRY THE SOURCE'S CHAPTERS INTO A CUT.
#:
#: ffmpeg copies chapters from the first input that has them unless told
#: otherwise, and the mov muxer writes them as a `text` DATA TRACK spanning the
#: whole source. `-map` does not touch it — it is metadata, not a stream being
#: selected — so a 1.5 second cut of a two-hour film came out with a 3763
#: second data track in it, and a `<video>` element takes its duration from the
#: LONGEST track: the library said 1.5 s (ffprobe's `format.duration` is right)
#: and the player showed over an hour.
#:
#: They would be wrong even if they were harmless: chapter marks name positions
#: in the SOURCE, and a cutlist has moved every one of them.
_NO_CHAPTERS = ("-map_chapters", "-1")


def render_cutlist(path: Path, out_path: Path, plan, duration: float,
                   width: int, height: int, audio_stream: int | None, *,
                   on_progress=None, should_cancel=None) -> Path:
    """Assemble `plan.cuts` of `path` (with the plan's transforms) into
    `out_path`.

    Two paths, and which one runs is decided by the plan, never guessed: a plan
    that touches no pixel AND whose cuts all start on a keyframe is assembled
    by COPYING the source's compressed frames (seconds, whatever the length);
    anything else is re-encoded through the filter graph, which is what makes a
    cut frame-accurate. See `cuts_are_keyframe_aligned` for why the second
    condition is not negotiable.
    """
    from . import videoedit

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cuts = plan.cuts
    has_audio = audio_stream is not None
    total = videoedit.total_duration(cuts)
    fps = None
    try:
        info = probe_video(path)
        fps = info.frame_rate
    except Exception:  # noqa: BLE001
        fps = None
    tol = (1.0 / fps) if fps else 0.04

    # A GAP cannot be copied: there are no compressed frames to copy, since
    # the picture and the silence do not exist in the source. It has to be
    # generated, so a plan holding one always re-encodes — stated here rather
    # than left to `cuts_are_keyframe_aligned`, which would answer about
    # timestamps that mean something else for a gap.
    if (not videoedit.has_gaps(cuts) and not plan.transforms_picture
            and cuts_are_keyframe_aligned(path, cuts, tol)):
        return _copy_cuts(path, out_path, cuts, total, audio_stream,
                          on_progress=on_progress, should_cancel=should_cancel)

    graph = videoedit.filter_complex(cuts, width, height, plan, audio_stream,
                                     fps=fps)
    cmd = [
        _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-progress", "pipe:1", "-nostats",
        "-i", str(path), *_NO_CHAPTERS, "-filter_complex", graph,
        "-map", "[vout]",
    ]
    if has_audio:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    run_ffmpeg_progress(cmd, total, on_progress=on_progress,
                        should_cancel=should_cancel)
    return out_path


def _copy_cuts(path: Path, out_path: Path, cuts, total: float,
               audio_stream: int | None, *,
               on_progress=None, should_cancel=None) -> Path:
    """The no-re-encode path: copy each range, then concat the pieces.

    One range is one command and no concat at all. Several go through the
    concat DEMUXER (a list of files) rather than the concat filter, because the
    filter decodes — which is the thing this whole path exists to avoid.
    """
    # WHICH STREAMS, said out loud. A bare `-c copy` leaves the choice to
    # ffmpeg's own stream selection, which takes the audio track with the MOST
    # CHANNELS — so a film with a stereo original and a 5.1 dub came out with
    # the dub whatever the container marked default.
    maps = ["-map", "0:v:0"]
    if audio_stream is not None:
        maps += ["-map", f"0:a:{audio_stream}"]
    if len(cuts) == 1:
        a, b = cuts[0]
        cmd = [
            _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-progress", "pipe:1", "-nostats",
            "-ss", f"{a:.6f}", "-to", f"{b:.6f}", "-i", str(path),
            *_NO_CHAPTERS, *maps,
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart", str(out_path),
        ]
        run_ffmpeg_progress(cmd, total, on_progress=on_progress,
                            should_cancel=should_cancel)
        return out_path
    with tempfile.TemporaryDirectory(prefix="mc_cut_") as td:
        tmp = Path(td)
        parts: list[Path] = []
        for i, (a, b) in enumerate(cuts):
            part = tmp / f"{i:04d}{out_path.suffix or '.mp4'}"
            cmd = [
                _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{a:.6f}", "-to", f"{b:.6f}", "-i", str(path),
                *_NO_CHAPTERS, *maps,
                "-c", "copy", "-avoid_negative_ts", "make_zero", str(part),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise MediaError(f"ffmpeg copy failed: {proc.stderr.strip()[-400:]}")
            if should_cancel is not None and should_cancel():
                raise Canceled("render canceled")
            if on_progress is not None and cuts:
                on_progress((i + 1) / len(cuts))
            parts.append(part)
        listing = tmp / "parts.txt"
        # ffconcat quoting: a single quote inside a path is escaped by closing
        # the quoted run, escaping the quote, and reopening it.
        lines = ["file '" + str(p).replace("'", "'\\''") + "'" for p in parts]
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [
            _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-progress", "pipe:1", "-nostats",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", "-movflags", "+faststart", str(out_path),
        ]
        run_ffmpeg_progress(cmd, total, on_progress=on_progress,
                            should_cancel=should_cancel)
    return out_path


def extract_clip(path: Path, start: float, end: float, out_path: Path) -> Path:
    """Re-encode ``[start, end]`` seconds of ``path`` into ``out_path`` (mp4)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(path), *_NO_CHAPTERS,
        "-ss", f"{max(0.0, start):.3f}", "-to", f"{end:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg clip failed on {path.name}: {proc.stderr.strip()}")
    return out_path


# ---- archives ----

def _member_dest(tmp: Path, name: str) -> Optional[Path]:
    """Where to extract an archive member, confined to ``tmp``.

    Archives come from third parties, and ``tmp / name`` trusts the name: a
    member called ``../../x`` walks out of the temp dir, and an absolute one
    replaces it outright (``Path.__truediv__`` discards the left side for an
    absolute right). Mirror ``ZipFile.extract``'s sanitization instead — drop
    any root and every ``..`` component — so a hostile name lands harmlessly
    inside ``tmp``. None for a name with nothing left (all slashes and dots).
    """
    parts = [p for p in PurePosixPath(name.replace("\\", "/")).parts
             if p not in ("/", "..", ".")]
    return tmp.joinpath(*parts) if parts else None


@contextlib.contextmanager
def extract_archive(path: Path):
    """Extract every member of an archive into a temporary directory and
    yield the list of ``(inner_name, extracted_path)``; the directory (and
    the paths) live until the ``with`` block ends.

    The list form — everything extracted first — is what lets a caller
    HASH MEMBERS AHEAD on a pool (`importer.Importer._archive_members`):
    a generator that extracted member by member deleted its directory the
    moment it was exhausted, which a look-ahead reaches while the last
    members are still waiting to be imported.
    """
    ext = ext_of(path.name)
    with tempfile.TemporaryDirectory(prefix="mc_arc_") as td:
        tmp = Path(td)
        members: list[tuple[str, Path]] = []
        if ext in ("zip", "cbz") or zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    dest = _member_dest(tmp, info.filename)
                    if dest is None:
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(dest, "wb") as out:
                        out.write(src.read())
                    members.append((info.filename, dest))
        elif ext == "cbr":
            try:
                import rarfile
            except ImportError as exc:  # pragma: no cover - optional dep
                raise MediaError(
                    "cbr/rar support requires the 'rarfile' package and an "
                    "'unrar'/'bsdtar' binary"
                ) from exc
            with rarfile.RarFile(path) as rf:
                for info in rf.infolist():
                    if info.is_dir():
                        continue
                    dest = _member_dest(tmp, info.filename)
                    if dest is None:
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with rf.open(info) as src, open(dest, "wb") as out:
                        out.write(src.read())
                    members.append((info.filename, dest))
        elif ext == "7z":
            import py7zr

            with py7zr.SevenZipFile(path, mode="r") as zf:
                zf.extractall(path=tmp)
            for member in sorted(tmp.rglob("*")):
                if member.is_file():
                    members.append((str(member.relative_to(tmp)), member))
        else:
            raise MediaError(f"unsupported archive: {path.name}")
        yield members


def iter_archive(path: Path) -> Iterator[tuple[str, Path]]:
    """Yield ``(inner_name, extracted_temp_path)`` for each archive member.

    Members are extracted to a temp dir the caller is responsible for treating
    as short-lived (paths become invalid once the generator's tempdir is gone).
    The generator spelling of `extract_archive`.
    """
    with extract_archive(path) as members:
        yield from members


def is_comic(path: Path) -> bool:
    """True for comic-book archives (cbz/cbr) whose pages form a sequence."""
    return ext_of(path.name) in COMIC_EXTS
