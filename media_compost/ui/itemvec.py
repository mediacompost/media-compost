"""Item feature vectors — the storage layer under the tag-batch session.

`facevec.py`'s little sibling: pack/unpack between the DB's raw bytes and
numpy, and a bulk loader that turns item ids into an L2-normalized float32
matrix. No faiss and no ANN — the session scores a pool with one matmul, so
there is nothing to index.

The DISK dtype is float16 (half the bytes; the vectors are unit-norm ViT
features, for which fp16's ~3 decimal digits are far below the noise floor of
what a cosine ordering can care about) and the RAM dtype is float32 — numpy's
fp16 matmul is slower, not smaller, once loaded.

A row only COUNTS while it describes the item's active file
(`ItemEmbedding.file_id == item.active_file_id`) — the OCR per-active-file
rule: an edited picture reads as unindexed rather than answering for pixels
it no longer shows.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from sqlalchemy import select

from ..db import Item, ItemEmbedding, chunked

#: Every embedder the tag-batch session knows: plugin model id → (space,
#: dim). Two spaces side by side is the FaceEmbedding shape — rows keyed on
#: (item, model/space), never compared across spaces. The space STRING
#: carries every constant of its recipe (embedder, dim, dtype,
#: preprocessing) — a changed recipe is a NEW string and a re-index, never
#: a silent mix.
EMBEDDERS: dict[str, tuple[str, int]] = {
    "dinov2_small": ("dinov2s-v1", 384),
    "clip_vit_b32": ("clipb32-v1", 512),
}

#: The default space — dinov2's, which predates the choice; `SPACE`/`DIM`
#: keep naming it for the callers and tests written against one space.
SPACE, DIM = EMBEDDERS["dinov2_small"]

#: Per /next request, at most this many candidates are scored (a rotating
#: sample covers larger pools across successive fetches).
SCORE_CAP = 20_000

#: Per tag and side, at most this many labeled examples feed the fit.
LABEL_CAP = 512


def pack(vec) -> bytes:
    """Vector → the DB's raw float16 bytes."""
    return np.asarray(vec, dtype=np.float16).tobytes()


def unpack(raw: Optional[bytes], dim: int) -> Optional[np.ndarray]:
    """DB bytes → a unit-norm float32 vector, or None for anything that is
    not a well-formed vector of ``dim`` (a truncated blob, a zero vector) —
    the caller treats those rows as absent rather than scoring garbage."""
    if not raw or dim <= 0:
        return None
    v = np.frombuffer(raw, dtype=np.float16)
    if v.shape[0] != dim:
        return None
    v = v.astype(np.float32)
    n = float(np.linalg.norm(v))
    if n <= 0 or not np.isfinite(n):
        return None
    return v / n


def load_matrix(s, item_ids, space: str = SPACE,
                ) -> tuple[list[int], np.ndarray]:
    """The vectors of ``item_ids`` in ``space`` as (ids, X) — ids in the rows'
    order, X (len(ids), dim) float32 L2-normalized. Items without a CURRENT
    row (none at all, another file's, or malformed bytes) are simply absent
    from the answer; the caller decides what absence means (they queue behind
    scored candidates).
    """
    ids: list[int] = []
    rows: list[np.ndarray] = []
    wanted = [int(i) for i in item_ids]
    for chunk in chunked(wanted):
        got = s.execute(
            select(ItemEmbedding.item_id, ItemEmbedding.file_id,
                   ItemEmbedding.dim, ItemEmbedding.vector,
                   Item.active_file_id)
            .join(Item, Item.id == ItemEmbedding.item_id)
            .where(ItemEmbedding.item_id.in_(chunk),
                   ItemEmbedding.model == space)
        ).all()
        for iid, fid, dim, raw, active in got:
            if fid is None or fid != active:
                continue  # stale — computed from a file no longer active
            v = unpack(raw, dim)
            if v is None:
                continue
            ids.append(int(iid))
            rows.append(v)
    if not rows:
        dim = next((d for sp, d in EMBEDDERS.values() if sp == space), DIM)
        return [], np.empty((0, dim), dtype=np.float32)
    return ids, np.stack(rows).astype(np.float32)


def indexed_ids(s, item_ids, space: str = SPACE) -> set[int]:
    """Which of ``item_ids`` carry a CURRENT vector in ``space`` — the
    coverage probe and the /index endpoint's skip-done rule, without loading
    a single blob."""
    out: set[int] = set()
    wanted = [int(i) for i in item_ids]
    for chunk in chunked(wanted):
        got = s.execute(
            select(ItemEmbedding.item_id)
            .join(Item, Item.id == ItemEmbedding.item_id)
            .where(ItemEmbedding.item_id.in_(chunk),
                   ItemEmbedding.model == space,
                   ItemEmbedding.file_id.is_not(None),
                   ItemEmbedding.file_id == Item.active_file_id)
        ).scalars().all()
        out.update(int(i) for i in got)
    return out
