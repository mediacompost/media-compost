"""Pure-stdlib training math: buckets, weighted sampling, caption composition.

This module runs inside the dedicated training env (which does NOT have
``media_compost`` installed), so it must stay stdlib-only. It is also imported
directly by the backend's pytest suite to unit-test the math, so keep every
function deterministic given its ``random.Random``.

All configuration arrives as plain dicts (parsed ``config.json`` /
``manifest.json``) — no Pydantic here.
"""

from __future__ import annotations

import math
import math
import random

# ---- aspect-ratio buckets ---------------------------------------------------


def make_buckets(base: int, step: int = 64, max_aspect: float = 2.0) -> list[tuple[int, int]]:
    """All (w, h) buckets at a roughly constant pixel area of ``base``².

    Widths run from ``base/max_aspect`` to ``base*max_aspect`` in ``step``
    increments; each height is the largest step multiple that keeps the area at
    or under base². The square bucket is always included.
    """
    area = base * base
    lo = int(math.ceil(base / max_aspect / step) * step)
    hi = int(math.floor(base * max_aspect / step) * step)
    out: set[tuple[int, int]] = set()
    w = lo
    while w <= hi:
        h = int(area // w // step * step)
        if h >= step:
            aspect = w / h
            if 1.0 / max_aspect - 1e-9 <= aspect <= max_aspect + 1e-9:
                out.add((w, h))
        w += step
    out.add((base, base))
    return sorted(out)


def assign_bucket(width: int, height: int, buckets: list[tuple[int, int]]) -> int:
    """Index of the bucket whose aspect ratio is nearest (in log space)."""
    if width <= 0 or height <= 0:
        width = height = 1
    target = math.log(width / height)
    best, best_d = 0, float("inf")
    for i, (bw, bh) in enumerate(buckets):
        d = abs(math.log(bw / bh) - target)
        if d < best_d:
            best, best_d = i, d
    return best


# ---- weighted dataset sampling ----------------------------------------------


class Sampler:
    """Bucket-consistent batches, one SHUFFLED PASS at a time.

    Every entry is visited exactly once per epoch, in an order reshuffled each
    time — the classical arrangement, and the one "epoch" has to mean for the
    word to be worth using. It replaced weighted draws WITH REPLACEMENT, where
    a picture could turn up twice in a batch and not at all in the next pass,
    and where "how many times has the model seen this image" had no answer.

    A batch may only hold one bucket (the sizes have to match), so an epoch is
    a shuffle WITHIN each bucket, cut into batches, with the batches themselves
    shuffled together. A bucket whose entries do not divide by the batch size
    ends in a SHORT batch rather than dropping the remainder: dropping is the
    convention, and with bucketed data it silently means a bucket holding
    fewer entries than one batch never trains at all.

    WEIGHT IS ONE NUMBER APPLIED IN ONE OF TWO PLACES (`weight_mode`). An
    entry's share is the sum over the query pools holding it of
    ``pool.weight / pool_mass``, normalised so the MEAN entry has 1.0 — which
    is what keeps an epoch one pass long however the pools are weighted.
    Then:

    * ``"sampling"`` spends it on VISITS: an entry with 1.6 appears once, and
      a second time with probability 0.6, so the ratio between two pools holds
      over the run while an epoch stays an epoch.
    * ``"loss"`` spends it on the GRADIENT: every entry appears exactly once
      and its loss is multiplied instead. Equal exposure, unequal influence —
      the same ratio, bought with the same compute for every picture.

    Neither can conjure steps: a run has a fixed number, and what the ratio
    decides is how they are shared out.
    """

    def __init__(self, items: list[dict], groups: list[dict], rng: random.Random,
                 weight_mode: str = "sampling"):
        self.rng = rng
        self.weight_mode = weight_mode
        weights = [0.0] * len(items)
        for g in groups:
            members = g.get("items", [])
            if not members:
                continue
            mass = sum(float(items[i].get("weight", 1.0)) for i in members)
            if mass <= 0:
                continue
            share = float(g.get("weight", 1.0)) / mass
            for idx in members:
                weights[idx] += share * float(items[idx].get("weight", 1.0))
        self.item_weights = weights
        # Per bucket: parallel lists of item index and cumulative weight.
        by_bucket: dict[int, list[int]] = {}
        for idx, it in enumerate(items):
            if weights[idx] > 0:
                by_bucket.setdefault(int(it.get("bucket", 0)), []).append(idx)
        self.buckets = sorted(by_bucket)
        self.bucket_items = [by_bucket[b] for b in self.buckets]
        self.bucket_mass = [
            sum(weights[i] for i in members) for members in self.bucket_items
        ]
        if not self.buckets:
            raise ValueError("no items with positive sampling weight")
        # Normalised so the mean entry is 1.0: that is what makes an epoch one
        # pass over the data whatever the pools weigh, and it is the same
        # number whether it is spent on visits or on the loss.
        live = [w for w in weights if w > 0]
        mean = sum(live) / len(live)
        self.scale = [w / mean if w > 0 else 0.0 for w in weights]
        self._queue: list[tuple[int, list[int]]] = []

    def loss_scale(self, index: int) -> float:
        """The entry's weight as a LOSS multiplier — 1.0 unless the run spends
        its query weights there rather than on how often a picture is seen."""
        return self.scale[index] if self.weight_mode == "loss" else 1.0

    def batches_per_epoch(self, batch_size: int) -> int:
        """How many batches one pass takes — what turns epochs into steps.

        Expected rather than exact under `"sampling"`, where a fractional
        weight is a coin flip per entry per epoch; the count is stable to
        within a batch and is only ever used to say how long a run will be.
        """
        total = 0
        for members in self.bucket_items:
            n = sum(self.scale[i] for i in members) if self.weight_mode == "sampling" \
                else len(members)
            total += max(1, math.ceil(n / max(1, batch_size)))
        return total

    def batch(self, batch_size: int) -> tuple[int, list[int]]:
        """(bucket id, item indices) for one training batch, from the current
        pass — refilling and reshuffling when it runs out."""
        if not self._queue:
            self._fill_epoch(batch_size)
        return self._queue.pop()

    def _fill_epoch(self, batch_size: int) -> None:
        out: list[tuple[int, list[int]]] = []
        for b, members in zip(self.buckets, self.bucket_items):
            pool: list[int] = []
            for idx in members:
                for _ in range(self._visits(idx)):
                    pool.append(idx)
            if not pool:
                continue
            self.rng.shuffle(pool)
            for k in range(0, len(pool), batch_size):
                # The tail is kept, not dropped — see the class docstring.
                out.append((b, pool[k:k + batch_size]))
        # Buckets interleave: without this a pass would train every portrait
        # and then every landscape, which is a schedule rather than a shuffle.
        self.rng.shuffle(out)
        # `batch()` pops from the end, so reverse to hand them out in order.
        out.reverse()
        self._queue = out

    def _visits(self, index: int) -> int:
        """How many times this entry appears in one pass."""
        if self.weight_mode != "sampling":
            return 1 if self.scale[index] > 0 else 0
        w = self.scale[index]
        n = int(w)
        # The fraction is a coin flip, so the RATIO between two pools holds
        # over a run even though neither can appear 1.6 times in one pass.
        return n + (1 if self.rng.random() < w - n else 0)


# ---- caption composition ------------------------------------------------------


def partial_match(a: str, b: str) -> bool:
    """True when the shorter of the two tags appears as a whole-word phrase
    inside the other ("shirt" ⊂ "white shirt", underscores count as spaces).
    Equal tags are NOT partial matches."""
    wa = a.replace("_", " ").split()
    wb = b.replace("_", " ").split()
    if not wa or not wb or len(wa) == len(wb):
        return False
    small, big = (wa, wb) if len(wa) < len(wb) else (wb, wa)
    k = len(small)
    return any(big[i:i + k] == small for i in range(len(big) - k + 1))


def _pick_skipping_partials(
    order: list[str], n: int, always: list[str]
) -> list[str]:
    """Walk the preference order accepting up to ``n`` tags, keeping the set
    free of partial matches: a candidate that is a partial of an accepted or
    guaranteed tag is skipped (the next candidate takes its slot), and a
    candidate that is MORE specific than an accepted tag replaces it (the
    freed slot is refilled from the remaining order)."""
    accepted: list[str] = []
    for t in order:
        if len(accepted) >= n:
            break
        if any(partial_match(t, u) and len(t) < len(u) for u in accepted + always):
            continue  # t is the generic side of a pair — draw another instead
        # t is the specific side: drop accepted tags it contains.
        accepted = [u for u in accepted if not partial_match(t, u)]
        accepted.append(t)
    return accepted


def pick_tags(
    tags: list[str],
    cfg: dict,
    tag_freq: dict[str, int],
    rng: random.Random,
) -> list[str]:
    """The tags used for ONE visit of an item (re-picked fresh every visit).

    Order of operations: drop excluded tags; tags listed in ``always_tags``
    are guaranteed a slot **when the item actually has them** (they are never
    forced onto items that lack them, and they are exempt from the min/max
    pick limits); the rest is randomly picked between ``min_tags`` and
    ``max_tags`` — uniformly, or with probability proportional to inverse
    frequency when ``balance`` is ``inverse_freq`` (rare tags surface as often
    as common ones across the run). With ``skip_partial_tags`` (default on)
    the picked set never contains a tag that is a whole-word part of another
    picked or guaranteed tag — the generic one is replaced by the next random
    candidate. The result is shuffled (so guaranteed tags land at random
    positions) unless ``shuffle`` is off, in which case the item's original
    tag order is kept.
    """
    excluded = set(cfg.get("exclude_tags", []))
    always_set = set(cfg.get("always_tags", [])) - excluded
    remaining = [t for t in tags if t not in excluded]
    always = [t for t in remaining if t in always_set]
    pool = [t for t in remaining if t not in always_set]

    min_n = int(cfg.get("min_tags", 0))
    max_n = int(cfg.get("max_tags", 0))
    # No limits configured -> use the whole pool; otherwise draw a count
    # between min and max (each clamped to what's available).
    if min_n <= 0 and max_n <= 0:
        n = len(pool)
    else:
        hi = len(pool) if max_n <= 0 else min(max_n, len(pool))
        lo = min(min_n, hi)
        n = rng.randint(lo, hi) if hi > lo else hi

    skip_partial = bool(cfg.get("skip_partial_tags", True))
    if n >= len(pool) and not skip_partial:
        picked = list(pool)
    else:
        # Full preference ORDER (not just n draws) so skipped partials can be
        # replaced by the next candidates without re-rolling.
        if cfg.get("balance") == "inverse_freq":
            order = _weighted_sample_without_replacement(
                pool, [1.0 / max(1, tag_freq.get(t, 1)) for t in pool],
                len(pool), rng,
            )
        else:
            order = rng.sample(pool, len(pool))
        picked = _pick_skipping_partials(order, n, always) if skip_partial else order[:n]

    out = always + picked
    if cfg.get("shuffle", True):
        rng.shuffle(out)
    else:
        order2 = {t: i for i, t in enumerate(tags)}
        out.sort(key=lambda t: order2.get(t, len(order2)))
    return out


def _weighted_sample_without_replacement(
    pool: list[str], weights: list[float], n: int, rng: random.Random
) -> list[str]:
    # Efraimidis–Spirakis: keys u^(1/w) — take the n largest.
    keyed = sorted(
        ((rng.random() ** (1.0 / w), t) for t, w in zip(pool, weights)),
        reverse=True,
    )
    return [t for _, t in keyed[:n]]


def _group_label(group: dict, cfg: dict) -> str:
    """What to write in front of a group's tags, or "" for nothing.

    A group with no subjects gets no label under the "subject" choice rather
    than falling back to its own name: the setting said what to write, and
    quietly writing something else is how bookkeeping words end up in prompts.
    """
    which = cfg.get("group_label", "none")
    if which == "group":
        return (group.get("name") or "").strip()
    if which == "subject":
        names = [n.strip() for n in (group.get("subjects") or []) if n.strip()]
        return ", ".join(names)
    return ""


def tag_writer(cfg: dict, aliases: dict, rng: random.Random):
    """How a picked tag is WRITTEN: sometimes one of its aliases, then spaces.

    The substitution lives here, at OUTPUT time, and nowhere else. A tag's
    aliases are the other words for one thing ("cat" / "kitty"), and a model
    trained only on the canonical name answers only to that word — but the
    canonical name is also what the rest of the run is keyed on: the boxes a
    crop must keep inside it, `tag_freq`, the loss weight. So the returned tag
    list stays canonical and only the PROMPT varies, exactly as `force_tags`
    reach the prompt without joining that list.

    Rolled per tag per visit, so one item drawn twice reads differently and the
    tag set is spread across the run rather than one alias per tag being
    chosen once and then repeated.
    """
    p = float(cfg.get("alias_p", 0.0) or 0.0)
    spaces = cfg.get("underscores_to_spaces", True)
    # VALUE RULES, arriving as a finished tag → {text, keep} map the manifest
    # builder resolved (`dataset._value_map`) — a raw `height:172cm` token
    # teaches nothing a text encoder can read, so a matched tag is written as
    # its rule's text instead, with `keep` riding the raw tag alongside. The
    # returned tag LIST stays raw either way, like the alias substitution
    # above it: boxes, `tag_freq` and the loss weight are keyed on the name.
    vmap = cfg.get("value_map") or {}
    sep = cfg.get("separator") or ", "
    # THE COMMENT, where the run asks for it (`tag_text`): a tag → comment map
    # the manifest builder resolved (`dataset._tag_comments`). "comment"
    # writes the comment IN PLACE of the name, "both" the name with the
    # comment in brackets; a tag with no comment is written as its name
    # either way, and "name" — the default — never reads the map.
    tag_text = cfg.get("tag_text") or "name"
    comments = (cfg.get("tag_comments") or {}) if tag_text != "name" else {}

    def write(tag: str) -> str:
        alts = aliases.get(tag) if p > 0 else None
        # `rng.random()` is drawn only when there is something to choose, so a
        # run with no aliases consumes exactly the randomness it always did and
        # its prompts are unchanged.
        name = rng.choice(alts) if alts and rng.random() < p else tag
        raw = name.replace("_", " ") if spaces else name
        comment = str(comments.get(tag) or "").strip()
        if comment:
            raw = comment if tag_text == "comment" else f"{raw} ({comment})"
        rule = vmap.get(tag)
        if rule is None:
            return raw
        text = str(rule.get("text") or "").strip()
        if not text:
            return raw
        # `keep` embeds the joining separator, like a group block does — the
        # two are one token of the tag list however they are spelled out.
        return f"{text}{sep}{raw}" if rule.get("keep") else text

    return write


def group_tag_text(
    used: list[str],
    item: dict,
    cfg: dict,
    rng: random.Random,
    aliases: dict | None = None,
) -> str:
    """The picked tags laid out by the TAG GROUP they sit in.

    A per-item tag group is usually about one thing in the picture — Alice's
    hair and dress, Bob's hat — and a flat comma list throws that away, leaving
    the model to guess which adjective belongs to whom. Grouped, one line says
    one thing.

    What a block is LABELLED with is a choice (``group_label``): nothing, the
    group's own name, or the subjects it is about. Plenty of libraries name
    groups for the person tagging ("front figure") while the subject is the
    thing you would actually type at generation time ("Alice").

    A tag in two groups is written under the FIRST one that claims it — the
    same tag twice in a prompt teaches nothing and reads as emphasis.
    Ungrouped tags lead, because they describe the scene the groups sit in.
    """
    fmt = tag_writer(cfg, aliases or {}, rng)
    groups = item.get("tag_groups") or []
    if not groups:
        return (cfg.get("separator") or ", ").join(fmt(t) for t in used)

    sep = cfg.get("separator") or ", "
    remaining = list(used)
    blocks: list[str] = []
    named: list[str] = []

    for g in groups:
        members = [t for t in remaining if t in set(g.get("tags") or [])]
        if not members:
            continue
        remaining = [t for t in remaining if t not in set(members)]
        # `used` is already in the order the pick produced (shuffled when the
        # run shuffles), so taking a subset of it keeps that randomness.
        text = sep.join(fmt(t) for t in members)
        label = _group_label(g, cfg)
        named.append(f"{label}: {text}" if label else text)

    # Ungrouped first: they are the scene the groups are things inside.
    if remaining:
        blocks.append(sep.join(fmt(t) for t in remaining))
    blocks.extend(named)
    return (cfg.get("group_separator") or "\n").join(b for b in blocks if b)


def compose_caption_and_tags(
    item: dict,
    cfg: dict,
    tag_freq: dict[str, int],
    rng: random.Random,
    aliases: dict | None = None,
) -> tuple[str, list[str]]:
    """One training prompt for one visit of ``item``, plus the *raw* tag names
    it contains (used to keep those tags' bounding boxes inside the crop).

    Tag selection/matching runs on the raw tag names; formatting (underscore
    replacement, the joining separator) is applied only here, at output time.

    An entry may carry ``force_tags`` — the words a DEGRADED copy of a picture
    is marked with. They are always in the prompt: they are the only thing
    saying this sample is the bad version, and a degraded picture that reached
    the model unmarked would teach it that its clean neighbours look like this
    too. Three consequences, and each is a rule the ordinary tags do not get:

    * They survive the random pick, the min/max cap and ``exclude_tags``,
      because they are not part of the item's own tag set to choose from.
    * They are NOT in the returned tag list. That list drives box-aware
      cropping and inverse-frequency loss weighting, and a synthetic tag has no
      box and no ``tag_freq`` entry — it would read as maximally rare and skew
      every weight in the batch.
    * They suppress caption **dropout** entirely. Dropout exists to keep the
      CFG unconditional path healthy by training on an empty prompt, and an
      empty prompt over a degraded picture teaches that path to produce
      compression artifacts. A degraded entry is never the sample to drop.
    """
    forced = [t for t in (item.get("force_tags") or []) if str(t).strip()]
    if not forced and rng.random() < float(cfg.get("dropout", 0.0)):
        return "", []
    # An entry may pin its own mode: a "caption + tags" run contributes the
    # picture TWICE, once under each, and this is which of the two this visit
    # is. Absent, the run's own source applies — which is every entry of a
    # single-mode run.
    source = item.get("prompt_mode") or cfg.get("source", "tags")
    if source == "caption":
        source = "captions"
    parts: list[str] = []
    used: list[str] = []
    trigger = cfg.get("trigger", "").strip()
    # A REGULARIZATION entry never carries the trigger word, and that is the
    # whole point of it being one. Those pictures are in the run to remind the
    # model what the ordinary version of a thing looks like; putting the
    # trigger on them would teach the trigger to mean the ordinary version,
    # which is the exact opposite of what it is for.
    if trigger and not item.get("reg"):
        parts.append(trigger)
    # "none" is the TRIGGER ALONE and reaches neither branch below — stated
    # rather than left to fall through, because a source this file does not
    # recognise producing a bare trigger is the right behaviour by accident
    # and a silent one by nature.
    if source in ("captions", "both"):
        captions = item.get("captions", [])
        if captions:
            parts.append(rng.choice(captions).strip())
    if source in ("tags", "both"):
        used = pick_tags(item.get("tags", []), cfg, tag_freq, rng)
        if cfg.get("group_tags"):
            # One part, not one per tag: the block carries its own two
            # separators and must not be re-joined by the outer one.
            block = group_tag_text(used, item, cfg, rng, aliases)
            if block:
                parts.append(block)
        else:
            write = tag_writer(cfg, aliases or {}, rng)
            parts.extend(write(t) for t in used)
    if forced:
        # At the tail, where booru convention puts a quality note — and after
        # the group blocks, which are about what is IN the picture.
        out = [str(t).strip() for t in forced]
        if cfg.get("underscores_to_spaces", True):
            out = [t.replace("_", " ") for t in out]
        parts.extend(out)
    return (cfg.get("separator") or ", ").join(p for p in parts if p), used


def compose_caption(
    item: dict,
    cfg: dict,
    tag_freq: dict[str, int],
    rng: random.Random,
) -> str:
    return compose_caption_and_tags(item, cfg, tag_freq, rng)[0]


def compose_instruction(
    item: dict,
    cfg: dict,
    rng: random.Random,
) -> tuple[str, list[dict]]:
    """One training prompt for one visit of an INSTRUCTION target, plus the
    ordered reference images the model is shown for it.

    An item may carry several instructions and one is drawn per visit, exactly
    as one caption is — and the text and its references come out of the SAME
    object, so they can never end up belonging to different instructions.

    The prompt is the trigger and the instruction, and nothing else: an edit
    model's prompt is an imperative sentence, and a booru tag list after it
    teaches the model that the list is part of what was asked for.
    """
    entries = item.get("instructions") or []
    if not entries:
        return "", []
    picked = rng.choice(entries)
    refs = list(picked.get("refs") or [])
    # Dropout empties the TEXT and keeps the references. What guidance compares
    # against is the unprompted path; with the references gone as well, the
    # sample degenerates into teaching the model to invent the target from
    # nothing.
    if rng.random() < float(cfg.get("dropout", 0.0)):
        return "", refs
    parts: list[str] = []
    trigger = cfg.get("trigger", "").strip()
    # A regularization entry is the reminder of what the model already knows;
    # the trigger word on it would teach the trigger to mean the ordinary
    # thing — the caption path's rule, which this one had skipped.
    if trigger and not item.get("reg"):
        parts.append(trigger)
    text = (picked.get("text") or "").strip()
    if text:
        parts.append(text)
    return (cfg.get("separator") or ", ").join(parts), refs


def ref_size(rw: int, rh: int, budget: int, step: int) -> tuple[int, int]:
    """The pixel size a REFERENCE image is encoded at for a visit.

    Its own aspect ratio, scaled to the target's pixel budget, rounded to the
    model's latent step. Deliberately NOT the target's exact width and height:
    a reference squashed to the result's aspect is a distortion the model
    would have to learn to undo, and an edit dataset's references are often a
    different shape from what was made out of them (a crop, a photograph
    beside a drawn page).

    Rounding to `step` is not cosmetic — every one of these models patchifies,
    so a size that is not a multiple of it fails inside the reshape.
    """
    rw, rh = max(1, int(rw)), max(1, int(rh))
    scale = math.sqrt(float(budget) / float(rw * rh))
    w = max(step, int(round(rw * scale / step)) * step)
    h = max(step, int(round(rh * scale / step)) * step)
    return w, h


def ref_layout(refs: list[dict], budget: int, step: int) -> tuple:
    """How a visit's references will SHAPE the model's input sequence.

    Two visits sharing this can be run in one forward pass; two that do not
    cannot be stacked at all, because the reference tokens are concatenated
    onto the noisy latent and tensors of different length do not batch. The
    loop groups a micro-batch by this and recombines the losses (see
    `loop._forward`), so the ordinary case — every visit carrying one
    reference of the same shape — stays a single pass.
    """
    return tuple(ref_size(r.get("width") or 1, r.get("height") or 1,
                          budget, step)
                 for r in refs)


def compose_visit(
    item: dict,
    cfg: dict,
    tag_freq: dict[str, int],
    rng: random.Random,
    aliases: dict | None = None,
) -> tuple[str, list[str], list[dict]]:
    """``(prompt, the raw tag names in it, the ordered reference images)``.

    The ONE entry point the training loop calls, so "an instruction run never
    runs the caption path" is a single branch to read rather than a condition
    buried inside a thirty-line function.
    """
    if cfg.get("source") == "instructions":
        text, refs = compose_instruction(item, cfg, rng)
        return text, [], refs
    text, used = compose_caption_and_tags(item, cfg, tag_freq, rng, aliases)
    return text, used, []


# ---- inverse-frequency loss weighting ----------------------------------------


def mean_inverse_freq(tags: list[str], tag_freq: dict[str, int]) -> float:
    if not tags:
        return 1.0
    return sum(1.0 / max(1, tag_freq.get(t, 1)) for t in tags) / len(tags)


def dataset_mean_inverse_freq(items: list[dict], tag_freq: dict[str, int]) -> float:
    vals = [mean_inverse_freq(it.get("tags", []), tag_freq) for it in items]
    vals = [v for v in vals if v > 0]
    return sum(vals) / len(vals) if vals else 1.0


def loss_weight(
    used_tags: list[str], tag_freq: dict[str, int], dataset_mean: float
) -> float:
    """Per-sample loss multiplier equalizing tag influence: samples dominated
    by rare tags count more, frequent-tag samples less. Clamped to [0.25, 4]
    so a single sample can never destabilize a step."""
    if dataset_mean <= 0:
        return 1.0
    w = mean_inverse_freq(used_tags, tag_freq) / dataset_mean
    return max(0.25, min(4.0, w))


# ---- crop -------------------------------------------------------------------


def cover_size(width: int, height: int, bw: int, bh: int) -> tuple[int, int]:
    """Smallest size >= (bw, bh) preserving aspect (resize-to-cover)."""
    scale = max(bw / max(1, width), bh / max(1, height))
    return max(bw, math.ceil(width * scale)), max(bh, math.ceil(height * scale))


def crop_offset(
    cw: int, ch: int, bw: int, bh: int, random_crop: bool, rng: random.Random,
    quantum: int = 1,
) -> tuple[int, int]:
    """Top-left offset of a (bw, bh) crop inside (cw, ch). ``quantum`` snaps
    offsets to a grid — pass 8 when cropping VAE latents in pixel terms, or 1
    in latent units."""
    mx, my = max(0, cw - bw), max(0, ch - bh)
    if random_crop:
        x, y = rng.randint(0, mx), rng.randint(0, my)
    else:
        x, y = mx // 2, my // 2
    return (x // quantum) * quantum, (y // quantum) * quantum


def flip_boxes(boxes: list) -> list:
    """Mirror fractional (x, y, w, h) boxes horizontally (for flipped visits).

    A box may carry a POLYGON as a conditional fifth element ([[x, y], ...]
    vertices in the same fractional frame; the first four values are then its
    bounding box) — the vertices mirror with it."""
    out = []
    for b in boxes:
        f = [1.0 - b[0] - b[2], b[1], b[2], b[3]]
        if len(b) > 4 and b[4]:
            f.append([[1.0 - p[0], p[1]] for p in b[4]])
        out.append(f)
    return out


def box_mask_cells(
    boxes: list, x: float, y: float, w: float, h: float,
    cw: float, ch: float, lw: int, lh: int,
) -> list[tuple[int, int, int, int]]:
    """The latent-cell rectangles the masked-region boxes cover, after a crop.

    ``boxes`` are (x, y, w, h) FRACTIONS of the full (cw, ch) frame — the
    shape ``mask_boxes`` carries and ``flip_boxes`` mirrors — and the visit's
    crop is the (x, y, w, h) window of that frame (in the same units as cw/ch:
    latent cells for a cached latent, pixels for a fresh encode). Each box is
    mapped into the crop and onto the ``lw``×``lh`` cell grid.

    Cells are rounded OUTWARD (floor the near edge, ceil the far one): the
    mask exists to hide something, and a watermark's last half-covered cell is
    exactly where it is most legible. A box the crop excludes yields nothing.
    """
    out: list[tuple[int, int, int, int]] = []
    if w <= 0 or h <= 0:
        return out
    for b in boxes:
        if len(b) > 4 and b[4]:
            out.extend(_poly_cells(b[4], x, y, w, h, cw, ch, lw, lh))
            continue
        bx0, by0 = b[0] * cw, b[1] * ch
        bx1, by1 = bx0 + b[2] * cw, by0 + b[3] * ch
        x0 = max(0, math.floor((bx0 - x) / w * lw))
        x1 = min(lw, math.ceil((bx1 - x) / w * lw))
        y0 = max(0, math.floor((by0 - y) / h * lh))
        y1 = min(lh, math.ceil((by1 - y) / h * lh))
        if x1 > x0 and y1 > y0:
            out.append((x0, y0, x1, y1))
    return out


def _poly_cells(points: list, x: float, y: float, w: float, h: float,
                cw: float, ch: float, lw: int, lh: int
                ) -> list[tuple[int, int, int, int]]:
    """Cell spans a POLYGON covers on the grid — the shape, not its bbox.

    Scanline over the polygon in cell units: each cell row is sampled at its
    top, centre and bottom (plus the polygon's own extreme heights, for a
    shape shallower than a row), the even-odd crossing spans are unioned, and
    each span is rounded OUTWARD like the rectangular path — a half-covered
    edge cell is where a watermark is most legible.
    """
    if len(points) < 3:
        return []
    pts = [((float(px) * cw - x) / w * lw, (float(py) * ch - y) / h * lh)
           for px, py in points]
    ys = [p[1] for p in pts]
    y_lo, y_hi = min(ys), max(ys)
    eps = 1e-6
    out: list[tuple[int, int, int, int]] = []
    for row in range(max(0, math.floor(y_lo)), min(lh, math.ceil(y_hi))):
        samples = {row + eps, row + 0.5, row + 1 - eps,
                   y_lo + eps, y_hi - eps}
        spans: list[tuple[float, float]] = []
        for sy in samples:
            if sy < row or sy > row + 1 or sy < y_lo or sy > y_hi:
                continue
            crossings = []
            for i in range(len(pts)):
                (ax, ay), (bx, by) = pts[i], pts[(i + 1) % len(pts)]
                if (ay <= sy) != (by <= sy):
                    crossings.append(ax + (sy - ay) / (by - ay) * (bx - ax))
            crossings.sort()
            for j in range(0, len(crossings) - 1, 2):
                spans.append((crossings[j], crossings[j + 1]))
        spans.sort()
        open_span: tuple[int, int] | None = None
        for a, b in spans:
            c0, c1 = max(0, math.floor(a)), min(lw, math.ceil(b))
            if c1 <= c0:
                continue
            if open_span is not None and c0 <= open_span[1]:
                open_span = (open_span[0], max(open_span[1], c1))
            else:
                if open_span is not None:
                    out.append((open_span[0], row, open_span[1], row + 1))
                open_span = (c0, c1)
        if open_span is not None:
            out.append((open_span[0], row, open_span[1], row + 1))
    return out


def crop_offset_for_boxes(
    cw: int, ch: int, bw: int, bh: int, boxes: list,
    random_crop: bool, rng: random.Random, quantum: int = 1,
    min_cover: float = 0.9,
) -> tuple[int, int]:
    """Like :func:`crop_offset`, but keeps the prompt tags' bounding boxes
    mostly inside the crop. ``boxes`` are (x, y, w, h) fractions of the
    (cw, ch) frame. Per axis, each box constrains the offset to an interval
    where at least ``min_cover`` of the box's achievable extent stays inside;
    the intervals are intersected across boxes and the offset drawn inside
    (random) or placed as close to the plain center as allowed (center crop).
    When no offset satisfies every box, the conflicting bounds are split down
    the middle — a best-effort compromise between the boxes."""
    if not boxes:
        return crop_offset(cw, ch, bw, bh, random_crop, rng, quantum)
    x = _axis_offset([(b[0] * cw, (b[0] + b[2]) * cw) for b in boxes],
                     cw, bw, random_crop, rng, min_cover)
    y = _axis_offset([(b[1] * ch, (b[1] + b[3]) * ch) for b in boxes],
                     ch, bh, random_crop, rng, min_cover)
    return (int(x) // quantum) * quantum, (int(y) // quantum) * quantum


def _axis_offset(spans, full: int, crop: int, random_crop: bool,
                 rng: random.Random, min_cover: float) -> int:
    m = max(0, full - crop)
    lo, hi = 0.0, float(m)
    for b0, b1 in spans:
        # overlap([o, o+crop], [b0, b1]) >= t  <=>  o in [b0 + t - crop, b1 - t]
        t = min_cover * min(b1 - b0, crop)
        lo = max(lo, min(float(m), b0 + t - crop))
        hi = min(hi, max(0.0, b1 - t))
    if lo > hi:
        return int(round(max(0.0, min(float(m), (lo + hi) / 2.0))))
    if random_crop:
        return int(lo + rng.random() * (hi - lo))
    return int(max(lo, min(hi, m / 2.0)))
