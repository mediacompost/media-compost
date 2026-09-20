"""Materialize a training job's dataset into ``manifest.json``.

Runs in the manager thread right before the trainer spawns. The manifest is
self-contained (absolute file paths, resolved tags/captions, bucket
assignments, tag frequencies) because the trainer process cannot import
``media_compost`` — it sees only this file.

**The library is read through the PUBLIC Python API and nothing else.** That
is what lets this whole subsystem live in a package of its own, and it is not
merely tidiness: this module used to build a `QueryCtx` by hand, which made it
the third place that had to know what a dataset query means. The other two are
the item grid and the scripting API, and keeping three copies in step is
exactly what the "every path that evaluates a query must build the SAME
QueryCtx" rule exists to police — a rule that had already been broken
once here, with `subject:` matching nothing in a training run while matching
in the app.

`lib.query()` answers instead, so a dataset query means what the search field
means by construction rather than by discipline. It also runs through the SQL
prefilter this module deliberately bypassed, so a selective query costs a
statement or two rather than a scan of the whole library.
"""

from __future__ import annotations

import importlib.util
import io
import random
import shutil
from pathlib import Path
from typing import Optional

from media_compost import QueryGroup
from media_compost.hub import pipeline_files
from . import paths as tp
from . import videoframes
from .paths import TRAIN_SCRIPTS
from .spec import TrainingConfig

_compose = None


def compose_module():
    """The stdlib math shared with the trainer (``train/scripts/compose.py``),
    imported by file path since the trainer scripts are not a package."""
    global _compose
    if _compose is None:
        p = TRAIN_SCRIPTS / "compose.py"
        spec = importlib.util.spec_from_file_location("mc_train_compose", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _compose = mod
    return _compose


def _match_all(tree) -> bool:
    """Whether a dataset query selects its whole scope (an empty root group)."""
    return tree is None or not getattr(tree, "children", None)


def selection_scope(cfg) -> dict:
    """The scope every one of a run's queries is resolved in.

    An instruction run takes images only: a video frame is nobody's
    instruction target — nothing wrote an instruction for one particular
    frame — so unpacking films to discard every frame would be minutes spent
    producing nothing.

    `show_hidden` because HIDING a picture is about the grid, not about what
    the library holds: a dataset that quietly shrank when somebody tidied
    their view would be the worst kind of wrong, and the scan this replaced
    never excluded them. The scope otherwise reproduces that scan exactly —
    not trashed, of the run's kinds, and carrying an active file, which the
    query's own join to `files` enforces.

    Shared with the editor's preview endpoint, which would otherwise count a
    different set of pictures from the one the job trains on — and a warning
    drawn from a different set is a warning about nothing.
    """
    instructing = cfg.captions.source == "instructions"
    kinds = "image,video" if cfg.video.include and not instructing else "image"
    return {"kind": kinds, "show_hidden": True}


def regularization_ids(queries, matched) -> set[int]:
    """Which of the matched items are REGULARIZATION ones.

    An item reached by an ordinary pool is a training picture whatever else
    also matches it: being asked for by name wins, or a broad reg query
    ("everything in this library") would quietly demote the very pictures the
    run is about — and strip their trigger word, which is the failure here
    that would be hardest to spot.

    `matched` is one id list per query, positionally. Extracted so the editor's
    preview (`POST /api/train/queries/preview`) answers with THIS rule rather
    than a second copy of it: the warning it drives says a pool will be empty,
    which is only worth showing if it cannot disagree with what the run does.
    """
    reg = {i for q, ms in zip(queries, matched) if q.regularize for i in ms}
    reg -= {i for q, ms in zip(queries, matched) if not q.regularize
            for i in ms}
    return reg


def build_manifest(lib, config: dict, job_dir: Path, progress=None,
                   should_stop=None) -> dict:
    """Materialize the dataset. ``progress(text)`` is called with a short line
    for the job's phase note while videos are being unpacked (the only part
    that can take minutes), and ``should_stop()`` lets a cancel cut it short.
    """
    # A job may name a user-added model; publish those before validating so the
    # key resolves (the manager thread never went through a request).
    from . import usermodels

    from . import training_dir

    usermodels.refresh(training_dir(lib.path))
    cfg = TrainingConfig.model_validate(config)
    compose = compose_module()
    base = cfg.resolution()
    # ONE BUCKET FAMILY PER RESOLUTION, and `buckets` is their union — the
    # flat list every entry's `bucket` indexes into and the trainer batches
    # by. A run naming one size has one family, so this is the list it
    # always had.
    sizes = Resolutions(compose, cfg.resolutions(), cfg.buckets.bucket_step,
                        cfg.buckets.max_aspect)
    buckets = sizes.flat

    # Images, plus videos when the job asks for them (each becomes a run of
    # extracted frames further down). Sequence containers fall outside the kind
    # filter — a sequence's member pages are ordinary image items and match on
    # their own.
    instructing = cfg.captions.source == "instructions"
    scope = selection_scope(cfg)

    # SORTED, not the query's own order, in both places. `lib.query` answers
    # newest-first; the scan this replaced walked the items table, i.e. by id.
    # Two things ride on that and neither is cosmetic: the order here fixes
    # every index in `manifest["items"]` and therefore every value in
    # `groups[].items`, and the order WITHIN a pool is the order the trainer's
    # seeded sampler draws in — so leaving it to the sort would make the same
    # job with the same seed visit its pictures in a different order.
    matched: list[list[int]] = [sorted(lib.query(q.tree, **scope).ids())
                                for q in cfg.queries]
    selected_ids: list[int] = sorted({i for ms in matched for i in ms})
    if not selected_ids:
        raise ValueError("no items match the training queries")

    reg_ids = regularization_ids(cfg.queries, matched)

    # ONE ItemSet over the union, so the bulk reads below are one set of
    # statements rather than one per query.
    trees = [q.tree for q in cfg.queries]
    union = None if any(_match_all(t) for t in trees) \
        else QueryGroup(op="or", children=list(trees))
    selected = lib.query(union, **scope).prefetch("tags")

    # WHAT THE LIBRARY SAYS ABOUT A TAG, resolved to tag names once per run.
    # Lazy: a job using none of the meta-tag-level settings never reads it.
    meta_tags = MetaTagResolver(lib)
    # The tags the TAG SET vetoes mirroring for. Only the meta-level half:
    # `no_flip_tags` names tags outright and the trainer has always read that
    # list itself, so resolving it here as well would be one rule with two
    # implementations. What this adds is a per-entry flag, written only where
    # it applies — so a run with no such setting produces the manifest it
    # always did, byte for byte.
    #
    # Tested against the item's EFFECTIVE tags rather than the manifest's
    # filtered list: the veto is about the PICTURE (mirroring it would be
    # wrong), and hiding a tag from the prompt does not make the picture
    # symmetrical.
    no_flip = meta_tags.names(cfg.buckets.no_flip_meta_tags)

    excluded = {n.strip().lower()
                for n in cfg.captions.exclude_tag_group_meta_tags if n.strip()}
    dropped, origins = _dropped_by_tag_group(selected, excluded)

    # THE MASKED REGIONS, resolved to a lowercased name set once. `plus`
    # already lowercases both halves. Boxes are read even on an instruction
    # run — the target picture may carry a watermark too — where the
    # crop-steering `boxes` key stays absent as it always has.
    mask_names = set(meta_tags.plus(cfg.buckets.mask_loss_tags,
                                    cfg.buckets.mask_loss_meta_tags))
    boxes_by_item = (_tag_boxes(selected)
                     if not instructing or mask_names else {})
    # Only when the run asks for it: another read over every selected item,
    # and a manifest is already the slow part of a start.
    groups_by_item = (_tag_groups(selected)
                      if cfg.captions.group_tags and not instructing else {})
    ranges_by_item = _tag_ranges(selected) if cfg.video.include else {}
    captions_by_item, instructions_by_item, frame_captions_by_item = _prompts(
        selected, cfg.captions, cfg.video, instructing)

    # Frames of a previous run of this job are not automatically this run's
    # dataset — the interval, the queries or the library may all have moved
    # on — but they are usually the same frames, and sampling a film is
    # minutes of decoding. So nothing is thrown away here: `videoframes`
    # keeps a stamp of what each film's frames were made of and re-samples
    # only what no longer matches, and the sweep below drops the films this
    # run does not select at all. A run that is not taking frames keeps
    # none.
    frames_root = job_dir / "frames"
    if not cfg.video.include:
        shutil.rmtree(frames_root, ignore_errors=True)
    # The JOB-LOCAL latents do go, every time. They are named by an entry's
    # POSITION in this file (`loop.LatentSource._path`, for the entries with
    # no shared library latent — a video frame is not a stored file, so every
    # one of them is such an entry), and the whole point of building the
    # manifest again is that the positions are not the same list. Reusing
    # them would train on the previous dataset's pixels under this one's
    # prompts. The SHARED latents live in the items' own artifact folders and
    # are keyed by file, model and bucket; nothing here touches those.
    shutil.rmtree(job_dir / "latents", ignore_errors=True)

    index_of: dict[int, list[int]] = {}
    manifest_items: list[dict] = []
    degrade_counts: dict[str, int] = {}
    # Items left out for having nothing to say in this run's prompt mode…
    skipped_no_text = 0
    # …and video frames left out for the same reason, counted apart because
    # the two send you to different places: an untagged picture is tagged, a
    # frame with nothing to say usually means a time range that does not cover
    # it or captions this run does not let a frame inherit.
    skipped_frames = 0
    # …and items left out for being smaller than the bucket they would have
    # been fitted to, when the run refuses to upscale.
    skipped_small = 0
    # Images that actually carry a masked region, for the job log: a masked
    # tag nobody drew a box for is silent by construction, since the run
    # trains perfectly well with nothing masked.
    masked_items = 0
    # A cancel arriving mid-degrade leaves BOTH loops — the resolutions of
    # one picture and the pictures themselves.
    stopping = False

    items = {it.id: it for it in selected}
    videos = [i for i in selected_ids if items[i].kind == "video"]
    if cfg.video.include:
        # The folder is made even when no video matched: `_sweep_frames`
        # below is what keeps a film's extracted frames across builds, and a
        # run that takes frames must have somewhere to have kept them.
        frames_root.mkdir(parents=True, exist_ok=True)
        _sweep_frames(frames_root, {items[i].uid for i in videos})
    # ONE transaction around the whole loop. `Library._do` commits per call
    # outside one, so a degrading run would otherwise be a commit and a
    # sidecar enqueue per artifact — thousands of them.
    with lib.transaction():
        for iid in selected_ids:
            it = items[iid]
            af = it.active_file
            path = it.path
            if af is None or path is None or not path.exists():
                continue
            effective = set(it.effective_tags)
            if it.kind == "video":
                # One entry per kept frame, each with the tags that hold at its
                # moment. The video item itself is never an entry — there is no
                # single picture to train on.
                if should_stop is not None and should_stop():
                    break
                idxs, no_text = _video_entries(
                    lib, it, af, effective, origins.get(iid, {}),
                    dropped.get(iid, frozenset()), ranges_by_item.get(iid, {}),
                    frame_captions_by_item.get(iid, []), cfg, sizes, compose,
                    frames_root, manifest_items, progress, should_stop,
                    place=(videos.index(iid) + 1, len(videos)),
                    reg=iid in reg_ids,
                    no_flip=bool(no_flip
                                 & {t.lower() for t in effective}),
                )
                skipped_frames += no_text
                if idxs:
                    index_of[iid] = idxs
                continue
            instr = instructions_by_item.get(iid) if instructing else None
            # BEFORE the index is assigned, or the pool would point at the NEXT
            # item's entry and the whole dataset would be silently mis-weighted.
            if instructing and not instr:
                continue
            # AN ITEM WITH NOTHING TO SAY IN THIS MODE IS LEFT OUT. A captions
            # run over a library where ten pictures are captioned trains on
            # those ten; it used to train on all of them, the rest with an
            # empty prompt — which is not "no caption", it is the dropout
            # signal, and a thousand of them teach the unconditional path that
            # this is what the concept looks like.
            # WHICH OF THE RUN'S RESOLUTIONS THIS PICTURE JOINS — one
            # bucket at each, less the ones it is too small for when the run
            # says never to upscale (a picture is fitted to a bucket of its
            # own aspect, so it is enlarged exactly when it is smaller than
            # that bucket on either side). Decided BEFORE the prompt modes,
            # so the "nothing to train against" message below counts each
            # item under the reason it was actually dropped for.
            fits = sizes.fitted(af.width or 1, af.height or 1,
                                cfg.buckets.skip_upscale)
            if not fits:
                skipped_small += 1
                continue
            item_tags = sorted(effective - dropped.get(iid, frozenset()))
            item_caps = captions_by_item.get(iid, [])
            modes = _prompt_modes(cfg.captions.source, item_tags, item_caps)
            if not modes:
                skipped_no_text += 1
                continue
            # ONE ENTRY PER RESOLUTION, in the order `fits` gives (the
            # families' own, smallest first). EXTRA entries, never a
            # replacement: with one resolution this loop runs once and the
            # manifest is exactly what it always was — which is also what
            # `tests/golden/training_manifests.json` holds it to.
            index_of[iid] = []
            for bucket_id in fits:
                entry = {
                    "path": str(path),
                    "width": af.width or 0,
                    "height": af.height or 0,
                    "tags": item_tags,
                    "captions": item_caps,
                    "bucket": bucket_id,
                    "item_id": iid,
                    "file_id": af.id,
                }
                # CONDITIONAL, like `boxes` and `tag_groups` below: a run with no
                # regularization pool produces the manifest it always did, byte
                # for byte. The trainer reads it to drop the trigger word from
                # this entry's prompt and to scale its loss.
                if iid in reg_ids:
                    entry["reg"] = True
                # Likewise conditional: mirroring this picture would be wrong,
                # because the tag set says so about one of its tags.
                if no_flip and (no_flip & {t.lower() for t in effective}):
                    entry["no_flip"] = True
                # Cached VAE latents are ARTIFACTS OF THE FILE, not of this job:
                # they live in the item's folder under a name carrying the file
                # number, the base model and the bucket size, so another job with
                # the same model and bucket reuses them and a different one can
                # never pick up a mismatched cache.
                _latents(entry, af, cfg.model, buckets[bucket_id],
                         cfg.buckets.alpha_mask)
                boxes = boxes_by_item.get(iid)
                if boxes and not instructing:
                    entry["boxes"] = boxes
                # The regions this run's loss largely ignores — the union of the
                # masked tags' boxes, whatever the visit's prompt says. Written
                # BEFORE the entries multiply below, so a degraded copy and every
                # per-caption entry inherit them: they are the same picture.
                # Conditional like `boxes`, so a run without the setting produces
                # the manifest it always did, byte for byte.
                if mask_names:
                    mboxes = [b
                              for name, rows in (boxes_by_item.get(iid) or {}).items()
                              if name.lower() in mask_names
                              for b in rows]
                    if mboxes:
                        entry["mask_boxes"] = mboxes
                        masked_items += 1
                tgroups = groups_by_item.get(iid)
                if tgroups:
                    entry["tag_groups"] = tgroups
                # Conditional like `boxes` and `tag_groups`, so a caption or tag
                # run's manifest is byte-identical to what it has always been.
                if instr:
                    entry["instructions"] = instr
                made = _text_entries(entry, modes, item_caps, cfg.captions)
                # The indices the pools point at, taken as the entries land.
                index_of[iid].extend(range(len(manifest_items),
                                           len(manifest_items) + len(made)))
                manifest_items.extend(made)
                # EXTRA entries, never a replacement: the clean one above is
                # already in the pool at its full weight.
                if cfg.degrade.variants:
                    if should_stop is not None and should_stop():
                        stopping = True
                        break
                    if progress is not None:
                        progress(f"degrading {len(index_of)} / {len(selected_ids)}")
                    for extra in _degrade_entries(
                        af, path, entry, cfg, buckets, effective,
                        origins.get(iid, {}), degrade_counts, meta_tags
                    ):
                        index_of[iid].append(len(manifest_items))
                        manifest_items.append(extra)
                if stopping:
                    break
            if stopping:
                break

    if not manifest_items:
        # Each cause gets its OWN sentence: they send you to different places,
        # and one of them ("missing their files") had been answering for all
        # three — including the case where every picture is simply untagged,
        # which is a five-second fix if you are told and an afternoon if you
        # are told the files are gone.
        if instructing:
            raise ValueError("no selected item carries an instruction with "
                             "its reference images")
        if skipped_small and not skipped_no_text:
            # Said against the SMALLEST size the run trains at, because that
            # is the one they all failed: with several sizes the fix is to
            # add a lower one, which is not obvious from a sentence naming
            # only the largest.
            raise ValueError(
                f"all {skipped_small} matched images are smaller than the "
                f"smallest resolution this job trains at ({min(sizes.bases)}"
                "px), and it is set never to upscale. Lower that resolution "
                "— or add a lower one — or allow upscaling.")
        # A trigger-only run cannot reach here for want of text (every
        # picture is in it), so the word is only ever about the other three.
        what = {"tags": "tags", "captions": "captions",
                "both": "tags or captions"}.get(cfg.captions.source, "text")
        if skipped_frames and not skipped_no_text:
            raise ValueError(
                f"none of the {skipped_frames} frames extracted from the "
                f"selected videos has {what} — a timed tag only holds over "
                "its own stretch, and a film's captions reach its frames only "
                "as far as the video settings allow, so a frame can end up "
                "with nothing to build a prompt from.")
        if skipped_no_text:
            raise ValueError(
                f"none of the {skipped_no_text} matched items has {what} — "
                "prompts are built from them, so there is nothing to train "
                "against. Tag or caption some items, or build prompts from "
                "something they have.")
        raise ValueError("all matched items are missing their files")

    # Which entries are held out for validation, decided BEFORE the pools are
    # built: a held-out image is out of training by not being in any pool,
    # which is the same mechanism a zero-weight entry already uses, so the
    # trainer's sampler needs to learn nothing.
    held, val_items, stable_entries, val_notes = _validation_split(
        cfg.validation, index_of, manifest_items, reg_ids)

    # A pool holds the ENTRIES its items produced — one for an image, one per
    # kept frame for a video, so a film's frames are drawn as often as the
    # pool's weight says and not once between them all.
    groups = [
        {"weight": q.weight,
         "items": [j for i in ms for j in index_of.get(i, ())
                   if j not in held]}
        for q, ms in zip(cfg.queries, matched)
    ]
    groups = [g for g in groups if g["items"]]

    tag_freq = _tag_freq(lib, cfg, manifest_items, scope, excluded)

    # The trainer process cannot import the model registry, so the resolved
    # model info (engine module, repo/local path, native area) rides along.
    from .models import model_spec

    spec = model_spec(cfg.model)
    # WHERE THE WEIGHTS COME FROM, asked in one place: the job's own
    # `local_path` override, else the model's repo — which is itself a path
    # when the user added the model by pointing at one. Both are local, and
    # the flag is what makes the trainer open a single-file checkpoint with
    # `from_single_file`; without it a user model's `.safetensors` went to
    # `from_pretrained`, which wants a folder.
    local_repo = cfg.local_path.strip()
    is_local = bool(local_repo) or bool(spec.local)
    manifest = {
        "version": 1,
        "resolution": base,
        "model": {
            "key": spec.key,
            "engine": spec.engine,
            "repo": local_repo or spec.repo,
            "local": is_local,
            "area": spec.default_area,
            # Load from the cached snapshot when it is complete, so the run
            # never asks the hub what it already has (see snapshot_dir_for).
            # A local path has no snapshot — it IS the source.
            "local_dir": "" if is_local
                         else pipeline_files.snapshot_dir_for(spec.repo),
        },
        "items": manifest_items,
        "groups": groups,
        "buckets": [list(b) for b in buckets],
        "tag_freq": tag_freq,
    }
    # THE META-LEVEL CAPTION RULES, resolved to tag names. `compose` reads one
    # list per rule and knows nothing about meta tags; the trainer unions
    # these into the caption config before it builds its sampler. CONDITIONAL,
    # so a job using neither setting produces the manifest it always did.
    # EVERY SIZE THIS RUN TRAINS AT, and only where there is more than one:
    # `resolution` above is the largest of them and the trainer needs
    # nothing else (a bucket index says the shape), so this is for the
    # reader of a manifest — and conditional, so a job naming one size
    # produces the file it always did, byte for byte.
    if len(sizes.bases) > 1:
        manifest["resolutions"] = list(sizes.bases)
        tp.append_log(job_dir, (
            f"resolutions: {', '.join(str(b) for b in sizes.bases)} — each "
            f"picture contributes one entry per size it is big enough for"))
    tag_meta_names = {
        key: sorted(names)
        for key, names in (
            ("always", meta_tags.names(cfg.captions.always_tag_meta_tags)),
            ("exclude", meta_tags.names(cfg.captions.exclude_tag_meta_tags)),
        )
        if names
    }
    if tag_meta_names:
        manifest["tag_meta_names"] = tag_meta_names
    # THE VALUE RULES, resolved to a finished tag → text map. Every raw tag
    # name the entries can put in a prompt is looked up against the rules
    # ONCE (first match wins — the list's order is configuration), and the
    # trainer's tag writer reads the map without ever learning what a value
    # is — the `MetaTagResolver` pattern again. CONDITIONAL, so a run with no
    # rules produces the manifest it always did, byte for byte.
    if cfg.captions.value_rules:
        vmap = _value_map(cfg.captions.value_rules, manifest_items)
        if vmap:
            manifest["value_map"] = vmap
            tp.append_log(job_dir, f"value rules matched {len(vmap)} tag(s)")
        else:
            tp.append_log(job_dir,
                          "value rules matched no tag in the dataset")
    # CONDITIONAL, like `boxes` and `tag_groups` on an entry: a run that does
    # not ask for aliases produces the manifest it always did, byte for byte.
    if cfg.captions.alias_p > 0:
        aliases = _tag_aliases(lib, manifest_items)
        if aliases:
            manifest["tag_aliases"] = aliases
    # THE COMMENTS, for a run that writes tags by them — the same shape as the
    # aliases: resolved here, keyed on the canonical name, CONDITIONAL so a
    # run writing names produces the manifest it always did.
    if cfg.captions.tag_text != "name":
        comments = _tag_comments(lib, manifest_items)
        if comments:
            manifest["tag_comments"] = comments
    # CONDITIONAL like everything above: a run that validates nothing writes
    # neither key. The entries themselves stay in `items` (they still need
    # their latents cached); being in no pool is what keeps them untrained.
    if val_items:
        manifest["val_items"] = val_items
    if stable_entries:
        manifest["stable_items"] = stable_entries
    tp.write_json(tp.manifest_path(job_dir), manifest)
    for line in val_notes:
        tp.append_log(job_dir, line)
    # A masked tag nobody drew a box for changes nothing, silently — the run
    # trains fine with nothing masked — so the log says what actually landed.
    if mask_names:
        tp.append_log(job_dir, (
            f"loss masking: {masked_items} of {len(index_of)} images carry "
            f"masked regions (masked cells count "
            f"{cfg.buckets.mask_loss_weight:g}x)" if masked_items else
            "loss masking: no selected image carries a box of the masked "
            "tags — nothing is masked"))
    # Say what each variant actually produced. A gate that matched nothing is
    # the failure mode here, and it is silent by construction: the run trains
    # perfectly well on the clean pictures alone.
    for label, n in degrade_counts.items():
        tp.append_log(job_dir, (
            f"degradation · {label}: {n} extra samples" if n else
            f"degradation · {label}: no pictures matched its tag filter"))
    # A regularization pool that contributed nothing is SILENT by
    # construction: the run trains perfectly well on the rest, and the class
    # drift the pool exists to prevent simply happens. Almost always the pool
    # overlaps the training pools entirely — where the training pools win —
    # so say which it was.
    if any(q.regularize for q in cfg.queries) and not reg_ids:
        tp.append_log(job_dir, (
            "regularization: no pictures — every item matched by a "
            "regularization query is also matched by a training query, and a "
            "training query wins. Narrow the regularization query so it "
            "selects pictures the run is NOT about."))
    return manifest


# ---- resolutions and their buckets ------------------------------------------


class Resolutions:
    """The run's bucket families — one per size it trains at — and the FLAT
    list the manifest carries.

    THE FAMILIES STAY APART. A picture is fitted to the bucket of its own
    aspect WITHIN one resolution; over a merged list the nearest aspect
    could belong to any of them, so a run training at 512 and 1024 would
    put a 3:2 picture wherever the arithmetic happened to land rather than
    once at each size. The flat list is their union, deduped and sorted,
    because a batch may hold exactly one bucket and two families that agree
    on a size agree about the batch too.

    `fitted` is the one rule both the pictures and the video frames ask:
    which flat bucket this picture takes at each of the run's resolutions,
    leaving out the ones it is too small for. With a single resolution and
    nothing dropped that is one index, which is what keeps a manifest
    without extra resolutions byte-identical.
    """

    def __init__(self, compose, bases: list[int], step: int,
                 max_aspect: float) -> None:
        self._compose = compose
        self.bases = list(bases)
        self.families = [compose.make_buckets(b, step, max_aspect)
                         for b in self.bases]
        self.flat: list[tuple[int, int]] = sorted(
            {wh for fam in self.families for wh in fam})
        self._at = {wh: i for i, wh in enumerate(self.flat)}

    def fitted(self, width: int, height: int,
               skip_upscale: bool) -> list[int]:
        """Flat bucket indices for this picture, one per resolution it can
        be trained at.

        NEVER UPSCALE IS ASKED PER RESOLUTION, which is the other half of
        what several of them are for: a 700 px scan is too small for a 1024
        bucket and perfectly good at 512, so it joins the run at the size it
        fits instead of being dropped from it.
        """
        out: list[int] = []
        for fam in self.families:
            bw, bh = fam[self._compose.assign_bucket(width, height, fam)]
            if skip_upscale and (width < bw or height < bh):
                continue
            out.append(self._at[(bw, bh)])
        return out


# ---- validation --------------------------------------------------------------


def _validation_split(val, index_of: dict, manifest_items: list[dict],
                      reg_ids: set[int]) -> tuple[set, list, list, list]:
    """``(held entry indices, val entries, stable entries, log lines)``.

    The hold-out is by whole IMAGE, never by entry: an item's degraded copies
    and per-caption entries go with it, or the model trains on the validation
    picture under another prompt and the series quietly measures memorized
    data. Regularization items are not eligible — they are reminders, and a
    validation score over pictures the run is deliberately not learning would
    answer a different question.

    The pick is seeded on ``validation.seed`` alone, over the sorted item ids,
    so re-materializing the same library gives the same split — a validation
    curve is only comparable to itself if every build asks about the same
    pictures. Clamped to HALF the eligible images: a validation setting must
    never eat the dataset it exists to protect.

    What comes back as scored entries is the CLEAN, plain-prompt subset —
    no ``degrade`` copies (they are augmentation, not the picture) — while
    the held set covers every entry of the held-out items.
    """
    if val.every_n_steps <= 0 or (val.holdout <= 0 and val.stable_items <= 0):
        return set(), [], [], []
    rng = random.Random(int(val.seed))
    notes: list[str] = []
    eligible = sorted(i for i, idxs in index_of.items()
                      if idxs and i not in reg_ids)
    held: set[int] = set()
    val_entries: list[int] = []
    if val.holdout > 0:
        n = min(int(val.holdout), len(eligible) // 2)
        if n > 0:
            held_ids = sorted(rng.sample(eligible, n))
            held = {j for i in held_ids for j in index_of[i]}
            val_entries = sorted(j for j in held
                                 if not manifest_items[j].get("degrade"))
            clamp = (f" (asked for {val.holdout}, clamped to half the "
                     f"dataset)" if n < val.holdout else "")
            notes.append(
                f"validation: holding {n} of {len(eligible)} images out of "
                f"training ({len(val_entries)} entries), scored every "
                f"{val.every_n_steps} steps{clamp}")
        else:
            notes.append(
                "validation: too few images to hold any out — the held-out "
                "series is off for this run")
    stable: list[int] = []
    if val.stable_items > 0:
        pool = [j for j in range(len(manifest_items))
                if j not in held
                and not manifest_items[j].get("degrade")
                and not manifest_items[j].get("reg")]
        n = min(int(val.stable_items), len(pool))
        if n > 0:
            stable = sorted(rng.sample(pool, n))
            notes.append(
                f"stable loss: {n} training entries, scored every "
                f"{val.every_n_steps} steps")
    return held, val_entries, stable, notes


# ---- the latent cache -------------------------------------------------------


def _latent_key(model: str, bucket, alpha_mask: bool,
                degrade_key: str = "") -> str:
    """The part of a latent's name that says WHICH encoding it is.

    A ``degrade_key`` marks the latents of one DEGRADED copy of the picture,
    and ``-am`` a masked run, which feeds the VAE a different image (the
    transparent region filled with an extension of the edge colours instead of
    whatever sat under the alpha) and stores the latent mask beside the
    latent — so the two caches must never be mistaken for each other. Both
    markers go BEFORE the size, because `register_latents` finds the bucket at
    the tail: that parse is the reason for the ordering, and it is the one
    thing a new marker can break.
    """
    bw, bh = bucket
    mark = f"-d{degrade_key}" if degrade_key else ""
    mark += "-am" if alpha_mask else ""
    return f"{model}{mark}-{bw}x{bh}"


def _latents(entry: dict, af, model: str, bucket, alpha_mask: bool,
             degrade_key: str = "") -> None:
    """Fill an entry's four latent-cache fields.

    The flipped variant is a separate cache: the VAE is not exactly
    flip-equivariant, so it is encoded from mirrored pixels rather than
    mirrored afterwards.
    """
    key = _latent_key(model, bucket, alpha_mask, degrade_key)
    entry["latent_rel"] = af.artifact_name("latent", key, "pt")
    entry["latent_rel_flipped"] = af.artifact_name("latent", key + "-f", "pt")
    entry["latent_path"] = str(af.artifact_path("latent", key, "pt"))
    entry["latent_path_flipped"] = str(
        af.artifact_path("latent", key + "-f", "pt"))


# ---- tags -------------------------------------------------------------------


def _with_implied(origins: dict, names: set[str]) -> set[str]:
    """``names`` plus every ancestor that was ONLY implied by them.

    Dropping `poodle` has to take `dog` and `animal` with it, unless they are
    assigned in their own right — otherwise an exclusion (a tag group this job
    ignores, or a timed tag that does not hold at this frame) half-works and
    the prompt still claims the thing it was meant to leave out.
    """
    if not origins or not names:
        return set(names)
    gone = set(names)
    # `implied_by` names every PRE-implication tag that entails an ancestor, so
    # one pass is enough — a source is never itself an implied ancestor. Test
    # against the original set, not the one being built, so the outcome cannot
    # depend on iteration order.
    for anc, origin in origins.items():
        if anc in gone or not origin.implied_by:
            continue
        if not set(origin.implied_by) <= names:
            continue
        if origin.direct and anc not in names:
            continue  # assigned in its own right
        if origin.from_groups:
            continue  # or granted by a library group
        gone.add(anc)
    return gone


def _dropped_by_tag_group(selected, excluded: set[str]) -> tuple[dict, dict]:
    """Per item, the tag names this job ignores because of the tag group they
    sit in — plus every item's tag origins, which the caller needs anyway and
    which this has to resolve regardless.

    Per-item tag groups are how a library separates what a picture shows from
    notes about it ("to redraw", "reference only"), and this is what makes that
    separation reach training. Two rules do the work:

    * A tag is dropped only when EVERY placement of it is in an excluded group.
      The same tag may sit in several groups at once, and an ungrouped instance
      is a placement too — a tag that also reaches the item by a route the user
      did not exclude stays. That second half is the whole reason
      `ungrouped_tags()` exists beside `tag_groups()`: a tag can be in a group
      AND ungrouped, and reading only the groups would drop it.
    * An ancestor that was *only* implied by dropped tags goes with them
      (``poodle`` dropped takes ``dog`` and ``animal`` with it), unless it is
      assigned in its own right. Leaving them behind would make an exclusion
      silently half-work.

    Matching is case-insensitive, like the caption filter: these names are
    typed into a training form, far from the autocomplete that produced them.
    """
    origins = {it.id: it.tags.explain_all() for it in selected}
    if not excluded:
        return {}, origins

    blocks = selected.tag_groups()
    ungrouped = selected.ungrouped_tags()
    out: dict[int, frozenset] = {}
    for iid, groups in blocks.items():
        bad = {g.id for g in groups
               if any(m.lower() in excluded for m in g.meta_tags)}
        if not bad:
            continue
        loose = ungrouped.get(iid, set())
        placed: dict[str, set[int]] = {}
        for g in groups:
            for name in g.tags:
                placed.setdefault(name, set()).add(g.id)
        names = {name for name, gids in placed.items()
                 if name not in loose and gids <= bad}
        if names:
            out[iid] = frozenset(_with_implied(origins.get(iid, {}), names))
    return out, origins


def _tag_freq(lib, cfg, manifest_items: list[dict], scope: dict,
              excluded: set[str]) -> dict[str, int]:
    """Tag frequencies for balancing and loss weighting.

    "dataset" counts over the selected items; "library" over every item the
    run's scope COULD have selected — the run's kinds, carrying an active
    file, not trashed, and including hidden ones. Not "every item in the
    library", whatever the setting is called: a videos-off run counts no video
    tags, and it has always been so.

    A THIRD base, "library_offset", added each tag's highest META-TAG count
    — the pictures it has somewhere this library is not — and went with the
    tag-level count offset it was named after. `spec` still reads a stored
    one as "library", so a job configured with it opens and runs; what it
    no longer does is count anything this library cannot see.
    """
    tag_freq: dict[str, int] = {}
    if cfg.captions.freq_base == "library":
        # Read only here: this walks every picture in the library, and is
        # provably unused for a dataset-based frequency.
        everything = lib.query(None, **scope).prefetch("tags")
        dropped, _ = _dropped_by_tag_group(everything, excluded)
        for it in everything:
            skip = dropped.get(it.id, frozenset())
            for t in set(it.effective_tags) - skip:
                tag_freq[t] = tag_freq.get(t, 0) + 1
        return tag_freq
    for entry in manifest_items:
        # Clean entries only. A degraded copy is the same picture, so counting
        # it again would inflate every tag it carries — and `remove_tags` would
        # deflate exactly the ones it takes off, which is the tag distribution
        # telling a story about the augmentation rather than about the library.
        if entry.get("degrade"):
            continue
        for t in entry["tags"]:
            tag_freq[t] = tag_freq.get(t, 0) + 1
    return tag_freq


def _tag_ranges(selected) -> dict[int, dict[str, list[tuple]]]:
    """Per item, each timed tag's POSITIVE time ranges (seconds).

    Only boxes with a time and no geometry count — those are a film tag's
    coverage. A timed box WITH geometry is a moving subject's placement on a
    still, and says nothing about whether the tag holds over the film.
    A tag with no row here is untimed and holds throughout.
    """
    out: dict[int, dict[str, list[tuple]]] = {}
    boxes = selected.tag_boxes()
    for it in selected:
        by_name = boxes.get(it.id)
        if not by_name:
            continue
        positive = set(it.tags)
        for name, rows in by_name.items():
            if name not in positive:
                continue
            for box in rows:
                span = box.time
                if span is None or box.rect is not None or box.negative:
                    continue
                out.setdefault(it.id, {}).setdefault(name, []).append(
                    (float(span.start),
                     None if span.end is None else float(span.end)))
    return out


def _prompt_modes(source: str, tags: list, captions: list) -> list[str]:
    """Which prompts this item contributes, or [] when it contributes none.

    "CAPTION + TAGS" IS TWO VISITS, not one prompt with both in it. A sentence
    and a tag list are two ways of saying what a picture is, and glueing them
    together teaches the model that the description always ends in a comma
    list — where showing the same picture under each teaches that either way
    of asking finds it. It also means an item captioned but untagged still
    contributes its caption, instead of the pair being dropped for missing
    half of itself.

    An item with nothing to say in a mode is simply not in it. Training an
    uncaptioned picture on a captions run does not give the model "no
    caption": an empty prompt is the DROPOUT signal, and a thousand of them
    teach the unconditional path that this is what the concept looks like.
    """
    if source == "instructions":
        return ["instruction"]
    # THE TRIGGER ALONE. Every selected picture is in the run whatever it
    # carries — there is nothing it could be missing, so the "nothing to say"
    # skip below does not apply — and the composer writes no tags and no
    # caption for it.
    if source == "none":
        return ["none"]
    out: list[str] = []
    if source in ("tags", "both") and tags:
        out.append("tags")
    if source in ("captions", "both") and captions:
        out.append("caption")
    return out


def _text_entries(entry: dict, modes: list[str], captions: list[str],
                  cfg) -> list[dict]:
    """The entries one picture contributes: one per prompt mode, and one per
    caption where the run repeats them.

    Shared by the image loop and the video one, because a frame is an ordinary
    training image and every rule about how many prompts a picture is worth
    has to reach it. It did not: a frame used to be exactly one entry carrying
    the whole caption list, so a "caption + tags" run glued a sentence and a
    tag list into ONE prompt for frames while showing every other picture
    twice, and "every caption" quietly did not apply to films at all.

    `prompt_mode` rides along whenever the RUN offers more than one — not
    whenever this picture happens to have both, or the captionless item of a
    "caption + tags" run would carry no mode and lean on the composer's
    fallback to mean the same thing. A single-mode run writes no key at all,
    so its manifest is byte-identical to what it always was.
    """
    multi = cfg.source == "both"
    repeat = cfg.caption_repeat
    out: list[dict] = []
    for m in modes:
        # A caption-mode entry may become ONE PER CAPTION. The tags entry of
        # the same picture never repeats: it has one set of tags however many
        # ways it has been described.
        texts = ([[c] for c in captions]
                 if m == "caption" and repeat != "random" and captions
                 else [None])
        for one_text in texts:
            one = dict(entry)
            if multi:
                one["prompt_mode"] = m
            if one_text is not None:
                one["captions"] = one_text
                if repeat == "each_shared":
                    # Every caption keeps its visit; together they carry one
                    # item's worth of gradient, so having been described ten
                    # ways is not a claim to ten times the influence.
                    one["loss_scale"] = round(1.0 / len(captions), 6)
            out.append(one)
    return out


def _value_map(rules, manifest_items: list[dict]) -> dict[str, dict]:
    """Every raw tag name the entries can prompt with, against the rules.

    First match wins — the rule list's order is part of the configuration,
    which is what lets overlapping ranges mean something. A name no rule
    matches is simply absent: the tag passes through the prompt unchanged,
    visible behavior rather than silent dropping. The map's values are what
    `compose.tag_writer` reads: the replacement text, and whether the raw
    tag rides alongside it.
    """
    from media_compost import tag_value_matches

    names: set[str] = set()
    for entry in manifest_items:
        names.update(entry.get("tags") or [])
    out: dict[str, dict] = {}
    for name in sorted(names):
        head, sep, rest = name.partition(":")
        if not sep or not head:
            continue
        for r in rules:
            if not r.namespace or not r.text.strip():
                continue  # an inert half-filled row, not a match-everything
            if head != r.namespace:
                continue
            if tag_value_matches(rest, r.op, r.value, r.unit):
                out[name] = {"text": r.text.strip(), "keep": bool(r.keep_raw)}
                break
    return out


def _tag_comments(lib, manifest_items: list[dict]) -> dict[str, str]:
    """Canonical tag name -> its COMMENT, for the tags this dataset uses that
    have one. `captions.tag_text` writes a tag as this instead of (or beside)
    its name; a tag with no comment is absent and is written as its name."""
    used: set[str] = set()
    for entry in manifest_items:
        used.update(entry.get("tags") or [])
    out: dict[str, str] = {}
    for name in sorted(used):
        try:
            comment = (lib.tags[name].comment or "").strip()
        except KeyError:
            continue
        if comment:
            out[name] = comment
    return out


def _tag_aliases(lib, manifest_items: list[dict]) -> dict[str, list[str]]:
    """Canonical tag name -> its aliases, for the tags this dataset uses.

    The library's aliases are the OTHER WORDS for one thing ("cat" / "kitty"),
    and a model trained only on the canonical name answers only to that word.
    The trainer writes one of these instead of the canonical name with
    probability `captions.alias_p`.

    Keyed on the CANONICAL name because that is what a manifest entry carries:
    assigning an alias redirects to its target, so an item's tags are always
    canonical and the substitution is a lookup rather than a search.

    It walks the whole catalog, which is the only way round: an alias points AT
    its target, so there is no way to ask a target for its aliases without
    reading every tag. That is why it is built ONLY for a run that asked for
    one (`alias_p > 0`) — on a big catalog this is a query per tag, and it
    would otherwise be paid by every run to produce a key nothing reads.
    """
    used: set[str] = set()
    for entry in manifest_items:
        used.update(entry.get("tags") or [])
    if not used:
        return {}
    out: dict[str, list[str]] = {}
    for name in lib.tags:
        target = lib.tags[name].alias_of
        if target is not None and target.name in used:
            out.setdefault(target.name, []).append(name)
    return {k: sorted(v) for k, v in sorted(out.items())}


def _tag_groups(selected) -> dict[int, list[dict]]:
    """Per item, its tag groups in their own order, each with the tag names in
    it — what ``compose.group_tag_text`` lays a prompt out by.

    Only groups that HAVE members are carried: an empty group is bookkeeping,
    and the manifest is the trainer's whole view of the library. System groups
    (the auto-managed Pending one) are left out — they are about the state of a
    tag, not about the picture.
    """
    out: dict[int, list[dict]] = {}
    for iid, groups in selected.tag_groups().items():
        for g in groups:
            if g.system or not g.tags:
                continue
            out.setdefault(iid, []).append({
                "name": g.name, "tags": list(g.tags),
                "subjects": list(g.subjects),
            })
    return out


def _clip_unit(pts: list) -> list:
    """Sutherland–Hodgman clip of a polygon to the unit square.

    What mapping a reference-frame polygon onto a cropped active file needs:
    a vertex outside the visible frame is replaced by where its edges cross
    the border, so the shape stays the visible part of what was drawn. An
    empty result (wholly outside) reads as "no polygon"."""
    def clip(poly, inside, cross):
        res = []
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            if inside(b):
                if not inside(a):
                    res.append(cross(a, b))
                res.append(b)
            elif inside(a):
                res.append(cross(a, b))
        return res

    def x_at(a, b, xv):
        t = (xv - a[0]) / (b[0] - a[0])
        return (xv, a[1] + t * (b[1] - a[1]))

    def y_at(a, b, yv):
        t = (yv - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), yv)

    poly = [(float(p[0]), float(p[1])) for p in pts]
    if all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in poly):
        return poly  # wholly visible — and the vertex order stays as drawn
    for inside, cross in (
        (lambda p: p[0] >= 0.0, lambda a, b: x_at(a, b, 0.0)),
        (lambda p: p[0] <= 1.0, lambda a, b: x_at(a, b, 1.0)),
        (lambda p: p[1] >= 0.0, lambda a, b: y_at(a, b, 0.0)),
        (lambda p: p[1] <= 1.0, lambda a, b: y_at(a, b, 1.0)),
    ):
        if len(poly) < 3:
            return []
        poly = clip(poly, inside, cross)
    return poly if len(poly) >= 3 else []


def _tag_boxes(selected) -> dict[int, dict]:
    """Spatial tag boxes per item, keyed by tag name, as (x, y, w, h) fractions
    of the item's *active file* frame.

    Boxes are stored in the item's reference frame; a cropped active file only
    shows part of it, so each box is mapped through the file's crop and clipped
    to the visible [0,1] square (dropped when it lands outside). The trainer
    uses these to keep prompted tags' boxes mostly inside random crops.

    **A subject's tag falls back to that subject's FACES.** A detected face is
    already the answer to "where in this picture is Alice", so making somebody
    draw the same rectangle again to get crop-aware training would be asking
    for work the detector has done. Only as a fallback, though: a box drawn by
    hand says something a face box does not (the whole person rather than the
    head), so a tag that has one keeps it.
    """
    out: dict[int, dict] = {}
    boxes = selected.tag_boxes()

    def place(iid: int, name: str, crop, rect, points=None) -> None:
        """Map one reference-frame rectangle onto the active file and keep it.

        A box carrying a POLYGON maps its vertices through the same crop and
        clips them to the visible square; the row then carries the clipped
        polygon as a conditional fifth element (the shape `compose.flip_boxes`
        and `box_mask_cells` read) with the first four values its bounding
        box. Without one, the row is the bare 4-list it always was — so a
        library with no polygons produces the manifest it always did.
        """
        if rect is None or not crop.w or not crop.h:
            return
        x = (rect.x - crop.x) / crop.w
        y = (rect.y - crop.y) / crop.h
        w = rect.w / crop.w
        h = rect.h / crop.h
        pts = None
        if points:
            pts = _clip_unit([((px - crop.x) / crop.w, (py - crop.y) / crop.h)
                              for px, py in points])
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        else:
            pts = None
            # Clip to the visible frame; skip boxes (mostly) outside it.
            x0, y0 = max(0.0, x), max(0.0, y)
            x1, y1 = min(1.0, x + w), min(1.0, y + h)
        if x1 - x0 < 0.005 or y1 - y0 < 0.005:
            return
        row = [round(x0, 5), round(y0, 5), round(x1 - x0, 5), round(y1 - y0, 5)]
        if pts:
            row.append([[round(px, 5), round(py, 5)] for px, py in pts])
        out.setdefault(iid, {}).setdefault(name, []).append(row)

    for it in selected:
        af = it.active_file
        if af is None:
            continue
        crop = af.crop
        positive = set(it.tags)
        for name, rows in (boxes.get(it.id) or {}).items():
            if name not in positive:
                continue
            for box in rows:
                place(it.id, name, crop, box.rect, box.points)

        # Which (item, tag) pairs already have a box of their own — taken
        # BEFORE anything is added, or a subject's second face would see its
        # own first one and stand down.
        drawn = set((out.get(it.id) or {}).keys())
        # An appearance's SUBJECT BOX comes before its face: a hand-drawn
        # rectangle says the whole person where the face says the head, the
        # same precedence a tag's own box has over both.
        boxed = set()
        for app in it.appearances:
            rect = app.rect
            if rect is None:
                continue
            tag = app.subject.tag
            name = tag.name if tag is not None else ""
            if not name or name in drawn or name not in positive:
                continue
            place(it.id, name, crop, rect, app.points)
            boxed.add(name)
        # EVERY name on a face, deliberately. A face of Craig-as-Bond is where
        # Bond is in the picture *and* where Craig is, so `james_bond` and
        # `daniel_craig` each get the box — taking one would leave the other's
        # tag with none, which is exactly the crop-aware training this feeds.
        for face in it.faces:
            if face.dismissed:
                continue
            # The face's hand-drawn OUTLINE stands in for the face box when
            # one exists — it says the whole figure where the box says the
            # head, exactly what crop steering wants. Read once per face, not
            # per subject on it.
            o_rect = face.outline
            o_pts = face.outline_points if o_rect is not None else None
            for subject in face.subjects:
                tag = subject.tag
                name = tag.name if tag is not None else ""
                if (not name or name in drawn or name in boxed
                        or name not in positive):
                    continue
                if o_rect is not None:
                    place(it.id, name, crop, o_rect, o_pts)
                else:
                    place(it.id, name, crop, face.rect)
    return out


# ---- prompts ----------------------------------------------------------------


def _prompts(selected, cfg, video, instructing: bool) -> tuple[dict, dict, dict]:
    """The text side of every selected item: captions, or instructions.

    The run trains on ONE kind, so exactly one of the first two comes back
    filled. That physical separation is the belt to the enum's braces: an
    imperative can never surface under the key `compose` reads for a
    description, or the other way round.

    The third is what a VIDEO's extracted frames inherit — a SECOND list per
    film rather than a different filter over the same one, because both are
    true at once: the film keeps every caption this run may use, and its
    frames keep whichever of those describe a moment (see `VideoConfig`). The
    frame list is a subset of the item's by construction, since it is built
    from the captions that already passed the run-wide filter.
    """
    keeps = _caption_filter(cfg.include_meta_tags, cfg.exclude_meta_tags)
    frame_keeps = _caption_filter(video.caption_include_meta_tags,
                                  video.caption_exclude_meta_tags)
    inherit = video.captions == "inherit"
    captions_by_item: dict[int, list[str]] = {}
    instructions_by_item: dict[int, list[dict]] = {}
    frame_captions_by_item: dict[int, list[str]] = {}
    for it in selected:
        film = not instructing and it.kind == "video"
        for c in (it.instructions if instructing else it.captions):
            if c.pending or not c.text.strip() or not keeps(c):
                continue
            if instructing:
                refs = _refs(c)
                if refs is None:
                    continue
                instructions_by_item.setdefault(it.id, []).append(
                    {"text": c.text.strip(), "refs": refs})
            else:
                captions_by_item.setdefault(it.id, []).append(c.text.strip())
                if film and inherit and frame_keeps(c):
                    frame_captions_by_item.setdefault(it.id, []).append(
                        c.text.strip())
    return captions_by_item, instructions_by_item, frame_captions_by_item


def _caption_filter(include, exclude):
    """Which captions a rule admits, by META TAG.

    An item commonly carries several captions — a one-liner and a paragraph, a
    translation, a machine draft someone approved — and a run usually wants one
    kind. ``include`` narrows to captions carrying at least one of the named
    tags; ``exclude`` drops any carrying one, and wins. Matching is
    case-insensitive: these names are typed in a training form, far from the
    autocomplete that produced them.

    Two rules are built from this — the run's own (`CaptionConfig`) and the
    one a video's frames inherit by (`VideoConfig`) — and they compose, so the
    lists mean the same thing in both places.

    Filtering here rather than in the trainer keeps the manifest the whole
    truth about what a run sees — and costs nothing at all when no rule is set.
    """
    inc = {n.strip().lower() for n in include if n.strip()}
    exc = {n.strip().lower() for n in exclude if n.strip()}
    if not inc and not exc:
        return lambda _c: True

    def keep(caption) -> bool:
        have = {n.lower() for n in caption.meta_tags}
        if exc & have:
            return False
        return not inc or bool(inc & have)

    return keep


def _refs(caption) -> Optional[list[dict]]:
    """One instruction's ORDERED reference images, or None if any is missing.

    An instruction sits on the picture it PRODUCED; the refs are the pictures
    it was made from, and they are ordinary library items usually not among the
    selected ones.

    An instruction whose references cannot all be resolved is dropped WHOLE,
    never shortened: how many there are and what order they are in is the
    training signal, and a two-reference edit quietly becoming a one-reference
    one teaches a relationship nobody stated.
    """
    out: list[dict] = []
    for ref in caption.refs:
        if ref.trashed or ref.kind != "image":
            return None
        af = ref.active_file
        path = ref.path
        if af is None or path is None or not path.exists():
            return None
        # No bucket (the trainer decides how a reference is sized), no tags or
        # captions (a reference is a picture, not a second prompt) and no
        # cached latent: the shared cache is keyed by file number + model +
        # bucket, and a reference is neither bucketed by its own aspect nor
        # cropped nor flipped on its own, so "reuse" would silently be a
        # different encoding.
        out.append({"path": str(path), "width": af.width or 0,
                    "height": af.height or 0, "item_id": ref.id,
                    "file_id": af.id})
    return out or None


# ---- videos -----------------------------------------------------------------


def _sweep_frames(root: Path, keep: set[str]) -> None:
    """Drop the frame folders of films this run does not select.

    Per FILM, not wholesale: the ones this run does select are the expensive
    half, and `videoframes.extract` is the judge of whether each is still
    what it would sample today. A film that has left the dataset has nothing
    to be the judge of.
    """
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name in keep:
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def _video_entries(lib, item, af, effective, origins, group_dropped, ranges,
                   captions, cfg, sizes, compose, frames_root,
                   manifest_items, progress, should_stop,
                   place, reg: bool = False,
                   no_flip: bool = False) -> tuple[list[int], int]:
    """Extract one video's frames and append the entries per frame.

    Returns the indices the frames took in ``manifest_items`` (empty when the
    video yielded nothing), so the query pools can point at them, and how many
    frames were left out for having nothing to say in this run's prompt mode.

    A frame is an ordinary training image once it exists, so it goes through
    the same `_prompt_modes` / `_text_entries` pair the pictures do — one
    entry per mode, one per caption where the run repeats them, and NO entry
    at all where the frame has neither tags nor captions. That last rule is
    the point: a frame's tags come and go with the film's time ranges and its
    captions can be withheld outright, so a frame with an empty prompt is easy
    to produce here — and an empty prompt is not "no caption", it is the
    dropout signal, which a thousand frames of teach the unconditional path.
    """
    from media_compost import MediaUnreadable

    step = videoframes.sample_fps(
        cfg.video.every, cfg.video.unit, af.frame_rate)
    # A frame only has to cover the largest bucket of the LARGEST resolution
    # the run trains at; extracting a 4K film at full size would cost tens of
    # gigabytes of scratch JPEG for pixels the trainer immediately throws
    # away. The LARGEST and not the run's nominal one, or a size added above
    # the rest would train its frames on pixels thrown away first.
    max_dim = int(max(sizes.bases) * cfg.buckets.max_aspect)
    nth, total = place
    name = item.name or item.uid

    def note(kept: int, scanned: int) -> None:
        if progress is not None and kept % 10 == 0:
            progress(f"video {nth}/{total} — {name}: {kept} frames")

    if progress is not None:
        progress(f"video {nth}/{total} — {name}")
    try:
        frames = videoframes.extract(
            item, frames_root / item.uid,
            every=cfg.video.every, unit=cfg.video.unit,
            dedupe=cfg.video.dedupe, threshold=lib.phash_threshold,
            max_dim=max_dim, on_progress=note, should_stop=should_stop,
        )
    except MediaUnreadable:
        # One unreadable video must not abandon the whole dataset.
        return [], 0

    # Half a sampling interval either side, so a tag placed on a single moment
    # reaches the frame nearest it rather than falling between two.
    tol = 0.5 / step if step > 0 else 0.0
    out: list[int] = []
    skipped = 0
    for fr in frames:
        inactive = {
            name_ for name_, spans in ranges.items()
            if not videoframes.covers(spans, fr.time, tol)
        }
        gone = set(group_dropped) | _with_implied(origins, inactive)
        tags = sorted(effective - gone)
        modes = _prompt_modes(cfg.captions.source, tags, captions)
        if not modes:
            skipped += 1
            continue
        # ONE ENTRY PER RESOLUTION, the pictures' rule (`Resolutions.
        # fitted`). NEVER UPSCALE is not asked of a frame: it is extracted
        # to order rather than found at whatever size somebody saved it, so
        # `fitted` is called without it and every resolution takes one.
        for bucket_id in sizes.fitted(fr.width, fr.height, False):
            entry = {
                "path": str(fr.path),
                "width": fr.width,
                "height": fr.height,
                "tags": tags,
                "captions": captions,
                "bucket": bucket_id,
                "item_id": item.id,
                # A frame is not a stored File, so it has no file_id and no
                # shared latent cache: the trainer falls back to a job-local
                # latent, which is right — these pixels vanish with the run.
                "video_time": round(fr.time, 3),
            }
            # A film in a regularization pool contributes regularization
            # frames — conditional, so a run without one is byte-identical.
            if reg:
                entry["reg"] = True
            # And a film the tag set says not to mirror passes that to every
            # frame of it: the veto is about what is IN the picture.
            if no_flip:
                entry["no_flip"] = True
            made = _text_entries(entry, modes, captions, cfg.captions)
            out.extend(range(len(manifest_items),
                             len(manifest_items) + len(made)))
            manifest_items.extend(made)
    return out, skipped


# ---- degradation ------------------------------------------------------------


class MetaTagResolver:
    """WHICH TAGS THE LIBRARY MARKS A GIVEN WAY, resolved once per run.

    Every meta-tag-level setting in a job's config means the same thing —
    "every tag carrying one of these" — so there is one resolver and every
    setting is a `names()` call unioned into the tag list beside it. The
    trainer therefore learns nothing about meta tags: what reaches it is the
    same list of names it has always read.

    Lazy, and empty when nothing asks: the map is one statement over the whole
    catalog, and a job using none of these settings must not pay for it.
    """

    def __init__(self, lib):
        self._lib = lib
        self._map: Optional[dict[str, set[str]]] = None

    def names(self, metas) -> set[str]:
        """The tag names carrying ANY of ``metas`` (lowercased). Empty for an
        empty selection, which is what makes a union with it a no-op."""
        want = {str(m).strip().lower() for m in metas or [] if str(m).strip()}
        if not want:
            return set()
        if self._map is None:
            self._map = self._lib.tags.meta_map()
        return {name for name, have in self._map.items() if have & want}

    def plus(self, tags, metas) -> list[str]:
        """``tags`` unioned with what ``metas`` resolves to — the shape every
        caller wants, and the one place the union is spelled out."""
        out = {str(t).strip().lower() for t in tags or [] if str(t).strip()}
        return sorted(out | self.names(metas))


def _variant_allows(variant, item_tags: set[str], meta: "MetaTagResolver",
                    ) -> bool:
    """Whether this variant may touch a picture carrying ``item_tags``.

    Asked before anything is generated, so a skipped picture costs no ffmpeg
    run, no artifact and no cache entry. ``item_tags`` is the item's EFFECTIVE
    positive set — implications count, so an item tagged `poodle` satisfies a
    `dog` requirement — and deliberately the set BEFORE this run's
    prompt-shaping exclusions: hiding a "quality notes" tag group from
    *prompts* must not quietly stop `skip_tags: low_quality` from working.
    Those are different questions.
    """
    have = {t.lower() for t in item_tags}
    skip = meta.plus(variant.skip_tags, variant.skip_tag_meta_tags)
    if any(t in have for t in skip):
        return False          # skip wins over require
    want = meta.plus(variant.require_tags, variant.require_tag_meta_tags)
    return not want or any(t in have for t in want)


def _degrade_entries(af, src_path: Path, base_entry: dict, cfg, buckets,
                     item_tags: set[str], origins, counts: dict,
                     meta: "MetaTagResolver") -> list[dict]:
    """The EXTRA manifest entries one item contributes for the run's variants.

    A degraded picture never replaces its original — the clean entry is built
    and weighted exactly as it would have been — so this only ever appends. An
    entry is a copy of the clean one with its pixels, its latent paths and its
    tag list swapped; width, height, bucket, boxes and tag groups carry over
    untouched, which is correct because it is the same picture at the same size.

    The pixels are made HERE and not in the trainer, which runs in a
    Pillow-only venv with no ffmpeg and no library. That is also what makes
    the cache possible: a value drawn per ``(file, variant, i)`` is one fixed
    thing, where a range could never be a cache key.
    """
    from PIL import Image

    from . import degrade as dg

    out: list[dict] = []
    src = None                       # opened lazily: most runs have no variants
    try:
        for variant in cfg.degrade.variants:
            label = variant.name.strip() or variant.method
            counts.setdefault(label, 0)
            if not _variant_allows(variant, item_tags, meta):
                continue
            # A removed tag goes before the trainer's random pick, so its slot
            # is refilled rather than lost — and its ancestors go with it, or
            # removing `masterpiece` while `high_quality` stays removes nothing.
            drop = meta.plus(variant.remove_tags,
                             variant.remove_tag_meta_tags)
            gone = _with_implied(origins, set(drop)) if drop else set()
            lowered = {g.lower() for g in gone}
            tags = [t for t in base_entry["tags"] if t.lower() not in lowered]
            forced = [t.strip() for t in variant.tags if t.strip()]
            # Seeded on the file's CONTENT, so the same picture degrades the
            # same way in every library and across a rebuild from item folders
            # — see `degrade.file_seed`.
            seed = dg.file_seed(af.sha256, af.id)
            for i in range(variant.variations):
                drawn = dg.draw(variant, seed, i)
                key = dg.key(drawn)
                ext = dg.output_format(drawn)
                rel = af.artifact_name("degraded", key, ext)
                dst = af.artifact_path("degraded", key, ext)
                # BOTH the bytes and the row are checked, because they can
                # disagree: a pruned file whose row survived, or bytes whose
                # row went with something else. Re-encoding is cheap; a
                # manifest pointing at a file that is not there is not.
                if not dst.is_file():
                    if src is None:
                        src = Image.open(src_path)
                        src.load()
                    data = dg.encode(src, drawn)
                    with Image.open(io.BytesIO(data)) as made:
                        w, h = made.size
                    if af.find_artifact("degraded", name=rel) is None:
                        # The drawn key IS the label — "jpeg-q37-s420" says
                        # more than any sentence the Source list could fit.
                        af.add_artifact("degraded", data, key=key, ext=ext,
                                        model=key, width=w, height=h)
                    else:
                        dst.write_bytes(data)
                elif af.find_artifact("degraded", name=rel) is None:
                    with Image.open(dst) as made:
                        w, h = made.size
                    af.record_artifact("degraded", key=key, ext=ext, model=key,
                                       width=w, height=h)
                entry = dict(base_entry)
                entry["path"] = str(dst)
                entry["tags"] = tags
                # SPLIT across the variations, not repeated per variation. The
                # weight is what share of the run this variant gets, and
                # `variations` is how many different strengths that share is
                # spread over — one is a training decision and the other a
                # cache-and-variety one, and entangling them means raising the
                # variety silently retunes the mix (and makes the editor's
                # stated ratio a lie).
                entry["weight"] = variant.weight / variant.variations
                entry["force_tags"] = forced
                entry["degrade"] = key
                entry["degrade_rel"] = rel
                _latents(entry, af, cfg.model, buckets[base_entry["bucket"]],
                         cfg.buckets.alpha_mask, key)
                out.append(entry)
                counts[label] += 1
    finally:
        if src is not None:
            src.close()
    return out


# ---- after the run ----------------------------------------------------------


def register_latents(lib, job_dir: Path) -> int:
    """Index the latent caches a run produced as ``FileArtifact`` rows.

    The trainer writes the bytes (it owns the VAE) but never touches the
    library; this runs afterwards in the manager and records what actually
    landed on disk, so latents show up in the library's bookkeeping, are
    cleaned up with their item, and are visibly attached to the file they
    belong to. Idempotent — re-running only adds rows that are missing.
    """
    manifest = tp.read_json(job_dir / "manifest.json")
    if not manifest:
        return 0
    model = (manifest.get("model") or {}).get("key", "")
    added = 0
    with lib.transaction():
        for entry in manifest.get("items", []):
            fid = entry.get("file_id")
            if not fid:
                continue
            try:
                af = lib.file(fid)
            except Exception:
                continue
            # A degraded copy's latents hang off the degraded IMAGE rather
            # than off the source file directly, so deleting that image takes
            # them with it by cascade — they describe pixels that no longer
            # exist. Looked up by the path the manifest carries, rather than
            # parsed back out of the latent's own name.
            parent = None
            if entry.get("degrade_rel"):
                parent = af.find_artifact("degraded",
                                          name=entry["degrade_rel"])
            for rel_key in ("latent_rel", "latent_rel_flipped"):
                rel = entry.get(rel_key)
                if not rel:
                    continue
                before = af.find_artifact("latent", name=rel)
                bw, bh = _bucket_from_name(rel)
                got = af.record_artifact(
                    "latent", key=_key_from_name(rel), ext="pt", model=model,
                    width=bw, height=bh, parent=parent)
                if got is not None and before is None:
                    added += 1
    return added


def _key_from_name(rel: str) -> str:
    """The cache key back out of ``artifacts/<n>-latent-<key>.pt``."""
    stem = rel.rsplit("/", 1)[-1]
    if stem.endswith(".pt"):
        stem = stem[:-3]
    return stem.split("-latent-", 1)[-1]


def _bucket_from_name(rel: str) -> tuple[int, int]:
    """The bucket size out of the tail (…-<w>x<h>[-f].pt)."""
    try:
        size = rel.rsplit("-", 2)[-2] if rel.endswith("-f.pt") \
            else rel.rsplit("-", 1)[-1].split(".")[0]
        bw, bh = (int(v) for v in size.split("x"))
        return bw, bh
    except (ValueError, IndexError):
        return 0, 0
