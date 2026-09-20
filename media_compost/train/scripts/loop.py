"""The real training loop (runs in the dedicated training venv).

Generic across engines: an engine (``engines/<name>.py``, named by the
manifest's ``model.engine``) owns everything model-specific — loading,
text encoding, the denoising forward/backward, checkpoint weights, sample
generation — while this loop owns the schedule: weighted/bucketed batches,
per-visit caption composition, latent caching, optimizer/scheduler stepping,
pause/cancel checks, checkpoints and test samples.

Heavy imports (torch/diffusers/peft) happen inside functions so ``--simulate``
runs never touch them.
"""

from __future__ import annotations

import importlib
import json
import math
import os
import random
import threading
import time
from pathlib import Path

import collections

import atomicio
import compose
import ema as ema_mod
import images
import latentio
import membudget
import profiling
from train import JobIO, PauseRequested


# ---- device / dtype ---------------------------------------------------------


def pick_device():
    """cuda > mps > cpu — unless the manager pinned the run to a device
    (``MEDIA_COMPOST_TRAIN_DEVICE``; a ``cuda:N`` pin arrives as
    ``CUDA_VISIBLE_DEVICES=N`` plus ``"cuda"``, so this process only ever
    sees its own card). A pin that doesn't exist on this machine is a hard
    error: failing loudly beats quietly training on the CPU for a week."""
    import torch

    want = os.environ.get("MEDIA_COMPOST_TRAIN_DEVICE", "")
    if want:
        if want.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                "this job is set to a CUDA GPU, but none is available here")
        if want == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError(
                "this job is set to the Apple GPU (MPS), "
                "which is not available here")
        return want
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def pick_dtype(precision: str, device: str):
    """bf16 by default; MPS gets probed and falls back to fp32 — never fp16
    on MPS (known NaN factory)."""
    import torch

    if device == "mps":
        if precision == "bf16" and _mps_supports_bf16():
            return torch.bfloat16
        return torch.float32
    if precision == "bf16":
        return torch.bfloat16
    if precision == "fp16":
        return torch.float16
    return torch.float32


def _mps_supports_bf16() -> bool:
    import torch

    try:
        t = torch.zeros(2, dtype=torch.bfloat16, device="mps")
        (t + t).sum().item()
        return True
    except Exception:  # noqa: BLE001 - probe failure = unsupported
        return False


# ---- LR schedule --------------------------------------------------------------


def lr_lambda(kind: str, warmup: int, total_fn):
    """``total_fn`` is a callable so an extended run (set_steps) re-stretches
    the decay instead of finishing the tail at LR 0."""

    def fn(step: int) -> float:
        total = total_fn()
        if warmup and step < warmup:
            return step / max(1, warmup)
        if kind == "cosine":
            p = (step - warmup) / max(1, total - warmup)
            return 0.5 * (1.0 + math.cos(math.pi * min(1.0, p)))
        if kind == "linear":
            p = (step - warmup) / max(1, total - warmup)
            return max(0.0, 1.0 - p)
        return 1.0  # constant / constant_with_warmup

    return fn


def _frame_ref(io, path: str) -> str:
    """A video frame's path relative to ``<job>/frames``, or "".

    The inspector asks for it back by this name; anything that is not under
    the job's own frames folder answers with nothing rather than a path the
    route would have to judge.
    """
    try:
        return Path(path).relative_to(io.dir / "frames").as_posix()
    except (TypeError, ValueError):
        return ""


# ---- a picture that is not there any more ----------------------------------


def drop_entries(manifest: dict, dead: set[int]) -> None:
    """Take entries out of everything this run DRAWS from, leaving `items`
    itself alone.

    Every pool and both validation lists name an entry by its POSITION in
    ``items``, so removing the entry itself would renumber the rest and hand
    the run somebody else's pixels under these prompts. The entry stays where
    it is, marked, and is simply in nothing: the same mechanism a held-out
    validation image already rides on.

    Every list here is shortened IN PLACE: the run reads the pools and the
    two validation lists into locals of its own long before the last of these
    calls, and a fresh list would leave those holding the entries this one
    just dropped.
    """
    items = manifest.get("items") or []
    for i in dead:
        items[i]["missing"] = True
    groups = manifest.get("groups") or []
    for g in groups:
        g["items"][:] = [j for j in g.get("items") or [] if j not in dead]
    groups[:] = [g for g in groups if g["items"]]
    for key in ("val_items", "stable_items"):
        if manifest.get(key):
            manifest[key][:] = [j for j in manifest[key] if j not in dead]


def vanished_entries(manifest: dict) -> list[int]:
    """Entries whose source file is not on disk any more.

    A manifest is a list of stored library paths and it is built once, while
    the library goes on being used: merge two files of an item or delete one
    and the file this run was told to train on is gone. The run does not
    depend on it — one picture of several hundred — so it is dropped with a
    line saying so, where opening it raised a FileNotFoundError that ended
    the job. A resume rebuilds the manifest for the same reason, and this is
    what covers the window between the two: the rest of the run, during which
    the library is still being worked in.
    """
    return [i for i, it in enumerate(manifest.get("items") or [])
            if not os.path.exists(str(it.get("path") or ""))]


def _say_dropped(items: list[dict], dead: list[int], why: str) -> None:
    names = ", ".join(Path(str(items[i].get("path") or "")).name
                      for i in dead[:3])
    more = "" if len(dead) <= 3 else f", +{len(dead) - 3} more"
    print(f"skipping {len(dead)} training image(s) — {why} ({names}{more})",
          flush=True)


# ---- latent cache --------------------------------------------------------------


class LatentSource:
    """Per-visit training latents: cached on disk (cropped in latent space) or
    encoded fresh from pixels each visit when caching is off.

    With ``alpha_mask`` on it also produces a per-latent-cell weight map from
    the image's alpha channel, travelling with the latent through caching,
    flipping and cropping so the weights always line up with the pixels."""

    def __init__(self, engine, io: JobIO, manifest: dict, buckets, cfg: dict,
                 rng: random.Random):
        self.engine = engine
        self.io = io
        self.items = manifest["items"]
        self.buckets = buckets
        self.random_crop = bool(cfg.get("random_crop", True))
        self.flip_p = float(cfg.get("flip_p", 0.0))
        # Lower-cased once: an item carrying any of these is never mirrored.
        self.no_flip_tags = {str(t).strip().lower()
                             for t in (cfg.get("no_flip_tags") or []) if str(t).strip()}
        self.cache = bool(cfg.get("cache_latents", True))
        self.alpha_mask = bool(cfg.get("alpha_mask", False))
        # What a fully transparent cell still counts for. 1.0 would be the
        # unmasked loss, so the whole feature turns itself off there.
        self.bg_weight = float(cfg.get("alpha_bg_weight", 0.1))
        if self.bg_weight >= 1.0:
            self.alpha_mask = False
        # MASKED REGIONS: what a cell inside an entry's `mask_boxes` counts
        # for. Loss-only, like the alpha mask — the pixels still reach the
        # encoder, so the cached latents are the ordinary shared ones.
        self.box_weight = float(cfg.get("mask_loss_weight", 0.0) or 0.0)
        self.rng = rng
        self.dir = io.dir / "latents"

    def prepare(self, on_progress=None, on_missing=None) -> None:
        """Encode every item once (plus a flipped copy when flipping is on).

        `on_progress(done, total)` is called as it goes: this is the longest
        stretch of a run before the first step, and the app has nothing else
        to report from it.

        `on_missing(index)` is called for an item whose file cannot be read.
        Encoding a few hundred images takes minutes, and the library is in
        use throughout — so a picture deleted or merged away WHILE this pass
        runs is an ordinary thing to meet, and the caller takes it out of the
        run rather than losing the job to it.
        """
        if not self.cache:
            return
        import torch

        self.dir.mkdir(parents=True, exist_ok=True)
        total = len(self.items)
        for idx, it in enumerate(self.items):
            self.io.check_control()
            if on_progress is not None and (idx % 5 == 0 or idx == total - 1):
                on_progress(idx + 1, total)
            if it.get("missing"):
                continue  # already dropped from the run; nothing to encode
            flips = (False, True) if (self.flip_p > 0 and self.may_flip(idx)) \
                else (False,)
            for flipped in flips:
                path = self._path(idx, flipped)
                if path.exists():
                    continue  # already cached (this run, or an earlier job)
                try:
                    lat, mask = self._encode(it, flipped)
                except OSError as exc:
                    # The source went while this pass was running. One
                    # picture, and the run has the rest of them.
                    if on_missing is None:
                        raise
                    print(f"cannot read {it.get('path')}: {exc}", flush=True)
                    on_missing(idx)
                    break
                path.parent.mkdir(parents=True, exist_ok=True)
                # Write via a temp file: another job may be reading this same
                # shared cache entry while we fill it. Per-PID name, because
                # the manager runs jobs concurrently on distinct devices and
                # two runs caching the same entry would truncate each other's
                # .part mid-save and publish a torn latent (the same lesson
                # paths.write_json already carries).
                tmp = path.with_suffix(path.suffix + f".part{os.getpid()}")
                torch.save(self._blob(lat, mask), tmp)
                tmp.replace(path)

    @staticmethod
    def _blob(lat, mask):
        """One cache entry, ready for ``torch.save``.

        Both halves are fp16 and both are packed by ``latentio`` — see there
        for why compressed, why lossless and why level 1. The record is
        tensors and ints and strs, so it still loads under ``torch.load``'s
        ``weights_only`` default.
        """
        import torch

        def packed(t):
            rec = latentio.encode(t.to(torch.float16).cpu().numpy())
            # The payload rides as a uint8 TENSOR and never as `bytes`:
            # `torch.save` pickles at protocol 2, which stores bytes latin-1
            # escaped at ~1.5x, and that alone turned this whole change into
            # an 8.6% GROWTH on disk. latentio's docstring has the numbers.
            rec["z"] = torch.frombuffer(bytearray(rec["z"]), dtype=torch.uint8)
            return rec

        blob = {"lat": packed(lat)}
        if mask is not None:
            blob["mask"] = packed(mask)
        return blob

    @staticmethod
    def _read(path):
        """``(lat, mask)`` from a cache entry.

        A cache entry is DERIVED — delete one and it is made again — so there
        is one shape here and no reader for any other: the dict of packed
        records `_blob` writes.
        """
        import torch

        def unpacked(rec):
            # zlib wants a buffer and the entry holds a uint8 TENSOR, which
            # is what keeps the pickle from storing it as a latin-1 string
            # (see `_blob` and `latentio`).
            return torch.from_numpy(latentio.decode({**rec,
                                                     "z": rec["z"].numpy()}))

        blob = torch.load(path, map_location="cpu")
        lat, mask = blob["lat"], blob.get("mask")
        return unpacked(lat), None if mask is None else unpacked(mask)

    def may_flip(self, idx: int) -> bool:
        """Whether this item may be mirrored at all.

        Checked before the dice, and before caching a flipped latent — an
        image vetoed by a tag never needs one.

        TWO vetoes, and the entry's own comes first: `no_flip` is set by the
        manifest builder for a picture whose tags the LIBRARY marks that way
        (it resolves the meta tags; this process knows nothing about them),
        while `no_flip_tags` names tags outright and is read here.
        """
        if self.items[idx].get("no_flip"):
            return False
        if not self.no_flip_tags:
            return True
        tags = self.items[idx].get("tags") or []
        return not any(str(t).strip().lower() in self.no_flip_tags for t in tags)

    def _path(self, idx: int, flipped: bool):
        """Where this item's latent lives. The manifest points at the LIBRARY
        item's artifact folder (shared across jobs, keyed by file number, base
        model and bucket); jobs from before that fall back to a job-local
        file."""
        it = self.items[idx]
        shared = it.get("latent_path_flipped" if flipped else "latent_path")
        if shared:
            return Path(shared)
        return self.dir / (f"i{idx:05d}_f.pt" if flipped else f"i{idx:05d}.pt")

    def _open(self, path: str):
        """``(rgb, alpha)`` for one source file — alpha only when masking is on
        and the image actually has a transparent region."""
        from PIL import Image

        img = Image.open(path)
        if not self.alpha_mask:
            return img.convert("RGB"), None
        return images.split_alpha(img)

    def _encode(self, it: dict, flipped: bool):
        """VAE-encode the image resized to cover its bucket (uncropped),
        returning ``(latent, latent_mask_or_None)``."""
        from PIL import Image

        bw, bh = self.buckets[it["bucket"]]
        cw, ch = compose.cover_size(it["width"], it["height"], bw, bh)
        # The cover size has to divide into whole latent cells, or the engine
        # is handed an image its VAE (and, for FLUX.2, its 2x2 patchify)
        # cannot reshape. `latent_scale` is 8 for most models and 16 there.
        s = self.engine.latent_scale
        cw, ch = (cw // s) * s, (ch // s) * s
        size = (max(bw, cw), max(bh, ch))
        img, alpha = self._open(it["path"])
        img = img.resize(size, Image.LANCZOS)
        if alpha is not None:
            alpha = alpha.resize(size, Image.LANCZOS)
        if flipped:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
            if alpha is not None:
                alpha = alpha.transpose(Image.FLIP_LEFT_RIGHT)
        lat = self.engine.encode_image(img)
        return lat, self._mask_tensor(alpha, lat.shape[-1], lat.shape[-2])

    def _mask_tensor(self, alpha, tw: int, th: int):
        """Alpha at latent resolution as a (1, 1, th, tw) tensor.

        None only when this run isn't masking at all — an OPAQUE item in a
        masked run gets an all-ones mask, because it must still contribute its
        full loss and the cache entry has to keep the masked layout either way.
        """
        import torch

        if not self.alpha_mask:
            return None
        if alpha is None:
            return torch.ones((1, 1, th, tw), dtype=torch.float32)
        flat = images.latent_mask(alpha, tw, th)
        return torch.tensor(flat, dtype=torch.float32).view(1, 1, th, tw)

    def batch_latents(self, indices: list[int], bucket: tuple[int, int],
                      box_lists: list[list] | None = None,
                      record: list | None = None):
        """``(latents, weights)`` for one batch: stacked (b, c, h, w) latents
        and, when masking is on, a (b, 1, h, w) per-cell loss weight (else
        None). ``box_lists`` (parallel to ``indices``) carries the fractional
        bounding boxes of the tags in each visit's prompt — the crop keeps them
        mostly inside. When ``record`` is given, one
        ``{"flip", "crop":[x,y,w,h]}`` dict per visit is appended — the crop as
        a fraction of the ORIGINAL (un-flipped) image, for the data inspector."""
        import torch

        bw, bh = bucket
        s = self.engine.latent_scale
        lw, lh = bw // s, bh // s
        out, masks, boxms = [], [], []
        for pos, idx in enumerate(indices):
            boxes = box_lists[pos] if box_lists else []
            flipped = (self.flip_p > 0 and self.may_flip(idx)
                       and self.rng.random() < self.flip_p)
            if flipped and boxes:
                boxes = compose.flip_boxes(boxes)
            if self.cache:
                lat, mask = self._read(self._path(idx, flipped))
                _, _, ch_l, cw_l = lat.shape
                x, y = compose.crop_offset_for_boxes(
                    cw_l, ch_l, lw, lh, boxes, self.random_crop, self.rng
                )
                if record is not None:
                    record.append(self._crop_record(flipped, x, y, lw, lh, cw_l, ch_l))
                lat = lat[:, :, y:y + lh, x:x + lw]
                # The mask is stored at the same resolution as the latent, so
                # the very same window applies to it.
                if mask is not None:
                    mask = mask[:, :, y:y + lh, x:x + lw]
                # The crop was chosen in latent units, which is also the grid
                # the mask is built on — so the window maps one to one.
                boxm = self._box_mask(self.items[idx], flipped,
                                      x, y, lw, lh, cw_l, ch_l, lw, lh)
            else:
                lat, mask, boxm = self._encode_cropped(self.items[idx], bw, bh,
                                                       flipped, boxes, record)
            out.append(lat)
            masks.append(mask)
            boxms.append(boxm)
        dev = self.engine.device
        lats = torch.cat(out).to(dev, dtype=self.engine.dtype)
        weights = []
        for i, (mask, boxm) in enumerate(zip(masks, boxms)):
            w = None
            if self.alpha_mask:
                m = mask if mask is not None else torch.ones_like(out[i][:, :1])
                # Blend toward the background weight, so a fully transparent
                # cell still counts for `bg_weight` instead of vanishing from
                # the average.
                w = self.bg_weight + (1.0 - self.bg_weight) * m.to(torch.float32)
            if boxm is not None:
                # The two masks MULTIPLY where both apply: a watermark on a
                # transparent region is doubly not the picture.
                w = boxm if w is None else w * boxm
            weights.append(w)
        if all(w is None for w in weights):
            return lats, None
        full = [w if w is not None else torch.ones_like(out[i][:, :1],
                                                        dtype=torch.float32)
                for i, w in enumerate(weights)]
        return lats, torch.cat(full).to(dev, dtype=torch.float32)

    def _box_mask(self, it: dict, flipped: bool, x, y, w, h, cw, ch,
                  lw: int, lh: int):
        """One visit's masked-region weight map, or None when the entry has no
        masked boxes (or the crop excluded them all — then there is nothing to
        mask and the sample must keep its full, unweighted loss)."""
        import torch

        boxes = it.get("mask_boxes") or []
        if not boxes or self.box_weight >= 1.0:
            return None
        if flipped:
            boxes = compose.flip_boxes(boxes)
        cells = compose.box_mask_cells(boxes, x, y, w, h, cw, ch, lw, lh)
        if not cells:
            return None
        m = torch.ones((1, 1, lh, lw), dtype=torch.float32)
        for (x0, y0, x1, y1) in cells:
            m[:, :, y0:y1, x0:x1] = self.box_weight
        return m

    def _encode_cropped(self, it: dict, bw: int, bh: int, flipped: bool,
                        boxes: list, record: list | None = None):
        from PIL import Image

        cw, ch = compose.cover_size(it["width"], it["height"], bw, bh)
        img, alpha = self._open(it["path"])
        img = img.resize((cw, ch), Image.LANCZOS)
        if alpha is not None:
            alpha = alpha.resize((cw, ch), Image.LANCZOS)
        if flipped:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
            if alpha is not None:
                alpha = alpha.transpose(Image.FLIP_LEFT_RIGHT)
        x, y = compose.crop_offset_for_boxes(
            cw, ch, bw, bh, boxes, self.random_crop, self.rng
        )
        if record is not None:
            record.append(self._crop_record(flipped, x, y, bw, bh, cw, ch))
        box = (x, y, x + bw, y + bh)
        lat = self.engine.encode_image(img.crop(box))
        # Here the crop is in PIXELS over the cover frame; the mask grid is
        # the encoded latent's own.
        boxm = self._box_mask(it, flipped, x, y, bw, bh, cw, ch,
                              lat.shape[-1], lat.shape[-2])
        return lat, self._mask_tensor(alpha.crop(box) if alpha else None,
                                      lat.shape[-1], lat.shape[-2]), boxm

    @staticmethod
    def _crop_record(flipped: bool, x: int, y: int, w: int, h: int,
                     cover_w: int, cover_h: int) -> dict:
        """A visit's crop as a fraction of the ORIGINAL (un-flipped) image plus
        the flip flag. The crop was chosen in the (possibly flipped) cover-sized
        frame, so a flipped crop is mirrored back to original coordinates; the
        inspector then mirrors the whole thumbnail in the browser."""
        xo = cover_w - (x + w) if flipped else x
        return {
            "flip": bool(flipped),
            "crop": [round(xo / cover_w, 4), round(y / cover_h, 4),
                     round(w / cover_w, 4), round(h / cover_h, 4)],
        }


# ---- main --------------------------------------------------------------------


def _forward(engine, lat, captions, weights, rng, masks, ref_lists, bucket):
    """One micro-batch's loss, split by REFERENCE LAYOUT where there is one.

    Every visit in a micro-batch already shares a target size — that is what a
    bucket is — but an instruction visit may carry one reference or three, of
    any shape, and the model is fed ONE sequence per sample with the reference
    tokens concatenated onto the noisy latent's. Sequences of different length
    do not stack, so a micro-batch mixing layouts cannot be one forward pass.

    Grouping by layout keeps the ordinary case (every visit carrying one
    reference of the same shape, which is what an edit dataset mostly is) a
    single pass, and splits only what genuinely cannot batch. The groups'
    losses are recombined by SIZE, so the number that comes out is what one
    pass over the whole micro-batch would have produced.

    A run with no references at all — every source but "instructions" — takes
    the first line and never touches any of this.
    """
    if not any(ref_lists):
        return engine.train_step(lat, captions, weights, rng, masks=masks)
    budget = bucket[0] * bucket[1]
    groups: dict[tuple, list[int]] = {}
    for i, refs in enumerate(ref_lists):
        key = compose.ref_layout(refs, budget, engine.latent_scale)
        groups.setdefault(key, []).append(i)
    total = None
    n = len(ref_lists)
    for idxs in groups.values():
        part = engine.train_step(
            lat[idxs],
            [captions[i] for i in idxs],
            [weights[i] for i in idxs],
            rng,
            masks=None if masks is None else masks[idxs],
            refs=[ref_lists[i] for i in idxs],
        ) * (len(idxs) / n)
        total = part if total is None else total + part
    return total


def _rng_snapshot():
    """The torch RNG states a validation round must put back.

    A round seeds torch (`manual_seed`) so its noise and timesteps are the
    same every time — including on MPS, where `_add_noise` uses the global
    stream — and that must not move the TRAINING run's stream: a run with
    validation on would otherwise train on different noise from the same run
    without it, which makes the setting change the thing it measures.
    """
    import torch

    states = {"cpu": torch.get_rng_state()}
    try:
        if torch.cuda.is_available():
            states["cuda"] = torch.cuda.get_rng_state_all()
    except Exception:  # noqa: BLE001 - a stats read must never fail a run
        pass
    try:
        if torch.backends.mps.is_available():
            states["mps"] = torch.mps.get_rng_state()
    except Exception:  # noqa: BLE001
        pass
    return states


def _rng_restore(states) -> None:
    import torch

    torch.set_rng_state(states["cpu"])
    try:
        if "cuda" in states:
            torch.cuda.set_rng_state_all(states["cuda"])
    except Exception:  # noqa: BLE001
        pass
    try:
        if "mps" in states:
            torch.mps.set_rng_state(states["mps"])
    except Exception:  # noqa: BLE001
        pass


def _eval_loss(engine, io: JobIO, latents: LatentSource, manifest: dict,
               entries: list[int], cap_cfg: dict, tag_freq: dict,
               tag_aliases: dict, batch_size: int, buckets: list,
               seed: int) -> float:
    """Mean PLAIN loss over ``entries`` — the validation measurement.

    Deterministic by construction: prompts, crops, flips and dropout come
    from one fresh ``random.Random(seed)`` swapped into the latent source for
    the duration, and the noise and timesteps from the torch RNG seeded the
    same way (snapshotted and restored, so the training stream is untouched).
    Every round therefore asks the model exactly the same questions, and the
    series moves only when the model does.

    PLAIN loss: every weight is 1.0 — no frequency weighting, no query
    weights, no per-entry ``loss_scale``, no regularization scaling — so two
    runs differing in those settings still measure the same thing. What is
    KEPT is the loss masks (alpha and masked regions): they define which part
    of the picture the run is about, and scoring the masked-out part would
    grade the model on regions training deliberately ignores.

    Runs under ``no_grad`` on the raw (non-averaged) weights — the same
    weights the training loss beside it on the graph is measured on.
    """
    import torch

    rng = random.Random(seed)
    states = _rng_snapshot()
    train_rng, latents.rng = latents.rng, rng
    total, n = 0.0, 0
    try:
        torch.manual_seed(seed)
        by_bucket: dict[int, list[int]] = {}
        for j in entries:
            it = manifest["items"][j]
            by_bucket.setdefault(int(it.get("bucket", 0)), []).append(j)
        with torch.no_grad():
            for b in sorted(by_bucket):
                idxs = by_bucket[b]
                for k in range(0, len(idxs), max(1, batch_size)):
                    # A pause clicked mid-round must not wait the round out;
                    # the caller treats it like a pause mid-sample-round.
                    io.check_control()
                    chunk = idxs[k:k + max(1, batch_size)]
                    captions, box_lists, ref_lists = [], [], []
                    for j in chunk:
                        item = manifest["items"][j]
                        text, used, refs = compose.compose_visit(
                            item, cap_cfg, tag_freq, rng, tag_aliases)
                        captions.append(text)
                        ref_lists.append(refs)
                        item_boxes = item.get("boxes") or {}
                        box_lists.append(
                            [bx for t in used for bx in item_boxes.get(t, [])])
                    lat, cell_w = latents.batch_latents(chunk, buckets[b],
                                                        box_lists)
                    loss = _forward(engine, lat, captions,
                                    [1.0] * len(chunk), rng, cell_w,
                                    ref_lists, buckets[b])
                    total += float(loss) * len(chunk)
                    n += len(chunk)
    finally:
        latents.rng = train_rng
        _rng_restore(states)
    return total / max(1, n)


def run(io: JobIO, config: dict, resume: bool = False) -> None:
    import torch

    manifest = io.load_manifest()
    if not manifest.get("items"):
        raise ValueError("dataset manifest is empty — no items matched")
    # BEFORE ANYTHING IS BUILT FROM IT: what the manifest names may not be
    # there any more (see `vanished_entries`).
    gone = vanished_entries(manifest)
    if gone:
        _say_dropped(manifest["items"], gone, "no longer in the library")
        drop_entries(manifest, set(gone))
        if not manifest.get("groups"):
            raise ValueError(
                "none of this run's images are in the library any more — "
                "they were deleted or merged away since the job was made")
    minfo = manifest.get("model") or {}

    hyper = config.get("hyper", {})
    # THE META-LEVEL TAG RULES ARRIVE ALREADY RESOLVED. A job may name the
    # tags a rule applies to by what the LIBRARY says about them ("everything
    # marked noprompt"); the manifest builder turns that into names, and they
    # are unioned in here — so `compose` goes on reading one list per rule and
    # this process never learns what a meta tag is. A copy, because the config
    # dict is written back to disk elsewhere.
    cap_cfg = dict(config.get("captions", {}))
    for key, field in (("always", "always_tags"), ("exclude", "exclude_tags")):
        extra = (manifest.get("tag_meta_names") or {}).get(key) or []
        if extra:
            cap_cfg[field] = sorted({*(cap_cfg.get(field) or []), *extra})
    # The VALUE RULES arrive the same way — resolved to a finished
    # tag → text map by the builder, read by `compose.tag_writer`, so this
    # process never learns what a value tag is.
    if manifest.get("value_map"):
        cap_cfg["value_map"] = manifest["value_map"]
    # And the tag COMMENTS, for `captions.tag_text` — resolved by the builder
    # for exactly the tags the dataset uses.
    if manifest.get("tag_comments"):
        cap_cfg["tag_comments"] = manifest["tag_comments"]
    bucket_cfg = config.get("buckets", {})
    sampling = config.get("sampling", {})
    # THE VALIDATION ROUNDS. The manifest names which entries they score —
    # `val_items` are held out of every pool by the builder, `stable_items`
    # are ordinary training entries — and a run whose manifest names neither
    # has nothing to score however the cadence is set (a config written
    # against an older builder, or a hold-out the dataset was too small for).
    val_cfg = config.get("validation", {}) or {}
    val_every = int(val_cfg.get("every_n_steps", 0) or 0)
    val_seed = int(val_cfg.get("seed", 42) or 42)
    val_entries = manifest.get("val_items") or []
    stable_entries = manifest.get("stable_items") or []
    if not (val_entries or stable_entries):
        val_every = 0
    total = int(hyper.get("steps", 1000))
    io.total_steps = total

    device = pick_device()
    dtype = pick_dtype(hyper.get("precision", "bf16"), device)
    # Say it out loud: "is it actually on the GPU?" is the first question of
    # every run, and on a Mac the answer also depends on a bf16 probe.
    asked = str(hyper.get("precision", "bf16"))
    fell_back = "" if str(dtype).endswith(asked) else f" (asked for {asked})"
    print(f"device: {device}, dtype: {str(dtype).replace('torch.', '')}{fell_back}",
          flush=True)

    # A CEILING, before anything large is allocated. On a discrete card an
    # oversized run raises a CUDA OOM and ends one job; on UNIFIED memory
    # nothing stops it growing into swap — `recommended_max_memory()` sits
    # ABOVE physical RAM — and the symptom is a machine that stops responding
    # rather than an error, with the run lost regardless. The job may name its
    # own figure; 0 means "work it out from the device".
    capped = membudget.arm(device, float(hyper.get("memory_budget_gb", 0) or 0))
    if capped:
        print(f"memory budget: {capped:.0f} GB of "
              f"{membudget.device_memory_gb(device):.0f} GB "
              f"({'unified' if membudget.is_unified_memory(device) else 'discrete'})",
              flush=True)

    # Naming the model matters here: this phase is where a first run silently
    # downloads several GB, and "loading model" alone leaves you watching a
    # spinner wondering whether anything is happening.
    io.write_state("loading_model", note=str(minfo.get("repo") or ""))
    print(f"loading {minfo.get('repo') or minfo.get('key')}", flush=True)
    # A pause/cancel clicked while the job was still spawning shouldn't wait
    # out a multi-minute model load first (the load itself is one library
    # call and cannot be interrupted midway).
    io.check_control()
    engine_mod = importlib.import_module(f"engines.{minfo.get('engine')}")
    engine = engine_mod.Engine(config, minfo, device, dtype)
    engine.load()  # may download into the shared HF cache on first use
    _report_resident(engine, device)
    # AFTER load, and from here rather than from inside each engine's own
    # `load()`: the encoders are placed by whichever engine this is, so the
    # one call that runs for every engine — including one written later — is
    # the one out here. It is a no-op unless the job asked for it.
    offloaded = engine.offload_text_encoders()
    if offloaded:
        print(f"text encoder on CPU: {', '.join(offloaded)} "
              f"(frees their weights from VRAM; each step pays one CPU "
              f"forward to embed its prompt)", flush=True)
    io.check_control()
    # The model's own shape, for the map the app draws — written once, from
    # the weights that were just loaded.
    io.write_architecture(engine.architecture())
    engine.record_block_order()
    # Which noise levels this run trains on. Said out loud because it is
    # invisible otherwise: two runs differing only here have the same loss
    # curve and differ only in what the model ends up good at.
    print(engine.noise_summary(), flush=True)

    seed = int(hyper.get("seed", 42))
    rng = random.Random(seed)
    torch.manual_seed(seed)

    buckets = [tuple(b) for b in manifest["buckets"]]
    sampler = compose.Sampler(manifest["items"], manifest["groups"], rng,
                              weight_mode=config.get("weight_mode", "sampling"))
    # EPOCHS RESOLVE HERE, not in the editor: a pass is as long as the manifest
    # is, and only the manifest knows a film's frames, a degraded copy or an
    # item contributing one entry per caption. A step is `grad_accum`
    # micro-batches, so the batches a pass takes divide by it.
    want_epochs = int(hyper.get("epochs", 0) or 0)
    ckpt_epochs = int(hyper.get("checkpoint_epochs", 0) or 0)
    sample_epochs = int(sampling.get("every_n_epochs", 0) or 0)
    # How many STEPS one pass is — needed by the run's length, by the
    # checkpoint cadence, by the sample cadence, or by none of them, so it is
    # asked for once and only when something wants it.
    steps_per_epoch = 0
    if want_epochs > 0 or ckpt_epochs > 0 or sample_epochs > 0:
        per_epoch = sampler.batches_per_epoch(int(hyper.get("batch_size", 1)))
        accum = max(1, int(hyper.get("grad_accum", 1)))
        steps_per_epoch = max(1, math.ceil(per_epoch / accum))
    if want_epochs > 0:
        io.total_steps = max(1, math.ceil(want_epochs * per_epoch / accum))
        print(f"length: {want_epochs} epochs x {per_epoch} batches / {accum} "
              f"accumulation = {io.total_steps} steps", flush=True)
    tag_freq = manifest.get("tag_freq", {})
    # Canonical tag name -> its aliases; empty unless the run asked for them.
    tag_aliases = manifest.get("tag_aliases", {})
    ds_mean_inv = compose.dataset_mean_inverse_freq(manifest["items"], tag_freq)
    weight_by_freq = bool(cap_cfg.get("loss_weight_by_freq"))
    # REGULARIZATION entries: pictures in the run to hold the model's existing
    # idea of a class in place rather than to teach it something new. They are
    # marked in the manifest, they never carry the trigger word (`compose`
    # drops it), and their loss is scaled here. Reported because a pool that
    # matched nothing is silent otherwise — the run trains perfectly well on
    # the rest, and the drift the pool exists to prevent simply happens.
    reg_strength = float(config.get("reg_strength", 1.0) or 0.0)
    n_reg = sum(1 for it in manifest["items"] if it.get("reg"))
    if n_reg:
        print(f"regularization: {n_reg} of {len(manifest['items'])} entries, "
              f"counting {reg_strength:g}x and without the trigger word",
              flush=True)

    latents = LatentSource(engine, io, manifest, buckets, {
        **bucket_cfg, "cache_latents": hyper.get("cache_latents", True),
    }, rng)
    if latents.alpha_mask:
        print(f"masked training on (transparent cells weigh "
              f"{latents.bg_weight:g})")
    n_masked = sum(1 for it in manifest["items"] if it.get("mask_boxes"))
    if n_masked and latents.box_weight < 1.0:
        print(f"masked regions on {n_masked} entries (masked cells weigh "
              f"{latents.box_weight:g})")
    if val_every:
        parts = [f"{len(val_entries)} held-out entries"] if val_entries else []
        if stable_entries:
            parts.append(f"{len(stable_entries)} stable-loss entries")
        print(f"validation every {val_every} steps: {', '.join(parts)} — "
              f"plain loss, fixed seed {val_seed}", flush=True)
    io.write_state("caching_latents")
    # Encoding a few hundred images takes minutes with nothing else to show
    # for it, so the count travels with the phase.
    unreadable: list[int] = []
    latents.prepare(on_progress=lambda done, total: io.write_state(
        "caching_latents", note=f"{done} / {total}"),
        on_missing=unreadable.append)
    if unreadable:
        # A picture that went while the cache was being filled. The SAMPLER is
        # built again rather than edited: it is derived from the pools, and
        # rebuilding it from the shortened ones is the same call with the same
        # rng, where reaching into its buckets and masses is four invariants
        # to keep in step. The run's LENGTH is left where it was: an epoch
        # was resolved into steps above, and a picture or two either way is
        # not a reason to move a number the schedule is already running on.
        _say_dropped(manifest["items"], unreadable, "unreadable")
        drop_entries(manifest, set(unreadable))
        if not manifest.get("groups"):
            raise ValueError("none of this run's images could be read")
        sampler = compose.Sampler(manifest["items"], manifest["groups"], rng,
                                  weight_mode=config.get("weight_mode",
                                                         "sampling"))
        # Both validation lists were shortened in place with the pools; a
        # run whose whole hold-out went has nothing left to score.
        if not (val_entries or stable_entries):
            val_every = 0
    engine.after_latent_cache(cached=latents.cache)  # may free the VAE

    params = engine.trainable_params(float(hyper.get("lr", 1e-4)))
    optimizer = _make_optimizer(params, hyper, device, engine.dtype)
    sched_fn = lr_lambda(hyper.get("lr_scheduler", "cosine"),
                         int(hyper.get("warmup_steps", 0)),
                         lambda: io.total_steps)

    # THE AVERAGED COPY OF THE WEIGHTS, when the run asks for one. Built from
    # the optimizer's own parameter list, so what is averaged is exactly what
    # is trained. See `ema.py` for what it is for; from here on the rule is
    # simply that anything anyone LOOKS AT is the average (checkpoints, the
    # final output, the test samples) while the resume point stays the raw
    # weights, because that is what training must continue from.
    ema = None
    if hyper.get("ema"):
        ema = ema_mod.Ema([p for g in optimizer.param_groups
                           for p in g["params"]],
                          float(hyper.get("ema_decay", 0.999) or 0.999))
        print(f"weight averaging on (decay {ema.decay:g}, "
              f"{len(ema.shadow)} tensors)", flush=True)

    start_step = 0
    if resume:
        last = io.last_checkpoint()
        if last is not None:
            start_step = engine.load_checkpoint(last, optimizer, ema=ema)
    te_stop = int(total * float(hyper.get("te_stop_ratio", 0.5))) \
        if hyper.get("train_text_encoder") else None

    grad_accum = max(1, int(hyper.get("grad_accum", 1)))
    batch_size = max(1, int(hyper.get("batch_size", 1)))
    ckpt_every = int(hyper.get("checkpoint_every", 0))
    if ckpt_epochs > 0:
        ckpt_every = ckpt_epochs * steps_per_epoch
        print(f"checkpoints: every {ckpt_epochs} epoch(s) = every "
              f"{ckpt_every} steps", flush=True)
    ckpt_keep = int(hyper.get("checkpoint_keep", 2))
    ckpt_keep_every = int(hyper.get("checkpoint_keep_every", 0) or 0)
    sample_every = int(sampling.get("every_n_steps", 0))
    if sample_epochs > 0:
        # An epoch cadence WINS, exactly as the checkpoint one does — and it
        # is resolved here rather than in the editor because only the built
        # manifest knows how long a pass is.
        sample_every = sample_epochs * steps_per_epoch
        print(f"test samples: every {sample_epochs} epoch(s) = every "
              f"{sample_every} steps", flush=True)
    # Published so the app counts down to the cadence the run is ACTUALLY
    # keeping — an epoch cadence is a step count only after the manifest has
    # said how long a pass is, and the config's step field is the one the
    # epoch setting overruled.
    io.ckpt_every = ckpt_every
    io.sample_every = sample_every if sampling.get("prompts") else 0
    base_lr = float(hyper.get("lr", 1e-4))

    # Optional untrained baseline: the prompts at step 0, before training.
    if sampling.get("at_start") and sampling.get("prompts") and start_step == 0:
        io.write_state("sampling", step=0)
        # No progress sampler thread yet (it starts with the loop), so this
        # round publishes its own count.
        with ema_mod.maybe_applied(ema):
            _generate_samples(io, engine, sampling, 0, note=lambda text:
                              io.write_state("sampling", step=0, note=text))

    # A round interrupted by a pause left fewer images than it promised, and
    # the step it belongs to is behind us — the cadence will never come back
    # to it. Finish it first, so resuming completes what the pause cut off
    # instead of leaving a permanently half-rendered round.
    if resume and sample_every and sampling.get("prompts"):
        unfinished = _unfinished_round(io)
        if unfinished is not None:
            io.write_state("sampling", step=unfinished)
            try:
                with ema_mod.maybe_applied(ema):
                    _generate_samples(
                        io, engine, sampling, unfinished,
                        note=lambda text: io.write_state(
                            "sampling", step=unfinished, note=text))
            except PauseRequested:
                raise

    io.write_state("training", step=start_step)
    # While-loop: a set_steps command may grow/shrink io.total_steps mid-run.
    step = start_step
    nan_streak = 0
    last_state = 0.0

    # A sampler thread for the progress display. The loop only gets to write
    # state between steps, and one step of a big-batch run is minutes; this
    # publishes the phase, sub-phase and intra-step image count as they
    # change. It reads plain attributes and writes the state file the loop
    # writes anyway; there is no lock and nothing to wait for.
    progress = {"step": start_step, "run": True, "note": "",
                "sub": "", "phase": "training"}

    def sample_progress():
        while progress["run"]:
            time.sleep(1.0)
            if not progress["run"]:
                return
            try:
                # The LOOP's current phase, not a hardcoded "training": this
                # thread writes once a second, and stamping "training" over
                # the loop's own "sampling"/"checkpoint" writes made the app
                # show a sample round as an idle training step.
                io.write_state(str(progress["phase"]), step=progress["step"],
                               note=str(progress["note"]),
                               sub=str(progress["sub"]))
            except OSError:
                pass

    watcher = threading.Thread(target=sample_progress, daemon=True,
                               name="mc-train-progress")
    watcher.start()
    # The sampler thread must not outlive the loop: a write after the
    # run has stopped would put `training` back into a state file that
    # says paused, and the manager would read that as a crash.
    # The step whose state a pause would have nothing new to save for: the
    # resume point, updated on every checkpoint. Pausing before any new step
    # finished skips the save entirely — for a resumed run `last/` already
    # holds exactly this state, and for a fresh run there is nothing trained
    # worth saving. Re-writing an identical multi-GB checkpoint was most of
    # what made "Pause" slow on a job that had barely started.
    ckpt_at = start_step
    # Off unless MEDIA_COMPOST_TRAIN_PROFILE names a number of steps; see
    # profiling.py. Every `mark` below is a no-op then.
    prof = profiling.StepProfiler(io.dir, device)

    def compose_micro(indices):
        """One micro-batch's prompts and per-sample weights — the
        `captions`, `weights`, `box_lists` and `ref_lists` the forward and
        the inspector read, composed in the order the visits are drawn."""
        captions, weights, box_lists = [], [], []
        # The ordered reference images this visit's prompt refers
        # to, parallel to `captions`. Empty on every run whose
        # source is not "instructions"; carried here so the
        # inspector can say what the model was shown, and so the
        # engines have one place to take it from when they learn
        # to condition on it.
        ref_lists: list[list[dict]] = []
        for idx in indices:
            item = manifest["items"][idx]
            text, used, refs = compose.compose_visit(
                item, cap_cfg, tag_freq, rng, tag_aliases
            )
            captions.append(text)
            ref_lists.append(refs)
            # The boxes of the tags in THIS visit's prompt — the
            # crop is chosen so they stay mostly inside (annotated
            # subjects that are prompted for shouldn't be cropped
            # away).
            item_boxes = item.get("boxes") or {}
            box_lists.append(
                [b for t in used for b in item_boxes.get(t, [])]
            )
            # Two independent multipliers on one sample's loss:
            # how RARE its tags are (a setting of its own), and its
            # query's weight when the run spends that on the
            # gradient rather than on how often it is seen —
            # `loss_scale` is 1.0 in the other mode.
            weights.append(
                (compose.loss_weight(item["tags"], tag_freq,
                                     ds_mean_inv)
                 if weight_by_freq else 1.0)
                * sampler.loss_scale(idx)
                # An entry may carry its own share: the captions of
                # one item split a single item's gradient between
                # them when the run asks for that.
                * float(item.get("loss_scale", 1.0))
                # …and a REGULARIZATION picture counts for however
                # much of a reminder the run wants it to be. 1.0
                # gives it the same say as a training picture,
                # which is the classic setting.
                * (reg_strength if item.get("reg") else 1.0)
            )
        return captions, weights, box_lists, ref_lists

    # ONE MICRO-BATCH AHEAD, only where the encoder sits on the CPU. Its
    # forward is then the loop waiting on the processor with the card idle —
    # measured on an RTX 5090, Chroma at 512 px: 1.34 s of a 1.82 s step in
    # `forward`, against 0.30 s with T5 on the card — so the NEXT
    # micro-batch's prompts are composed while this one's are still being
    # read and encoded in a thread while this one trains
    # (`engine.prefetch_prompts`). The stream of random draws keeps its
    # order (compose, then the latents' crop and flip, per micro-batch) but
    # not its interleaving with the noise an SD/SDXL step draws, which is
    # why this is gated on the offload rather than always on: a run without
    # it produces exactly the stream it always did.
    lookahead = engine.prefetches_prompts()
    pending: collections.deque = collections.deque()

    try:
        while step < io.total_steps:
            step += 1
            prof.begin_step(step)
            try:
                # Checked again between the micro-batches below: one pause
                # check per step meant a pause waited out a whole step, which
                # for SDXL at batch×accum 8 is minutes.
                io.check_control()

                if te_stop is not None and step == te_stop + 1:
                    engine.stop_text_encoder_training()

                optimizer.zero_grad(set_to_none=True)
                loss_total = 0.0
                micro_losses: list[float] = []
                step_visits: list[dict] = []
                # THE STEP'S BATCHES ARE DRAWN UP FRONT, so the accumulation
                # can divide by how many images the step ACTUALLY holds.
                # A micro-batch is not always `batch_size` long — a bucket
                # whose entries do not divide by it ends in a SHORT batch,
                # kept deliberately (`compose.Sampler`: dropping it would mean
                # a bucket smaller than one batch never trains at all). A flat
                # 1/grad_accum therefore gave each of a short batch's samples
                # 1/(len·accum) of the step where a full batch's got
                # 1/(batch·accum), up to `batch_size`x the intended influence.
                # That does not average out over epochs: a bucket's size is
                # fixed, so its gradient share was `ceil(n/batch)` rather than
                # `n` — measured at 7.2x for a rare aspect ratio holding one
                # picture at batch 8, silently overriding the pool weights,
                # `loss_scale` and `loss_weight` this loop is otherwise
                # careful to normalise. Dividing by the step's own sample
                # count makes a step exactly one pass over the same images,
                # which is the whole promise of accumulation; it is the rule
                # `masked_mean` states one level down, and the one `_forward`
                # already follows when it splits a micro-batch by layout.
                # Drawing is pure bookkeeping, so it costs nothing here.
                micros = [pending.popleft() if pending
                          else (*sampler.batch(batch_size), None)
                          for _ in range(grad_accum)]
                step_samples = sum(len(ix) for _, ix, _ in micros)
                done_samples = 0
                for micro, (bucket_id, indices, composed) in enumerate(micros):
                    if micro:
                        io.check_control()
                    # The in-step phase, published by the sampler thread for
                    # the app's phase line. It is where the LOOP is, not where
                    # the GPU is — an async backend queues a pass in
                    # milliseconds and executes it later — so treat it as
                    # approximate.
                    progress["sub"] = "batch"
                    prof.mark("compose")
                    if composed is None:
                        composed = compose_micro(indices)
                    captions, weights, box_lists, ref_lists = composed
                    if lookahead:
                        # The next micro-batch — the rest of this step, else
                        # the first of the next — composed now and its
                        # prompts already encoding when the card is done.
                        if micro + 1 < len(micros):
                            b2, ix2, c2 = micros[micro + 1]
                            if c2 is None:
                                c2 = compose_micro(ix2)
                                micros[micro + 1] = (b2, ix2, c2)
                        else:
                            b2, ix2 = sampler.batch(batch_size)
                            c2 = compose_micro(ix2)
                            pending.append((b2, ix2, c2))
                        engine.prefetch_prompts(c2[0])
                    crops: list[dict] = []
                    prof.mark("latents")
                    lat, cell_w = latents.batch_latents(
                        indices, buckets[bucket_id], box_lists, record=crops)
                    progress["sub"] = "forward"
                    prof.mark("forward")
                    loss = _forward(engine, lat, captions, weights, rng,
                                    cell_w, ref_lists, buckets[bucket_id])
                    # Between forward and backward too: the backward pass is
                    # about half of a micro-batch, and a pause lands mid-step
                    # anyway (the partial gradients are discarded).
                    io.check_control()
                    progress["sub"] = "backward"
                    prof.mark("backward")
                    # This micro-batch's SHARE of the step, not a flat
                    # 1/accum: `loss` is already a mean over its own samples,
                    # so weighting by how many it holds gives every image in
                    # the step exactly 1/step_samples. See the note above.
                    share = len(indices) / step_samples
                    (loss * share).backward()
                    micro_loss = float(loss.detach())
                    prof.mark("bookkeeping")
                    loss_total += micro_loss * share
                    micro_losses.append(micro_loss)
                    # One inspector row per image in this micro-batch (they share
                    # the micro-batch's single loss).
                    bpx = buckets[bucket_id]
                    for pos, idx in enumerate(indices):
                        it = manifest["items"][idx]
                        cr = crops[pos] if pos < len(crops) else {}
                        step_visits.append({
                            "file_id": it.get("file_id"),
                            # A video frame is not a stored file, so it has no
                            # thumbnail to show — the moment it came from is
                            # what identifies it instead, and the extracted
                            # frame ITSELF is named so the inspector can show
                            # the picture the model actually saw. Named
                            # relative to the job's own frames folder: an
                            # absolute path out of a manifest is not something
                            # a request may ask a server to open.
                            "video_time": it.get("video_time"),
                            **({"frame": _frame_ref(io, it["path"])}
                               if it.get("video_time") is not None else {}),
                            "prompt": captions[pos],
                            "flip": cr.get("flip", False),
                            "crop": cr.get("crop"),
                            "img": [it.get("width", 0), it.get("height", 0)],
                            "bucket": [bpx[0], bpx[1]],
                            "loss": round(micro_loss, 6) if micro_loss == micro_loss else None,
                            # An instruction visit's source pictures, in order,
                            # so the inspector can show what the prompt was
                            # about. Absent on every other kind of run.
                            **({"refs": [r.get("file_id")
                                         for r in ref_lists[pos]]}
                               if ref_lists[pos] else {}),
                            # Which degradation this sample was, and at what
                            # strength ("jpeg-q37-s420"). Every degraded entry
                            # shares its source file's id, so without this the
                            # inspector cannot tell the clean visit from the
                            # spoiled one — and a range is unreadable from its
                            # midpoint after the fact. Absent on a clean visit.
                            **({"degrade": it["degrade"]}
                               if it.get("degrade") else {}),
                        })
                    # Intra-step progress ("4 / 8" images), published by the
                    # sampler thread. A big-batch SDXL step can take minutes,
                    # during which the step counter alone reads as "stuck".
                    # A one-image step would only flash "1 / 1" — skip it.
                    # Counted from the batches actually drawn rather than
                    # multiplied out of `batch_size`: a step holding a short
                    # batch has fewer images than the product, and the note
                    # would have promised images it was never going to show.
                    done_samples += len(indices)
                    if step_samples > 1:
                        progress["note"] = f"{done_samples} / {step_samples}"
            except PauseRequested:
                # A pause mid-step discards the partial step (its gradients
                # were never applied), so the checkpoint is the last finished
                # step — and if that is exactly what `last/` already holds,
                # saving it again would only make the pause slower.
                if ckpt_at != step - 1:
                    _checkpoint_last(io, engine, optimizer, step - 1,
                                     ema=ema, timed=True)
                raise

            progress["sub"] = "update"
            prof.mark("update")
            torch.nn.utils.clip_grad_norm_([p for g in optimizer.param_groups
                                            for p in g["params"]], 1.0)
            scale = sched_fn(step)
            for g in optimizer.param_groups:
                g["lr"] = g.get("initial_lr", base_lr) * scale
            optimizer.step()
            # Once per OPTIMIZER step, so a run with gradient accumulation
            # averages over the same number of updates as one without.
            if ema is not None:
                ema.update()
            prof.mark("after")

            # A NaN loss means the run is computing nothing — the weights are
            # being updated with garbage, the graph is flat and every sample comes
            # out black. It used to keep going for hours; now it says so and stops
            # while the last good checkpoint is still the newest thing on disk.
            if loss_total != loss_total or loss_total in (float("inf"),
                                                          float("-inf")):
                nan_streak += 1
                if nan_streak >= 3:
                    raise RuntimeError(
                        f"the loss became NaN at step {step} and stayed there — "
                        "training is not learning anything. On Apple silicon this "
                        "is usually attention slicing (turn it off under Memory); "
                        "otherwise lower the learning rate or switch the precision "
                        "to fp32.")
            else:
                nan_streak = 0
            if step == start_step + 1:
                # One forward pass has run, so the block map can be rewritten
                # in the order the model actually executes them — and the
                # hooks that answered that question come straight back out of
                # the forward path.
                io.write_architecture(engine.architecture())
                engine.stop_block_order()
            finite_micros = [m for m in micro_losses if m == m and abs(m) != float("inf")]
            io.append_metric(
                step, loss_total, base_lr * scale,
                lo=min(finite_micros) if len(finite_micros) > 1 else None,
                hi=max(finite_micros) if len(finite_micros) > 1 else None,
            )
            io.append_visits(step, step_visits)
            progress["step"] = step
            progress["note"] = ""
            progress["sub"] = ""
            now = time.time()
            if step % 10 == 0 or step >= io.total_steps or now - last_state > 1.5:
                last_state = now
                io.write_state("training", step=step)

            if ckpt_every and step % ckpt_every == 0 and step < io.total_steps:
                progress["phase"] = "checkpoint"
                io.write_state("checkpoint", step=step)
                snap = io.snapshot_step(step, ckpt_keep, ckpt_keep_every,
                                        ckpt_every)
                # The SNAPSHOT holds the averaged weights — it is the thing
                # somebody picks and uses — while `last/` below keeps the raw
                # ones, because training has to continue from those.
                with ema_mod.maybe_applied(ema):
                    engine.save_weights(snap)
                _checkpoint_last(io, engine, optimizer, step, ema=ema)
                ckpt_at = step
                progress["phase"] = "training"
                io.write_state("training", step=step)

            if sample_every and sampling.get("prompts") and \
                    step % sample_every == 0:
                progress["phase"] = "sampling"
                io.write_state("sampling", step=step)
                try:
                    # Rendered from the AVERAGED weights when there are any,
                    # so a sample predicts what the checkpoint beside it will
                    # actually produce rather than what the raw weights would.
                    with ema_mod.maybe_applied(ema):
                        _generate_samples(
                            io, engine, sampling, step,
                            note=lambda text: progress.__setitem__("note", text))
                except PauseRequested:
                    # The round is interrupted mid-render (its finished images
                    # are kept; the rest re-render on resume) — but the STEP
                    # is done and its gradients are applied, so it must be
                    # checkpointed or the pause would silently lose training.
                    if ckpt_at != step:
                        _checkpoint_last(io, engine, optimizer, step,
                                         ema=ema, timed=True)
                    raise
                progress["phase"] = "training"
                # The round's image count would otherwise stay on the state
                # as the step's note — the micro loop only overwrites it when
                # a step runs more than one image.
                progress["note"] = ""
                io.write_state("training", step=step)

            if val_every and step % val_every == 0:
                progress["phase"] = "validating"
                io.write_state("validating", step=step)
                try:
                    series: dict[str, float] = {}
                    # RAW weights, deliberately — the training loss beside
                    # these on the graph is raw, and a curve half-averaged
                    # and half not would compare two different models.
                    if val_entries:
                        series["val"] = _eval_loss(
                            engine, io, latents, manifest, val_entries,
                            cap_cfg, tag_freq, tag_aliases, batch_size,
                            buckets, val_seed)
                    if stable_entries:
                        series["stable"] = _eval_loss(
                            engine, io, latents, manifest, stable_entries,
                            cap_cfg, tag_freq, tag_aliases, batch_size,
                            buckets, val_seed)
                except PauseRequested:
                    # The STEP is finished and applied, exactly as a pause
                    # mid-sample-round: checkpoint it or the pause silently
                    # loses training.
                    if ckpt_at != step:
                        _checkpoint_last(io, engine, optimizer, step,
                                         ema=ema, timed=True)
                    raise
                io.append_eval(step, series)
                said = " · ".join(f"{k} {v:.4f}" for k, v in series.items())
                print(f"validation at step {step}: {said}", flush=True)
                progress["phase"] = "training"
                progress["note"] = ""
                io.write_state("training", step=step)

    finally:
        prof.close()
        progress["run"] = False
        _report_peak_memory(device, at_least=prof.high)

    _checkpoint_last(io, engine, optimizer, io.total_steps, ema=ema)
    # ONE call: `save_weights` writes both the trainer's own copy (so a later
    # job can start from this result) and the portable file other tools load.
    # Every step checkpoint gets exactly the same pair, which is what makes
    # picking an earlier checkpoint a choice rather than a conversion job.
    with ema_mod.maybe_applied(ema):
        engine.save_weights(io.output_dir())


def _tensor_bytes(p) -> int:
    inner = getattr(p, "_data", None)
    if inner is not None and hasattr(inner, "element_size"):
        return inner.numel() * inner.element_size()
    return p.numel() * p.element_size()


def _report_resident(engine, device: str) -> None:
    """What each component's WEIGHTS occupy once loaded, and the device's
    total — one line, so a quantized load that did not shrink, or a parked
    encoder that is still resident, is visible before the first step rather
    than deduced from an out-of-memory error inside it."""
    import torch

    parts = []
    names = ([engine.backbone_component] + list(engine.text_encoder_components)
             + ["vae"])
    for name in names:
        comp = getattr(engine, name, None)
        params = getattr(comp, "parameters", None)
        if params is None:
            continue
        try:
            # A quanto weight is a tensor subclass whose dtype is still the
            # bf16 it stands in for; the bytes are in its `_data`. Ask that
            # first, or an int8 transformer reports its bf16 size.
            gb = sum(_tensor_bytes(p) for p in params()) / 1e9
        except Exception:  # noqa: BLE001 - a proxy, or a parked encoder
            continue
        parts.append(f"{name} {gb:.2f} GB")
    total = ""
    if str(device).startswith("cuda") and torch.cuda.is_available():
        total = f"; {torch.cuda.memory_allocated() / 1e9:.2f} GB allocated"
    if parts:
        print("resident: " + ", ".join(parts) + total, flush=True)


def _report_peak_memory(device: str, at_least: float = 0.0) -> None:
    """Print what the run actually used, once, at the end.

    The editor's VRAM figure is an ESTIMATE built from per-model constants,
    and those constants were measured on Apple Silicon. Without the real
    number written down beside them, there is no way to tell a wrong constant
    from a wrong config — a job that OOMs and one that fits with room to spare
    look the same in the log. Cheap: two counters the allocator already keeps.

    `max_memory_allocated` is live tensors at their peak — the figure the
    estimate is trying to predict. `max_memory_reserved` is what the caching
    allocator took from the driver, always larger (pooled free blocks and
    fragmentation), and is the one an out-of-memory message quotes. Both are
    printed because comparing the estimate against the wrong one is how the
    constants get "calibrated" to a number that is not what they model.
    """
    try:
        import torch

        if device == "cuda" and torch.cuda.is_available():
            # The profiler resets the allocator's peak at every phase boundary
            # to attribute it, so with one running the run's own reading is
            # only its last stretch; the profiler's high-water mark is the
            # floor.
            alloc = max(torch.cuda.max_memory_allocated() / 1e9, at_least)
            reserved = torch.cuda.max_memory_reserved() / 1e9
            print(f"peak VRAM: {alloc:.2f} GB allocated, "
                  f"{reserved:.2f} GB reserved", flush=True)
        elif device == "mps" and hasattr(torch, "mps"):
            alloc = torch.mps.current_allocated_memory() / 1e9
            print(f"peak memory: {alloc:.2f} GB currently allocated",
                  flush=True)
    except Exception:  # noqa: BLE001 - never fail a finished run over a stat
        pass


def _make_optimizer(param_groups, hyper: dict, device: str, dtype=None):
    """The optimizer this run asked for, or the nearest thing that runs here.

    Every fallback SAYS SO in the log. What an optimizer costs in memory is
    part of the editor's estimate, so silently substituting one would make
    that figure wrong with nothing to read.

    With `bf16_masters` the answer is WRAPPED rather than replaced: the
    parameters are at half precision and their updates have to carry what the
    rounding drops to land at all (`kahan.py`), which is a fact about the
    WRITE and nothing to do with which optimizer computed it. So Adafactor's
    factored state, AdamW's moments and bitsandbytes' 8-bit state all go on
    meaning exactly what they meant, every fallback above still applies, and
    the editor's memory constants are unchanged.
    """
    import torch

    narrow = (dtype is not None and dtype is not torch.float32
              and bool(hyper.get("bf16_masters")))

    def wrap(inner):
        if not narrow:
            return inner
        from kahan import KahanMasters

        print(f"master weights kept at {str(dtype).split('.')[-1]}, with the "
              f"rounding carried (Kahan summation)", flush=True)
        return KahanMasters(inner, dtype)

    kind = str(hyper.get("optimizer", "adamw") or "adamw")
    if kind == "adafactor":
        made = _adafactor(param_groups)
        if made is not None:
            print("optimizer: Adafactor", flush=True)
            return wrap(made)
    if kind == "prodigy":
        made = _prodigy(param_groups, hyper)
        if made is not None:
            print("optimizer: Prodigy (it works the learning rate out itself)",
                  flush=True)
            return wrap(made)
    if kind == "adamw_8bit" and device != "cuda":
        # The one fallback that used to say nothing: bitsandbytes is
        # CUDA/ROCm-only, so on MPS or CPU the run quietly trained on plain
        # AdamW while the editor's memory estimate assumed the 8-bit one.
        print("the 8-bit optimizer needs CUDA (or ROCm) — falling back to "
              "AdamW", flush=True)
    if kind == "adamw_8bit" and device == "cuda":
        try:
            import bitsandbytes as bnb

            # One tiny REAL step before trusting it. ROCm also reads as
            # "cuda" here, and a CUDA-only bitsandbytes build imports fine
            # on an AMD box and fails at the first optimizer step — hours
            # in, out of the trainer's own error handler. 8192 elements
            # because AdamW8bit keeps params below its min_8bit_size (4096)
            # in 32-bit state: a small probe exercises the wrong kernels
            # and proves nothing.
            p = torch.nn.Parameter(torch.zeros(8192, device=device))
            p.grad = torch.zeros_like(p)
            bnb.optim.AdamW8bit([p]).step()

            return wrap(bnb.optim.AdamW8bit(param_groups, weight_decay=1e-2))
        except ImportError:
            print("bitsandbytes not installed — falling back to AdamW")
        except Exception as exc:  # noqa: BLE001 - unusable build for this GPU
            print(f"bitsandbytes cannot run on this GPU — falling back to "
                  f"AdamW ({exc})")
    return wrap(torch.optim.AdamW(param_groups, weight_decay=1e-2))


def _adafactor(param_groups):
    """Adam's behaviour without Adam's two moment tensors.

    AdamW keeps two running statistics the size of the model itself, which for
    a full finetune is most of the memory a run needs. Adafactor keeps the
    same second moment FACTORED into a row vector and a column vector per
    matrix — O(n+m) where Adam is O(n·m) — so that term all but disappears.

    It is the only memory-efficient optimizer that runs EVERYWHERE. The 8-bit
    AdamW above is bitsandbytes, which needs an NVIDIA or ROCm GPU, so on
    Apple silicon a run had no saving available at all and always paid full
    fp32 Adam state.

    **`relative_step=False` is load-bearing.** Left at its default, Adafactor
    computes a learning rate of its own from the step number and IGNORES the
    one in the param group — which is the value this loop's schedule writes
    every step, so warmup, cosine decay and the rate you typed would all
    quietly do nothing. Turning it off (with `scale_parameter`, which is the
    other half of that machinery) is what makes it an ordinary optimizer the
    schedule drives, and it is what the transformers docs prescribe for use
    with an external scheduler.

    Returns None when it is unavailable, so the caller can fall back and say
    so rather than failing a run over an optimizer choice.
    """
    try:
        from transformers.optimization import Adafactor
    except ImportError:
        print("this transformers build has no Adafactor — falling back to "
              "AdamW", flush=True)
        return None
    try:
        return Adafactor(
            param_groups, weight_decay=1e-2,
            relative_step=False, scale_parameter=False, warmup_init=False,
        )
    except (TypeError, ValueError) as exc:  # a signature that has moved on
        print(f"Adafactor could not be built ({exc}) — falling back to AdamW",
              flush=True)
        return None


def _prodigy(param_groups, hyper: dict):
    """An optimizer that works out its own learning rate.

    Prodigy measures how far the weights have travelled from where they
    started and grows an internal estimate `d` from that, so the rate comes
    out of the run rather than being guessed at in advance. That matters here
    because the right rate is not a property of the settings: it depends on
    the model, the dataset size and what is being taught, so a rate that is
    right for SDXL at twenty pictures is wrong for Chroma at eight hundred,
    and finding it costs runs.

    **THE LEARNING RATE BECOMES A MULTIPLIER.** The value in the param groups
    is no longer a step size — Prodigy multiplies its own estimate by it — so
    1.0 is the neutral setting and the number that means "as before" for every
    other optimizer means "a ten-thousandth of what I worked out" here. That
    is silent (the run trains, and learns almost nothing), so it is warned
    about rather than left to be discovered. The editor sets 1.0 when this
    optimizer is picked.

    The LR SCHEDULE still applies, and composes correctly: the loop rescales
    the group's rate each step and Prodigy multiplies through it, so a cosine
    decay decays what Prodigy found. `safeguard_warmup` is what keeps that
    honest during a warmup ramp.
    """
    try:
        from prodigyopt import Prodigy
    except ImportError:
        print("prodigyopt is not installed in the training environment — "
              "falling back to AdamW. Re-run the training setup to add it.",
              flush=True)
        return None
    lr = float(hyper.get("lr", 1.0) or 1.0)
    if not 0.1 <= lr <= 10.0:
        print(f"warning: Prodigy treats the learning rate as a MULTIPLIER on "
              f"the rate it works out for itself, where 1.0 is neutral — this "
              f"run is set to {lr:g}, so it will train about {lr:g}x as fast "
              f"as intended. Set the learning rate to 1 unless you meant "
              f"this.", flush=True)
    try:
        return Prodigy(
            param_groups, weight_decay=1e-2,
            # Both are what the authors prescribe for training with a warmup
            # and a decaying schedule, which is what this loop always applies.
            safeguard_warmup=True, use_bias_correction=True,
        )
    except (TypeError, ValueError) as exc:
        print(f"Prodigy could not be built ({exc}) — falling back to AdamW",
              flush=True)
        return None


def _checkpoint_last(io: JobIO, engine, optimizer, step: int,
                     ema=None, timed: bool = False) -> None:
    """The RESUME POINT — everything training needs to carry on.

    Deliberately the RAW weights, never the average: training continues from
    where it actually is, and an average fed back into itself would compound
    at every step after the resume. The average rides in `trainer_state.pt`
    beside the optimizer, which is the other thing that must survive a pause
    and is nobody's finished artifact either.
    """
    import shutil

    import torch

    t0 = time.time()
    staged = io.checkpoints() / "last.staging"
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir(parents=True)
    engine.save_weights(staged)
    torch.save(
        {
            "step": step,
            "optimizer": optimizer.state_dict(),
            "torch_rng": torch.get_rng_state(),
            **({"ema": ema.state_dict()} if ema is not None else {}),
        },
        staged / "trainer_state.pt",
    )
    # A tiny sidecar so the app can place this checkpoint in the timeline:
    # the step lives inside trainer_state.pt, which the torch-free server
    # cannot open.
    try:
        with open(staged / "step.json", "w", encoding="utf-8") as f:
            json.dump({"step": int(step)}, f)
    except OSError:
        pass
    io.publish_last(staged)
    if timed:
        # Part of the pause-latency breakdown (the other parts are logged by
        # check_control and train.main). Saving from a GPU also drains the
        # queued async work, so this number includes the in-flight step.
        print(f"pause: checkpoint of step {step} saved in "
              f"{time.time() - t0:.1f}s", flush=True)


def _read_meta(d) -> dict:
    try:
        with open(d / "meta.json", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_meta(d, meta: dict) -> None:
    try:
        with open(d / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f)
    except OSError:
        pass


def _sample_fingerprint(pairs: list, sampling: dict) -> str:
    """Identifies the round: change a prompt, a size, the seed or the sampler
    and the images would come out different, so the old ones no longer stand
    in for them."""
    import hashlib

    payload = json.dumps({
        "pairs": pairs,
        "seed": int(sampling.get("seed", 42)),
        "steps": int(sampling.get("steps", 25)),
        "cfg": float(sampling.get("cfg", 6.0)),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _unfinished_round(io: JobIO) -> "int | None":
    """The newest sample round that promised more images than it wrote, or
    None. That is exactly what a pause mid-round leaves behind."""
    root = io.dir / "samples"
    if not root.is_dir():
        return None
    best = None
    for d in root.iterdir():
        if not d.is_dir() or not d.name.startswith("step-"):
            continue
        try:
            step = int(d.name.split("-", 1)[1])
        except ValueError:
            continue
        meta = _read_meta(d)
        expected = int(meta.get("expected") or 0)
        if not expected:
            continue
        done = len([f for f in d.glob("p*.png")])
        if done < expected and (best is None or step > best):
            best = step
    return best


def _generate_samples(io: JobIO, engine, sampling: dict, step: int,
                      note=lambda text: None) -> None:
    d = io.sample_dir(step)
    # Prompts are (prompt, negative, width, height) tuples; a 0 size falls
    # back to the section's shared size (and then to the model's native one,
    # resolved in the engine).
    shared_w = int(sampling.get("width", 0)) or None
    shared_h = int(sampling.get("height", 0)) or None
    pairs: list[tuple[str, str, "int | None", "int | None"]] = []
    for p in sampling.get("prompts", []):
        pairs.append((
            p.get("prompt", ""), p.get("negative") or "",
            int(p.get("width") or 0) or shared_w,
            int(p.get("height") or 0) or shared_h,
        ))
    # A resumed run replays steps it has already sampled — and a sample round
    # is minutes of the GPU that training could be using. If this exact round
    # was rendered before (same prompts, sizes, seed, sampler settings) its
    # images still say what they said, so keep them.
    want = _sample_fingerprint(pairs, sampling)
    meta = _read_meta(d)
    have = sorted(f.name for f in d.glob("p*.png"))
    if meta.get("fingerprint") == want and len(have) >= len(pairs):
        print(f"samples for step {step} already rendered — keeping them",
              flush=True)
        return

    # Announce the round before rendering it: the app shows the round the
    # moment it starts, with a placeholder per image still to come, so a long
    # round is visible progress instead of several silent minutes. Any images
    # left from an earlier, different round would be counted as done, so they
    # go first.
    for stale in d.glob("p*.png"):
        try:
            stale.unlink()
        except OSError:
            pass
    meta["expected"] = len(pairs)
    meta.pop("fingerprint", None)   # not these images until they exist
    # When this round actually starts rendering. A round interrupted by a
    # pause is rendered again on resume, and it belongs in the timeline
    # where that happened — not at the moment the folder was first created,
    # hours earlier.
    meta["started"] = round(time.time(), 3)
    _write_meta(d, meta)

    written = 0

    def write(slot: int, img) -> None:
        # Atomically: the app lists whatever files are there, and a half-written
        # PNG loads as a broken (black) image that the browser then caches.
        nonlocal written
        tmp = d / f".p{slot:02d}.png.tmp"
        img.save(tmp, "PNG")   # the name has no usable extension for Pillow
        atomicio.replace(tmp, d / f"p{slot:02d}.png")
        # A round is minutes long and renders one image at a time; this is
        # what the app shows under the Sample phase while it runs.
        written += 1
        note(f"{written} / {len(pairs)}")

    note(f"0 / {len(pairs)}")

    images = engine.generate_samples(
        pairs,
        seed=int(sampling.get("seed", 42)),
        steps=int(sampling.get("steps", 25)),
        cfg=float(sampling.get("cfg", 6.0)),
        batch=int(sampling.get("batch", 1) or 1),
        on_image=write,
        # Checked once per denoising step: a sample round is minutes of GPU
        # time, and it used to be the one phase a pause could not interrupt.
        check=io.check_control,
    )
    # `on_image` wrote them as they finished; catch anything an engine that
    # does not report progress produced.
    for i, img in enumerate(images):
        if img is not None and not (d / f"p{i:02d}.png").exists():
            write(i, img)
    # Stamp what these images are of, so a later run can recognise them. The
    # start time written by `sample_dir` is preserved.
    meta["fingerprint"] = want
    _write_meta(d, meta)
