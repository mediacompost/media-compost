"""The manifest a dataset materializes to, pinned byte for byte.

This exists for ONE change: moving the manifest builder off `db.py`,
`searchctx` and `resolve` and onto the public Python API, so training can
live in a package of its own. That rewrite deletes about three hundred lines
and replaces a hand-built `QueryCtx` with `lib.query()` — and almost every way
of getting it subtly wrong produces a manifest that still looks entirely
reasonable. A dataset that quietly lost the hidden items, or ordered its
entries differently so every `groups[].items` index shifted, or re-derived a
cache name one character off, trains perfectly well and trains on the wrong
thing.

So the answer is a corpus rather than assertions: a library with one of
everything, a spread of configs over it, and the whole manifest compared.
Two things are recorded, because neither catches the other's failure —
the manifest (which is what the trainer reads) and the set of `FileArtifact`
rows the run creates (which is where a cache-key drift shows up, and which
the manifest's normalized paths would hide).

The fixture is built in-test rather than pointing at a demo library on disk,
and deliberately: such a library lives outside the repository, so a test that
reached for one would stop working on any other machine. It also has no
hidden items, which is exactly the case the rewrite is most likely to get
wrong.

Regenerate with MEDIA_COMPOST_UPDATE_GOLDEN=1, and say in the commit which
entries moved and why. There is nothing here that should be re-recorded
merely because it went red.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from media_compost import media, open_library
from media_compost.ui.config import UiConfig
from media_compost.db import FileArtifact
from media_compost.ui.server.deps import Library
from media_compost.train.dataset import build_manifest
from media_compost.testing import make_image

GOLDEN = Path(__file__).parent / "golden" / "training_manifests.json"


# ---- the library -------------------------------------------------------------


def _video(path: Path, seconds: int = 4) -> None:
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi",
         "-i", f"testsrc=size=320x180:rate=10:duration={seconds}",
         "-pix_fmt", "yuv420p", str(path)], check=True)


@pytest.fixture(scope="session")
def _corpus_template(tmp_path_factory):
    """The corpus, built ONCE and never handed to a test.

    Building it is 0.60 s (six pictures, a video through ffmpeg, then the
    tag set and the assignments below); COPYING the finished library is
    0.006 s. So it is built once and every test gets its own copy — see
    `corpus`.
    """
    return _make_corpus(tmp_path_factory.mktemp("corpus-template"))


@pytest.fixture
def corpus(_corpus_template, tmp_path: Path):
    """A private copy of the corpus, per test.

    It used to be ONE module-scoped library shared by all thirteen tests that
    build a dataset against it — and several of those leave `degraded` copies
    and cached latents behind, so what each test found depended on which of its
    siblings had run first. Invisible to a test asserting on a MANIFEST, which
    describes only its own build; not invisible to the one asserting on the
    artifact TABLE, which was comparing the sediment of all of them in rowid
    order. That is how inserting a test earlier in this file, reordering two,
    or splitting the module across xdist workers each silently changed what a
    golden compared.

    Sharing was only ever a runtime optimisation — the fixture's own comment
    said so — and at 100x cheaper to copy than to build, the optimisation is
    now to copy. Full independence costs ~6 ms a test.
    """
    dst = tmp_path / "lib"
    data, uids = _corpus_template
    shutil.copytree(data, dst)
    return dst, uids


def _make_corpus(tmp: Path) -> tuple[Path, dict]:
    """Build the library the fixtures above hand out."""
    src = tmp / "src"
    src.mkdir()
    for i in range(6):
        make_image(src / f"p{i}.png", seed=i, size=(400 + i * 8, 300))
    _video(src / "clip.mp4")

    data = tmp / "data"
    with open_library(data, user="alice") as lib:
        lib.import_all(sorted(src.iterdir()))
        items = sorted(lib.query(), key=lambda i: i.id)
        pics = [i for i in items if i.kind == "image"]
        film = next(i for i in items if i.kind == "video")

        # A tag set with implications and a granting group, so effective
        # tags are not merely the direct ones.
        lib.tags.get_or_create("animal")
        lib.tags.create("dog", implies="animal")
        lib.tags.create("poodle", implies="dog")
        lib.tags.get_or_create("masterpiece")
        lib.tags.get_or_create("photo")
        group = lib.groups.create("Pets")
        group.tags.add("creature")

        for i, it in enumerate(pics):
            it.tags.add("photo")
            if i % 2 == 0:
                it.tags.add("poodle")
                it.groups.add(group)
            else:
                it.tags.add("masterpiece")

        # Geometry, in the item's reference frame.
        pics[0].tags["poodle"].boxes.add(0.25, 0.2, 0.4, 0.5)

        # A per-item tag group with a meta tag, and one without.
        block = pics[0].tag_groups.create("hers")
        pics[0].tags.add("scarf", group=block)
        pics[0].tags.add("hat", group=block)
        block.meta_tags.add("clothing")
        plain = pics[1].tag_groups.create("scene")
        pics[1].tags.add("beach", group=plain)

        # A subject with a face — the box fallback a subject's tag gets.
        alice = lib.create_subject("Alice")
        pics[2].tags.add(alice.tag.name)
        pics[2].add_face(0.3, 0.15, 0.25, 0.3).name(alice)

        # Captions, one carrying a meta tag, plus an instruction with refs.
        for i, it in enumerate(pics[:4]):
            cap = it.add_caption(f"a photograph, number {i}")
            if i % 2 == 0:
                cap.meta_tags.add("short")
        pics[3].add_instruction("make it snow", refs=[pics[0], pics[1]])

        # A film with an untimed tag and a timed one covering its first half.
        film.tags.add("photo")
        film.tags.add("dog")
        film.tags["dog"].boxes.add(time=(0.0, 2.0))

        # The three states the candidate scan has to get right.
        pics[4].hide()
        pics[5].trash()
        lib.create_sequence([pics[0], pics[1]], name="a chapter")

        uids = {i.uid: f"item{i.id}" for i in lib.query(None, show_hidden=True)}
        uids.update({i.uid: f"item{i.id}" for i in lib.trash})
    return data, uids


# ---- normalizing --------------------------------------------------------------


#: `items/<uid[:2]>/<uid>/…` — the shard directory is the first two characters
#: of a uid, so it is as random as the uid and has to go the same way.
_SHARD = re.compile(r"items/[0-9a-f]{2}/item(?=\d)")


def _norm(value, data: Path, uids: dict, job: Path = None):
    """Everything machine-specific out, and NOTHING else.

    Not ordering, not `tag_groups[].tags` — those are exactly what a rewrite
    is liable to change without meaning to, so they stay in the comparison.
    """
    if isinstance(value, dict):
        return {k: _norm(v, data, uids, job) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v, data, uids, job) for v in value]
    if isinstance(value, str):
        out = value.replace(os.sep, "/")
        if job is not None:
            out = out.replace(str(job).replace(os.sep, "/"), "<job>")
        out = out.replace(str(data).replace(os.sep, "/"), "<lib>")
        for uid, name in uids.items():
            out = out.replace(uid, name)
        return _SHARD.sub("items/item", out)
    return value


def _artifact_rows(data: Path, uids: dict) -> list:
    cfg = UiConfig(data_dir=data)
    lib = Library(cfg)
    try:
        with lib.db.session() as s:
            # By PATH, not by rowid: the path is what this test is about (a
            # renamed artifact is the failure it exists to catch), and it is
            # the same string whatever order the rows were inserted in. Rowid
            # order made the comparison depend on insertion order, which is
            # a fact about the test run rather than about the library.
            rows = s.query(FileArtifact).order_by(FileArtifact.path).all()
            return [{"kind": r.kind, "model": r.model, "format": r.format,
                     "path": _norm(r.path, data, uids),
                     "nested": r.parent_id is not None,
                     # A list, not a tuple: this is compared against JSON,
                     # where a tuple has come back as a list and would never
                     # match however right the numbers are.
                     "size": [r.width, r.height]} for r in rows]
    finally:
        lib.db.engine.dispose()


def _build(data: Path, config: dict, job_dir: Path) -> dict:
    """Materialize one dataset.

    The one line that knows which `Library` the builder takes. It was
    `server.deps.Library` — the server's — when these goldens were recorded,
    and is the public `open_library` now. The recorded goldens did not move,
    which is the whole proof the rewrite was a rewrite.
    """
    job_dir.mkdir(parents=True, exist_ok=True)
    with open_library(data, source="cli") as lib:
        return build_manifest(lib, config, job_dir)


# ---- the corpus of configs ----------------------------------------------------


def _cfg(**over) -> dict:
    from media_compost.train.spec import DatasetQuery, TrainingConfig

    base = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)])
    got = base.model_dump(mode="json")
    # PINNED, not inherited: `skip_upscale` defaults to True, and this corpus's
    # pictures are a few hundred pixels wide — every one of them is below its
    # bucket, so the whole corpus would build nothing but "all N matched images
    # are smaller than the training resolution". These cases are about what a
    # manifest CONTAINS; the default is exercised where it belongs, in
    # test_training.py. Pinning it is also what keeps this golden byte-identical
    # across the flip, which is the evidence the flip changed only the default.
    got["buckets"]["skip_upscale"] = False
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(got.get(key), dict):
            got[key].update(value)
        else:
            got[key] = value
    return got


def _q(search: str, weight: float = 1.0, regularize: bool = False) -> dict:
    from media_compost.querystring import parse
    from media_compost.train.spec import DatasetQuery

    return DatasetQuery(tree=parse(search), search=search, weight=weight,
                        regularize=regularize).model_dump(mode="json")


def cases() -> dict:
    return {
        "tags": _cfg(),
        "captions": _cfg(captions={"source": "captions"}),
        "both": _cfg(captions={"source": "both", "trigger": "mystyle"}),
        # An instruction run needs an EDITING checkpoint; the config refuses
        # the pair outright, which is the point of `TrainModelSpec.edit`.
        "instructions": _cfg(model="flux1_kontext",
                             captions={"source": "instructions"}),
        "freq_library": _cfg(captions={"freq_base": "library",
                                       "balance": "inverse_freq"}),
        "freq_dataset": _cfg(captions={"freq_base": "dataset",
                                       "balance": "inverse_freq"}),
        "group_tags": _cfg(captions={"group_tags": True,
                                     "group_label": "subject"}),
        "exclude_group": _cfg(captions={
            "exclude_tag_group_meta_tags": ["clothing"]}),
        "caption_meta": _cfg(captions={"include_meta_tags": ["short"]}),
        "caption_meta_excl": _cfg(captions={"exclude_meta_tags": ["short"]}),
        "video": _cfg(video={"include": True, "every": 1.0,
                             "unit": "seconds", "dedupe": True}),
        "query_tag": _cfg(queries=[_q("poodle")]),
        # `SUBJECT:` keys on the identity TAG's name, not the display name.
        "query_subject": _cfg(queries=[_q("SUBJECT:subject:alice")]),
        "query_meta": _cfg(queries=[_q("INFO:width>=408")]),
        "multi_query": _cfg(queries=[_q("poodle", 2.0), _q("masterpiece", 0.5),
                                     _q("")]),
        "degrade": _cfg(degrade={"variants": [{
            "name": "jpeg", "method": "jpeg", "weight": 0.5,
            "tags": ["jpeg artifacts"], "remove_tags": ["masterpiece"],
            "require_tags": ["photo"], "variations": 2,
            "quality": {"lo": 20, "hi": 60}}]}),
    }


@pytest.fixture(autouse=True)
def _no_hub_cache(tmp_path_factory, monkeypatch):
    """The golden must not depend on what this developer has downloaded.

    `model.local_dir` is `snapshot_dir_for(repo)` — the cached snapshot
    directory when the cache holds every file the pipeline loads, and "" when
    it does not. That is a fact about the MACHINE, and it made this golden
    fail the day somebody downloaded FLUX.1 Kontext: the run wrote an absolute
    path into their home directory where the recording says "".

    So every case here resolves against an empty cache and records "". The key
    stays in the golden, saying what it says — nothing cached, nothing to load
    locally from — and `test_a_complete_cache_is_loaded_from_its_snapshot_dir`
    covers the other half, which no golden can hold because its value is
    a path that differs per machine.

    Pointing `HF_HUB_CACHE` at a temp dir is what this WOULD be, and it does
    not work from inside a test: huggingface_hub reads that variable once, at
    import, into `constants.HF_HUB_CACHE`. Setting the constant is the same
    thing at the moment it is actually read (`try_to_load_from_cache` resolves
    it per call), and it also holds when the variable is already set in the
    environment — which is how this file is meant to be verified.
    """
    from huggingface_hub import constants

    empty = tmp_path_factory.mktemp("empty-hf-cache")
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(empty))


@pytest.mark.parametrize("name", sorted(cases()))
def test_the_manifest_is_what_it_was(name, corpus, tmp_path: Path):
    data, uids = corpus
    job = tmp_path / "job"
    got = _norm(_build(data, cases()[name], job), data, uids, job)

    stored = json.loads(GOLDEN.read_text(encoding="utf-8")) \
        if GOLDEN.is_file() else {}
    if os.environ.get("MEDIA_COMPOST_UPDATE_GOLDEN"):
        stored[name] = got
        GOLDEN.write_text(json.dumps(stored, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
        pytest.skip(f"recorded {name}")
    assert name in stored, (
        f"no golden for {name!r} — record it with MEDIA_COMPOST_UPDATE_GOLDEN=1")
    assert got == stored[name]


# ---- regularization pools ----------------------------------------------------
#
# Behaviour rather than a golden, because the rule that matters is a
# PRECEDENCE — a picture in both kinds of pool is a training picture — and the
# way to get it wrong quietly is to have it come out the other way round: the
# run's own pictures would lose their trigger word and be down-weighted, and
# nothing about the manifest would look unusual.


def _reg_flags(data, config, job_dir):
    m = _build(data, config, job_dir)
    return [bool(e.get("reg")) for e in m["items"]], m


def test_a_regularization_pool_marks_ONLY_its_own_entries(corpus, tmp_path):
    data, _ = corpus
    cfg = _cfg(queries=[_q("poodle"), _q("photo", regularize=True)])
    flags, m = _reg_flags(data, cfg, tmp_path / "job")
    assert any(flags), "the regularization pool marked nothing"
    assert not all(flags), "it marked the training pool too"


def test_a_TRAINING_query_WINS_over_a_regularization_one(corpus, tmp_path):
    """The precedence rule. The reminder query here selects everything, so
    without it the run's own pictures would be demoted to reminders."""
    data, _ = corpus
    cfg = _cfg(queries=[_q("poodle"), _q("", regularize=True)])
    flags, _ = _reg_flags(data, cfg, tmp_path / "job")
    assert any(flags), "nothing was left as a reminder"
    poodle_only = _cfg(queries=[_q("poodle")])
    n_training = len(_build(data, poodle_only, tmp_path / "job2")["items"])
    assert flags.count(False) == n_training, (
        "the training pool's own entries were marked as regularization")


def test_a_FULLY_OVERLAPPING_reminder_query_contributes_nothing(corpus, tmp_path):
    data, _ = corpus
    cfg = _cfg(queries=[_q("poodle"), _q("poodle", regularize=True)])
    flags, _ = _reg_flags(data, cfg, tmp_path / "job")
    assert not any(flags)


def test_a_run_of_NOTHING_BUT_reminders_is_refused(corpus, tmp_path):
    """Decidable from the config alone, so it is refused before the job can be
    queued rather than materialized and trained."""
    from media_compost.train.spec import TrainingConfig

    cfg = TrainingConfig.model_validate(
        _cfg(queries=[_q("poodle", regularize=True)]))
    assert "regularization" in (cfg.ready_to_queue() or "")


def test_a_reminder_entry_gets_NO_TRIGGER_WORD(corpus, tmp_path):
    """The half that lives in the trainer: the flag is only worth setting
    because `compose` reads it, and a reminder carrying the trigger would
    teach the trigger to mean the ordinary thing."""
    import importlib.util

    from media_compost.train.paths import TRAIN_SCRIPTS

    spec = importlib.util.spec_from_file_location(
        "compose_for_reg", TRAIN_SCRIPTS / "compose.py")
    compose = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compose)

    import random

    cfg = {"source": "tags", "trigger": "mystyle", "separator": ", "}
    train = {"tags": ["poodle"]}
    remind = {"tags": ["poodle"], "reg": True}
    assert compose.compose_caption_and_tags(
        train, cfg, {}, random.Random(0))[0].startswith("mystyle")
    assert "mystyle" not in compose.compose_caption_and_tags(
        remind, cfg, {}, random.Random(0))[0]


# ---- meta tags on the tag set ---------------------------------------------
#
# Every one of these settings names the tags a rule applies to by what the
# LIBRARY says about them rather than one by one, and every one is resolved to
# tag names HERE — the trainer never learns what a meta tag is. So what these
# check is the resolution: that the setting reaches the manifest, and that a
# job using none of them produces exactly the manifest it always did (which is
# what the goldens above already say, since none of them set one).


def _mark(data: Path, tag: str, meta: str) -> None:
    """Say something about a tag, the way the Tags tab does."""
    with open_library(data, source="cli") as lib:
        lib.tags.get_or_create(tag).meta_tags.add(meta)


def test_a_meta_tag_can_veto_mirroring(corpus, tmp_path: Path):
    """`no_flip_meta_tags` marks the ENTRIES, not the config: the trainer
    reads a per-entry flag, so the rule is stated once in the library and
    still applies to a tag added after the job was written."""
    data, _ = corpus
    _mark(data, "masterpiece", "noflip")
    plain = _build(data, _cfg(), tmp_path / "plain")
    assert not any("no_flip" in e for e in plain["items"]), (
        "an unused setting must leave the manifest exactly as it was")

    cfg = _cfg(buckets={"no_flip_meta_tags": ["noflip"]})
    m = _build(data, cfg, tmp_path / "job")
    flagged = {e["item_id"] for e in m["items"] if e.get("no_flip")}
    assert flagged, "nothing was vetoed"
    # Exactly the pictures carrying a marked tag, and no others. The scope is
    # the BUILDER's — `lib.query` folds a sequence container in (a container
    # carries its members' tags), and a container has no picture to flip.
    with open_library(data, source="cli") as lib:
        want = {i.id for i in lib.query("masterpiece", kind="image",
                                        show_hidden=True)}
    assert flagged == want


def test_a_marked_tag_is_excluded_from_prompts(corpus, tmp_path: Path):
    """`exclude_tag_meta_tags` resolves to names in the manifest, which the
    trainer unions into the caption config it already reads."""
    data, _ = corpus
    _mark(data, "photo", "noprompt")
    cfg = _cfg(captions={"exclude_tag_meta_tags": ["noprompt"]})
    m = _build(data, cfg, tmp_path / "job")
    assert m["tag_meta_names"] == {"exclude": ["photo"]}
    # And the other half of the pair, so one key cannot quietly serve both.
    cfg = _cfg(captions={"always_tag_meta_tags": ["noprompt"]})
    m = _build(data, cfg, tmp_path / "job2")
    assert m["tag_meta_names"] == {"always": ["photo"]}


def test_a_degrade_variant_can_be_gated_by_what_a_tag_is_marked(corpus,
                                                                tmp_path: Path):
    """The variant's require / skip pair, one level up. `skip` wins over
    `require` here exactly as it does for the named lists."""
    data, _ = corpus
    _mark(data, "poodle", "degradable")

    def variant(**over) -> dict:
        from media_compost.train.spec import DegradeVariant

        base = {"name": "j", "method": "jpeg", "tags": ["jpeg_artifacts"]}
        return DegradeVariant(**{**base, **over}).model_dump(mode="json")

    got = _build(data, _cfg(degrade={"variants": [
        variant(require_tag_meta_tags=["degradable"])]}), tmp_path / "a")
    degraded = {e["item_id"] for e in got["items"] if e.get("degrade")}
    with open_library(data, source="cli") as lib:
        want = {i.id for i in lib.query("poodle", kind="image",
                                        show_hidden=True)}
    assert degraded == want and degraded

    got = _build(data, _cfg(degrade={"variants": [
        variant(require_tag_meta_tags=["degradable"],
                skip_tag_meta_tags=["degradable"])]}), tmp_path / "b")
    assert not any(e.get("degrade") for e in got["items"]), "skip must win"


# ---- masked regions ----------------------------------------------------------
#
# The loss-mask boxes are resolved HERE, at manifest time — the trainer only
# ever sees rectangles — so what these pin is the resolution: the boxes reach
# the entries that carry a masked tag's box, every copy of an entry inherits
# them, and a run without the setting produces the manifest it always did
# (which the goldens above already say, since none of them set one).


def test_value_rules_resolve_first_match_and_stay_conditional(tmp_path: Path):
    """The rules become a finished tag → text map at manifest time — first
    match wins (the list's order is configuration), units convert through the
    family, a word sharing the namespace never matches, and a run with no
    rules writes no key at all."""
    from media_compost import open_library
    from media_compost.testing import make_image

    src = tmp_path / "pics"
    src.mkdir()
    for i in range(2):
        make_image(src / f"p{i}.png", seed=i, size=(256, 256))
    with open_library(tmp_path / "lib", source="cli") as lib:
        lib.import_all(sorted(src.iterdir()))
        items = list(lib.query())
        items[0].tags.add("height:172cm")
        items[0].tags.add("height:tall")
        items[1].tags.add("height:2.10m")
    rules = [
        {"namespace": "height", "op": ">", "value": 2.0, "unit": "m",
         "text": "very tall", "keep_raw": False},
        {"namespace": "height", "op": ">", "value": 1.5, "unit": "m",
         "text": "tall", "keep_raw": True},
    ]
    m = _build(tmp_path / "lib",
               _cfg(captions={"source": "tags", "value_rules": rules}),
               tmp_path / "job")
    vm = m["value_map"]
    assert vm["height:2.10m"] == {"text": "very tall", "keep": False}
    assert vm["height:172cm"] == {"text": "tall", "keep": True}
    assert "height:tall" not in vm
    plain = _build(tmp_path / "lib", _cfg(captions={"source": "tags"}),
                   tmp_path / "job2")
    assert "value_map" not in plain


def test_masked_regions_reach_the_manifest(corpus, tmp_path: Path):
    data, _ = corpus
    plain = _build(data, _cfg(), tmp_path / "plain")
    assert not any("mask_boxes" in e for e in plain["items"]), (
        "an unused setting must leave the manifest exactly as it was")

    cfg = _cfg(buckets={"mask_loss_tags": ["poodle"], "mask_loss_weight": 0.0})
    m = _build(data, cfg, tmp_path / "job")
    masked = [e for e in m["items"] if e.get("mask_boxes")]
    assert masked, "the drawn poodle box reached no entry"
    # The masked boxes are exactly that tag's crop-steering boxes — one
    # resolution, not a second one that can drift.
    for e in masked:
        assert e["mask_boxes"] == e["boxes"]["poodle"]


def test_masked_regions_resolve_meta_tags_and_reach_degraded_copies(
        corpus, tmp_path: Path):
    data, _ = corpus
    _mark(data, "poodle", "maskme")
    cfg = _cfg(buckets={"mask_loss_meta_tags": ["maskme"],
                        "mask_loss_weight": 0.1},
               degrade=cases()["degrade"]["degrade"])
    m = _build(data, cfg, tmp_path / "job")
    clean = [e for e in m["items"]
             if e.get("mask_boxes") and not e.get("degrade")]
    spoiled = [e for e in m["items"]
               if e.get("mask_boxes") and e.get("degrade")]
    assert clean, "the meta tag resolved to nothing"
    # A degraded copy is the same picture, so it carries the same regions.
    assert spoiled and all(
        s["mask_boxes"] == clean[0]["mask_boxes"]
        for s in spoiled if s["item_id"] == clean[0]["item_id"])


def test_a_mask_weight_of_one_is_off(corpus, tmp_path: Path):
    """Weighting a masked cell at 1 IS the unmasked loss, so the validator
    settles it and the builder never resolves a box for it."""
    data, _ = corpus
    cfg = _cfg(buckets={"mask_loss_tags": ["poodle"], "mask_loss_weight": 1.0})
    m = _build(data, cfg, tmp_path / "job")
    assert not any("mask_boxes" in e for e in m["items"])


# ---- more than one resolution ------------------------------------------------
#
# Behaviour rather than a golden, for the reason the validation split below is:
# what matters is the RULE (one entry per size a picture fits, its own latent
# cache) rather than the exact bytes — and the goldens above are the other
# half of it, since every one of them names one size and must therefore be
# untouched.


def test_a_second_resolution_adds_an_entry_per_picture(corpus, tmp_path: Path):
    data, _ = corpus
    one = _build(data, _cfg(buckets={"resolutions": [512]}), tmp_path / "one")
    two = _build(data, _cfg(buckets={"resolutions": [256, 512]}),
                 tmp_path / "two")
    # EXTRA, never a replacement: everything the one-size run built is still
    # there, entry for entry.
    assert one["resolution"] == two["resolution"] == 512, (
        "`resolution` is the LARGEST size — the one the run costs what it "
        "costs for, and the only one when there is only one")
    assert "resolutions" not in one, (
        "a run at one size must write the manifest it always did")
    assert two["resolutions"] == [256, 512]
    assert len(two["items"]) == 2 * len(one["items"])

    per_item: dict[int, set[int]] = {}
    for e in two["items"]:
        per_item.setdefault(e["item_id"], set()).add(e["bucket"])
    assert all(len(b) == 2 for b in per_item.values()), per_item
    # The two are the two FAMILIES and not two shapes of one: a bucket's
    # area is its resolution squared, give or take the step's rounding.
    for buckets in per_item.values():
        areas = sorted(two["buckets"][b][0] * two["buckets"][b][1]
                       for b in buckets)
        assert 256 ** 2 * 0.8 <= areas[0] <= 256 ** 2
        assert 512 ** 2 * 0.8 <= areas[1] <= 512 ** 2
    # A LATENT CACHE PER SIZE, or the second resolution would read the
    # first's pixels back: the key carries the bucket, so this is really a
    # check that the entry was built against its own family.
    for e in two["items"]:
        bw, bh = two["buckets"][e["bucket"]]
        assert e["latent_rel"].endswith(f"-{bw}x{bh}.pt"), e["latent_rel"]
    # Every entry is in the pool: a size nothing points at trains nothing.
    pooled = {i for g in two["groups"] for i in g["items"]}
    assert pooled == set(range(len(two["items"])))


def test_never_upscale_is_asked_PER_RESOLUTION(corpus, tmp_path: Path):
    """The other half of what several resolutions are for.

    The corpus's pictures are a few hundred pixels wide, so at 512 every one
    of them is below its bucket and the run has nothing to train on. Adding
    256 does not lower the run — it lets each picture join at the size it
    actually fits, which is the alternative to dropping it.
    """
    cfg = _cfg(buckets={"resolutions": [512], "skip_upscale": True})
    with pytest.raises(ValueError, match="smallest resolution"):
        _build(corpus[0], cfg, tmp_path / "too-big")

    cfg["buckets"]["resolutions"] = [256, 512]
    m = _build(corpus[0], cfg, tmp_path / "job")
    assert m["items"], "no picture joined the resolution it fits"
    # ONLY the small one: a picture that cannot be trained at 512 is not
    # quietly trained there because another size let it in.
    for e in m["items"]:
        bw, bh = m["buckets"][e["bucket"]]
        assert e["width"] >= bw and e["height"] >= bh, e


def test_the_resolutions_are_a_set_of_sizes(tmp_path: Path):
    """Normalized on the config, so the file on disk, the editor and the run
    cannot disagree — and 0 is resolved where the model is KNOWN."""
    from media_compost.train.spec import (
        MAX_RESOLUTIONS, BucketConfig, DatasetQuery, TrainingConfig,
    )

    assert BucketConfig(resolutions=[768, 512, 768]).resolutions == [512, 768]
    # 0 IS A MEMBER — the model's own size — and sorts to the front.
    assert BucketConfig(resolutions=[512, 0]).resolutions == [0, 512]
    # Naming nothing is naming the model's own size. A run trains at some
    # size, so there is no empty answer to store.
    assert BucketConfig(resolutions=[]).resolutions == [0]
    with pytest.raises(ValueError, match="at most"):
        BucketConfig(resolutions=list(
            range(256, 256 + 64 * (MAX_RESOLUTIONS + 1), 64)))
    # THE EDITOR HOLDS THE SAME NUMBER, because the picker stops offering
    # another tick rather than letting Save answer 400 — and a cap that
    # disagreed would do exactly that, on the press after the last one it
    # allowed. The backend is the authority; this is the copy.
    ui = (Path(__file__).resolve().parents[2]
          / "frontend/src/train/util.ts").read_text(encoding="utf-8")
    assert ("export const MAX_RESOLUTIONS = %d;" % MAX_RESOLUTIONS
            in ui), "the editor's cap no longer matches the config's"

    def cfg(**b):
        return TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                              buckets=BucketConfig(**b))

    native = cfg().resolutions()[0]
    # A 0 BESIDE THE NUMBER IT RESOLVES TO IS THAT SIZE NAMED TWICE, and
    # `TrainingConfig` is the only level that can tell — it settles the
    # STORED list, which is what the cap counts and what the picker draws as
    # one marked row. The 0 survives: it is the more general answer, and the
    # one the picker writes.
    assert cfg(resolutions=[0, native]).buckets.resolutions == [0]
    assert cfg(resolutions=[0, native]).resolutions() == [native]
    # (SD 1.5's own size IS 512, so the third size here has to be one
    # that is not the model's, or the collapse eats the wrong row.)
    assert cfg(resolutions=[0, 768, native]).buckets.resolutions == [0, 768]
    assert cfg(resolutions=[768, 512]).resolutions() == [512, 768]
    # `resolution()` is the LARGEST, which is what the peak memory and the
    # slowest step are, and what `manifest["resolution"]` records.
    assert cfg(resolutions=[768, 512]).resolution() == 768




def test_validation_holds_images_out_of_every_pool(corpus, tmp_path: Path):
    data, _ = corpus
    cfg = _cfg(validation={"every_n_steps": 50, "holdout": 2,
                           "stable_items": 2})
    m = _build(data, cfg, tmp_path / "job")
    val = m["val_items"]
    stable = m["stable_items"]
    assert val and stable
    pooled = {j for g in m["groups"] for j in g["items"]}
    assert not (set(val) & pooled), "a held-out entry is still trained on"
    assert set(stable) <= pooled, "a stable-loss entry must stay in training"
    assert not (set(val) & set(stable))
    # In `items` regardless — being in no pool is what keeps them untrained.
    assert all(0 <= j < len(m["items"]) for j in val)

    # Deterministic: the same config over the same library asks about the
    # same pictures, whatever else happened in between.
    again = _build(data, cfg, tmp_path / "job2")
    assert again["val_items"] == val
    assert again["stable_items"] == stable


def test_the_holdout_holds_out_whole_IMAGES(corpus, tmp_path: Path):
    """Every entry of a held-out item leaves the pools — its degraded copies
    included, or the model trains on the validation picture under another
    prompt and the series quietly measures memorized data. The scored list
    itself stays clean (no degraded entries): they are augmentation, not the
    picture."""
    data, _ = corpus
    cfg = _cfg(validation={"every_n_steps": 50, "holdout": 2},
               degrade=cases()["degrade"]["degrade"])
    m = _build(data, cfg, tmp_path / "job")
    val_ids = {m["items"][j]["item_id"] for j in m["val_items"]}
    pooled = {j for g in m["groups"] for j in g["items"]}
    for j, e in enumerate(m["items"]):
        if e["item_id"] in val_ids:
            assert j not in pooled
    assert not any(m["items"][j].get("degrade") for j in m["val_items"])


def test_the_holdout_is_clamped_to_half_the_dataset(corpus, tmp_path: Path):
    data, _ = corpus
    cfg = _cfg(validation={"every_n_steps": 50, "holdout": 100})
    m = _build(data, cfg, tmp_path / "job")
    held_ids = {m["items"][j]["item_id"] for j in m["val_items"]}
    total_ids = {e["item_id"] for e in m["items"]}
    assert len(held_ids) == len(total_ids) // 2
    assert m["groups"], "a validation setting must never eat the dataset"


def test_validation_off_writes_no_keys(corpus, tmp_path: Path):
    data, _ = corpus
    # A cadence with nothing to score, and counts with no cadence: both off.
    for i, over in enumerate((
            {"every_n_steps": 0, "holdout": 8, "stable_items": 8},
            {"every_n_steps": 50, "holdout": 0, "stable_items": 0})):
        m = _build(data, _cfg(validation=over), tmp_path / f"job{i}")
        assert "val_items" not in m and "stable_items" not in m


def test_a_complete_cache_is_loaded_from_its_snapshot_dir(corpus, tmp_path: Path,
                                                          monkeypatch):
    """The other value of `model.local_dir`, which the goldens cannot hold.

    They resolve against an empty cache and so record "" forever (see
    `_no_hub_cache`) — but the branch that matters is the other one: with
    every file the pipeline loads already cached, the run is handed the
    SNAPSHOT DIRECTORY rather than the repo id, because loading by id makes
    diffusers ask the hub what the revision contains and offline it cannot,
    failing on a model that is entirely present. A golden cannot pin that: the
    value is an absolute path under whoever's home directory ran it.

    The cache is faked the way `tests/core/test_pipeline_files.py` fakes one —
    real files on disk plus a `cached_index` that points at them — so
    `local_state` reads the files rather than being told the answer, and
    everything from `snapshot_dir_for` down runs for real.
    """
    from media_compost.hub import pipeline_files as pf

    data, _ = corpus
    index = {"_class_name": "StableDiffusionPipeline",
             "unet": ["diffusers", "UNet2DConditionModel"],
             "vae": ["diffusers", "AutoencoderKL"]}
    snap = tmp_path / "snap"
    for folder in ("unet", "vae"):
        (snap / folder).mkdir(parents=True)
        (snap / folder / "config.json").write_text("{}", encoding="utf-8")
        (snap / folder / "diffusion_pytorch_model.safetensors").write_text(
            "x", encoding="utf-8")
    (snap / "model_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(pf, "cached_index", lambda repo: (index, snap))
    assert pf.local_state("any/repo") == "ready", "the fake cache must look complete"

    got = _build(data, cases()["tags"], tmp_path / "job")
    assert got["model"]["local_dir"] == str(snap)
    # And it is still the REPO that names the model — the directory says where
    # to load it from, not what it is.
    assert got["model"]["repo"] == "stable-diffusion-v1-5/stable-diffusion-v1-5"
    assert got["model"]["local"] is False


def test_a_local_path_overrides_the_cache(corpus, tmp_path: Path, monkeypatch):
    """A hand-pointed `local_path` is already a directory, so `local_dir` stays
    empty however complete the hub cache is — `repo` carries the path and
    `local` says which of the two it is. Without this, the two ways of naming a
    local model could both be filled in and the trainer would have to choose."""
    from media_compost.hub import pipeline_files as pf

    data, _ = corpus
    monkeypatch.setattr(pf, "snapshot_dir_for",
                        lambda repo: "/cache/should/not/be/consulted")
    got = _build(data, _cfg(local_path="/models/mine"), tmp_path / "job")
    assert got["model"] == {**got["model"], "repo": "/models/mine",
                            "local": True, "local_dir": ""}


def test_a_model_ADDED_AS_A_PATH_is_local_without_a_local_path(
        corpus, tmp_path: Path, monkeypatch):
    """The other way the weights are already here, and the one the app
    actually offers: a model added on the Models page by pointing at a
    checkpoint. Its `repo` IS the path, and nothing else says so — the
    manifest read `local` off `local_path` alone, so a user model's
    `.safetensors` went to the trainer marked as a hub id and was loaded with
    `from_pretrained`, which wants a folder."""
    from media_compost.hub import pipeline_files as pf
    from media_compost.train import training_dir, usermodels

    data, _ = corpus
    monkeypatch.setattr(pf, "snapshot_dir_for",
                        lambda repo: "/cache/should/not/be/consulted")
    store = training_dir(data)
    store.mkdir(parents=True, exist_ok=True)
    usermodels.write(store, [usermodels.UserModel(
        key="user:mine", label="Mine", base="sd15",
        repo="/models/mine.safetensors", local=True, area=0)])
    usermodels.refresh(store)
    try:
        got = _build(data, _cfg(model="user:mine"), tmp_path / "job")
    finally:
        from media_compost.train.models import set_user_specs
        set_user_specs({})
    assert got["model"] == {**got["model"], "repo": "/models/mine.safetensors",
                            "local": True, "local_dir": ""}


def test_the_artifacts_a_run_creates_are_what_they_were(corpus, tmp_path: Path):
    """The manifest alone cannot catch this: its paths are normalized, and a
    degraded copy or a latent named one character differently still appears
    in it. What breaks is every library that already has the old files —
    they stay on disk under a name nothing looks for, and everything is
    generated again with nothing to see.

    Every test gets its OWN copy of the corpus, so these rows are this build's
    and only this build's — see the `corpus` fixture for what the shared one
    was quietly including, and why comparing it in rowid order was the bug.
    """
    data, uids = corpus
    _build(data, cases()["degrade"], tmp_path / "job")
    got = _artifact_rows(data, uids)

    stored = json.loads(GOLDEN.read_text(encoding="utf-8")) \
        if GOLDEN.is_file() else {}
    if os.environ.get("MEDIA_COMPOST_UPDATE_GOLDEN"):
        stored["_artifacts"] = got
        GOLDEN.write_text(json.dumps(stored, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
        pytest.skip("recorded _artifacts")
    assert got == stored["_artifacts"]


def test_a_trigger_only_run_takes_every_picture_and_prompts_with_the_trigger(
        corpus, tmp_path: Path):
    """`source: "none"` is the trigger word ALONE.

    Two halves, and both matter. HERE: every selected picture is in the run
    whatever it carries, since there is nothing it could be missing — the
    "nothing to say in this mode" skip that drops an untagged picture from a
    tags run cannot apply. IN THE TRAINER: the composer writes the trigger
    and neither the tags nor the captions, and returns no used-tag list (so
    nothing steers a crop and nothing is weighted by frequency).
    """
    import importlib.util
    import random

    from media_compost.train.paths import TRAIN_SCRIPTS

    data, _uids = corpus
    every = _build(data, _cfg(queries=[_q("")]), tmp_path / "all")
    trigger_only = _build(
        data, _cfg(queries=[_q("")],
                   captions={"source": "none", "trigger": "mystyle"}),
        tmp_path / "none")
    # Same pictures, and at least one of them has nothing a CAPTIONS run
    # could have prompted with — or the claim above would be vacuous. (Every
    # picture in this corpus is tagged, so captions are the source that
    # drops one.)
    assert len(trigger_only["items"]) == len(every["items"])
    captioned = _build(
        data, _cfg(queries=[_q("")], captions={"source": "captions"}),
        tmp_path / "captions")
    assert len(captioned["items"]) < len(trigger_only["items"]), \
        "every picture here has a caption, so this proves nothing"

    spec = importlib.util.spec_from_file_location(
        "compose_for_none", TRAIN_SCRIPTS / "compose.py")
    compose = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compose)
    cfg = {"source": "none", "trigger": "mystyle", "separator": ", "}
    entry = {"tags": ["poodle", "outdoor"], "captions": ["a dog outside"]}
    prompt, used = compose.compose_caption_and_tags(entry, cfg, {},
                                                    random.Random(0))
    assert prompt == "mystyle", prompt
    assert used == []
    # A reminder entry still gets no trigger — which for this source leaves
    # it with nothing at all, correctly: it is in the run to be seen, not to
    # be named.
    assert compose.compose_caption_and_tags(
        {**entry, "reg": True}, cfg, {}, random.Random(0))[0] == ""
