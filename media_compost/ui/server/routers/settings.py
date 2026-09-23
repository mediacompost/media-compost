"""User-adjustable app settings, persisted in the library's key/value store.

Covers per-model local path overrides and a per-model offline (local-files-only)
flag. The Hugging Face access token is deliberately NOT persisted here — it is
read from the environment, and can be set into the current process environment
(only for this run) via the /hf-token endpoint."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from media_compost.hub import hf
from media_compost.db import get_setting, set_setting
from ...plugins import registry
from ...plugins.impl import florence
from media_compost import prefs as prefs_mod
from media_compost.prefs import (  # noqa: F401  (re-exported for existing importers)
    MODEL_PATHS, PREFS, PREFS_GLOBAL, SAVED_SEARCHES, TAG_SET_ORDER,
    read_face_match_threshold, read_tag_prefix,
)
from media_compost.prefs import read_json as _read_json
from ..deps import get_current_user, get_session
from ..schemas import (RequestModel, AppSettings, SavedSearch,
                       TagSetOrderIn, TagSetOrderOut)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Allowed date-display patterns (first entry is the default). Tokens: YYYY/YY
# (year), MMMM/MMM (month name), MM/M (month number), DD/D (day). Kept in sync
# with the frontend's DATE_FORMAT_OPTIONS.
_DATE_FORMATS = (
    "D MMM YYYY",     # 9 Jul 2026
    "MMM D, YYYY",    # Jul 9, 2026
    "D MMMM YYYY",    # 9 July 2026
    "MMMM D, YYYY",   # July 9, 2026
    "M/D/YYYY",       # 7/9/2026
    "MM/DD/YYYY",     # 07/09/2026
    "D/M/YYYY",       # 9/7/2026
    "DD/MM/YYYY",     # 09/07/2026
    "D.M.YYYY",       # 9.7.2026
    "DD.MM.YYYY",     # 09.07.2026
    "YYYY-MM-DD",     # 2026-07-09
    "YYYY/MM/DD",     # 2026/07/09
)

# The setting KEYS and the library-global readers live in `media_compost.prefs`
# (imported above and re-exported from here, so existing callers are unchanged):
# core reads them — `facevec` needs the face threshold, the subject/place/event
# routers need the tag prefixes — and a core module importing from a router
# points the dependency arrow the wrong way round. Writing them is still this
# router's job, since it validates the whole AppSettings payload.

# Personal settings are stored per user so multiple people sharing one library
# don't clobber each other's language/date/search choices. Anonymous ("") keeps
# the un-suffixed base key, so a library upgraded from the single-user era keeps
# working unchanged.
def user_key(base: str, user: str) -> str:
    return base if not user else f"{base}:{user}"

# Allowed double-click behaviors per media kind (first entry is the default).
_DBLCLICK_IMAGE = ("quicklook", "annotate", "none", "editor")
# Videos annotate too (timed tags are the annotator's video half) — the
# Settings dropdown has always offered it, and this list silently reverting
# the choice to Quick Look on save was the bug.
_DBLCLICK_VIDEO = ("quicklook", "annotate", "editor", "none")

# Selectable Florence-2 checkpoints (first entry is the default). Includes both
# the fine-tuned (…_ft) and plain base/large checkpoints.
_FLORENCE_MODELS = ("florence2_base", "florence2_large",
                    "florence2_base_plain", "florence2_large_plain")

# Supported UI languages (first entry is the default).
_LANGUAGES = ("en", "de", "ja", "zh-Hans", "ko", "es", "pt-BR", "fr")

# Environment variables that carry a Hugging Face token.
_TOKEN_ENV = hf.TOKEN_ENV


def env_token() -> str:
    """The Hugging Face token this machine can use, or "" (see `hf.token`)."""
    return hf.token()


def read_model_paths(s: Session) -> dict[str, str]:
    """Known families with a non-empty local path override."""
    return {k: v for k, v in _read_json(s, MODEL_PATHS).items()
            if registry.source_for(k) is not None and v}


def _read_global_florence(s: Session) -> str:
    """The shared active Florence checkpoint (global, not per-user). Falls back to
    a value left in a legacy single-user ``prefs`` blob so an existing selection
    survives the upgrade until settings are next saved."""
    flo = _read_json(s, PREFS_GLOBAL).get("florence_model")
    if flo not in _FLORENCE_MODELS:
        flo = _read_json(s, PREFS).get("florence_model")
    return flo if flo in _FLORENCE_MODELS else _FLORENCE_MODELS[0]


def _read_prefs(s: Session, user: str) -> dict:
    prefs = _read_json(s, user_key(PREFS, user))
    glob = _read_json(s, PREFS_GLOBAL)
    img = prefs.get("dblclick_image")
    vid = prefs.get("dblclick_video")
    fmt = prefs.get("date_format")
    lang = prefs.get("language")
    flo = _read_global_florence(s)
    # Keep the running process's active-Florence selection in sync with the pref
    # (this GET runs on every app load, so the worker/menus reflect the choice).
    florence.set_active(flo)
    return {
        "dblclick_image": img if img in _DBLCLICK_IMAGE else _DBLCLICK_IMAGE[0],
        "dblclick_video": vid if vid in _DBLCLICK_VIDEO else _DBLCLICK_VIDEO[0],
        "florence_model": flo,
        "language": lang if lang in _LANGUAGES else _LANGUAGES[0],
        "date_format": fmt if fmt in _DATE_FORMATS else _DATE_FORMATS[0],
        "time_24h": bool(prefs.get("time_24h", False)),
        # HIDING UNREADY ACTIONS IS THE WHOLE SERVER'S (owner 2026-09). It
        # was per user for a while, beside a "hide the Faces tab" that was
        # server-wide, which made the same kind of switch mean two different
        # things. It reads from the GLOBAL blob, so whatever a person had
        # stored under their own key is left behind, which costs a default
        # and nothing else. (The Faces switch went when Faces became a page
        # of the Tags tab; its stored value is dropped by the next save,
        # which writes the blob whole.)
        "hide_unready_actions": bool(glob.get("hide_unready_actions", False)),
        "subject_tag_prefix": read_tag_prefix(s, "subject"),
        "place_tag_prefix": read_tag_prefix(s, "place"),
        "event_tag_prefix": read_tag_prefix(s, "event"),
        "face_match_threshold": read_face_match_threshold(s),
        "watermark_tag": prefs_mod.read_watermark_tag(s),
        "text_tag": prefs_mod.read_text_tag(s),
    }


def _current(s: Session, user: str) -> AppSettings:
    return AppSettings(model_paths=read_model_paths(s), **_read_prefs(s, user))


def apply_runtime_prefs(s: Session) -> None:
    """Sync process-level runtime state (the active Florence checkpoint) from the
    persisted global pref. Called from the ML router so the action menus/worker
    reflect the choice even before the frontend fetches settings."""
    florence.set_active(_read_global_florence(s))


@router.get("", response_model=AppSettings)
def get_settings(s: Session = Depends(get_session),
                 user: str = Depends(get_current_user)):
    return _current(s, user)


@router.put("", response_model=AppSettings)
def update_settings(body: AppSettings, s: Session = Depends(get_session),
                    user: str = Depends(get_current_user)):
    # Global (deployment-level) settings: model path overrides + Florence
    # checkpoint (the shared out-of-process worker can only load one at a time).
    paths = {
        k: v.strip()
        for k, v in (body.model_paths or {}).items()
        if registry.source_for(k) is not None and v and v.strip()
    }
    set_setting(s, MODEL_PATHS, json.dumps(paths))
    flo = body.florence_model if body.florence_model in _FLORENCE_MODELS else _FLORENCE_MODELS[0]
    set_setting(s, PREFS_GLOBAL, json.dumps({
        "florence_model": flo,
        # Lowercase: a prefix is the front of a tag name, and every tag this
        # app mints from a typed name is lowercase (see `read_tag_prefix`).
        "subject_tag_prefix": (body.subject_tag_prefix or "").strip().lower(),
        "place_tag_prefix": (body.place_tag_prefix or "").strip().lower(),
        "event_tag_prefix": (body.event_tag_prefix or "").strip().lower(),
        "face_match_threshold": float(body.face_match_threshold),
        # Server-wide — see the comment in `_read_prefs`.
        "hide_unready_actions": bool(body.hide_unready_actions),
        # Tag NAMES, so they take the tag fields' normalization on the way in
        # (lowercase; the readers normalize again on the way out, so a value
        # an older build stored still reads right without a re-save).
        "watermark_tag": (body.watermark_tag or "").strip().lower(),
        "text_tag": (body.text_tag or "").strip().lower(),
    }))
    # Personal (per-user) settings.
    img = body.dblclick_image if body.dblclick_image in _DBLCLICK_IMAGE else _DBLCLICK_IMAGE[0]
    vid = body.dblclick_video if body.dblclick_video in _DBLCLICK_VIDEO else _DBLCLICK_VIDEO[0]
    fmt = body.date_format if body.date_format in _DATE_FORMATS else _DATE_FORMATS[0]
    lang = body.language if body.language in _LANGUAGES else _LANGUAGES[0]
    set_setting(s, user_key(PREFS, user), json.dumps({
        "dblclick_image": img, "dblclick_video": vid,
        "language": lang, "date_format": fmt, "time_24h": bool(body.time_24h),
    }))
    florence.set_active(flo)
    s.flush()
    # Re-read from the flushed state so the response can never echo pre-write
    # values (which would make the settings UI revert the change it just saved).
    s.expire_all()
    return _current(s, user)


def read_saved_searches(s: Session, user: str) -> list[SavedSearch]:
    raw = get_setting(s, user_key(SAVED_SEARCHES, user), "")
    try:
        data = json.loads(raw) if raw else []
    except ValueError:
        data = []
    out: list[SavedSearch] = []
    if isinstance(data, list):
        for x in data:
            if isinstance(x, dict) and isinstance(x.get("name"), str):
                out.append(SavedSearch(
                    name=x["name"], query=str(x.get("query", ""))
                ))
    return out


@router.get("/saved-searches", response_model=list[SavedSearch])
def get_saved_searches(s: Session = Depends(get_session),
                       user: str = Depends(get_current_user)):
    return read_saved_searches(s, user)


def read_tag_set_order(s: Session, user: str) -> list[str]:
    """The caller's preferred order of tag sets — which set's description the
    `?` popover shows first. Stored as the keys the user has ranked; read
    back with unknown keys dropped and every enabled set appended in its
    global position order, so the answer always names every set there is."""
    from media_compost.ops import tagsets as tagsets_ops

    raw = get_setting(s, user_key(TAG_SET_ORDER, user), "")
    try:
        data = json.loads(raw) if raw else []
    except ValueError:
        data = []
    keys = [k for k in data if isinstance(k, str)] if isinstance(data, list) else []
    have = [ts.key for ts in tagsets_ops.all_sets(s) if ts.enabled]
    out = [k for k in dict.fromkeys(keys) if k in have]
    out += [k for k in have if k not in out]
    return out


@router.get("/tag-set-order", response_model=TagSetOrderOut)
def get_tag_set_order(s: Session = Depends(get_session),
                      user: str = Depends(get_current_user)):
    return TagSetOrderOut(keys=read_tag_set_order(s, user))


@router.put("/tag-set-order", response_model=TagSetOrderOut)
def put_tag_set_order(body: TagSetOrderIn, s: Session = Depends(get_session),
                      user: str = Depends(get_current_user)):
    clean = [k for k in dict.fromkeys(body.keys) if k.strip()]
    set_setting(s, user_key(TAG_SET_ORDER, user), json.dumps(clean))
    s.flush()
    return TagSetOrderOut(keys=read_tag_set_order(s, user))


@router.put("/saved-searches", response_model=list[SavedSearch])
def put_saved_searches(body: list[SavedSearch],
                       s: Session = Depends(get_session),
                       user: str = Depends(get_current_user)):
    """Replace the caller's saved-search list. Names are kept as-is (order
    preserved); entries with a blank name are dropped. Queries are stored
    opaquely."""
    clean = [{"name": x.name, "query": x.query} for x in body if x.name.strip()]
    set_setting(s, user_key(SAVED_SEARCHES, user), json.dumps(clean))
    s.flush()
    return [SavedSearch(**x) for x in clean]


class HfTokenBody(RequestModel):
    token: str = ""


@router.get("/hf-token")
def hf_token_status():
    """Whether a Hugging Face token is available in the environment."""
    return {"token_available": bool(env_token())}


@router.put("/hf-token")
def set_hf_token(body: HfTokenBody):
    """Set (or clear) the Hugging Face token in the *current process*
    environment. It is never written to disk, so it lasts only until the server
    restarts — a launch-time env var is the durable way to set it."""
    token = (body.token or "").strip()
    if token:
        for name in _TOKEN_ENV:
            os.environ[name] = token
    else:
        for name in _TOKEN_ENV:
            os.environ.pop(name, None)
    return {"token_available": bool(env_token())}
