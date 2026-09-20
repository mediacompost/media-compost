"""Training feature: compose math, manifest builder, manager lifecycle on the
simulator, and the /api/train contract.

MARKED `slow`, so it is out of the default run — 88 s of the backend suite's
~314, and almost none of it computing. The manager's scheduler is a 2 s TICK
THREAD and these tests wait on it: they spawn the fake trainer, then poll for
the state it writes. That is what makes them worth having (the lifecycle is
the thing that broke twice) and what makes them the wrong thing to pay for on
every edit to something else.

`pytest -m ""` runs them, and so does `pytest -m "not perf" -q`. CI does NOT
(owner 2026-09): a hosted runner repeating the long half of a suite that
passed here before the push buys a queue, and what it is there for is the
other machine — Linux, x86-64, an empty venv. The rule that argued for
running them there has moved rather than gone: a marker CI skips has to be
named in `ci.yml`'s header beside the command that runs it, which
`tests/ui/test_packaging.py` holds it to. A marker nobody runs and nobody
mentions is a test that has quietly stopped existing.
"""

from __future__ import annotations

import importlib.util
import json
import collections
import random
import time
from pathlib import Path

import pytest

from media_compost.db import Item as _Item
from media_compost.ops import tagassign
from media_compost.ops.context import Ctx

from media_compost.train.paths import TRAIN_SCRIPTS
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.db import (
    Item, ItemTag, ItemTagBox, ItemTagPlacement, Tag,
)
from media_compost.importer import ImportOptions, Importer
from media_compost.query import Group, TagCond
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from media_compost.train import paths as tp
from media_compost.train import training_dir
from media_compost.train.dataset import build_manifest, register_latents
from media_compost.querystring import parse
from media_compost.train.spec import (
    BucketConfig, CaptionConfig, DatasetQuery, TrainingConfig,
)
from media_compost.train import manager as manager_mod
from media_compost.train.manager import TrainingConflict, TrainingManager
from tests.train.conftest import (loop_module as _loop_module,
                                  train_module as _train_module)

#: See the module docstring. Whole-file, because the cost is the fixture and
#: the tick it waits on rather than any one case.
pytestmark = pytest.mark.slow


def _compose():
    p = TRAIN_SCRIPTS / "compose.py"
    spec = importlib.util.spec_from_file_location("compose_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


compose = _compose()


def _images():
    p = TRAIN_SCRIPTS / "images.py"
    spec = importlib.util.spec_from_file_location("images_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


images = _images()


# ---- alpha handling (masked training) ----------------------------------------


def _cutout(size=(64, 64), box=(16, 16, 48, 48)):
    """A red square on a fully transparent background."""
    from PIL import Image

    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste((220, 30, 30, 255), box)
    return img


def test_split_alpha_returns_none_for_opaque_images():
    from PIL import Image

    rgb, alpha = images.split_alpha(Image.new("RGB", (8, 8), (1, 2, 3)))
    assert rgb.mode == "RGB" and alpha is None
    # RGBA with a fully opaque alpha counts as opaque too.
    rgb, alpha = images.split_alpha(Image.new("RGBA", (8, 8), (1, 2, 3, 255)))
    assert alpha is None


def test_transparent_area_is_filled_with_the_edge_colour_not_black():
    """The VAE reaches across the alpha boundary, so the fill must be a smooth
    extension of the subject — a black hole would be encoded as a hard edge."""
    filled = images.fill_transparent(_cutout())
    assert filled.mode == "RGB"
    # Inside the square: untouched.
    assert filled.getpixel((32, 32)) == (220, 30, 30)
    # Just outside it: pulled toward the subject's colour, nowhere near black.
    r, g, b = filled.getpixel((10, 32))
    assert r > 120 and r > b + 40
    # Far away in the corner: still the subject's hue, and still not black.
    assert sum(filled.getpixel((0, 0))) > 90


def test_fill_is_low_frequency_so_the_vae_sees_no_hard_edge():
    """Neighbouring pixels in the filled region must differ only gently."""
    filled = images.fill_transparent(_cutout())
    worst = max(
        abs(filled.getpixel((x, 4))[0] - filled.getpixel((x + 1, 4))[0])
        for x in range(0, 62)
    )
    assert worst <= 8, f"fill has a {worst}-step jump — that is an edge"


def test_latent_mask_is_the_visible_fraction_of_each_cell():
    # 64x64 with a 32x32 opaque square -> 8x8 latent cells, each covering 8x8
    # pixels; the square covers cells 2..5 in both axes exactly.
    mask = images.latent_mask(_cutout().getchannel("A"), 8, 8)
    assert len(mask) == 64
    grid = [mask[r * 8:(r + 1) * 8] for r in range(8)]
    assert grid[4][4] == 1.0            # fully inside
    assert grid[0][0] == 0.0            # fully outside
    # A half-covered cell reports the fraction, not a 0/1 decision.
    half = images.latent_mask(_cutout(box=(0, 0, 4, 64)).getchannel("A"), 8, 8)
    assert abs(half[0] - 0.5) < 0.02


def test_background_weight_of_one_normalizes_masking_away():
    """A no-op mask must not be recorded as masked: the manifest would send the
    run to the masked latent cache and fill it with unfilled pixels."""
    from media_compost.train.spec import BucketConfig

    assert BucketConfig(alpha_mask=True, alpha_bg_weight=1.0).alpha_mask is False
    assert BucketConfig(alpha_mask=True, alpha_bg_weight=0.9).alpha_mask is True


def test_alpha_mask_gets_its_own_latent_cache_entries():
    """Masked runs feed the VAE different pixels, so the two caches must never
    be mistaken for each other — and the marker must not break the bucket-size
    parsing `register_latents` does on the name."""
    from media_compost.ops.artifacts import cache_name
    from media_compost.train.dataset import _latent_key

    def rels(masked: bool) -> tuple[str, str]:
        key = _latent_key("sdxl", (1024, 768), masked)
        return (cache_name(3, "latent", key, "pt"),
                cache_name(3, "latent", key + "-f", "pt"))

    plain, plain_f = rels(False)
    masked, masked_f = rels(True)
    assert plain != masked and plain_f != masked_f
    assert masked.endswith("-1024x768.pt") and masked_f.endswith("-1024x768-f.pt")
    assert "-am-" in masked


























def test_sample_size_falls_back_per_prompt_then_shared(tmp_path: Path):
    """Each test prompt may carry its own size; 0 means "use the section's
    shared size", and a 0 there means "the model's native one" (resolved in the
    engine, which is why it arrives as None)."""
    loop = _loop_module()

    captured = {}

    class _Engine:
        def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                             on_image=None, check=None):
            captured["prompts"] = prompts
            captured["batch"] = batch
            return []

    class _IO:
        def check_control(self):
            pass

        def sample_dir(self, step):
            # A real directory: _generate_samples stamps the round it rendered,
            # and Path(".") wrote that stamp into the repo's working directory.
            d = Path(tmp_path) / f"step-{step:06d}"
            d.mkdir(parents=True, exist_ok=True)
            return d

    loop._generate_samples(_IO(), _Engine(), {
        "width": 768, "height": 512,
        "prompts": [
            {"prompt": "shared", "negative": ""},
            {"prompt": "own", "negative": "", "width": 832, "height": 1216},
            {"prompt": "half", "negative": "", "width": 640, "height": 0},
        ],
    }, 100)
    assert captured["prompts"] == [
        ("shared", "", 768, 512),
        ("own", "", 832, 1216),
        ("half", "", 640, 512),        # only the width is overridden
    ]

    # No shared size either: the engine gets None and uses the native area.
    loop._generate_samples(_IO(), _Engine(), {
        "prompts": [{"prompt": "bare", "negative": ""}],
    }, 0)
    assert captured["prompts"] == [("bare", "", None, None)]


def test_a_round_is_announced_before_it_renders_and_images_land_one_by_one(
        tmp_path: Path):
    """The app draws the round from the folder, so the folder has to say how
    many images are coming BEFORE the first one exists — otherwise a round of
    eight looks finished at one image."""
    loop = _loop_module()
    from PIL import Image

    seen: list[dict] = []

    class _Engine:
        def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                             on_image=None, check=None):
            out = []
            for i, _ in enumerate(prompts):
                img = Image.new("RGB", (8, 8), (i * 20, 0, 0))
                out.append(img)
                on_image(i, img)
                # What the app would see at this moment.
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                seen.append({"expected": meta.get("expected"),
                             "done": len(list(d.glob("p*.png")))})
            return out

    d = tmp_path / "step-000010"

    class _IO:
        def check_control(self):
            pass

        def sample_dir(self, step):
            d.mkdir(parents=True, exist_ok=True)
            return d

    loop._generate_samples(_IO(), _Engine(), {
        "prompts": [{"prompt": p, "negative": ""} for p in ("a", "b", "c")],
    }, 10)
    # Every image was on disk the moment it was rendered, and the round always
    # knew it was rendering three.
    assert seen == [{"expected": 3, "done": 1}, {"expected": 3, "done": 2},
                    {"expected": 3, "done": 3}]
    assert sorted(f.name for f in d.glob("p*.png")) == [
        "p00.png", "p01.png", "p02.png"]
    assert not list(d.glob("*.tmp"))     # written atomically, nothing left over


def test_an_engine_that_does_not_stream_still_gets_its_images_written(
        tmp_path: Path):
    loop = _loop_module()
    from PIL import Image

    class _Engine:
        def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                             on_image=None, check=None):
            return [Image.new("RGB", (8, 8)) for _ in prompts]

    d = tmp_path / "step-000000"

    class _IO:
        def check_control(self):
            pass

        def sample_dir(self, step):
            d.mkdir(parents=True, exist_ok=True)
            return d

    loop._generate_samples(_IO(), _Engine(), {
        "prompts": [{"prompt": "a", "negative": ""}], }, 0)
    assert (d / "p00.png").is_file()


def test_make_buckets_area_and_aspect():
    buckets = compose.make_buckets(1024, 64, 2.0)
    assert (1024, 1024) in buckets
    for w, h in buckets:
        assert w % 64 == 0 and h % 64 == 0
        assert w * h <= 1024 * 1024
        assert 0.5 - 1e-9 <= w / h <= 2.0 + 1e-9
    # Wide, square and tall shapes must all be represented.
    aspects = [w / h for w, h in buckets]
    assert min(aspects) < 0.7 and max(aspects) > 1.4


def test_assign_bucket_nearest_aspect():
    buckets = compose.make_buckets(1024, 64, 2.0)
    square = buckets[compose.assign_bucket(1000, 1000, buckets)]
    assert square == (1024, 1024)
    wide = buckets[compose.assign_bucket(1920, 1080, buckets)]
    assert wide[0] > wide[1]
    tall = buckets[compose.assign_bucket(1080, 1920, buckets)]
    assert tall[0] < tall[1]


def test_sampler_weights_and_determinism():
    items = [{"bucket": 0} for _ in range(4)]
    groups = [{"weight": 3.0, "items": [0, 1]}, {"weight": 1.0, "items": [2, 3]}]
    s = compose.Sampler(items, groups, random.Random(7))
    counts = [0] * 4
    for _ in range(10_000):
        _, picked = s.batch(1)
        counts[picked[0]] += 1
    pool_a, pool_b = counts[0] + counts[1], counts[2] + counts[3]
    assert 2.6 < pool_a / pool_b < 3.5  # ~3:1 by weight

    a = compose.Sampler(items, groups, random.Random(11))
    b = compose.Sampler(items, groups, random.Random(11))
    assert [a.batch(2) for _ in range(50)] == [b.batch(2) for _ in range(50)]


def test_sampler_respects_buckets():
    items = [{"bucket": 0}, {"bucket": 1}, {"bucket": 1}]
    groups = [{"weight": 1.0, "items": [0, 1, 2]}]
    s = compose.Sampler(items, groups, random.Random(3))
    for _ in range(200):
        bucket, picked = s.batch(2)
        for idx in picked:
            assert items[idx]["bucket"] == bucket


def test_pick_tags_rules():
    rng = random.Random(5)
    tags = ["one", "two", "common", "watermark", "banned"]
    cfg = {
        "exclude_tags": ["banned"], "always_tags": ["watermark", "absent"],
        "min_tags": 1, "max_tags": 2, "shuffle": True, "balance": "none",
    }
    for _ in range(200):
        out = compose.pick_tags(tags, cfg, {}, rng)
        assert "banned" not in out
        # The item HAS "watermark", so it always survives the random pick…
        assert "watermark" in out
        # …but an always-tag the item does NOT have is never invented.
        assert "absent" not in out
        # watermark (guaranteed, exempt from limits) + 1..2 picked
        assert 2 <= len(out) <= 3


def test_pick_tags_always_only_when_present():
    rng = random.Random(6)
    cfg = {"always_tags": ["watermark"], "shuffle": False}
    assert compose.pick_tags(["a", "b"], cfg, {}, rng) == ["a", "b"]
    # Unshuffled output keeps the item's original tag order.
    assert compose.pick_tags(["b", "watermark", "a"], cfg, {}, rng) == \
        ["b", "watermark", "a"]
    # An excluded tag loses even against always_tags.
    cfg2 = {"always_tags": ["watermark"], "exclude_tags": ["watermark"],
            "shuffle": False}
    assert compose.pick_tags(["watermark", "a"], cfg2, {}, rng) == ["a"]


def test_pick_tags_inverse_freq_balances():
    rng = random.Random(9)
    tags = ["common", "rare"]
    freq = {"common": 100, "rare": 1}
    cfg = {"min_tags": 1, "max_tags": 1, "balance": "inverse_freq",
           "shuffle": False}
    picks = {"common": 0, "rare": 0}
    for _ in range(4000):
        out = compose.pick_tags(tags, cfg, freq, rng)
        picks[out[0]] += 1
    # p(rare) ∝ 1/1 vs p(common) ∝ 1/100 -> rare dominates overwhelmingly.
    assert picks["rare"] > picks["common"] * 20


def test_partial_match():
    assert compose.partial_match("shirt", "white_shirt")
    assert compose.partial_match("white shirt", "shirt")  # symmetric
    assert compose.partial_match("red fox", "big red fox tail")
    assert not compose.partial_match("shirt", "shirt")     # equal ≠ partial
    assert not compose.partial_match("shirt", "t-shirt")   # whole words only
    assert not compose.partial_match("red fox", "red hat")


def test_pick_tags_skips_partial_matches():
    rng = random.Random(7)
    tags = ["shirt", "white_shirt", "hat", "shoes", "pants"]
    cfg = {"min_tags": 3, "max_tags": 3, "shuffle": False}
    for _ in range(300):
        out = compose.pick_tags(tags, cfg, {}, rng)
        # Never the generic tag next to its specific variant…
        assert not ("shirt" in out and "white_shirt" in out)
        # …and the freed slot is refilled from the remaining pool.
        assert len(out) == 3


def test_pick_tags_partial_respects_always_and_opt_out():
    rng = random.Random(8)
    tags = ["shirt", "white_shirt", "hat"]
    # A guaranteed specific tag suppresses its generic partial entirely.
    cfg = {"always_tags": ["white_shirt"], "shuffle": False}
    for _ in range(100):
        assert compose.pick_tags(tags, cfg, {}, rng) == ["white_shirt", "hat"]
    # Opting out restores the old keep-everything behavior.
    cfg2 = {"skip_partial_tags": False, "shuffle": False}
    assert compose.pick_tags(tags, cfg2, {}, rng) == tags


def test_compose_caption_formatting():
    rng = random.Random(1)
    item = {"tags": ["red_fox", "snow"], "captions": []}
    # Defaults: underscores become spaces, comma+space separator.
    assert compose.compose_caption(
        item, {"source": "tags", "shuffle": False}, {}, rng
    ) == "red fox, snow"
    # Both formatting knobs off/custom; matching still used the raw names.
    assert compose.compose_caption(
        item, {"source": "tags", "shuffle": False,
               "underscores_to_spaces": False, "separator": " | "}, {}, rng
    ) == "red_fox | snow"


def test_compose_caption_sources_and_dropout():
    rng = random.Random(1)
    item = {"tags": ["dog"], "captions": ["a good dog"]}
    base = {"source": "both", "trigger": "trg", "shuffle": False,
            "dropout": 0.0}
    cap = compose.compose_caption(item, base, {}, rng)
    assert cap.startswith("trg, a good dog") and cap.endswith("dog")
    assert compose.compose_caption(item, {**base, "dropout": 1.0}, {}, rng) == ""


def test_loss_weight_clamped():
    freq = {"common": 1000, "rare": 1}
    items = [{"tags": ["common"]}, {"tags": ["rare"]}]
    mean = compose.dataset_mean_inverse_freq(items, freq)  # ≈ 0.5
    assert 1.9 < compose.loss_weight(["rare"], freq, mean) < 2.1
    assert compose.loss_weight(["common"], freq, mean) == 0.25  # clamped low
    assert compose.loss_weight(["rare"], freq, 0.01) == 4.0     # clamped high


def test_crop_offset_center_and_quantum():
    rng = random.Random(2)
    assert compose.crop_offset(120, 100, 100, 100, False, rng) == (10, 0)
    for _ in range(50):
        x, y = compose.crop_offset(130, 117, 100, 100, True, rng, quantum=8)
        assert x % 8 == 0 and y % 8 == 0
        assert 0 <= x <= 30 and 0 <= y <= 17


def _overlap(off: int, crop: int, b0: float, b1: float) -> float:
    return max(0.0, min(off + crop, b1) - max(float(off), b0))


def test_crop_offset_for_boxes_keeps_box_inside():
    rng = random.Random(5)
    # A 200x200 image, 100x100 crop, box on the right half — every random
    # crop must cover at least 90% of the box.
    box = [0.6, 0.3, 0.3, 0.3]  # px: x 120..180, y 60..120
    # Integer offsets floor, so allow one pixel of slack on the 90% bound.
    for _ in range(100):
        x, y = compose.crop_offset_for_boxes(
            200, 200, 100, 100, [box], True, rng
        )
        assert _overlap(x, 100, 120, 180) >= 0.9 * 60 - 1
        assert _overlap(y, 100, 60, 120) >= 0.9 * 60 - 1
    # Center-crop mode also respects the box (plain center x=50 would cut it).
    x, y = compose.crop_offset_for_boxes(200, 200, 100, 100, [box], False, rng)
    assert _overlap(x, 100, 120, 180) >= 0.9 * 60 - 1
    # No boxes -> plain crop_offset behavior.
    assert compose.crop_offset_for_boxes(120, 100, 100, 100, [], False, rng) \
        == (10, 0)


def test_crop_offset_for_boxes_conflicting_boxes_compromise():
    rng = random.Random(9)
    # Boxes at opposite edges can't both fit a 100px crop of a 300px image;
    # the offset must split the difference (roughly centered between them).
    boxes = [[0.0, 0.0, 0.1, 1.0], [0.9, 0.0, 0.1, 1.0]]
    x, _ = compose.crop_offset_for_boxes(300, 100, 100, 100, boxes, True, rng)
    assert 50 <= x <= 150  # never pinned to either edge


def test_flip_boxes_mirrors_x():
    (flipped,) = compose.flip_boxes([[0.1, 0.2, 0.3, 0.4]])
    assert flipped == pytest.approx([0.6, 0.2, 0.3, 0.4])


def test_compose_caption_and_tags_reports_used_tags():
    rng = random.Random(4)
    item = {"tags": ["red_fox", "tree"], "captions": []}
    text, used = compose.compose_caption_and_tags(
        item, {"source": "tags", "shuffle": False}, {}, rng
    )
    assert used == ["red_fox", "tree"]
    assert text == "red fox, tree"  # formatting applied to text only
    _, dropped = compose.compose_caption_and_tags(
        item, {"source": "tags", "dropout": 1.0}, {}, rng
    )
    assert dropped == []


def test_value_rules_rewrite_the_prompt_and_never_the_tag_list():
    """A matched value tag is WRITTEN as its rule's text; `keep` rides the
    raw tag alongside; an unmatched one passes through unchanged — and the
    returned tag list stays raw throughout, because boxes and `tag_freq` are
    keyed on the name (the alias substitution's rule)."""
    rng = random.Random(4)
    item = {"tags": ["height:172cm", "people:3", "tree"], "captions": []}
    vmap = {"height:172cm": {"text": "tall", "keep": False}}
    text, used = compose.compose_caption_and_tags(
        item, {"source": "tags", "shuffle": False, "value_map": vmap}, {}, rng)
    assert text == "tall, people:3, tree"
    assert used == ["height:172cm", "people:3", "tree"]
    # `keep` embeds the separator, like a group block does.
    vmap = {"height:172cm": {"text": "tall", "keep": True}}
    text, _ = compose.compose_caption_and_tags(
        item, {"source": "tags", "shuffle": False, "value_map": vmap}, {}, rng)
    assert text == "tall, height:172cm, people:3, tree"


def test_an_instruction_and_its_references_are_picked_together():
    """An item may carry several instructions and one is drawn per visit, so
    the text and the pictures it refers to must come out of the same object —
    a prompt describing one edit with another's inputs is a lie the loss has
    no way to notice."""
    pairs = {"make it snow": 1, "make it night": 2}
    item = {"tags": ["red_fox"], "captions": ["a red fox"], "instructions": [
        {"text": t, "refs": [{"path": f"/x/{n}.png", "item_id": n}]}
        for t, n in pairs.items()
    ]}
    cfg = {"source": "instructions"}
    seen = set()
    for seed in range(40):
        text, refs = compose.compose_instruction(item, cfg,
                                                 random.Random(seed))
        assert [r["item_id"] for r in refs] == [pairs[text]]
        seen.add(text)
    assert seen == set(pairs)          # both really do come up


def test_an_instruction_prompt_is_the_trigger_and_the_instruction():
    """Tags are NOT appended: an edit model's prompt is an imperative
    sentence, and a tag list after it teaches the model that the list is part
    of what was asked for."""
    item = {"tags": ["red_fox", "tree"], "captions": ["a red fox"],
            "instructions": [{"text": "make it snow", "refs": []}]}
    text, used, refs = compose.compose_visit(
        item, {"source": "instructions", "trigger": "ohwx"}, {},
        random.Random(1))
    assert text == "ohwx, make it snow"
    assert used == [] and refs == []
    # And the other direction: a caption run never reaches the instructions.
    text, used, refs = compose.compose_visit(
        item, {"source": "captions"}, {}, random.Random(1))
    assert text == "a red fox" and refs == []


def test_instruction_dropout_keeps_the_reference_images():
    """What guidance compares against is the unprompted path. With the
    references gone too, the sample degenerates into teaching the model to
    invent the target from nothing."""
    item = {"instructions": [
        {"text": "make it snow", "refs": [{"path": "/x/1.png", "item_id": 1}]}]}
    text, refs = compose.compose_instruction(
        item, {"source": "instructions", "dropout": 1.0}, random.Random(3))
    assert text == ""
    assert [r["item_id"] for r in refs] == [1]


# ---- manifest builder ----------------------------------------------------------

def _public(lib):
    """A PUBLIC handle on the same library the fixture built.

    The fixtures here seed their data straight through the ORM, deliberately:
    they are testing the manifest, not the API. But `build_manifest` takes a
    public `Library` now — reading the library through nothing but the
    published surface is exactly what lets the whole training subsystem live
    in a package of its own — so the call goes through this.
    """
    from media_compost import open_library

    return open_library(lib.config.data_dir, source="cli")


def _manifest(lib, config, *args, pin_upscale=True, **kw):
    """Build a manifest, with `skip_upscale` PINNED OFF unless asked otherwise.

    The setting defaults to ON, and this fixture library's pictures are a few
    hundred pixels wide — so at sd15's native resolution every one of them is
    below its bucket and every manifest here would raise "all N matched images
    are smaller than the training resolution". That is the setting working
    exactly as designed, and it has nothing to do with what these tests are
    about; pinning it keeps each of them measuring the one thing it names.

    `pin_upscale=False` is for the tests that ARE about it, which set it
    themselves and must be left alone.
    """
    if pin_upscale:
        if hasattr(config, "model_dump"):
            config = config.model_dump(mode="json")
        else:
            config = {**config, "buckets": {**config.get("buckets", {})}}
        config["buckets"]["skip_upscale"] = False
    with _public(lib) as pub:
        return build_manifest(pub, config, *args, **kw)


def _register(lib, job_dir):
    with _public(lib) as pub:
        return register_latents(pub, job_dir)




@pytest.fixture
def seeded_lib(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([images], ImportOptions())
        items = s.query(Item).all()
        dog = Tag(name="dog")
        cat = Tag(name="cat")
        s.add_all([dog, cat])
        s.flush()
        it_dog = ItemTag(item_id=items[0].id, tag_id=dog.id)
        s.add(it_dog)
        s.flush()
        # The dog tag carries a spatial bounding box (reference frame).
        pl = ItemTagPlacement(item_tag_id=it_dog.id, group_id=None)
        s.add(pl)
        s.flush()
        s.add(ItemTagBox(placement_id=pl.id, x=0.25, y=0.25, w=0.5, h=0.5))
        for it in items:
            s.add(ItemTag(item_id=it.id, tag_id=cat.id))
        s.commit()
    return lib


def test__manifest(seeded_lib, tmp_path: Path):
    jd = tmp_path / "job"
    jd.mkdir()
    config = TrainingConfig(
        model="sd15",
        queries=[
            DatasetQuery(tree=Group(op="and", children=[TagCond(name="dog")]),
                         weight=2.0),
            DatasetQuery(tree=None, weight=1.0),
        ],
    )
    m = _manifest(seeded_lib, config.model_dump(mode="json"), jd)
    assert (jd / "manifest.json").is_file()
    assert m["model"]["engine"] == "sd" and m["resolution"] == 512
    assert len(m["items"]) == 2  # a (+alt merged) and b
    for entry in m["items"]:
        assert Path(entry["path"]).is_file()
        assert "cat" in entry["tags"]
        assert 0 <= entry["bucket"] < len(m["buckets"])
    # Group 0 = dog-only (1 item), group 1 = everything.
    assert [len(g["items"]) for g in m["groups"]] == [1, 2]
    assert m["groups"][0]["weight"] == 2.0
    assert m["tag_freq"]["cat"] == 2 and m["tag_freq"]["dog"] == 1
    # The dog tag's bounding box rides along on its item (file frame fractions).
    dogged = [e for e in m["items"] if "dog" in e["tags"]]
    assert len(dogged) == 1
    assert dogged[0]["boxes"]["dog"] == [[0.25, 0.25, 0.5, 0.5]]
    assert all("boxes" not in e for e in m["items"] if "dog" not in e["tags"])


def test_manifest_latent_paths_are_file_artifacts(seeded_lib, tmp_path: Path):
    """Latent caches are addressed per FILE (not per job) and keyed by model
    and bucket, so two jobs share them but a different model/size never does."""
    cfg = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                         buckets=BucketConfig(skip_upscale=False))
    m1 = _manifest(seeded_lib, cfg.model_dump(mode="json"), tmp_path / "j1")
    m2 = _manifest(seeded_lib, cfg.model_dump(mode="json"), tmp_path / "j2")
    # Same library, same model -> byte-identical cache locations (reuse).
    assert [e["latent_path"] for e in m1["items"]] == \
        [e["latent_path"] for e in m2["items"]]
    for e in m1["items"]:
        rel = e["latent_rel"]
        assert rel.startswith("artifacts/") and rel.endswith(".pt")
        # …-<file number>-latent-<model>-<w>x<h>.pt
        assert "-latent-sd15-" in rel
        assert e["latent_rel_flipped"] == rel[:-3] + "-f.pt"
        # The path really is inside the item's own folder. Compared as PATHS,
        # not as strings: `latent_rel` is stored forward-slashed (it is a DB
        # `File.path`), while `latent_path` is an OS path — so on Windows the
        # absolute one ends "artifacts\\…" and a plain endswith never matches.
        assert Path(e["latent_path"]).as_posix().endswith(rel)
        assert e["file_id"] and e["item_id"]

    # A different base model gets different names — no cross-model confusion.
    other = TrainingConfig(model="sdxl", queries=[DatasetQuery(tree=None)])
    m3 = _manifest(seeded_lib, other.model_dump(mode="json"), tmp_path / "j3")
    assert {e["latent_rel"] for e in m3["items"]}.isdisjoint(
        {e["latent_rel"] for e in m1["items"]})


def test_register_latents_indexes_written_caches(seeded_lib, tmp_path: Path):
    from media_compost.db import FileArtifact
    from media_compost.train.dataset import register_latents
    from sqlalchemy import select as sa_select

    jd = tmp_path / "j"
    m = _manifest(seeded_lib, TrainingConfig(
        model="sd15", queries=[DatasetQuery(tree=None)]
    ).model_dump(mode="json"), jd)
    # Nothing on disk yet -> nothing registered.
    assert _register(seeded_lib, jd) == 0

    # Simulate the trainer writing one cache entry.
    first = m["items"][0]
    path = Path(first["latent_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-latent-bytes")

    assert _register(seeded_lib, jd) == 1
    with seeded_lib.db.session() as s:
        rows = s.execute(sa_select(FileArtifact).where(
            FileArtifact.kind == "latent")).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.file_id == first["file_id"] and row.item_id == first["item_id"]
        assert row.path == first["latent_rel"] and row.format == "pt"
        assert row.model == "sd15" and row.bytes == len(b"fake-latent-bytes")
        # Bucket size is recovered from the name.
        assert (row.width, row.height) == tuple(m["buckets"][first["bucket"]])
    # Idempotent: a second pass adds nothing.
    assert _register(seeded_lib, jd) == 0


# ---- the trainer's half of degradation -----------------------------------------


def _entry(**kw) -> dict:
    e = {"tags": ["red", "blue", "green"], "captions": [], "bucket": 0}
    e.update(kw)
    return e


def test_forced_tags_are_always_in_the_prompt():
    """They are the only thing saying this sample is the bad version, so no
    random rule may drop them: not the cap, not the exclude list, not dropout."""
    rng = random.Random(0)
    cfg = {"source": "tags", "max_tags": 1, "min_tags": 1,
           "exclude_tags": ["jpeg_artifacts"], "dropout": 1.0,
           "underscores_to_spaces": False}
    for _ in range(30):
        text, used = compose.compose_caption_and_tags(
            _entry(force_tags=["jpeg_artifacts", "low_quality"]),
            cfg, {}, rng)
        assert "jpeg_artifacts" in text and "low_quality" in text
        # …and never in the tag list: that drives box-aware cropping and
        # inverse-frequency weighting, where a synthetic name has no box and
        # no frequency and would read as maximally rare.
        assert "jpeg_artifacts" not in used and "low_quality" not in used
        assert len(used) == 1        # the cap still applies to the real tags


def test_dropout_still_empties_a_clean_prompt():
    rng = random.Random(0)
    text, used = compose.compose_caption_and_tags(
        _entry(), {"source": "tags", "dropout": 1.0}, {}, rng)
    assert (text, used) == ("", [])


def test_forced_tags_come_last():
    rng = random.Random(1)
    text, _ = compose.compose_caption_and_tags(
        _entry(force_tags=["low_quality"]),
        {"source": "tags", "trigger": "mystyle", "underscores_to_spaces": False},
        {}, rng)
    assert text.startswith("mystyle")
    assert text.split(", ")[-1] == "low_quality"


def test_a_degraded_entry_is_drawn_at_exactly_the_ratio_configured():
    """The pool is split by the SUM of its entries' weights, not by how many
    there are — so a 0.25 copy is drawn once per four visits to its original,
    and does not halve it the way a per-count split would."""
    items = [_entry(), _entry(weight=0.25)]
    s = compose.Sampler(items, [{"weight": 1.0, "items": [0, 1]}],
                        random.Random(0))
    assert s.item_weights[1] == pytest.approx(s.item_weights[0] * 0.25)
    assert sum(s.item_weights) == pytest.approx(1.0)   # the pool's own weight
    drawn = [i for _ in range(4000) for i in s.batch(1)[1]]
    assert 0.15 < drawn.count(1) / len(drawn) < 0.25


def test_every_clean_entry_keeps_the_weight_every_other_clean_entry_has():
    """The one guarantee weighting can actually make: degraded copies take
    their share from the pool and never displace one picture for another —
    including when a tag gate degrades some items and not others."""
    items = [_entry(), _entry(weight=0.25), _entry()]   # item B is un-gated
    s = compose.Sampler(items, [{"weight": 1.0, "items": [0, 1, 2]}],
                        random.Random(0))
    assert s.item_weights[0] == pytest.approx(s.item_weights[2])


def test_a_manifest_without_weights_samples_exactly_as_it_always_did():
    items = [_entry(), _entry(), _entry()]
    groups = [{"weight": 1.0, "items": [0, 1, 2]}]
    s = compose.Sampler(items, groups, random.Random(0))
    assert s.item_weights == [1 / 3, 1 / 3, 1 / 3]


# ---- degradation variants ------------------------------------------------------


def _variant(**kw):
    from media_compost.train.spec import DegradeVariant, IntRange

    kw.setdefault("tags", ["jpeg_artifacts"])
    kw.setdefault("quality", IntRange(lo=20, hi=20))
    return DegradeVariant(**kw)


def _degrade_cfg(*variants):
    from media_compost.train.spec import DegradeConfig

    return TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                          degrade=DegradeConfig(variants=list(variants)))


def test_degraded_entries_are_extra_and_never_replace_the_clean_one(
        seeded_lib, tmp_path: Path):
    """The whole premise: a degraded picture is an ADDITIONAL sample. The clean
    entry keeps its full pool weight, so a run can never train on fewer good
    pictures than were selected."""
    plain = _manifest(seeded_lib, TrainingConfig(
        model="sd15", queries=[DatasetQuery(tree=None)]
    ).model_dump(mode="json"), tmp_path / "plain")
    m = _manifest(seeded_lib, _degrade_cfg(
        _variant(weight=0.25)).model_dump(mode="json"), tmp_path / "j")

    clean = [e for e in m["items"] if not e.get("degrade")]
    dirty = [e for e in m["items"] if e.get("degrade")]
    assert len(clean) == len(plain["items"]) and len(dirty) == len(clean)
    # The clean entries are untouched, weight included (absent = 1.0).
    assert [e["path"] for e in clean] == [e["path"] for e in plain["items"]]
    assert all("weight" not in e for e in clean)
    assert all(e["weight"] == 0.25 for e in dirty)
    # Both ends of a pool: every entry an item produced is in it, so the
    # degraded copies are drawn alongside their originals.
    assert sum(len(g["items"]) for g in m["groups"]) == len(m["items"])
    # The degraded picture is a real file, the same size, with its own latents.
    size_of = {e["item_id"]: (e["width"], e["height"]) for e in clean}
    for e in dirty:
        assert Path(e["path"]).is_file()
        assert (e["width"], e["height"]) == size_of[e["item_id"]]
        assert e["degrade"] == "jpeg-q20-s420"
        assert e["force_tags"] == ["jpeg_artifacts"]
        assert f"-d{e['degrade']}-" in e["latent_rel"]
    # A degraded copy is the same picture: counting it again would inflate
    # every tag it carries.
    assert m["tag_freq"]["cat"] == plain["tag_freq"]["cat"]


def test_degraded_copies_are_cached_artifacts_and_reused(seeded_lib, tmp_path: Path):
    from media_compost.db import FileArtifact
    from sqlalchemy import select as sa_select

    cfg = _degrade_cfg(_variant()).model_dump(mode="json")
    m1 = _manifest(seeded_lib, cfg, tmp_path / "j1")
    with seeded_lib.db.session() as s:
        rows = s.execute(sa_select(FileArtifact).where(
            FileArtifact.kind == "degraded")).scalars().all()
        assert len(rows) == 2 and {r.model for r in rows} == {"jpeg-q20-s420"}
        assert all(r.format == "jpg" and r.bytes > 0 for r in rows)
        stamps = {r.path: Path(m1["items"][0]["path"]).stat().st_mtime
                  for r in rows}
    # A second job over the same library re-uses them: same paths, no new rows.
    m2 = _manifest(seeded_lib, cfg, tmp_path / "j2")
    assert [e.get("degrade_rel") for e in m1["items"]] == \
        [e.get("degrade_rel") for e in m2["items"]]
    with seeded_lib.db.session() as s:
        again = s.execute(sa_select(FileArtifact).where(
            FileArtifact.kind == "degraded")).scalars().all()
        assert len(again) == 2 and stamps  # nothing re-written


def test_a_widened_range_redraws_but_a_renamed_variant_does_not(
        seeded_lib, tmp_path: Path):
    """The cache key is the DRAWN values. Tags, name and weight are not
    properties of the pixels, so editing them must keep the cache."""
    from media_compost.train.spec import IntRange

    base = _variant(name="mild", weight=0.25)
    keys = lambda m: {e["degrade"] for e in m["items"] if e.get("degrade")}
    first = keys(_manifest(seeded_lib, _degrade_cfg(base).model_dump(
        mode="json"), tmp_path / "a"))
    same = keys(_manifest(seeded_lib, _degrade_cfg(_variant(
        name="renamed", weight=0.9, tags=["low_quality"])).model_dump(
            mode="json"), tmp_path / "b"))
    assert same == first
    moved = keys(_manifest(seeded_lib, _degrade_cfg(_variant(
        quality=IntRange(lo=5, hi=90))).model_dump(mode="json"), tmp_path / "c"))
    assert moved.isdisjoint(first)


def test_variations_split_the_weight_rather_than_multiplying_it(
        seeded_lib, tmp_path: Path):
    """`weight` is the share of the run this variant gets; `variations` is how
    many strengths that share is spread over. Entangling them would mean
    raising the variety silently retunes the mix — and would make the editor's
    stated ratio, which sums the weights, a lie."""
    m = _manifest(seeded_lib, _degrade_cfg(
        _variant(weight=0.4, variations=4)).model_dump(mode="json"),
        tmp_path / "j")
    dirty = [e for e in m["items"] if e.get("degrade")]
    assert all(e["weight"] == pytest.approx(0.1) for e in dirty)
    # Per item: one clean at 1.0 against four draws summing to 0.4.
    per_item: dict[int, float] = {}
    for e in dirty:
        per_item[e["item_id"]] = per_item.get(e["item_id"], 0.0) + e["weight"]
    assert all(v == pytest.approx(0.4) for v in per_item.values())


def test_variations_give_one_picture_several_draws(seeded_lib, tmp_path: Path):
    from media_compost.train.spec import IntRange

    m = _manifest(seeded_lib, _degrade_cfg(_variant(
        variations=3, quality=IntRange(lo=5, hi=90))
    ).model_dump(mode="json"), tmp_path / "j")
    per_item: dict[int, set] = {}
    for e in m["items"]:
        if e.get("degrade"):
            per_item.setdefault(e["item_id"], set()).add(e["degrade"])
    assert all(len(v) == 3 for v in per_item.values())
    # Drawn per FILE, so the dataset spans the range instead of every picture
    # landing on one shared ladder.
    assert len(set().union(*per_item.values())) > 3


def test_tag_gates_decide_before_anything_is_generated(seeded_lib, tmp_path: Path):
    """A skipped picture costs no encode, no artifact and no cache entry."""
    from media_compost.db import FileArtifact
    from sqlalchemy import select as sa_select

    m = _manifest(seeded_lib, _degrade_cfg(
        _variant(require_tags=["dog"])).model_dump(mode="json"), tmp_path / "j")
    dirty = [e for e in m["items"] if e.get("degrade")]
    assert len(dirty) == 1 and "dog" in dirty[0]["tags"]
    with seeded_lib.db.session() as s:
        assert len(s.execute(sa_select(FileArtifact).where(
            FileArtifact.kind == "degraded")).scalars().all()) == 1

    # `skip` wins over `require` when both match.
    m2 = _manifest(seeded_lib, _degrade_cfg(_variant(
        require_tags=["cat"], skip_tags=["dog"])).model_dump(mode="json"),
        tmp_path / "j2")
    left = [e for e in m2["items"] if e.get("degrade")]
    assert len(left) == 1 and "dog" not in left[0]["tags"]
    # An empty `require` admits everything.
    m3 = _manifest(seeded_lib, _degrade_cfg(_variant()).model_dump(
        mode="json"), tmp_path / "j3")
    assert len([e for e in m3["items"] if e.get("degrade")]) == 2


def test_a_gate_that_matched_nothing_says_so_in_the_log(seeded_lib, tmp_path: Path):
    jd = tmp_path / "j"
    jd.mkdir()
    _manifest(seeded_lib, _degrade_cfg(
        _variant(name="heavy", require_tags=["nobody_has_this"])
    ).model_dump(mode="json"), jd)
    log = (jd / "log.txt").read_text("utf-8")
    assert "heavy" in log and "no pictures matched" in log


def test_removing_a_tag_takes_the_ancestors_only_it_implied(
        seeded_lib, tmp_path: Path):
    """Removing `masterpiece` while `high_quality` stays removes nothing —
    the same trap the tag-group exclusion documents."""
    from media_compost.db import Tag, TagImplication, ItemTag
    from sqlalchemy import select as sa_select

    with seeded_lib.db.session() as s:
        hq = Tag(name="high_quality")
        mp = Tag(name="masterpiece")
        s.add_all([hq, mp])
        s.flush()
        s.add(TagImplication(tag_id=mp.id, implies_id=hq.id))
        items = s.execute(sa_select(Item)).scalars().all()
        s.add(ItemTag(item_id=items[0].id, tag_id=mp.id))
        # The second item is tagged high_quality in its OWN right.
        s.add(ItemTag(item_id=items[1].id, tag_id=hq.id))
        s.commit()
        implied_item, direct_item = items[0].id, items[1].id

    m = _manifest(seeded_lib, _degrade_cfg(_variant(
        remove_tags=["masterpiece"])).model_dump(mode="json"), tmp_path / "j")
    by_item = {(e["item_id"], bool(e.get("degrade"))): e for e in m["items"]}
    # The implied ancestor goes with it…
    assert "high_quality" in by_item[(implied_item, False)]["tags"]
    assert "masterpiece" not in by_item[(implied_item, True)]["tags"]
    assert "high_quality" not in by_item[(implied_item, True)]["tags"]
    # …but one assigned in its own right stays.
    assert "high_quality" in by_item[(direct_item, True)]["tags"]


def test_degraded_latents_nest_under_their_degraded_image(
        seeded_lib, tmp_path: Path):
    from media_compost.db import FileArtifact
    from media_compost.train.dataset import register_latents
    from sqlalchemy import select as sa_select

    jd = tmp_path / "j"
    m = _manifest(seeded_lib, _degrade_cfg(_variant()).model_dump(
        mode="json"), jd)
    for e in m["items"]:                     # the trainer's job, faked
        p = Path(e["latent_path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake-latent")
    assert _register(seeded_lib, jd) == len(m["items"])
    with seeded_lib.db.session() as s:
        lats = s.execute(sa_select(FileArtifact).where(
            FileArtifact.kind == "latent")).scalars().all()
        parents = {a.id: a for a in s.execute(sa_select(FileArtifact).where(
            FileArtifact.kind == "degraded")).scalars().all()}
        nested = [a for a in lats if a.parent_id]
        assert len(nested) == 2 and all(a.parent_id in parents for a in nested)
        assert all(parents[a.parent_id].model == "jpeg-q20-s420" for a in nested)
        # A clean latent hangs off the file directly, as it always did.
        assert len([a for a in lats if not a.parent_id]) == 2
        # The bucket still parses off the tail despite the -d marker.
        assert all(a.width and a.height for a in lats)
        # Deleting the degraded image takes its latents with it (the DB's
        # cascade, so re-read rather than asking the identity map).
        doomed = [a.id for a in nested if a.parent_id == nested[0].parent_id]
        s.delete(parents[nested[0].parent_id])
        s.commit()
        s.expire_all()
        left = s.execute(sa_select(FileArtifact.id)).scalars().all()
        assert not set(doomed) & set(left)


def test_the_preview_renders_both_ends_of_a_range(seeded_lib):
    """What a person needs before committing a run is the gentlest and the
    harshest thing it can produce — so the ends are addressable, and a lower
    JPEG quality is the HARSHER one while a higher CRF is."""
    from media_compost.train.spec import IntRange
    from sqlalchemy import select as sa_select

    app.dependency_overrides[get_library] = lambda: seeded_lib
    client = TestClient(app)
    try:
        with seeded_lib.db.session() as s:
            iid = s.execute(sa_select(Item.id)).scalars().first()
        v = _variant(quality=IntRange(lo=10, hi=90)).model_dump(mode="json")
        got = {}
        for end in ("low", "high"):
            r = client.post("/api/train/degrade/preview",
                            json={"item_id": iid, "variant": v, "end": end})
            assert r.status_code == 200
            assert r.headers["content-type"] == "image/png"
            got[end] = (r.headers["x-degrade-key"], len(r.content))
        assert got["low"][0] == "jpeg-q90-s420"
        assert got["high"][0] == "jpeg-q10-s420"
        # The harsh end really is the smaller picture.
        assert got["high"][1] < got["low"][1]

        # A CRF range counts the other way round.
        vv = _variant(method="video", crf=IntRange(lo=20, hi=50)).model_dump(
            mode="json")
        r = client.post("/api/train/degrade/preview",
                        json={"item_id": iid, "variant": vv, "end": "high"})
        assert r.status_code in (200, 409)   # 409 = this ffmpeg has no encoder
        if r.status_code == 200:
            assert r.headers["x-degrade-key"] == "h264-crf50"
        assert client.post("/api/train/degrade/preview",
                           json={"item_id": 999999, "variant": v}
                           ).status_code == 404
    finally:
        app.dependency_overrides.pop(get_library, None)


def test_an_instruction_run_refuses_degradation(seeded_lib, tmp_path: Path):
    from media_compost.train.spec import CaptionConfig, DegradeConfig

    with pytest.raises(ValueError, match="references"):
        TrainingConfig(model="flux2_klein", method="lora",
                       captions=CaptionConfig(source="instructions"),
                       degrade=DegradeConfig(variants=[_variant()]))


def test_a_quantized_text_encoder_CAN_be_trained_but_an_offloaded_one_cannot():
    """A quantized encoder is a frozen encoder with an adapter over it — the
    same QLoRA the backbone has always been, and what makes T5-XXL trainable
    on a 32 GB card. It used to be refused here. An OFFLOADED one stays
    refused: an encoder on the CPU cannot be the one gradients flow through.
    Both pairs are decidable from the config alone, so the answer is at save
    rather than at load."""
    from media_compost.train.spec import Hyperparams

    cfg = TrainingConfig(model="sdxl", method="lora",
                         hyper=Hyperparams(quantization="int8",
                                           quantize_text_encoder=True,
                                           train_text_encoder=True))
    assert cfg.hyper.train_text_encoder and cfg.hyper.quantize_text_encoder
    with pytest.raises(ValueError, match="kept on the CPU cannot be trained"):
        TrainingConfig(model="sdxl", method="lora",
                       hyper=Hyperparams(offload_text_encoder=True,
                                         train_text_encoder=True))
    # …and quantizing needs a scheme to apply, or the toggle claims a saving
    # the run would not make.
    with pytest.raises(ValueError, match="needs a quantization scheme"):
        TrainingConfig(model="sdxl", method="lora",
                       hyper=Hyperparams(quantize_text_encoder=True))
    # The combination that is the whole point of the setting is accepted.
    TrainingConfig(model="sdxl", method="lora",
                   hyper=Hyperparams(quantization="int8",
                                     quantize_text_encoder=True))


def _caption(s, item_id: int, text: str, *meta: str) -> None:
    """One caption with meta tags, the way the caption endpoints write it."""
    from media_compost.db import Caption, CaptionTag

    c = Caption(item_id=item_id, text=text, position=0)
    s.add(c)
    s.flush()
    for name in meta:
        s.add(CaptionTag(caption_id=c.id, name=name))


def test_captions_are_filtered_by_meta_tag(seeded_lib, tmp_path: Path):
    """An item usually has several captions and a run wants one kind of them.
    The filter runs where the dataset is materialized, so the manifest — the
    only thing the trainer ever sees — already holds just the survivors."""
    from media_compost.db import Item

    with seeded_lib.db.session() as s:
        item = s.query(Item).all()[0].id
        _caption(s, item, "a long descriptive paragraph", "long")
        _caption(s, item, "a red car", "short", "German")
        _caption(s, item, "note to self")
        s.commit()

    def captions(**caps) -> list[str]:
        cfg = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                             captions=CaptionConfig(source="both", **caps))
        m = _manifest(seeded_lib, cfg.model_dump(mode="json"),
                           tmp_path / f"j{len(caps)}{hash(str(caps)) & 0xffff}")
        return [e for e in m["items"] if e["item_id"] == item][0]["captions"]

    # No rule: every caption, as before.
    assert len(captions()) == 3
    # Include narrows to the named kind — and matches case-insensitively,
    # because these names are typed into a form, not picked from autocomplete.
    assert captions(include_meta_tags=["LONG"]) == ["a long descriptive paragraph"]
    # Exclude drops a kind and leaves the untagged ones alone.
    assert captions(exclude_meta_tags=["german"]) == [
        "a long descriptive paragraph", "note to self"]
    # Exclude wins over include, on the very caption include let in.
    assert captions(include_meta_tags=["short"],
                    exclude_meta_tags=["German"]) == []


def test_tag_groups_can_be_excluded_by_meta_tag(seeded_lib, tmp_path: Path):
    """A tag group marked with a meta tag is ignored by the run: its tags stay
    on the item and out of the prompts. The two rules that make it honest are
    what this pins down — a tag placed elsewhere as well survives, and an
    ancestor only implied by dropped tags goes with them."""
    from media_compost.db import (
        Item, ItemTag, ItemTagGroup, ItemTagGroupTag, ItemTagPlacement, Tag,
        TagImplication,
    )

    with seeded_lib.db.session() as s:
        item = s.query(Item).all()[0].id
        # poodle -> dog -> animal, so the implication chain is exercised.
        animal = Tag(name="animal")
        dog = Tag(name="dog2")
        poodle = Tag(name="poodle")
        note = Tag(name="to_redraw")
        both = Tag(name="in_two_places")
        s.add_all([animal, dog, poodle, note, both])
        s.flush()
        s.add(TagImplication(tag_id=dog.id, implies_id=animal.id))
        s.add(TagImplication(tag_id=poodle.id, implies_id=dog.id))
        s.flush()

        notes = ItemTagGroup(item_id=item, name="Notes", position=1)
        keep = ItemTagGroup(item_id=item, name="Subject", position=2)
        s.add_all([notes, keep])
        s.flush()
        s.add(ItemTagGroupTag(group_id=notes.id, name="not for training"))

        def place(tag, *groups):
            it = ItemTag(item_id=item, tag_id=tag.id)
            s.add(it)
            s.flush()
            for g in groups:
                s.add(ItemTagPlacement(item_tag_id=it.id, group_id=g))

        place(poodle, notes.id)          # only in the excluded group
        place(note, notes.id)            # only in the excluded group
        place(both, notes.id, keep.id)   # also somewhere the user kept
        s.commit()

    def tags(*meta) -> set[str]:
        cfg = TrainingConfig(
            model="sd15", queries=[DatasetQuery(tree=None)],
            captions=CaptionConfig(exclude_tag_group_meta_tags=list(meta)),
        )
        m = _manifest(seeded_lib, cfg.model_dump(mode="json"),
                           tmp_path / f"g{len(meta)}")
        return set([e for e in m["items"] if e["item_id"] == item][0]["tags"])

    before = tags()
    assert {"poodle", "to_redraw", "in_two_places", "dog2", "animal"} <= before

    after = tags("Not For Training")   # case-insensitive, like the caption filter
    # Placed only in the excluded group -> gone.
    assert "poodle" not in after and "to_redraw" not in after
    # Ancestors that nothing else implies go with it.
    assert "dog2" not in after and "animal" not in after
    # Placed in a kept group as well -> still there.
    assert "in_two_places" in after
    # Everything else the item has is untouched.
    assert "cat" in after
    # And the tags are still ON the item — only the prompts ignore them.
    with seeded_lib.db.session() as s:
        names = {t.name for t in s.query(Tag).all()}
        assert {"poodle", "to_redraw"} <= names


def test_a_dataset_query_can_select_by_subject(seeded_lib, tmp_path: Path):
    """`subject:` used to select NOTHING here. The manifest built its QueryCtx
    without `subjects=`/`places=`, so the field defaulted empty and the whole
    run trained on an empty dataset — the same query working in the search
    field the entire time."""
    from media_compost.db import Subject
    from media_compost.query import SubjectCond

    with seeded_lib.db.session() as s:
        dog = s.query(Tag).filter(Tag.name == "dog").one()
        s.add(Subject(tag_id=dog.id, display_name="Rex"))
        s.commit()

    m = _manifest(seeded_lib, TrainingConfig(model="sd15", queries=[
        DatasetQuery(tree=Group(op="and",
                                children=[SubjectCond(name="dog")]))
    ]).model_dump(mode="json"), tmp_path / "jsub")
    assert len(m["items"]) == 1
    assert "dog" in m["items"][0]["tags"]


def test_never_upscale_drops_the_pictures_that_would_be_enlarged(
        seeded_lib, tmp_path: Path):
    """`skip_upscale` is decided while the dataset is BUILT.

    Before anything is encoded, so a dropped picture costs no time and no
    cache — and dropping every one of them is an error with its own sentence
    rather than the generic "nothing to train against", which would send
    somebody looking at their tags for a problem that is about resolution.
    """
    from media_compost.train.spec import BucketConfig

    # Explicitly OFF: this is the baseline the other two are measured against,
    # and `skip_upscale` is on by default now.
    base = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                          buckets=BucketConfig(skip_upscale=False))
    every = _manifest(seeded_lib, base.model_dump(mode="json"),
                      tmp_path / "j-all", pin_upscale=False)
    assert every["items"], "the fixture library should train on something"

    # The fixture's pictures are small, so at the model's native resolution
    # every one of them would have to be enlarged.
    picky = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                           buckets=BucketConfig(skip_upscale=True))
    with pytest.raises(ValueError, match="never to upscale"):
        _manifest(seeded_lib, picky.model_dump(mode="json"), tmp_path / "j-none",
                  pin_upscale=False)

    # …and at a resolution they clear, the same setting keeps them all.
    small = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                           buckets=BucketConfig(resolutions=[64],
                                                bucket_step=8,
                                                skip_upscale=True))
    kept = _manifest(seeded_lib, small.model_dump(mode="json"),
                     tmp_path / "j-small", pin_upscale=False)
    assert len(kept["items"]) == len(every["items"])


def test_build_manifest_no_matches(seeded_lib, tmp_path: Path):
    config = TrainingConfig(model="sd15", queries=[
        DatasetQuery(tree=Group(op="and",
                                children=[TagCond(name="nonexistent")]))
    ])
    with pytest.raises(ValueError):
        _manifest(seeded_lib, config.model_dump(mode="json"),
                       tmp_path / "job2")


# ---- manager lifecycle on the simulator ------------------------------------------


def _wait(mgr: TrainingManager, uid: str, statuses, timeout=30.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        rec = mgr.get(uid)
        if rec["status"] in statuses:
            return rec
        time.sleep(0.1)
    raise AssertionError(
        f"timeout waiting for {statuses}; last: {mgr.get(uid)}")


# The product ships no simulation: pytest points the manager at the
# test-only fake trainer in tests/fake_trainer (same job-dir protocol,
# stdlib+Pillow, runs in the main venv).
FAKE_TRAINER = Path(__file__).resolve().parent / "fake_trainer"


def _use_fake_trainer(monkeypatch):
    import sys as _sys

    monkeypatch.setattr(manager_mod, "_TICK_SECONDS", 0.2)
    monkeypatch.setattr(manager_mod, "TRAIN_SCRIPTS", FAKE_TRAINER)
    from media_compost.train import evaluate as evaluate_mod

    monkeypatch.setattr(evaluate_mod, "TRAIN_SCRIPTS", FAKE_TRAINER)
    # Both managers ask `paths.interpreter()` for the training venv, and each
    # imported it by name — so the patch has to land on all three bindings,
    # not just the module that defines it.
    from media_compost.train import paths as _paths

    for mod in (_paths, manager_mod, evaluate_mod):
        monkeypatch.setattr(mod, "interpreter", lambda: _sys.executable,
                            raising=False)


@pytest.fixture
def sim_mgr(tmp_path: Path, images: Path, monkeypatch):
    _use_fake_trainer(monkeypatch)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    # The manifest builder requires matching items now that the empty-library
    # simulate fallback is gone — and a TAG on each of them, because a run
    # builds its prompts from tags by default and an item with none is left
    # out of that mode entirely. These tests are about the manager's
    # lifecycle; the dataset just has to be non-empty.
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([images], ImportOptions())
    with lib.db.session() as s:
        for item in s.query(_Item).all():
            tagassign.stamp(Ctx(s, source="cli"), [item.id], ["photo"], [])
        s.commit()
    return lib.training


def _cfg(steps=40, **hyper) -> TrainingConfig:
    return TrainingConfig(
        model="sd15",
        hyper={"steps": steps, "checkpoint_every": 0, **hyper},
        queries=[DatasetQuery(weight=1.0)],
        # These are LIFECYCLE tests and the dataset just has to be non-empty
        # (see `_lib` above). `skip_upscale` is on by default and the fixture's
        # pictures are tiny, so leaving it would fail every job at the manifest
        # with "all N matched images are smaller than the training resolution"
        # — a real refusal, and nothing to do with pausing and resuming.
        buckets=BucketConfig(skip_upscale=False),
    )


def test_manager_full_run(sim_mgr):
    uid = sim_mgr.create("run", _cfg(steps=30), "tester")
    assert sim_mgr.get(uid)["status"] == "draft"
    sim_mgr.enqueue(uid)
    assert sim_mgr.get(uid)["status"] == "queued"  # queueing starts nothing
    sim_mgr.queue_run()
    rec = _wait(sim_mgr, uid, ("completed", "failed"))
    assert rec["status"] == "completed", rec["message"]
    assert rec["step"] == 30
    jd = tp.job_dir(sim_mgr.dir, uid)
    assert (jd / "output" / "model.safetensors").is_file()
    assert (jd / "metrics.jsonl").is_file()


def test_a_finished_run_has_a_checkpoint_and_samples_at_its_last_step(
        sim_mgr):
    """A cadence is arithmetic and the end of a run is not a multiple of
    anything: 25 steps every 10 leaves the final state — the one anybody
    actually wants — as the only one with no entry of its own."""
    from media_compost.train.spec import SampleConfig, SamplePrompt

    cfg = _cfg(steps=25, checkpoint_every=10)
    cfg.sampling = SampleConfig(every_n_steps=10,
                                prompts=[SamplePrompt(prompt="a fox")])
    uid = sim_mgr.create("ends well", cfg, "tester")
    sim_mgr.enqueue(uid)
    sim_mgr.queue_run()
    rec = _wait(sim_mgr, uid, ("completed", "failed"))
    assert rec["status"] == "completed", rec["message"]

    jd = tp.job_dir(sim_mgr.dir, uid)
    steps = sorted(int(p.name.split("-")[1])
                   for p in (jd / "checkpoints").iterdir()
                   if p.is_dir() and p.name.startswith("step-"))
    assert steps[-1] == 25, f"no checkpoint at the last step: {steps}"
    rounds = sorted(int(p.name.split("-")[1])
                    for p in (jd / "samples").iterdir() if p.is_dir())
    assert rounds[-1] == 25, f"no sample round at the last step: {rounds}"
    assert list((jd / "samples" / "step-000025").glob("p*.png"))


def test_manager_pause_resume_cancel(sim_mgr):
    uid = sim_mgr.create("pr", _cfg(steps=400), "tester")
    sim_mgr.enqueue(uid)
    sim_mgr.queue_run()
    # Wait until it is actually training, then pause.
    end = time.time() + 30
    while time.time() < end and sim_mgr.get(uid).get("step", 0) < 30:
        time.sleep(0.1)
    sim_mgr.pause(uid)
    # A hand-paused job lands back in the QUEUE, at the front (pausing is
    # "not now"); the queue itself is switched off, so nothing restarts.
    rec = _wait(sim_mgr, uid, ("queued",))
    paused_step = rec["step"]
    assert (tp.checkpoints_dir(tp.job_dir(sim_mgr.dir, uid)) / "last").is_dir()

    # A started job now TAKES edits (they apply to the next run) and the
    # change lands in the timeline.
    sim_mgr.update(uid, "renamed", None)
    assert sim_mgr.get(uid)["name"] == "renamed"
    kinds = [json.loads(ln)["kind"] for ln in
             tp.events_path(tp.job_dir(sim_mgr.dir, uid)).read_text(encoding="utf-8").splitlines()]
    assert "edited" in kinds

    sim_mgr.queue_run()       # pausing by hand stopped the queue
    end = time.time() + 30
    while time.time() < end:
        rec = sim_mgr.get(uid)
        if rec["status"] == "running" and rec["step"] > paused_step + 10:
            break
        time.sleep(0.1)

    # Both runs appended to the same log, so each one announces itself — a
    # reader has to be able to tell where the second attempt begins.
    log = tp.log_path(tp.job_dir(sim_mgr.dir, uid)).read_text(encoding="utf-8")
    assert "training started" in log and "training resumed" in log
    assert log.index("training started") < log.index("training resumed")

    sim_mgr.cancel(uid)
    rec = _wait(sim_mgr, uid, ("canceled",))
    assert rec["status"] == "canceled"


def test_queue_reorder_changes_which_job_runs_next(sim_mgr):
    a = sim_mgr.create("a", _cfg(steps=800), "t")
    b = sim_mgr.create("b", _cfg(steps=30), "t")
    c = sim_mgr.create("c", _cfg(steps=30), "t")
    # a starts (oldest); b and c wait in line.
    for u in (a, b, c):
        sim_mgr.enqueue(u)
    sim_mgr.queue_run()
    _wait(sim_mgr, a, ("running",))
    # Move c ahead of b, then let a finish its wait by cancelling it.
    sim_mgr.reorder_queue([c, b])
    assert (sim_mgr.get(c)["queued_at"] < sim_mgr.get(b)["queued_at"])
    sim_mgr.cancel(a)
    _wait(sim_mgr, c, ("running", "completed"))
    # b never started while c was in front of it.
    assert sim_mgr.get(b)["status"] == "queued"
    sim_mgr.cancel(c)
    sim_mgr.cancel(b)


def test_reorder_covers_paused_and_draft_jobs_and_start_keeps_the_slot(sim_mgr):
    """The app's Queued section lists queued, paused and draft jobs as ONE
    list, and a queued job just waits for the queue to be told to run —
    so those are the rows there are to drag. Starting a positioned job must
    keep its slot rather than jumping to the back."""
    blocker = sim_mgr.create("blocker", _cfg(steps=800), "t")
    sim_mgr.enqueue(blocker)
    sim_mgr.queue_run()
    _wait(sim_mgr, blocker, ("running",))

    a = sim_mgr.create("a", _cfg(steps=30), "t")     # draft
    b = sim_mgr.create("b", _cfg(steps=30), "t")     # draft
    sim_mgr.enqueue(b)                                # queued behind blocker
    # Put draft a ahead of queued b — impossible when only "queued" reorders.
    sim_mgr.reorder_queue([a, b])
    assert sim_mgr.get(a)["queued_at"] < sim_mgr.get(b)["queued_at"]

    # Starting a keeps the slot it was dragged to.
    sim_mgr.enqueue(a)
    assert sim_mgr.get(a)["queued_at"] < sim_mgr.get(b)["queued_at"]

    # And de-queueing does not lose the position either — and returns the job
    # to what it was (no checkpoint here, so draft; with one it goes back to
    # paused, since the checkpoint is what makes the job worth keeping).
    sim_mgr.pause(b)                                  # queued -> draft
    assert sim_mgr.get(b)["status"] == "draft"
    assert sim_mgr.get(b)["queued_at"] is not None

    sim_mgr.cancel(blocker)
    _wait(sim_mgr, a, ("running", "completed"))       # a runs first
    sim_mgr.cancel(a)
    sim_mgr.cancel(b)


def test_manager_delete_and_conflicts(sim_mgr):
    uid = sim_mgr.create("del", _cfg(steps=800), "tester")
    with pytest.raises(TrainingConflict):
        sim_mgr.pause(uid)  # draft can't pause
    sim_mgr.enqueue(uid)
    sim_mgr.queue_run()
    _wait(sim_mgr, uid, ("running",))
    with pytest.raises(TrainingConflict):
        sim_mgr.delete(uid)
    sim_mgr.cancel(uid)
    _wait(sim_mgr, uid, ("canceled",))
    sim_mgr.delete(uid)
    assert not tp.job_dir(sim_mgr.dir, uid).exists()


def test_manager_checkpoint_pruning(sim_mgr):
    uid = sim_mgr.create("ckpt", _cfg(steps=60, checkpoint_every=10,
                                      checkpoint_keep=2), "tester")
    sim_mgr.enqueue(uid)
    sim_mgr.queue_run()
    rec = _wait(sim_mgr, uid, ("completed",))
    assert rec["step"] == 60
    cdir = tp.checkpoints_dir(tp.job_dir(sim_mgr.dir, uid))
    snaps = [d.name for d in cdir.iterdir() if d.name.startswith("step-")]
    assert len(snaps) <= 2
    assert (cdir / "last").is_dir()


def test_manager_recovery(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(manager_mod, "_TICK_SECONDS", 0.2)
    cfg = UiConfig(data_dir=tmp_path / "data")
    cfg.ensure_dirs()

    def plant(uid: str, status: str, with_ckpt: bool):
        jd = tp.job_dir(training_dir(cfg.data_dir), uid)
        jd.mkdir(parents=True)
        tp.write_json(tp.config_path(jd),
                      _cfg(steps=10).model_dump(mode="json"))
        tp.write_json(tp.job_path(jd), {
            "uid": uid, "name": uid, "username": "", "status": status,
            "step": 5, "total_steps": 10, "message": "", "phase": "training",
            "created_at": time.time(),
        })
        if with_ckpt:
            (tp.checkpoints_dir(jd) / "last").mkdir(parents=True)

    plant("deadnockpt00000", "running", with_ckpt=False)
    plant("deadwithckpt000", "running", with_ckpt=True)

    lib = Library(cfg)
    mgr = lib.training
    # Interrupted, not finished: both wait in the queue. The one without a
    # checkpoint simply has nothing to resume from and starts over.
    dead = mgr.get("deadnockpt00000")
    assert dead["status"] == "paused"
    assert "interrupted" in dead["message"]
    rec = mgr.get("deadwithckpt000")
    assert rec["status"] == "paused" and rec["phase"] == ""


def test_recovery_normalizes_records_written_before_the_paused_rule(
        tmp_path: Path, monkeypatch):
    """Old job.json files say "failed"; there is no migration mechanism, so
    the manager rewrites them on the way past instead of stranding them in
    the finished list."""
    monkeypatch.setattr(manager_mod, "_TICK_SECONDS", 0.2)
    cfg = UiConfig(data_dir=tmp_path / "data")
    cfg.ensure_dirs()
    jd = tp.job_dir(training_dir(cfg.data_dir), "oldfailure00000")
    jd.mkdir(parents=True)
    tp.write_json(tp.config_path(jd), _cfg(steps=10).model_dump(mode="json"))
    tp.write_json(tp.job_path(jd), {
        "uid": "oldfailure00000", "name": "old", "username": "",
        "status": "failed", "step": 3, "total_steps": 10,
        "message": "RuntimeError: boom", "phase": "",
        "created_at": time.time(), "finished_at": time.time(),
    })

    rec = Library(cfg).training.get("oldfailure00000")
    assert rec["status"] == "paused"
    assert rec["message"] == "RuntimeError: boom"


# ---- API contract -----------------------------------------------------------------


@pytest.fixture
def train_client(tmp_path: Path, images: Path, monkeypatch):
    _use_fake_trainer(monkeypatch)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([images], ImportOptions())
    # Tagged for the same reason `sim_mgr`'s are: prompts come from tags by
    # default, and an item with none is not in that mode.
    with lib.db.session() as s:
        for item in s.query(_Item).all():
            tagassign.stamp(Ctx(s, source="cli"), [item.id], ["photo"], [])
        s.commit()
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _api_cfg(steps=30) -> dict:
    return {
        "model": "sd15", "method": "lora",
        "hyper": {"steps": steps, "checkpoint_every": 0},
        "queries": [{"search": "", "tree": None, "weight": 1.0}],
        "sampling": {"every_n_steps": 15,
                     "prompts": [{"prompt": "a fox"}]},
        # See `_cfg`: on by default, and this fixture's pictures are tiny, so
        # every run would fail at the manifest. These tests are about the API.
        "buckets": {"skip_upscale": False},
    }


def test_starting_a_download_does_no_network_under_the_lock(train_client,
                                                            monkeypatch):
    """The base-model download endpoint must not touch the hub.

    It used to resolve the repo's file list — two hub round-trips — while
    holding `_dl_lock`, which `_download_state` takes for EVERY model row on
    EVERY `/api/train/status` poll. Three downloads started together plus a
    polling Models page therefore queued every request behind a network call,
    and because these endpoints are sync each blocked request holds a
    threadpool thread: the whole server stopped answering. The resolution
    belongs to the download's own subprocess (`resolve_patterns`).

    Asserted as "never called", not "fast": a timing test on a network call
    is exactly the flake this rule exists to avoid.
    """
    from media_compost.hub import pipeline_files
    from media_compost.train.web import routes as train_router

    called: list[str] = []
    monkeypatch.setattr(pipeline_files, "download_patterns",
                        lambda repo, token="": called.append(repo) or ())

    started: list[dict] = []

    class _FakeDownload:
        def __init__(self, repo, token, allow_patterns=(),
                     resolve_patterns=False):
            started.append({"repo": repo, "resolve": resolve_patterns,
                            "patterns": allow_patterns})

        def start(self):
            pass

        def status(self):
            return 0            # RUNNING

    monkeypatch.setattr(train_router, "ModelDownload", _FakeDownload)

    try:
        r = train_client.post("/api/train/models/sd15/download")
        assert r.status_code == 200, r.text
        assert called == [], (
            "the request thread resolved download patterns over the network; "
            "that belongs in the download subprocess")
        assert started and started[0]["resolve"] is True, started
    finally:
        # `_downloads` is a module global and outlives the monkeypatch, so the
        # fake left in it would answer `_download_state` for every later test
        # that reads /api/train/status.
        train_router._downloads.pop("sd15", None)


def test_api_lifecycle(train_client):
    c = train_client
    st = c.get("/api/train/status").json()
    assert st["env_ready"]  # the fixture's fake interpreter resolves
    # The whole registry, in registry order — a new model belongs here, so the
    # list is spelled out rather than probed. The order is also what groups
    # the app's Models page: entries sharing an engine sit together, and the
    # first of each group is the release that architecture is named after.
    assert [m["key"] for m in st["models"]] == [
        "sd15", "sdxl", "chroma", "chroma_base", "flux1_dev", "flux1_kontext",
        "flux2_klein", "flux2_klein_9b", "zimage", "zimage_turbo",
        "qwen_image", "qwen_image_2512",
        "qwen_image_edit", "qwen_image_edit_2509", "qwen_image_edit_2511"]

    r = c.post("/api/train/jobs", json={"name": "job1",
                                        "config": _api_cfg()})
    assert r.status_code == 200
    uid = r.json()["uid"]
    assert r.json()["status"] == "draft"

    # Queue-readiness: a config without queries is rejected at queue time.
    r2 = c.post("/api/train/jobs",
                json={"name": "empty", "config":
                      {**_api_cfg(), "queries": []}})
    assert c.post(f"/api/train/jobs/{r2.json()['uid']}/queue").status_code == 409

    assert c.post(f"/api/train/jobs/{uid}/queue").status_code == 200
    assert c.post("/api/train/queue/run").status_code == 200
    end = time.time() + 40
    while time.time() < end:
        j = c.get(f"/api/train/jobs/{uid}").json()
        if j["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert j["status"] == "completed", j["message"]

    # A finished job takes edits (they apply to the next run) — and can be
    # duplicated into a fresh one either way.
    assert c.put(f"/api/train/jobs/{uid}",
                 json={"name": "x", "config": _api_cfg()}).status_code == 200
    kinds = [e["kind"] for e in
             c.get(f"/api/train/jobs/{uid}/events").json()["events"]]
    assert "edited" in kinds
    dup = c.post(f"/api/train/jobs/{uid}/duplicate").json()
    assert dup["status"] == "draft" and dup["name"].endswith("(copy)")

    m = c.get(f"/api/train/jobs/{uid}/metrics").json()
    assert m["last_step"] == 30 and len(m["points"]) == 30
    inc = c.get(f"/api/train/jobs/{uid}/metrics?after=25").json()
    assert all(p["step"] > 25 for p in inc["points"])

    # The training-data inspector: every step recorded its visits, and a step
    # can be fetched by number.
    v = c.get(f"/api/train/jobs/{uid}/visits").json()
    assert v["step"] == 30 and v["steps"] == list(range(1, 31))
    assert len(v["visits"]) >= 1
    assert "prompt" in v["visits"][0]
    v15 = c.get(f"/api/train/jobs/{uid}/visits?step=15").json()
    assert v15["step"] == 15

    samples = c.get(f"/api/train/jobs/{uid}/samples").json()["samples"]
    assert [s["step"] for s in samples] == [15, 30]
    assert samples[0]["prompt"] == "a fox"
    img = c.get(f"/api/train/jobs/{uid}/samples/15/p00.png")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"

    # Path traversal in the sample name is rejected.
    assert c.get(
        f"/api/train/jobs/{uid}/samples/15/notasample.png"
    ).status_code == 404
    evil = c.get(f"/api/train/jobs/{uid}/samples/15/%2E%2E%2Fjob.json")
    assert evil.headers.get("content-type") != "application/json" or \
        evil.status_code == 404

    # `kept` is how many LOCKED weight sets survived the deletion — none
    # here, since nothing was locked.
    assert c.delete(f"/api/train/jobs/{uid}").json() == {"ok": True, "kept": 0}
    assert c.get(f"/api/train/jobs/{uid}").status_code == 404
    assert c.get("/api/train/jobs/nope").status_code == 404


def test_set_steps_live_and_after_completion(sim_mgr):
    uid = sim_mgr.create("extend", _cfg(steps=600), "tester")
    with pytest.raises(TrainingConflict):
        sim_mgr.set_steps(uid, 0)  # bounds-checked via TrainingConfig
    sim_mgr.enqueue(uid)
    sim_mgr.queue_run()
    end = time.time() + 30
    while time.time() < end and sim_mgr.get(uid).get("step", 0) < 20:
        time.sleep(0.1)
    # Live shrink: the running trainer adopts the new, nearer target.
    sim_mgr.set_steps(uid, 60)
    rec = _wait(sim_mgr, uid, ("completed",))
    assert rec["total_steps"] == 60 and rec["step"] == 60

    # Extending a finished job flips it to paused; resume continues the run.
    with pytest.raises(TrainingConflict):
        sim_mgr.set_steps(uid, 50)  # must exceed the reached step
    sim_mgr.set_steps(uid, 90)
    rec = sim_mgr.get(uid)
    assert rec["status"] == "paused" and rec["total_steps"] == 90
    sim_mgr.enqueue(uid)
    sim_mgr.queue_run()  # the drained queue switched itself off
    rec = _wait(sim_mgr, uid, ("completed",))
    assert rec["step"] == 90


def test_api_checkpoints(train_client):
    c = train_client
    cfg = _api_cfg(steps=40)
    cfg["hyper"]["checkpoint_every"] = 10
    cfg["hyper"]["checkpoint_keep"] = 1
    uid = c.post("/api/train/jobs",
                 json={"name": "ckpts", "config": cfg}).json()["uid"]
    c.post(f"/api/train/jobs/{uid}/queue")
    c.post("/api/train/queue/run")
    end = time.time() + 40
    while time.time() < end:
        if c.get(f"/api/train/jobs/{uid}").json()["status"] in (
                "completed", "failed"):
            break
        time.sleep(0.2)

    cks = c.get(f"/api/train/jobs/{uid}/checkpoints").json()["checkpoints"]
    # Cadence snapshots at 10/20/30, then the finish writes the LAST STEP's
    # (40, which the cadence itself skips), and keep-last-1 leaves that one.
    # The pruned steps are still listed — the timeline marks where a
    # checkpoint was saved — and step 40 is also the RESUME POINT, so its row
    # says BOTH: `snapshot` is what makes it a real checkpoint to the app,
    # `resume` is what stops it being offered as one to keep.
    assert [k["step"] for k in cks] == [10, 20, 30, 40]
    assert [k["step"] for k in cks if k["resume"]] == [40]
    existing = [k for k in cks if k["exists"]]
    assert [k["step"] for k in existing] == [40]
    assert existing[0]["snapshot"] and existing[0]["size"] > 0
    assert all(k["size"] == 0 for k in cks if not k["exists"])

    dl = c.get(f"/api/train/jobs/{uid}/checkpoints/40/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/zip"
    assert len(dl.content) > 0
    assert c.get(f"/api/train/jobs/{uid}/checkpoints/10/download") \
        .status_code == 404

    # Deleting the last step takes the SNAPSHOT; the resume point underneath
    # it stays, and is then undeletable — it is what continuing the job reads.
    assert c.delete(f"/api/train/jobs/{uid}/checkpoints/40").json() == {"ok": True}
    cks = c.get(f"/api/train/jobs/{uid}/checkpoints").json()["checkpoints"]
    assert not any(k["snapshot"] for k in cks)
    resume = [k for k in cks if k["resume"]]
    assert len(resume) == 1 and resume[0]["exists"]
    assert c.delete(
        f"/api/train/jobs/{uid}/checkpoints/{resume[0]['step']}"
    ).status_code == 409


def test_api_evaluation(train_client):
    c = train_client
    assert c.get("/api/train/eval/loras").json() == {"loras": []}
    r = c.post("/api/train/eval/runs", json={
        "model": "sd15", "prompt": "a fox", "count": 2,
    })
    assert r.status_code == 200
    run = r.json()
    uid = run["uid"]
    assert run["status"] == "running"
    assert run["width"] == 512 and run["height"] == 512  # auto = native
    assert run["seed"] >= 0  # auto seed drawn and recorded

    end = time.time() + 30
    while time.time() < end:
        run = c.get(f"/api/train/eval/runs/{uid}").json()
        if run["status"] != "running":
            break
        time.sleep(0.3)
    assert run["status"] == "completed", run
    assert run["images"] == ["p00.png", "p01.png"]
    img = c.get(f"/api/train/eval/runs/{uid}/images/p00.png")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    # ONE image out of the run — the grid's selection is per picture — and
    # the rest of the generation stays.
    assert c.delete(f"/api/train/eval/runs/{uid}/images/p00.png").json() == {"ok": True}
    assert c.get(f"/api/train/eval/runs/{uid}").json()["images"] == ["p01.png"]
    assert c.get(f"/api/train/eval/runs/{uid}/images/p00.png").status_code == 404
    assert c.delete(f"/api/train/eval/runs/{uid}/images/nope.txt").status_code == 404

    # An EMPTY prompt is accepted: the unconditional image is a legitimate
    # thing to generate (it is how you see what a LoRA does on its own).
    empty = c.post("/api/train/eval/runs", json={"model": "sd15", "prompt": " "})
    assert empty.status_code == 200, empty.text
    c.post(f"/api/train/eval/runs/{empty.json()['uid']}/cancel")
    c.delete(f"/api/train/eval/runs/{empty.json()['uid']}")

    assert c.delete(f"/api/train/eval/runs/{uid}").json() == {"ok": True}
    assert c.get(f"/api/train/eval/runs/{uid}").status_code == 404


def test_api_evaluation_queues_instead_of_refusing(train_client):
    """One generation runs at a time, but asking for another queues it — and a
    request that hasn't started can be dropped without touching the running one."""
    c = train_client
    body = {"model": "sd15", "prompt": "a", "steps": 1, "count": 1}
    first = c.post("/api/train/eval/runs", json=body).json()["uid"]
    second = c.post("/api/train/eval/runs", json=body).json()["uid"]
    third = c.post("/api/train/eval/runs", json=body).json()["uid"]

    by_uid = {r["uid"]: r for r in c.get("/api/train/eval/runs").json()["runs"]}
    # Whatever the first one is doing, the later two are waiting rather than
    # refused — and a queued run is never mistaken for a dead process.
    assert by_uid[second]["status"] in ("queued", "running", "completed")
    assert "failed" not in (by_uid[second]["status"], by_uid[third]["status"])

    # Dropping a pending request needs no signal — it never started.
    c.post(f"/api/train/eval/runs/{third}/cancel")
    assert c.get(f"/api/train/eval/runs/{third}").json()["status"] == "canceled"

    for u in (first, second, third):
        c.post(f"/api/train/eval/runs/{u}/cancel")
        c.delete(f"/api/train/eval/runs/{u}")


def test_api_events_timing_and_baseline_samples(train_client):
    c = train_client
    cfg = _api_cfg(steps=60)
    cfg["sampling"]["every_n_steps"] = 30
    cfg["sampling"]["at_start"] = True
    uid = c.post("/api/train/jobs",
                 json={"name": "tl", "config": cfg}).json()["uid"]
    c.post(f"/api/train/jobs/{uid}/queue")
    c.post("/api/train/queue/run")

    # Pause once mid-run so the event log gets a pause/resume pair.
    end = time.time() + 30
    while time.time() < end:
        j = c.get(f"/api/train/jobs/{uid}").json()
        if j["status"] == "running" and j["step"] >= 10:
            break
        time.sleep(0.2)
    c.post(f"/api/train/jobs/{uid}/pause")
    end = time.time() + 30
    while time.time() < end and c.get(f"/api/train/jobs/{uid}").json()[
            "status"] not in ("queued", "paused"):
        time.sleep(0.2)
    # A pause parks the job at the front of the queue; running it again is
    # the Start button (the queue was switched off by the pause).
    c.post(f"/api/train/jobs/{uid}/start")
    end = time.time() + 40
    while time.time() < end:
        j = c.get(f"/api/train/jobs/{uid}").json()
        if j["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert j["status"] == "completed", j

    kinds = [e["kind"] for e in
             c.get(f"/api/train/jobs/{uid}/events").json()["events"]]
    assert kinds == ["started", "paused", "resumed", "completed"]

    samples = c.get(f"/api/train/jobs/{uid}/samples").json()["samples"]
    steps = sorted({s["step"] for s in samples})
    assert steps == [0, 30, 60]  # at_start baseline + cadence rounds
    late = [s for s in samples if s["step"] == 60][0]
    assert late["t"] > 0 and late["train_seconds"] > 0
    # Net training time excludes the pause: the sim runs ~20 steps/s, so 60
    # steps stay well under a minute even though the wall span includes waits.
    assert late["train_seconds"] < 60


def test_concurrent_writers_never_tear_a_record(tmp_path: Path):
    """The manager writes job.json from its tick thread and from request
    threads. With a per-process temp name, two threads truncated and wrote the
    same temp file through separate descriptors — a shorter record over a
    longer one kept the old tail (`}}`), the file stopped being JSON, and the
    job vanished from every list (readers treat unparseable as missing)."""
    import threading

    target = tmp_path / "job.json"
    # Two shapes of clearly different lengths, so an interleave would show.
    long_rec = {"uid": "x" * 40, "status": "running", "note": "y" * 200}
    short_rec = {"uid": "x"}
    stop = time.time() + 2.0
    torn: list[str] = []

    def writer(rec):
        while time.time() < stop:
            try:
                tp.write_json(target, rec)
            except PermissionError:
                # Windows: two concurrent MoveFileEx calls onto ONE
                # destination collide, and this loop writes thousands per
                # second per thread, so the bounded retry in write_json can
                # still be exhausted. It does not weaken what is asserted
                # below: a replace that fails leaves the PREVIOUS file
                # completely intact, so the record is still whole — which is
                # the property this test exists for.
                pass

    def reader():
        while time.time() < stop:
            raw = None
            try:
                # Through the same opener the real readers use. On Windows a
                # plain open withholds FILE_SHARE_DELETE, which does not just
                # make THIS read fail — it makes the concurrent os.replace
                # fail, so the test would be measuring a reader it does not
                # have rather than the tearing it is about.
                with tp._open_text(target) as f:
                    raw = f.read()
                json.loads(raw)
            except FileNotFoundError:
                pass
            except PermissionError:
                pass    # landed exactly in a replace window; try again
            except ValueError:
                torn.append(raw or "?")
                return

    threads = [threading.Thread(target=writer, args=(long_rec,)),
               threading.Thread(target=writer, args=(short_rec,)),
               threading.Thread(target=reader)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not torn, f"reader saw a torn record: {torn[0][:120]!r}"
    # And the final file parses to one of the two records.
    assert json.loads(target.read_text(encoding="utf-8"))["uid"].startswith("x")


def test_the_phase_carries_a_progress_note(tmp_path: Path):
    """The minutes before step 1 — loading the model, encoding every image —
    used to report a bare phase name. The note is what the app can show for
    them, and it has to survive the whole trainer -> state.json -> API path."""
    mod = _train_module()

    io = mod.JobIO(tmp_path)
    io.write_state("caching_latents", note="62 / 162")
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "caching_latents"
    assert state["note"] == "62 / 162"
    # And a phase with nothing to add still writes a well-formed state.
    io.write_state("training", step=3)
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["note"] == ""




def test_a_diverged_step_is_recorded_as_null_and_reported_as_diverged(
        train_client, tmp_path):
    """`json.dumps(float("nan"))` writes a bare NaN — not JSON — which reached
    the browser as `null` and took the loss graph (and the whole page) down."""
    mod = _train_module()

    c = train_client
    uid = c.post("/api/train/jobs",
                 json={"name": "nan", "config": _api_cfg(steps=5)}).json()["uid"]
    jd = tp.job_dir(training_dir(tmp_path / "data"), uid)
    io = mod.JobIO(jd)
    io.append_metric(1, 0.5, 1e-4)
    io.append_metric(2, float("nan"), 1e-4)
    io.append_metric(3, float("inf"), 1e-4)
    text = tp.metrics_path(jd).read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    for line in text.splitlines():
        json.loads(line)              # every line is valid JSON

    body = c.get(f"/api/train/jobs/{uid}/metrics").json()
    assert [p["step"] for p in body["points"]] == [1]
    assert body["diverged"] == 2


def test_a_validation_round_merges_onto_its_steps_point(train_client, tmp_path):
    """`append_eval` writes a record with NO "loss" key; the endpoint merges
    it into the step's training point rather than counting it as a diverged
    step — which is what a bare record would otherwise read as."""
    mod = _train_module()

    c = train_client
    uid = c.post("/api/train/jobs",
                 json={"name": "val", "config": _api_cfg(steps=5)}).json()["uid"]
    jd = tp.job_dir(training_dir(tmp_path / "data"), uid)
    io = mod.JobIO(jd)
    io.append_metric(1, 0.5, 1e-4)
    io.append_metric(2, 0.4, 1e-4)
    io.append_eval(2, {"val": 0.7, "stable": 0.35})
    # An orphan (its training point diverged or was never written) is dropped
    # rather than invented, and it is NOT a diverged step.
    io.append_eval(9, {"val": 0.9})

    body = c.get(f"/api/train/jobs/{uid}/metrics").json()
    assert body["diverged"] == 0
    by_step = {p["step"]: p for p in body["points"]}
    assert set(by_step) == {1, 2}
    assert by_step[1]["val"] is None and by_step[1]["stable"] is None
    assert by_step[2]["val"] == 0.7 and by_step[2]["stable"] == 0.35
    # The incremental poll carries them too — the graph accumulates from it.
    inc = c.get(f"/api/train/jobs/{uid}/metrics?after=1").json()
    assert [p["step"] for p in inc["points"]] == [2]
    assert inc["points"][0]["val"] == 0.7


def test_a_round_with_no_images_yet_is_still_reported(train_client, tmp_path):
    """What makes the placeholders possible: the round is in the response from
    the moment the trainer opens its folder, saying how many images to expect
    and how many have landed."""
    c = train_client
    uid = c.post("/api/train/jobs",
                 json={"name": "round", "config": _api_cfg(steps=5)}).json()["uid"]
    jd = tp.job_dir(training_dir(tmp_path / "data"), uid)
    d = tp.samples_dir(jd) / "step-000010"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"started": time.time(),
                                             "expected": 4}))

    body = c.get(f"/api/train/jobs/{uid}/samples").json()
    assert body["samples"] == []
    assert [(r["step"], r["expected"], r["done"]) for r in body["rounds"]] \
        == [(10, 4, 0)]


def test_api_gpu_and_log(train_client):
    c = train_client
    stats = c.get("/api/train/gpu").json()
    assert isinstance(stats, list)  # content is platform-dependent
    r = c.post("/api/train/jobs", json={"name": "log",
                                        "config": _api_cfg(steps=5)})
    uid = r.json()["uid"]
    assert c.get(f"/api/train/jobs/{uid}/log").json() == {"log": ""}


# ---- per-image flip veto --------------------------------------------------


def _flip_source(no_flip, items):
    """A LatentSource with just the fields `may_flip` reads."""
    loop = _loop_module()
    src = loop.LatentSource.__new__(loop.LatentSource)
    src.items = items
    src.flip_p = 0.5
    src.no_flip_tags = {str(t).strip().lower() for t in no_flip if str(t).strip()}
    return src


_FLIP_ITEMS = [
    {"path": "a.png", "tags": ["dog", "outdoors"]},
    {"path": "b.png", "tags": ["Text", "poster"]},
    {"path": "c.png", "tags": ["comic_text"]},   # must not match "text"
    {"path": "d.png"},                            # no tags at all
]


def test_no_flip_tags_veto_only_the_images_that_carry_them():
    src = _flip_source(["text"], _FLIP_ITEMS)
    assert [src.may_flip(i) for i in range(4)] == [True, False, True, True]


def test_no_flip_tags_ignore_case_and_padding_but_match_whole_tags():
    src = _flip_source([" TEXT ", "logo", ""], _FLIP_ITEMS)
    assert [src.may_flip(i) for i in range(4)] == [True, False, True, True]


def test_no_flip_tags_empty_flips_everything():
    src = _flip_source([], _FLIP_ITEMS)
    assert all(src.may_flip(i) for i in range(4))


def test_no_flip_tags_survive_the_config_round_trip():
    from media_compost.train.spec import TrainingConfig

    cfg = TrainingConfig.model_validate({
        **_cfg().model_dump(),
        "buckets": {"flip_p": 0.5, "no_flip_tags": ["text", "logo"]},
    })
    assert cfg.buckets.no_flip_tags == ["text", "logo"]
    assert json.loads(cfg.model_dump_json())["buckets"]["no_flip_tags"] == \
        ["text", "logo"]


# ---- sample batching -------------------------------------------------------


def _sample_groups():
    import sys

    d = str(TRAIN_SCRIPTS)
    added = d not in sys.path
    if added:
        sys.path.insert(0, d)
    try:
        return importlib.import_module("engines.common").sample_groups
    finally:
        if added:
            sys.path.remove(d)


_SAMPLE_PROMPTS = [
    ("a", "", None, None),      # native size
    ("b", "no", None, None),
    ("c", "", 512, 768),        # its own size
    ("d", "", None, None),
    ("e", "", 512, 768),
]


def test_sample_groups_batch_within_each_size():
    groups = list(_sample_groups()(_SAMPLE_PROMPTS, 1024, 8))
    # Two calls: one per distinct size, never mixing them.
    assert [(g[0], g[3], g[4]) for g in groups] == [
        ([0, 1, 3], 1024, 1024),
        ([2, 4], 512, 768),
    ]


def test_sample_groups_respect_the_batch_limit():
    groups = list(_sample_groups()(_SAMPLE_PROMPTS, 1024, 2))
    assert [g[0] for g in groups] == [[0, 1], [3], [2, 4]]


def test_sample_groups_keep_every_slot_exactly_once():
    for batch in (1, 2, 3, 8):
        groups = list(_sample_groups()(_SAMPLE_PROMPTS, 1024, batch))
        slots = sorted(i for g in groups for i in g[0])
        assert slots == list(range(len(_SAMPLE_PROMPTS)))
        for idxs, ps, ns, _w, _h in groups:
            # The parallel lists a pipeline call needs must line up, and each
            # prompt has to keep its own negative.
            assert len(ps) == len(ns) == len(idxs)
            assert ps == [_SAMPLE_PROMPTS[i][0] for i in idxs]
            assert ns == [_SAMPLE_PROMPTS[i][1] for i in idxs]


def test_sample_batch_reaches_the_engine(tmp_path: Path):
    loop = _loop_module()
    captured = {}

    class _Engine:
        def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                             on_image=None, check=None):
            captured["batch"] = batch
            return []

    class _IO:
        def check_control(self):
            pass

        def sample_dir(self, step):
            # A real directory: _generate_samples stamps the round it rendered,
            # and Path(".") wrote that stamp into the repo's working directory.
            d = Path(tmp_path) / f"step-{step:06d}"
            d.mkdir(parents=True, exist_ok=True)
            return d

    loop._generate_samples(_IO(), _Engine(),
                           {"prompts": [{"prompt": "x"}], "batch": 4}, 0)
    assert captured["batch"] == 4


# ---- a failure before the first step ---------------------------------------


def _fail_at(sim_mgr, step: int) -> dict:
    """Create a job, plant a trainer failure at `step`, and finalize it."""
    from media_compost.train import paths as tp

    uid = sim_mgr.create("boom", _cfg(steps=40), "tester")
    jd = sim_mgr._dir(uid)
    # A crash happens on a RUNNING record — and _finalize is idempotent now,
    # standing down on anything already terminal (or never started).
    rec = sim_mgr._read(uid)
    rec["status"] = "running"
    sim_mgr._write(uid, rec)
    tp.write_json(tp.state_path(jd), {
        "phase": "failed", "step": step,
        "error": "RuntimeError: out of memory",
    })
    sim_mgr._finalize(uid, 1)
    return sim_mgr.get(uid)


def test_failure_before_the_first_step_is_editable_again(sim_mgr):
    """Nothing was produced, so the job goes back to the queue as paused —
    editable and startable — rather than freezing as a read-only failure."""
    rec = _fail_at(sim_mgr, 0)
    assert rec["status"] == "paused"
    # The reason must survive: it is the whole point of looking at the card.
    assert "out of memory" in rec["message"]
    # Editable is the property that matters; update() 409s on a real failure.
    sim_mgr.update(rec["uid"], "boom (fixed)", _cfg(steps=10))
    assert sim_mgr.get(rec["uid"])["name"] == "boom (fixed)"


def test_failure_after_real_progress_is_paused_and_still_editable(sim_mgr):
    """A failure is never "finished": the job waits so it can be resumed from
    its last checkpoint — and fixing whatever caused the failure means
    editing it, which is allowed and recorded in the timeline."""
    rec = _fail_at(sim_mgr, 17)
    assert rec["status"] == "paused"
    assert "out of memory" in rec["message"]
    sim_mgr.update(rec["uid"], "boom (smaller batch)", _cfg(steps=10))
    assert sim_mgr.get(rec["uid"])["name"] == "boom (smaller batch)"
    kinds = [json.loads(ln)["kind"] for ln in
             tp.events_path(sim_mgr._dir(rec["uid"])).read_text(encoding="utf-8").splitlines()]
    assert "edited" in kinds


def test_a_job_that_is_pausing_still_takes_edits(sim_mgr):
    """PAUSING is on the editable side of the line.

    The trainer read its config when it was spawned and is now writing a
    checkpoint, so an edit lands on the NEXT run exactly as it does on a job
    already paused. A pause takes as long as the in-flight micro-batch does —
    a minute on a big-batch job — and refusing edits for that whole time is a
    refusal whose reason has already stopped applying.
    """
    uid = sim_mgr.create("pausing edit", _cfg(steps=400), "tester")
    sim_mgr.enqueue(uid)
    sim_mgr.queue_run()
    _wait(sim_mgr, uid, ("running",))
    sim_mgr.pause(uid)
    if sim_mgr.get(uid)["status"] == "pausing":
        sim_mgr.update(uid, "renamed mid-pause", _cfg(steps=400))
        assert sim_mgr.get(uid)["name"] == "renamed mid-pause"
    # RUNNING is still refused, which is the half of the rule that stays.
    other = sim_mgr.create("running", _cfg(steps=400), "tester")
    sim_mgr.enqueue(other)
    sim_mgr.queue_run()
    _wait(sim_mgr, other, ("running",))
    with pytest.raises(TrainingConflict):
        sim_mgr.update(other, "nope", _cfg(steps=400))
    sim_mgr.cancel(other)


def test_a_failure_is_still_recorded_as_failed_in_the_timeline(sim_mgr):
    from media_compost.train import paths as tp

    rec = _fail_at(sim_mgr, 17)
    import json as _json

    lines = tp.events_path(sim_mgr._dir(rec["uid"])).read_text(encoding="utf-8").splitlines()
    assert _json.loads(lines[-1])["kind"] == "failed"


# ---- the model registry ----------------------------------------------------


def test_every_registry_model_has_an_engine_and_estimate():
    """Adding a model is a registry entry plus an engine module, and the
    editor's memory estimate is built from the entry's constants — a model
    missing either looks fine until someone tries to queue it."""
    import ast

    from media_compost.train.manager import TRAIN_SCRIPTS
    from media_compost.train.models import REGISTRY

    for spec in REGISTRY:
        path = TRAIN_SCRIPTS / "engines" / f"{spec.engine}.py"
        assert path.is_file(), f"{spec.key}: no engine module {path.name}"
        # Parsed rather than imported: the engines live in the training venv
        # and import torch/diffusers at call time, neither of which exists in
        # the venv these tests run in.
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        assert "Engine" in classes, f"{spec.key}: {path.name} defines no Engine"
        # …and the pipeline the Evaluate tab generates with. This used to be a
        # second table in generate.py, and a model added to the registry and
        # engines/ but not to it raised `KeyError: 'flux2'` — at generation
        # time, on a model that trained perfectly well.
        names = {
            n.targets[0].id
            for n in tree.body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
        }
        assert "PIPELINE" in names, \
            f"{spec.key}: {path.name} declares no PIPELINE"

        # An engine serving a FAMILY (FLUX.2 is Klein and dev over one
        # transformer) declares the whole family, and its own default has to
        # be one of them — a repo with nothing cached yet falls back to
        # PIPELINE, so a default outside the family is a class the engine
        # says it cannot handle.
        assigned = {
            n.targets[0].id: n.value for n in tree.body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
        }
        if "PIPELINES" in assigned:
            family = [e.value for e in assigned["PIPELINES"].elts]
            assert assigned["PIPELINE"].value in family, (
                f"{spec.key}: {path.name} declares a PIPELINE outside its "
                f"own PIPELINES")

        # …and which component quantization applies to. `BaseEngine` defaults
        # to "unet", so a DiT engine that forgets to say "transformer" builds
        # a quant_mapping naming a component its pipeline does not have —
        # and that fails only when someone turns quantization ON, i.e. on the
        # big models where it is the difference between fitting on the card
        # and not.
        #
        # DERIVED, not tabled: the expected value is whichever component the
        # engine's own `load()` takes off the pipeline (`self.unet = pipe.unet`
        # / `self.transformer = pipe.transformer`). A hardcoded list of which
        # engines are DiT would be the same second table this test exists to
        # prevent, and would silently pass for the next model added.
        engine_cls = next(n for n in ast.walk(tree)
                          if isinstance(n, ast.ClassDef) and n.name == "Engine")
        declared = {
            t.id: getattr(a.value, "value", None)
            for a in engine_cls.body if isinstance(a, ast.Assign)
            for t in a.targets if isinstance(t, ast.Name)
        }
        taken = {
            n.value.attr
            for n in ast.walk(engine_cls)
            if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Attribute)
            and isinstance(n.value.value, ast.Name) and n.value.value.id == "pipe"
            and n.value.attr in ("unet", "transformer")
        }
        assert len(taken) == 1, (
            f"{spec.key}: {path.name} takes {sorted(taken)} off the pipeline; "
            "expected exactly one backbone")
        want = taken.pop()
        backbone = declared.get("backbone_component", "unet")
        assert backbone == want, (
            f"{spec.key}: {path.name} assigns self.{want} = pipe.{want} but "
            f"declares backbone_component={backbone!r} — quantization would "
            f"name a component the pipeline does not have")

        # …and which components the TEXT ENCODER quantization applies to.
        # DERIVED the same way and for the same reason: SDXL and FLUX.1 each
        # have two, the second is the big one in both (OpenCLIP ViT-bigG,
        # T5-XXL), and naming only the first would quantize the smaller sixth
        # of `aux_gb` while the estimate showed the whole saving.
        taken_te = {
            n.value.attr
            for n in ast.walk(engine_cls)
            if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Attribute)
            and isinstance(n.value.value, ast.Name) and n.value.value.id == "pipe"
            and n.value.attr.startswith("text_encoder")
        }
        # `self.text_encoders = [pipe.text_encoder, pipe.text_encoder_2]` is a
        # LIST, so the attributes hang off the list element rather than off an
        # assignment — walk for any `pipe.text_encoder*` in the class.
        taken_te |= {
            n.attr for n in ast.walk(engine_cls)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "pipe" and n.attr.startswith("text_encoder")
        }
        # PRESENCE, not the value: `declared` maps a name to
        # `getattr(node.value, "value", None)`, which is None for a TUPLE
        # literal — so `.get(...) is None` cannot tell "declared as a tuple"
        # from "not declared", and read every engine as taking the default.
        if "text_encoder_components" not in declared:
            declared_te = ("text_encoder",)      # BaseEngine's own default
        else:
            item = next(n for n in engine_cls.body
                        if isinstance(n, ast.Assign)
                        and any(getattr(t, "id", "") == "text_encoder_components"
                                for t in n.targets))
            declared_te = tuple(e.value for e in item.value.elts)
        assert set(declared_te) == taken_te, (
            f"{spec.key}: {path.name} takes {sorted(taken_te)} off the "
            f"pipeline but declares text_encoder_components={declared_te} — "
            f"quantizing the text encoder would miss one, and the VRAM "
            f"estimate would promise a saving the run does not make")

        assert spec.repo and spec.default_area > 0, spec.key
        # The VRAM estimate returns nothing at all without these, which is
        # better than a wrong number but not what a shipped model should do.
        assert spec.backbone_gb > 0 and spec.act_gb > 0, \
            f"{spec.key}: no memory-estimate constants"
        if not spec.lora_only:
            assert spec.full_gb > 0, f"{spec.key}: no full-finetune size"


def test_models_sharing_an_architecture_are_listed_together():
    """The Models page groups by ENGINE and lays the groups out in registry
    order, so a model filed away from the rest of its family splits that
    family into two headings with the same name — Chroma Base under one and
    Chroma HD under another. The registry's order IS the grouping."""
    from media_compost.train.models import REGISTRY

    seen: list[str] = []
    for spec in REGISTRY:
        if seen and seen[-1] == spec.engine:
            continue
        assert spec.engine not in seen, (
            f"{spec.key} reopens the {spec.engine!r} group after "
            f"{seen[-1]!r} — move it next to the rest of its architecture")
        seen.append(spec.engine)


# ---- the warm generator yields to training ---------------------------------


def test_release_idle_frees_a_warm_generator(tmp_path: Path, monkeypatch):
    """A generator kept warm for the next click must let go when a training
    job needs the GPU — on unified memory the two collide rather than queue."""
    _use_fake_trainer(monkeypatch)
    cfg = UiConfig(data_dir=tmp_path / "data")
    ev = Library(cfg).evaluation
    ev._root().mkdir(parents=True, exist_ok=True)

    class _Idle:
        returncode = None
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    proc = _Idle()
    ev._proc, ev._proc_uid = proc, "whatever"
    assert ev.release_idle() is True
    assert proc.terminated and ev._proc is None


def test_release_idle_spares_a_generator_that_is_working(tmp_path: Path,
                                                         monkeypatch):
    _use_fake_trainer(monkeypatch)
    cfg = UiConfig(data_dir=tmp_path / "data")
    ev = Library(cfg).evaluation
    d = ev._root() / "busy0000000000000"
    d.mkdir(parents=True, exist_ok=True)
    tp.write_json(d / "state.json", {"phase": "generating"})

    class _Busy:
        def poll(self):
            return None

        def terminate(self):
            raise AssertionError("a running generation must not be killed")

    ev._proc, ev._proc_uid = _Busy(), "busy0000000000000"
    assert ev.release_idle() is False


def test_a_crashed_runs_stale_state_is_not_a_phantom_generation(
        tmp_path: Path, monkeypatch):
    """A generator that dies mid-run leaves its state.json at "generating"
    forever (status is derived lazily, never written back). That stale dir
    must not make a LATER warm-idle process read as rendering — it blocked
    release_idle and parked queued training jobs behind a phantom run."""
    _use_fake_trainer(monkeypatch)
    cfg = UiConfig(data_dir=tmp_path / "data")
    ev = Library(cfg).evaluation
    crashed = ev._root() / "dead0000000000000"
    crashed.mkdir(parents=True, exist_ok=True)
    tp.write_json(crashed / "state.json",
                  {"phase": "generating", "pid": 999999999})

    class _Idle:
        pid = 4242

        def poll(self):
            return None

        def terminate(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

    ev._proc, ev._proc_uid = _Idle(), "warm0000000000000"
    assert ev.rendering() is False, "the stale dir belongs to a dead pid"
    assert ev.release_idle() is True, "a warm-idle process is droppable"


def test_a_generation_waits_for_a_training_run_on_the_same_gpu(
        tmp_path: Path, monkeypatch):
    """The two tabs share one GPU. On unified memory especially they do not
    queue on their own — they collide as an out-of-memory failure — so a
    generation asked for while training holds the device is QUEUED, and the
    training manager pumps it the moment the device frees."""
    _use_fake_trainer(monkeypatch)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    ev = lib.evaluation
    monkeypatch.setattr(type(ev), "device", lambda self: "mps")

    spawned: list[str] = []
    monkeypatch.setattr(type(ev), "_spawn",
                        lambda self, uid: spawned.append(uid))

    busy: set[str] = set()
    monkeypatch.setattr(type(lib.training), "busy_devices",
                        lambda self: set(busy))

    def ask() -> str:
        return ev.generate(
            model="sd15", loras=[], prompt="a fox", negative="",
            width=0, height=0, seed=1, steps=4, cfg_scale=6.0,
            count=1, batch=1, username="")

    # Nothing training: it starts at once.
    uid = ask()
    assert spawned == [uid]

    # Training takes the device -> the next one waits instead of colliding.
    spawned.clear()
    busy.add("mps")
    queued_uid = ask()
    assert spawned == []
    assert ev.get(queued_uid)["status"] == "queued"

    # Still waiting while training holds it, however often it is pumped.
    ev.pump()
    assert spawned == []

    # A job on a DIFFERENT card is no conflict at all.
    busy.clear()
    busy.add("cuda:1")
    ev.pump()
    assert spawned == [queued_uid]


def test_training_waits_for_a_generation_on_the_same_gpu(tmp_path: Path,
                                                         monkeypatch):
    """The other direction: a queued job does not start while a generation is
    actually rendering — and a generation only holding a model warm is not a
    reason to wait, since `release_idle` can simply drop that."""
    _use_fake_trainer(monkeypatch)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    mgr = lib.training
    monkeypatch.setattr(type(lib.evaluation), "device", lambda self: "mps")

    rendering = {"now": True}
    monkeypatch.setattr(type(lib.evaluation), "rendering",
                        lambda self: rendering["now"])

    started: list[tuple[str, str]] = []

    def fake_start(self, rec, device):
        # Mark it running the way the real one does, so the live tick thread
        # can't start the same job a second time and make this flaky.
        started.append((rec["uid"], device))
        rec["status"] = "running"
        self._write(rec["uid"], rec)
        self._on_device[rec["uid"]] = device
        return True

    monkeypatch.setattr(type(mgr), "_start_job", fake_start)

    uid = mgr.create("j", TrainingConfig(model="sd15", gpu="mps",
                                         queries=[DatasetQuery(tree=None)]),
                     "")
    mgr.enqueue(uid)
    # `_maybe_start` is driven by hand rather than by turning the queue's run
    # switch on: with the tick thread also calling it, both could pick up the
    # same job between snapshots and the assertion below would be a race.
    mgr._maybe_start()
    assert started == [], "started while a generation was rendering"

    # The generation finishes; the queue proceeds.
    rendering["now"] = False
    mgr._maybe_start()
    assert started == [(uid, "mps")]


def test_start_now_waits_for_the_evaluate_tab_rather_than_refusing(
        tmp_path: Path, monkeypatch):
    """Pressing start while the other tab is generating must WORK — the job is
    accepted and waits for the GPU. Refusing made the button look broken, and
    it is a wait either way: the request stays pending until the device
    frees."""
    _use_fake_trainer(monkeypatch)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    mgr = lib.training
    monkeypatch.setattr(type(lib.evaluation), "device", lambda self: "mps")
    rendering = {"now": True}
    monkeypatch.setattr(type(lib.evaluation), "rendering",
                        lambda self: rendering["now"])

    started: list[str] = []

    def fake_start(self, rec, device):
        started.append(rec["uid"])
        rec["status"] = "running"
        self._write(rec["uid"], rec)
        self._on_device[rec["uid"]] = device
        return True

    monkeypatch.setattr(type(mgr), "_start_job", fake_start)

    uid = mgr.create("j", TrainingConfig(model="sd15", gpu="mps",
                                         queries=[DatasetQuery(tree=None)]),
                     "")
    mgr.start_now(uid)                      # accepted, not refused
    assert mgr.get(uid)["status"] == "queued"
    assert mgr.evaluating_device() == "mps"  # …and the status says why

    mgr._start_explicit()
    assert started == [], "started while a generation was rendering"

    # The generation ends; the pending start goes through on the next pass.
    rendering["now"] = False
    assert mgr.evaluating_device() is None
    mgr._start_explicit()
    assert started == [uid]


# ---- sample rounds are not re-rendered -------------------------------------


class _CountingEngine:
    """Counts how many rounds it was actually asked to render."""

    def __init__(self):
        self.calls = 0

    def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                             on_image=None, check=None):
        from PIL import Image

        self.calls += 1
        return [Image.new("RGB", (8, 8)) for _ in prompts]


def _sample_io(tmp_path: Path):
    from media_compost.train import paths as tp   # noqa: F401 (path style)

    class _IO:
        def __init__(self, d):
            self.d = d

        def check_control(self):
            pass

        def sample_dir(self, step):
            p = self.d / "samples" / f"step-{step:06d}"
            fresh = not p.exists()
            p.mkdir(parents=True, exist_ok=True)
            if fresh:
                (p / "meta.json").write_text(json.dumps({"started": 1.0}))
            return p

    return _IO(tmp_path)


_SAMPLING = {
    "prompts": [{"prompt": "a cat"}, {"prompt": "a dog"}],
    "seed": 42, "steps": 8, "cfg": 6.0,
}


def test_a_rendered_sample_round_is_not_rendered_again(tmp_path: Path):
    """Resuming replays steps that were already sampled; re-rendering them
    spends minutes of GPU on images that would come out identical."""
    loop = _loop_module()
    io, eng = _sample_io(tmp_path), _CountingEngine()

    loop._generate_samples(io, eng, _SAMPLING, 250)
    assert eng.calls == 1
    loop._generate_samples(io, eng, _SAMPLING, 250)
    assert eng.calls == 1, "the second pass re-rendered an identical round"
    # The images are still there for the timeline.
    assert len(list((tmp_path / "samples" / "step-000250").glob("p*.png"))) == 2


def test_changing_the_prompts_renders_the_round_again(tmp_path: Path):
    loop = _loop_module()
    io, eng = _sample_io(tmp_path), _CountingEngine()
    loop._generate_samples(io, eng, _SAMPLING, 250)
    changed = {**_SAMPLING, "prompts": [{"prompt": "a cat"}, {"prompt": "a bird"}]}
    loop._generate_samples(io, eng, changed, 250)
    assert eng.calls == 2


def test_changing_the_sampler_renders_the_round_again(tmp_path: Path):
    loop = _loop_module()
    io, eng = _sample_io(tmp_path), _CountingEngine()
    loop._generate_samples(io, eng, _SAMPLING, 250)
    for patch in ({"seed": 7}, {"steps": 30}, {"cfg": 9.0}):
        eng.calls = 0
        loop._generate_samples(io, eng, {**_SAMPLING, **patch}, 250)
        assert eng.calls == 1, f"{patch} should force a re-render"


def test_a_different_step_still_renders(tmp_path: Path):
    loop = _loop_module()
    io, eng = _sample_io(tmp_path), _CountingEngine()
    loop._generate_samples(io, eng, _SAMPLING, 250)
    loop._generate_samples(io, eng, _SAMPLING, 500)
    assert eng.calls == 2


# ---- attention slicing ------------------------------------------------------


class _Sliceable:
    def __init__(self):
        self.slice = None

    def set_attention_slice(self, size):
        self.slice = size


def _engine_for_slicing(mode, device):
    """A BaseEngine with only the fields apply_attention_slicing reads."""
    import sys

    d = str(TRAIN_SCRIPTS)
    added = d not in sys.path
    if added:
        sys.path.insert(0, d)
    try:
        common = importlib.import_module("engines.common")
    finally:
        if added:
            sys.path.remove(d)
    e = common.BaseEngine.__new__(common.BaseEngine)
    e.hyper = {"attention_slicing": mode}
    e.device = device
    return e


def _engine_for_quant(mode: str, device: str, method: str = "lora"):
    e = _engine_for_slicing("off", device)
    e.hyper = {"quantization": mode}
    e.method = method
    return e


def test_which_library_quantizes_is_decided_by_the_device(monkeypatch):
    """nf4 is bitsandbytes on CUDA; int8 is quanto EVERYWHERE, CUDA included.

    The quanto path is what makes the largest models trainable on Apple
    silicon at all — measured on an M4 Max, Qwen-Image's 57.7 GB of bf16
    weights become 37.5, and 30.3 with the text encoder quantized too, where
    bf16 will not load. On CUDA it is what makes int8 SAVE memory at all:
    bitsandbytes' int8 keeps an activation-sized tensor per layer that
    gradient checkpointing cannot reach (`_quant_backend` has the table), so
    a Chroma run peaked higher quantized than not. nf4 has no substitute and
    still refuses off CUDA.
    """
    monkeypatch.delenv("MEDIA_COMPOST_INT8_BACKEND", raising=False)
    assert _engine_for_quant("none", "mps")._quant_backend("none") is None
    # fp8 is not a load-time scheme — `apply_fp8` converts in place after the
    # adapter is attached, so there is no config to build.
    assert _engine_for_quant("fp8", "cuda")._quant_backend("fp8") is None

    e = _engine_for_quant("int8", "cuda:0")
    e._have = lambda module, name: True
    assert e._quant_backend("int8") == "quanto"
    # …bitsandbytes only where neither quanto nor torchao is there, or when
    # asked for by name — the comparison knob.
    e._have = lambda module, name: False
    assert e._quant_backend("int8") == "bitsandbytes"
    monkeypatch.setenv("MEDIA_COMPOST_INT8_BACKEND", "bitsandbytes")
    e._have = lambda module, name: True
    assert e._quant_backend("int8") == "bitsandbytes"
    monkeypatch.delenv("MEDIA_COMPOST_INT8_BACKEND")
    assert _engine_for_quant("nf4", "cuda:0")._quant_backend("nf4") == "bitsandbytes"

    # Off CUDA it is quanto while diffusers still has it, and torchao once
    # diffusers 1.0 removes it — both measured to give the identical saving,
    # quanto chosen first because it is 24% faster a step. `_have` is what
    # decides, so it is what the test drives: this suite runs in the app's
    # torch-free venv, where the real answer is always "no diffusers".
    e = _engine_for_quant("int8", "mps")
    e._have = lambda module, name: True
    assert e._quant_backend("int8") == "quanto"
    e._have = lambda module, name: False
    assert e._quant_backend("int8") == "torchao"

    # nf4 is bitsandbytes-only, and the message says what DOES run here rather
    # than only what does not.
    with pytest.raises(RuntimeError, match="int8, which runs here"):
        _engine_for_quant("nf4", "mps")._quant_backend("nf4")

    # A full finetune has nothing frozen to quantize, on any device.
    with pytest.raises(RuntimeError, match="only applies to LoRA"):
        _engine_for_quant("int8", "cuda:0", method="full")._quant_backend("int8")


def test_auto_never_slices():
    """"auto" is off everywhere: CUDA's fused kernels beat slicing, and on MPS
    slicing returns NaN (measured: SDXL bf16, batch 2, `loss=nan` from step 1
    with it and a normal loss without)."""
    for device in ("mps", "cuda", "cpu"):
        m = _Sliceable()
        assert _engine_for_slicing("auto", device).apply_attention_slicing(m) is False
        assert m.slice is None


def test_slicing_is_refused_on_mps_even_when_asked_for():
    """A memory saving that computes NaN is not a saving — and it fails
    silently: flat loss graph, black samples, hours of wasted training."""
    m = _Sliceable()
    assert _engine_for_slicing("on", "mps").apply_attention_slicing(m) is False
    assert m.slice is None


def test_slicing_can_be_forced_on_or_off():
    on = _Sliceable()
    assert _engine_for_slicing("on", "cuda").apply_attention_slicing(on) is True
    off = _Sliceable()
    assert _engine_for_slicing("off", "cuda").apply_attention_slicing(off) is False
    assert off.slice is None


def test_a_backbone_that_cannot_slice_is_not_an_error():
    class _Plain:
        pass

    assert _engine_for_slicing("on", "cuda").apply_attention_slicing(_Plain()) is False

    class _Refuses:
        def set_attention_slice(self, size):
            raise NotImplementedError

    assert _engine_for_slicing("on", "cuda").apply_attention_slicing(_Refuses()) is False


# ---- explicit queue run + one job per device --------------------------------


def test_enqueue_and_dequeue_never_start_anything(sim_mgr):
    """Queueing is placement only: nothing runs until the queue is told to
    run, so removing a job from the queue can never race a start."""
    uid = sim_mgr.create("q", _cfg(steps=30), "t")
    sim_mgr.enqueue(uid)
    time.sleep(1.0)  # several ticks at the test's 0.2 s cadence
    assert sim_mgr.get(uid)["status"] == "queued"
    sim_mgr.pause(uid)  # remove from the queue
    assert sim_mgr.get(uid)["status"] == "draft"
    time.sleep(0.5)
    assert sim_mgr.get(uid)["status"] == "draft"


def test_queue_chains_then_switches_itself_off_when_drained(sim_mgr):
    a = sim_mgr.create("a", _cfg(steps=20), "t")
    b = sim_mgr.create("b", _cfg(steps=20), "t")
    for u in (a, b):
        sim_mgr.enqueue(u)
    sim_mgr.queue_run()
    assert sim_mgr.queue_active()
    _wait(sim_mgr, a, ("completed",))
    _wait(sim_mgr, b, ("completed",))  # chained without another run click
    end = time.time() + 10
    while time.time() < end and sim_mgr.queue_active():
        time.sleep(0.1)
    assert not sim_mgr.queue_active()  # drained -> off
    c = sim_mgr.create("c", _cfg(steps=20), "t")
    sim_mgr.enqueue(c)
    time.sleep(1.0)
    assert sim_mgr.get(c)["status"] == "queued"  # needs an explicit run again


def test_pausing_a_running_job_stops_the_queue(sim_mgr):
    a = sim_mgr.create("a", _cfg(steps=800), "t")
    b = sim_mgr.create("b", _cfg(steps=20), "t")
    for u in (a, b):
        sim_mgr.enqueue(u)
    sim_mgr.queue_run()
    _wait(sim_mgr, a, ("running",))
    sim_mgr.pause(a)
    _wait(sim_mgr, a, ("queued",))   # back in the queue, at the front
    assert not sim_mgr.queue_active()
    time.sleep(1.0)
    assert sim_mgr.get(b)["status"] == "queued"  # the freed device stays idle
    sim_mgr.cancel(a)
    sim_mgr.cancel(b)


def test_one_job_per_device_and_distinct_devices_run_concurrently(
        sim_mgr, monkeypatch):
    from media_compost.train import gpu as gputil

    monkeypatch.setattr(gputil, "train_devices", lambda: [
        {"id": "cuda:0", "label": "fake0"}, {"id": "cuda:1", "label": "fake1"},
    ])

    def cfg_on(gpu: str) -> TrainingConfig:
        return TrainingConfig(**{**_cfg(steps=800).model_dump(), "gpu": gpu})

    a = sim_mgr.create("a", cfg_on("cuda:0"), "t")
    b = sim_mgr.create("b", cfg_on("cuda:0"), "t")  # same card: must wait
    c = sim_mgr.create("c", cfg_on("cuda:1"), "t")  # other card: concurrent
    for u in (a, b, c):
        sim_mgr.enqueue(u)
    sim_mgr.queue_run()
    _wait(sim_mgr, a, ("running",))
    _wait(sim_mgr, c, ("running",))                 # runs alongside a
    time.sleep(1.0)
    assert sim_mgr.get(a)["status"] == "running"    # really concurrent
    assert sim_mgr.get(b)["status"] == "queued"     # cuda:0 is taken
    sim_mgr.cancel(a)
    _wait(sim_mgr, b, ("running",))                 # cancel = skip, queue on
    for u in (b, c):
        sim_mgr.cancel(u)
        _wait(sim_mgr, u, ("canceled",))


def test_start_now_runs_one_job_without_chaining(sim_mgr):
    """The card's Start button: run THIS job, and only it — the queue's run
    switch stays off, so a queued job behind it does not follow."""
    a = sim_mgr.create("a", _cfg(steps=20), "t")
    b = sim_mgr.create("b", _cfg(steps=20), "t")
    sim_mgr.enqueue(b)                     # waiting in the queue
    sim_mgr.start_now(a)                   # draft, started directly
    rec = _wait(sim_mgr, a, ("completed",))
    assert rec["status"] == "completed"
    assert not sim_mgr.queue_active()
    time.sleep(1.0)
    assert sim_mgr.get(b)["status"] == "queued"  # no chain after a one-off

    # A busy device refuses a second explicit start up front.
    c = sim_mgr.create("c", _cfg(steps=800), "t")
    d = sim_mgr.create("d", _cfg(steps=800), "t")
    sim_mgr.start_now(c)
    _wait(sim_mgr, c, ("running",))
    with pytest.raises(TrainingConflict):
        sim_mgr.start_now(d)
    sim_mgr.cancel(c)
    sim_mgr.cancel(b)


def test_sample_render_polls_the_control_check(tmp_path: Path):
    """The engine gets `check` (the trainer's control poll) so a pause or
    cancel interrupts a sample round mid-render — a round used to be the one
    phase that could not be paused, and an SDXL round is minutes long."""
    loop = _loop_module()
    from train import PauseRequested

    class _Engine:
        def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                             on_image=None, check=None):
            assert check is not None
            check()  # what a pipeline's per-step callback does
            raise AssertionError("check() must have raised")

    class _IO:
        def check_control(self):
            raise PauseRequested()

        def sample_dir(self, step):
            d = Path(tmp_path) / f"step-{step:06d}"
            d.mkdir(parents=True, exist_ok=True)
            return d

    with pytest.raises(PauseRequested):
        loop._generate_samples(_IO(), _Engine(), {
            "prompts": [{"prompt": "a cat"}], "seed": 1, "steps": 2,
        }, 10)


# ---- one manager per library, one finalize per exit -------------------------


def test_lazy_training_manager_is_built_once_under_concurrency(
        tmp_path: Path, monkeypatch):
    """Concurrent first requests must share ONE TrainingManager. Unlocked
    check-then-set let each early request build its own — every one adopted
    the live trainer and kept a tick thread after losing the assignment
    race, which is how one trainer exit became three "paused" events."""
    import threading

    from media_compost.train import manager as manager_mod

    built = []

    class _Slow:
        def __init__(self, lib):
            time.sleep(0.05)  # wide construction window, so races would show
            built.append(self)

    monkeypatch.setattr(manager_mod, "TrainingManager", _Slow)
    lib = Library(UiConfig(data_dir=tmp_path / "data"))
    got: list[object] = []
    barrier = threading.Barrier(6)

    def grab():
        barrier.wait()
        got.append(lib.training)

    threads = [threading.Thread(target=grab) for _ in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(built) == 1
    assert len({id(o) for o in got}) == 1


def test_finalize_is_idempotent_on_a_terminal_record(sim_mgr):
    """A watcher that shows up late — another tick, a stale thread — finds
    the job already finalized and stands down instead of stamping duplicate
    lifecycle events."""
    uid = sim_mgr.create("f", _cfg(steps=40), "t")
    jd = sim_mgr._dir(uid)
    rec = sim_mgr._read(uid)
    rec["status"] = "running"
    sim_mgr._write(uid, rec)
    tp.write_json(tp.state_path(jd), {"phase": "paused", "step": 5})

    sim_mgr._finalize(uid, 0)
    sim_mgr._finalize(uid, 0)
    sim_mgr._finalize(uid, 0)

    kinds = [json.loads(ln)["kind"]
             for ln in tp.events_path(jd).read_text(encoding="utf-8").splitlines()]
    assert kinds == ["paused"]
    assert sim_mgr.get(uid)["status"] == "paused"


# ---- locked checkpoints ------------------------------------------------------


def test_keep_rules_are_a_union_of_window_and_milestones(tmp_path: Path):
    """The two retention rules are independent: a snapshot survives if the
    last-N window OR the every-Nth milestones want it (or a lock does)."""
    import importlib.util as ilu

    spec = ilu.spec_from_file_location(
        "train_mod2", TRAIN_SCRIPTS / "train.py")
    train_mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(spec and train_mod)

    def steps_after(keep_last, keep_every, upto=90):
        io = train_mod.JobIO(tmp_path / f"j{keep_last}-{keep_every}")
        for step in range(10, upto + 1, 10):
            io.snapshot_step(step, keep_last, keep_every, every=10)
        return sorted(int(d.name.split("-")[1])
                      for d in io.checkpoints().iterdir() if d.is_dir())

    # Milestones only (every 2nd of a 10-step cadence = every 20 steps),
    # plus the newest, which is always kept.
    assert steps_after(0, 2) == [20, 40, 60, 80, 90]
    # Window only — the old behaviour.
    assert steps_after(3, 0) == [70, 80, 90]
    # The union is the point: milestones AND the last two.
    assert steps_after(2, 3) == [30, 60, 80, 90]
    # Neither rule keeps anything: only the snapshot just written survives.
    assert steps_after(0, 0) == [90]

    # A lock still overrides both, and never uses a window slot.
    io = train_mod.JobIO(tmp_path / "locked")
    io.snapshot_step(10, 2, 0, every=10)
    (io.checkpoints() / "step-000010" / ".locked").touch()
    for step in (20, 30, 40):
        io.snapshot_step(step, 2, 0, every=10)
    names = sorted(d.name for d in io.checkpoints().iterdir() if d.is_dir())
    assert names == ["step-000010", "step-000030", "step-000040"]


def test_api_lock_blocks_delete_and_reports(train_client):
    c = train_client
    cfg = _api_cfg(steps=20)
    cfg["hyper"]["checkpoint_every"] = 10
    cfg["hyper"]["checkpoint_keep"] = 5
    uid = c.post("/api/train/jobs",
                 json={"name": "lock", "config": cfg}).json()["uid"]
    c.post(f"/api/train/jobs/{uid}/queue")
    c.post("/api/train/queue/run")
    end = time.time() + 40
    while time.time() < end:
        if c.get(f"/api/train/jobs/{uid}").json()["status"] in (
                "completed", "failed"):
            break
        time.sleep(0.2)

    assert c.post(f"/api/train/jobs/{uid}/checkpoints/10/lock",
                  json={"locked": True}).status_code == 200
    cks = {k["step"]: k for k in
           c.get(f"/api/train/jobs/{uid}/checkpoints").json()["checkpoints"]}
    assert cks[10]["locked"] is True
    # Locked -> delete refused; unlock -> delete works.
    assert c.delete(f"/api/train/jobs/{uid}/checkpoints/10").status_code == 409
    assert c.post(f"/api/train/jobs/{uid}/checkpoints/10/lock",
                  json={"locked": False}).status_code == 200
    assert c.delete(f"/api/train/jobs/{uid}/checkpoints/10").status_code == 200


def test_deleting_a_job_KEEPS_what_was_locked(sim_mgr, tmp_path: Path):
    """A lock says "this one stays", and deleting the job is the moment that
    promise is worth something.

    The kept weights move out of the job folder and into the user's own LoRA
    list, because a job-owned weight set is listed by walking the jobs — left
    in place with the job gone they would be invisible in the LoRAs list and
    in the Evaluate dropdown, which is a quieter way of losing them.
    """
    from media_compost.train import paths as tp
    from media_compost.train import usermodels

    uid = sim_mgr.create("run", _cfg(steps=10), "t")
    jd = tp.job_dir(sim_mgr.dir, uid)
    # One locked snapshot, one unlocked, and a locked final output.
    for step, locked in ((10, True), (20, False)):
        d = tp.checkpoints_dir(jd) / f"step-{step:06d}"
        d.mkdir(parents=True)
        (d / "adapter.safetensors").write_bytes(b"w")
        if locked:
            tp.lock_marker(d).touch()
    out = tp.output_dir(jd)
    out.mkdir(parents=True)
    (out / "adapter.safetensors").write_bytes(b"o")
    tp.lock_marker(out).touch()

    assert sim_mgr.delete(uid) == 2
    assert not jd.exists()
    kept = sorted(d.name for d in tp.kept_dir(sim_mgr.dir).iterdir())
    assert kept == [f"{uid}-output", f"{uid}-step-000010"]
    # The unlocked snapshot went with the job.
    assert not any("step-000020" in name for name in kept)
    # …and each survivor is listed, pointed at where it now lives, under the
    # model it was trained for.
    loras = usermodels.read_loras(sim_mgr.dir)
    assert {lo.path for lo in loras} == {
        str(tp.kept_dir(sim_mgr.dir) / f"{uid}-output"),
        str(tp.kept_dir(sim_mgr.dir) / f"{uid}-step-000010"),
    }
    assert all(lo.model == "sd15" for lo in loras)
    # The lock marker does not travel: it protected the file from the job's
    # own machinery, and there is no job now.
    for lo in loras:
        assert not tp.is_locked(Path(lo.path))


def test_deleting_a_job_with_nothing_locked_keeps_nothing(sim_mgr):
    uid = sim_mgr.create("run", _cfg(steps=10), "t")
    from media_compost.train import paths as tp
    from media_compost.train import usermodels

    d = tp.checkpoints_dir(tp.job_dir(sim_mgr.dir, uid)) / "step-000010"
    d.mkdir(parents=True)
    assert sim_mgr.delete(uid) == 0
    assert not tp.kept_dir(sim_mgr.dir).exists()
    assert usermodels.read_loras(sim_mgr.dir) == []


def test_pause_puts_the_job_at_the_front_of_the_queue(sim_mgr):
    """Pausing is "not now", not "not at all" — the job waits FIRST in line
    (a failure, which needs fixing first, still stays out of the queue)."""
    other = sim_mgr.create("other", _cfg(steps=30), "t")
    sim_mgr.enqueue(other)
    uid = sim_mgr.create("pauseme", _cfg(steps=800), "t")
    sim_mgr.start_now(uid)
    _wait(sim_mgr, uid, ("running",))
    sim_mgr.pause(uid)
    rec = _wait(sim_mgr, uid, ("queued", "paused"))
    assert rec["status"] == "queued"
    assert rec["queued_at"] < sim_mgr.get(other)["queued_at"]
    sim_mgr.cancel(uid)
    sim_mgr.cancel(other)


def test_the_resume_point_is_listed_and_cannot_be_deleted(train_client):
    """A pause's checkpoint is a real timeline entry — downloadable like any
    other, never deletable (a job without it can only start over)."""
    c = train_client
    cfg = _api_cfg(steps=600)
    cfg["hyper"]["checkpoint_every"] = 0     # only the resume point exists
    uid = c.post("/api/train/jobs",
                 json={"name": "resume", "config": cfg}).json()["uid"]
    c.post(f"/api/train/jobs/{uid}/start")
    end = time.time() + 40
    while time.time() < end:
        j = c.get(f"/api/train/jobs/{uid}").json()
        if j["status"] == "running" and j["step"] >= 15:
            break
        time.sleep(0.2)
    c.post(f"/api/train/jobs/{uid}/pause")
    end = time.time() + 40
    while time.time() < end and c.get(f"/api/train/jobs/{uid}").json()[
            "status"] == "pausing":
        time.sleep(0.2)

    cks = c.get(f"/api/train/jobs/{uid}/checkpoints").json()["checkpoints"]
    resume = [k for k in cks if k["resume"]]
    assert len(resume) == 1, cks
    assert resume[0]["exists"] and resume[0]["size"] > 0
    step = resume[0]["step"]
    # Downloadable…
    r = c.get(f"/api/train/jobs/{uid}/checkpoints/{step}/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    # …but not deletable.
    assert c.delete(f"/api/train/jobs/{uid}/checkpoints/{step}").status_code == 409


def test_editing_a_started_job_records_what_changed(sim_mgr):
    """Settings stay editable after a run — they apply to the NEXT one — so
    the timeline has to say what was changed, old value → new."""
    uid = sim_mgr.create("edit me", _cfg(steps=40, batch_size=1), "t")
    sim_mgr.update(uid, "edit me", _cfg(steps=60, batch_size=2))

    events = [json.loads(ln) for ln in
              tp.events_path(sim_mgr._dir(uid)).read_text(encoding="utf-8").splitlines()]
    edited = [e for e in events if e["kind"] == "edited"]
    assert len(edited) == 1
    by_field = {c["field"]: c for c in edited[0]["data"]["changes"]}
    assert by_field["hyper.steps"] == {"field": "hyper.steps",
                                       "old": "40", "new": "60"}
    assert by_field["hyper.batch_size"]["old"] == "1"
    assert by_field["hyper.batch_size"]["new"] == "2"
    # A no-op edit writes nothing.
    sim_mgr.update(uid, "edit me", _cfg(steps=60, batch_size=2))
    again = [json.loads(ln)["kind"] for ln in
             tp.events_path(sim_mgr._dir(uid)).read_text(encoding="utf-8").splitlines()]
    assert again.count("edited") == 1


def test_a_running_job_still_refuses_edits(sim_mgr):
    uid = sim_mgr.create("busy", _cfg(steps=800), "t")
    sim_mgr.start_now(uid)
    _wait(sim_mgr, uid, ("running",))
    with pytest.raises(TrainingConflict):
        sim_mgr.update(uid, "nope", None)
    sim_mgr.cancel(uid)


def test_an_edit_ignores_settings_a_config_only_gained_by_default(sim_mgr):
    """A job written before a setting existed misses that key; the first edit
    must report what the USER changed, not what the schema grew."""
    uid = sim_mgr.create("old job", _cfg(steps=40), "t")
    stored = tp.read_json(tp.config_path(sim_mgr._dir(uid)))
    stored.pop("gpu", None)                    # as an older config would be
    tp.write_json(tp.config_path(sim_mgr._dir(uid)), stored)

    sim_mgr.update(uid, None, _cfg(steps=50))
    events = [json.loads(ln) for ln in
              tp.events_path(sim_mgr._dir(uid)).read_text(encoding="utf-8").splitlines()]
    fields = {c["field"] for e in events if e["kind"] == "edited"
              for c in e["data"]["changes"]}
    assert fields == {"hyper.steps"}


def test_an_interrupted_sample_round_is_finished_on_resume(tmp_path: Path):
    """A pause mid-round leaves fewer images than promised, and the cadence
    never comes back to that step — so a resume finishes it first."""
    loop = _loop_module()

    root = tmp_path / "samples"
    (root / "step-000050").mkdir(parents=True)
    (root / "step-000050" / "meta.json").write_text(
        json.dumps({"started": 1.0, "expected": 3}))
    (root / "step-000050" / "p00.png").write_bytes(b"x")   # 1 of 3 rendered
    (root / "step-000100").mkdir(parents=True)
    (root / "step-000100" / "meta.json").write_text(
        json.dumps({"started": 2.0, "expected": 2}))
    for n in ("p00.png", "p01.png"):
        (root / "step-000100" / n).write_bytes(b"x")       # complete

    class _IO:
        dir = tmp_path

    assert loop._unfinished_round(_IO()) == 50
    # Completing it clears the finding.
    for n in ("p01.png", "p02.png"):
        (root / "step-000050" / n).write_bytes(b"x")
    assert loop._unfinished_round(_IO()) is None


def test_offload_is_decided_by_model_size_against_the_machine(monkeypatch):
    """Big-for-the-machine models get shuttled; small ones stay resident.

    The rule is a fraction of RAM, not a fixed size, so the same model has to
    answer differently on two machines — that is the whole point of it.
    """
    from media_compost.train import evaluate as ev
    from media_compost.train.models import model_spec

    sdxl, chroma = model_spec("sdxl"), model_spec("chroma")

    monkeypatch.setattr(ev.gputil, "system_memory", lambda: (0.0, 64.0))
    assert ev._should_offload(sdxl) is False        # 6.9 GB of 64
    assert ev._should_offload(chroma) is True       # 25.7 GB of 64

    monkeypatch.setattr(ev.gputil, "system_memory", lambda: (0.0, 512.0))
    assert ev._should_offload(chroma) is False      # room to spare

    monkeypatch.setattr(ev.gputil, "system_memory", lambda: (0.0, 8.0))
    assert ev._should_offload(sdxl) is True         # no room at all

    # A machine that will not say how much memory it has must not be guessed
    # at: staying resident is what every earlier version did.
    monkeypatch.setattr(ev.gputil, "system_memory", lambda: None)
    assert ev._should_offload(chroma) is False


# ---- grouping the prompt by tag group -----------------------------------------

def _grouped_item():
    return {
        "tags": ["rain", "blonde_hair", "dress", "hat"],
        "tag_groups": [
            {"name": "Alice", "tags": ["blonde_hair", "dress"]},
            {"name": "Bob", "tags": ["hat"]},
        ],
    }


def test_grouping_puts_each_group_on_its_own_line():
    """A tag group is usually about one thing in the picture; a flat comma list
    leaves the model to guess which adjective belongs to whom."""
    cfg = {"group_tags": True, "separator": ", "}
    out = compose.group_tag_text(
        ["rain", "blonde_hair", "hat", "dress"], _grouped_item(), cfg,
        random.Random(0))
    assert out == "rain\nblonde hair, dress\nhat"


def test_the_block_label_is_a_choice_of_three():
    item = {
        "tag_groups": [
            {"name": "front figure", "tags": ["blonde_hair", "dress"],
             "subjects": ["Alice"]},
        ],
    }
    picked = ["blonde_hair", "dress"]
    plain = compose.group_tag_text(picked, item, {"group_tags": True}, random.Random(0))
    by_group = compose.group_tag_text(
        picked, item, {"group_tags": True, "group_label": "group"}, random.Random(0))
    by_subject = compose.group_tag_text(
        picked, item, {"group_tags": True, "group_label": "subject"}, random.Random(0))
    assert plain == "blonde hair, dress", "nothing by default"
    assert by_group.startswith("front figure: "), "the group's own name"
    assert by_subject.startswith("Alice: "), "who it is about — what you would type"


def test_a_group_with_no_subjects_gets_no_label_rather_than_its_name():
    """The setting said what to write; quietly writing something else is how
    bookkeeping words end up in prompts."""
    item = {"tag_groups": [{"name": "to check", "tags": ["hat"], "subjects": []}]}
    out = compose.group_tag_text(["hat"], item,
                                 {"group_tags": True, "group_label": "subject"},
                                 random.Random(0))
    assert out == "hat"


def test_several_subjects_are_all_named():
    item = {"tag_groups": [{"name": "", "tags": ["hat"],
                            "subjects": ["Alice", "Bob"]}]}
    out = compose.group_tag_text(["hat"], item,
                                 {"group_tags": True, "group_label": "subject"},
                                 random.Random(0))
    assert out == "Alice, Bob: hat"


def test_only_the_picked_tags_appear():
    """The random pick happens first; grouping only lays out what it chose."""
    out = compose.group_tag_text(
        ["dress"], _grouped_item(), {"group_tags": True, "group_label": "group"},
        random.Random(0))
    assert out == "Alice: dress"


def test_the_order_the_pick_produced_is_kept():
    """`used` is already shuffled when the run shuffles, so a subset of it stays
    shuffled — grouping must not quietly sort the tags."""
    item = {"tag_groups": [{"name": "A", "tags": ["one", "two", "three"]}]}
    out = compose.group_tag_text(["three", "one", "two"], item,
                                 {"group_tags": True}, random.Random(0))
    assert out == "three, one, two"


def test_ungrouped_tags_lead():
    out = compose.group_tag_text(["hat", "rain"], _grouped_item(),
                                 {"group_tags": True}, random.Random(0))
    assert out == "rain\nhat", "the scene, then the things inside it"


def test_a_tag_in_two_groups_is_written_once():
    """The same tag twice in a prompt teaches nothing and reads as emphasis."""
    item = {"tag_groups": [{"name": "A", "tags": ["shared"]},
                           {"name": "B", "tags": ["shared", "other"]}]}
    out = compose.group_tag_text(["shared", "other"], item,
                                 {"group_tags": True, "group_label": "group"},
                                 random.Random(0))
    assert out == "A: shared\nB: other"


def test_the_group_separator_is_the_user_s():
    out = compose.group_tag_text(
        ["blonde_hair", "hat"], _grouped_item(),
        {"group_tags": True, "group_separator": " | "}, random.Random(0))
    assert out == "blonde hair | hat"


def test_an_item_with_no_groups_reads_as_a_plain_list():
    out = compose.group_tag_text(["a", "b"], {"tags": ["a", "b"]},
                                 {"group_tags": True}, random.Random(0))
    assert out == "a, b"


def test_the_whole_prompt_keeps_its_trigger_and_grouping():
    cfg = {"source": "tags", "trigger": "mystyle", "group_tags": True,
           "group_label": "group", "separator": ", ", "shuffle": False}
    text, used = compose.compose_caption_and_tags(
        _grouped_item(), cfg, {}, random.Random(0))
    assert text.startswith("mystyle, ")
    assert "Alice: " in text and "\n" in text
    assert set(used) == {"rain", "blonde_hair", "dress", "hat"}


def test_grouping_off_is_the_flat_list_it_always_was():
    cfg = {"source": "tags", "separator": ", ", "shuffle": False}
    text, _ = compose.compose_caption_and_tags(
        _grouped_item(), cfg, {}, random.Random(0))
    assert "\n" not in text
    assert text == "rain, blonde hair, dress, hat"


def test_the_manifest_carries_tag_groups_only_when_asked(seeded_lib, tmp_path: Path):
    """Reading them is a second query over every selected item, and building a
    manifest is already the slow part of starting a run."""
    from media_compost.db import ItemTag, ItemTagGroup, ItemTagPlacement, Tag

    with seeded_lib.db.session() as s:
        it = s.query(Item).filter(Item.kind != "sequence").first()
        g = ItemTagGroup(item_id=it.id, name="Alice", position=0)
        s.add(g)
        s.flush()
        for row in s.query(ItemTag).filter(ItemTag.item_id == it.id).all():
            s.add(ItemTagPlacement(item_tag_id=row.id, group_id=g.id))
        s.commit()
        item_id = it.id

    everything = [DatasetQuery(tree=None, weight=1.0)]
    off = TrainingConfig(model="sd15", queries=everything)
    m = _manifest(seeded_lib, off.model_dump(mode="json"), tmp_path / "off")
    assert all("tag_groups" not in e for e in m["items"])

    on = TrainingConfig(model="sd15", queries=everything)
    on.captions.group_tags = True
    m = _manifest(seeded_lib, on.model_dump(mode="json"), tmp_path / "on")
    entry = next(e for e in m["items"] if e["item_id"] == item_id)
    assert entry["tag_groups"], "the group the tags were placed in"
    assert entry["tag_groups"][0]["name"] == "Alice"
    assert set(entry["tag_groups"][0]["tags"]) <= set(entry["tags"])


def test_the_manifest_carries_who_each_group_is_about(seeded_lib, tmp_path: Path):
    """The 'subject' label option reads these; without them it would silently
    write nothing for every group."""
    from media_compost.db import (ItemTag, ItemTagGroup, ItemTagGroupSubject,
                                  ItemTagPlacement, Subject)

    with seeded_lib.db.session() as s:
        it = s.query(Item).filter(Item.kind != "sequence").first()
        g = ItemTagGroup(item_id=it.id, name="front figure", position=0)
        sub = Subject(display_name="Alice")
        s.add_all([g, sub])
        s.flush()
        s.add(ItemTagGroupSubject(group_id=g.id, subject_id=sub.id))
        for row in s.query(ItemTag).filter(ItemTag.item_id == it.id).all():
            s.add(ItemTagPlacement(item_tag_id=row.id, group_id=g.id))
        s.commit()
        item_id = it.id

    cfg = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None, weight=1.0)])
    cfg.captions.group_tags = True
    m = _manifest(seeded_lib, cfg.model_dump(mode="json"), tmp_path / "j")
    entry = next(e for e in m["items"] if e["item_id"] == item_id)
    assert entry["tag_groups"][0]["subjects"] == ["Alice"]


def test_a_subjects_tag_takes_its_boxes_from_the_faces(seeded_lib, tmp_path: Path):
    """A detected face already answers "where in this picture is Alice", so the
    subject's tag trains on those boxes rather than asking for the same
    rectangle to be drawn a second time. A tag that HAS a drawn box keeps it —
    a hand-drawn one says something a face box does not."""
    from media_compost.db import Face, File, ItemSubject, Subject

    with seeded_lib.db.session() as s:
        items = s.query(Item).order_by(Item.id).all()
        alice_tag = Tag(name="alice")
        s.add(alice_tag)
        s.flush()
        alice = Subject(display_name="Alice", tag_id=alice_tag.id)
        s.add(alice)
        s.flush()
        # Alice is on both items; the first also carries the drawn `dog` box.
        for it in items:
            s.add(ItemTag(item_id=it.id, tag_id=alice_tag.id))
        s.flush()
        # Two faces on the first item, one on the second.
        faces = [
            Face(item_id=items[0].id, file_id=items[0].active_file_id,
                 x=0.1, y=0.1, w=0.2, h=0.2),
            Face(item_id=items[0].id, file_id=items[0].active_file_id,
                 x=0.6, y=0.1, w=0.2, h=0.2),
            # Dismissed: not evidence of anything, so not a box either.
            Face(item_id=items[1].id, file_id=items[1].active_file_id,
                 x=0.4, y=0.4, w=0.1, h=0.1, dismissed=True),
        ]
        s.add_all(faces)
        s.flush()
        for f in faces:
            s.add(ItemSubject(item_id=f.item_id, subject_id=alice.id,
                              face_id=f.id))
        s.commit()
        first_id, second_id = items[0].id, items[1].id

    jd = tmp_path / "job"
    jd.mkdir()
    cfg = TrainingConfig(model="sd15",
                        queries=[DatasetQuery(tree=None, weight=1.0)])
    m = _manifest(seeded_lib, cfg.model_dump(mode="json"), jd)
    by_path = {e["path"]: e for e in m["items"]}
    with seeded_lib.db.session() as s:
        paths = {i: str(seeded_lib.store.path_of(s, s.get(File, s.get(Item, i).active_file_id)))
                 for i in (first_id, second_id)}

    first = by_path[paths[first_id]]
    # Both of Alice's faces became her boxes — one face must not veto the next.
    assert sorted(first["boxes"]["alice"]) == [[0.1, 0.1, 0.2, 0.2],
                                               [0.6, 0.1, 0.2, 0.2]]
    # The drawn box on another tag is untouched.
    assert first["boxes"]["dog"] == [[0.25, 0.25, 0.5, 0.5]]
    # A dismissed face contributes nothing.
    assert "alice" not in by_path[paths[second_id]].get("boxes", {})


def test_a_drawn_box_beats_the_faces(seeded_lib, tmp_path: Path):
    """The fallback is only a fallback: a subject tag with a box of its own
    keeps it, because a hand-drawn rectangle may mean the whole person."""
    from media_compost.db import Face, File, ItemSubject, Subject

    with seeded_lib.db.session() as s:
        item = s.query(Item).order_by(Item.id).first()
        tag = Tag(name="bob")
        s.add(tag)
        s.flush()
        bob = Subject(display_name="Bob", tag_id=tag.id)
        s.add(bob)
        s.flush()
        it = ItemTag(item_id=item.id, tag_id=tag.id)
        s.add(it)
        s.flush()
        pl = ItemTagPlacement(item_tag_id=it.id, group_id=None)
        s.add(pl)
        s.flush()
        s.add(ItemTagBox(placement_id=pl.id, x=0.0, y=0.0, w=1.0, h=1.0))
        face = Face(item_id=item.id, file_id=item.active_file_id,
                    x=0.1, y=0.1, w=0.2, h=0.2)
        s.add(face)
        s.flush()
        s.add(ItemSubject(item_id=item.id, subject_id=bob.id, face_id=face.id))
        s.commit()
        path = str(seeded_lib.store.path_of(s, s.get(File, item.active_file_id)))

    jd = tmp_path / "job"
    jd.mkdir()
    cfg = TrainingConfig(model="sd15",
                        queries=[DatasetQuery(tree=None, weight=1.0)])
    m = _manifest(seeded_lib, cfg.model_dump(mode="json"), jd)
    entry = next(e for e in m["items"] if e["path"] == path)
    assert entry["boxes"]["bob"] == [[0.0, 0.0, 1.0, 1.0]]


# ---- instructions ----------------------------------------------------------
#
# An INSTRUCTION is a caption of the other kind: it says how the picture was
# made from the items it references, and an edit model trains on the pair. The
# whole point of the two kinds is that a run trains on ONE of them, so most of
# what is pinned here is what each run does NOT see.


def _instruction(s, item_id: int, text: str, refs: list[int]) -> None:
    """An instruction with its ordered references, as the endpoints write it."""
    from media_compost.db import Caption, CaptionRef

    c = Caption(item_id=item_id, text=text, position=0, kind="instruction")
    s.add(c)
    s.flush()
    for pos, riid in enumerate(refs):
        s.add(CaptionRef(caption_id=c.id, item_id=riid, position=pos))


def _instruction_cfg(**caps):
    return TrainingConfig(
        model="flux2_klein", queries=[DatasetQuery(tree=None)],
        captions=CaptionConfig(source="instructions", **caps))


def test_a_caption_run_and_an_instruction_run_see_different_text(
        seeded_lib, tmp_path: Path):
    from media_compost.db import Item

    with seeded_lib.db.session() as s:
        ids = [i.id for i in s.query(Item).all()]
        target, source = ids[0], ids[1]
        _caption(s, target, "a red car")
        _instruction(s, target, "make it snow", [source])
        s.commit()

    caps = _manifest(
        seeded_lib,
        TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                       captions=CaptionConfig(source="both")
                       ).model_dump(mode="json"),
        tmp_path / "jcap")
    entry = next(e for e in caps["items"] if e["item_id"] == target)
    assert entry["captions"] == ["a red car"]
    assert "instructions" not in entry     # conditional, like boxes/tag_groups

    ins = _manifest(seeded_lib, _instruction_cfg().model_dump(mode="json"),
                         tmp_path / "jins")
    # ONLY the target is in the run: nothing else carries an instruction.
    assert [e["item_id"] for e in ins["items"]] == [target]
    entry = ins["items"][0]
    assert entry["captions"] == []
    assert [i["text"] for i in entry["instructions"]] == ["make it snow"]
    assert [r["item_id"] for r in entry["instructions"][0]["refs"]] == [source]


def test_a_caption_nobody_gave_a_kind_is_a_description(
        seeded_lib, tmp_path: Path):
    """A writer that says nothing about the kind writes a DESCRIPTION.

    That is the invariant the readers lean on: every one of them takes an
    absent kind as "caption", and the column's own default is what makes a
    caption written by any path — the endpoints, the importer, a script,
    `copy_item_associations` — land in the list it belongs in rather than
    quietly out of every training run.
    """
    from media_compost.db import Caption, Item

    with seeded_lib.db.session() as s:
        item = s.query(Item).all()[0].id
        # Deliberately NOT passing kind, the way `_caption` and every other
        # existing writer in this file does.
        s.add(Caption(item_id=item, text="said nothing about its kind",
                      position=0))
        s.commit()
        assert s.query(Caption).all()[0].kind == "caption"

    m = _manifest(
        seeded_lib,
        TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                       captions=CaptionConfig(source="captions")
                       ).model_dump(mode="json"),
        tmp_path / "jold")
    entry = next(e for e in m["items"] if e["item_id"] == item)
    assert entry["captions"] == ["said nothing about its kind"]


def test_an_instruction_with_a_lost_reference_is_dropped_whole(
        seeded_lib, tmp_path: Path):
    """How many references there are and what order they are in IS the training
    signal, so a two-reference edit must never quietly become a one-reference
    one — the instruction goes, not one of its references."""
    from media_compost.db import Item

    with seeded_lib.db.session() as s:
        ids = [i.id for i in s.query(Item).all()]
        target, keep = ids[0], ids[1]
        # A reference whose item has no picture to show — one of the ways a
        # reference stops resolving.
        ghost = Item(name="gone.png", kind="image")
        s.add(ghost)
        s.flush()
        _instruction(s, target, "combine these", [keep, ghost.id])
        s.commit()

    # Both references would be needed, so the run has nothing left to train on.
    with pytest.raises(ValueError, match="carries an instruction"):
        _manifest(seeded_lib, _instruction_cfg().model_dump(mode="json"),
                       tmp_path / "jgone")


def test_an_item_with_no_instruction_leaves_the_pools_pointing_right(
        seeded_lib, tmp_path: Path):
    """The skip has to happen BEFORE the entry index is assigned, or a query
    pool points at the next item's entry and the whole dataset is mis-weighted."""
    from media_compost.db import Item

    with seeded_lib.db.session() as s:
        ids = sorted(i.id for i in s.query(Item).all())
        # The FIRST selected item is the one with nothing, so a stale index
        # would be off by one for everything after it.
        _instruction(s, ids[-1], "make it snow", [ids[0]])
        s.commit()

    m = _manifest(seeded_lib, _instruction_cfg().model_dump(mode="json"),
                       tmp_path / "jskip")
    assert [e["item_id"] for e in m["items"]] == [ids[-1]]
    assert m["groups"][0]["items"] == [0]


def test_only_the_edit_models_are_marked_as_such():
    """The flag is what lets the editor offer an instruction run at all, and
    training one on a model that cannot take a reference picture is refused."""
    from media_compost.train.models import REGISTRY, registry_entry

    assert {m.key for m in REGISTRY if m.edit} == {
        "flux1_kontext", "flux2_klein", "flux2_klein_9b",
        "qwen_image_edit", "qwen_image_edit_2509", "qwen_image_edit_2511"}
    # And the editor is told, or it can never offer the option.
    assert registry_entry(
        next(m for m in REGISTRY if m.key == "flux2_klein"))["edit"] is True

    # A checkpoint that exists FOR editing is a subset — the flag decides
    # which caption source the editor starts on. FLUX.2 Klein is a generator
    # that also takes references, so it is deliberately not in it: starting
    # that on instructions would be the wrong default for the thing people
    # mostly train it for.
    assert {m.key for m in REGISTRY if m.edit_only} == {
        "flux1_kontext",
        "qwen_image_edit", "qwen_image_edit_2509", "qwen_image_edit_2511"}
    assert all(m.edit for m in REGISTRY if m.edit_only)
    assert registry_entry(
        next(m for m in REGISTRY if m.key == "qwen_image_edit"))["edit_only"]


def test_a_reference_keeps_its_aspect_at_the_target_s_budget():
    """`ref_size` is what decides how big a reference picture is encoded, and
    both halves of it matter: the aspect is the REFERENCE's (squashing it to
    the result's shape is a distortion the model would have to undo) and the
    area is the TARGET's, so a reference costs about what the picture being
    produced costs."""
    # Square target, square reference: exactly the target's size.
    assert compose.ref_size(512, 512, 1024 * 1024, 16) == (1024, 1024)
    # A wide reference keeps its shape, at the same budget — to within the
    # rounding, which is per axis and so costs up to half a step each way.
    w, h = compose.ref_size(2000, 1000, 1024 * 1024, 16)
    assert 1.95 < w / h < 2.05 and 0.9 < (w * h) / (1024 * 1024) < 1.1
    # Rounded to the model's step, both axes, always at least one step.
    for step in (8, 16):
        for rw, rh in ((1000, 500), (37, 9001), (3, 3)):
            got = compose.ref_size(rw, rh, 640 * 640, step)
            assert all(v % step == 0 and v >= step for v in got), (step, got)


def test_reference_layouts_group_what_can_share_one_forward_pass():
    """Two visits can be run together only if their reference tokens line up:
    same count, same shapes. `loop._forward` groups on exactly this."""
    a = {"width": 512, "height": 512}
    b = {"width": 1000, "height": 500}
    budget, step = 1024 * 1024, 16
    assert (compose.ref_layout([a], budget, step)
            == compose.ref_layout([{"width": 256, "height": 256}], budget, step))
    assert (compose.ref_layout([a], budget, step)
            != compose.ref_layout([a, a], budget, step))
    assert (compose.ref_layout([a], budget, step)
            != compose.ref_layout([b], budget, step))
    # ORDER counts: two references of different shapes are a different input
    # sequence the other way round.
    assert (compose.ref_layout([a, b], budget, step)
            != compose.ref_layout([b, a], budget, step))
    assert compose.ref_layout([], budget, step) == ()


def test_every_edit_model_has_an_engine_that_takes_references():
    """`edit=True` is a promise the ENGINE has to keep.

    The flag lets the editor offer an instruction run, and the loop then calls
    `train_step(..., refs=[...])`. An engine whose `train_step` does not take
    that argument fails with a TypeError minutes into a run — and one that
    takes it and ignores it is worse, because it trains the model to produce
    the target from the prompt alone and the loss curve looks normal.
    """
    import ast

    from media_compost.train.manager import TRAIN_SCRIPTS
    from media_compost.train.models import REGISTRY

    for spec in {m.engine: m for m in REGISTRY if m.edit}.values():
        path = TRAIN_SCRIPTS / "engines" / f"{spec.engine}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        step = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "train_step")
        args = [a.arg for a in step.args.args] + \
               [a.arg for a in step.args.kwonlyargs]
        assert "refs" in args, (
            f"{spec.engine}.py: train_step takes no `refs`, but "
            f"{spec.key} is marked as an editing model")
        # …and reads it at least once. A parameter added to silence the check
        # above and then dropped is the silent half of this failure; that it
        # is used CORRECTLY is what the tiny-model smoke runs are for.
        used = sum(1 for n in ast.walk(step)
                   if isinstance(n, ast.Name) and n.id == "refs")
        assert used, f"{spec.engine}.py: train_step ignores `refs`"


def test_an_instruction_run_is_refused_on_a_model_that_cannot_edit():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="cannot train on instructions"):
        TrainingConfig(model="sdxl", queries=[DatasetQuery(tree=None)],
                       captions=CaptionConfig(source="instructions"))
    # And the one that can is accepted.
    TrainingConfig(model="flux2_klein", queries=[DatasetQuery(tree=None)],
                   captions=CaptionConfig(source="instructions"))


# ---- user models live in files now -------------------------------------------


def _client_lib(tmp_path: Path):
    """A TestClient over a library of our own, so the training routes see it."""
    from fastapi.testclient import TestClient

    from media_compost.ui.server.app import app
    from media_compost.ui.server.deps import get_library

    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    app.dependency_overrides[get_library] = lambda: lib
    try:
        yield TestClient(app), lib
    finally:
        app.dependency_overrides.pop(get_library, None)


@pytest.fixture
def models_client(tmp_path: Path):
    """A client AND its library — these tests read the files the routes
    wrote, so they need to know where the library is. Deliberately not the
    `train_client` above, which stands up a whole fake-trainer world."""
    yield from _client_lib(tmp_path)


def test_a_user_model_round_trips_through_a_file(models_client):
    """The list moved out of the `settings` table, which was the single thing
    keeping the training subsystem attached to a database."""
    from media_compost.train import usermodels

    client, lib = models_client
    got = client.post("/api/train/models", json={
        "label": "My SDXL", "base": "sdxl", "repo": "someone/my-sdxl",
        "local": False, "area": 768})
    assert got.status_code == 200
    keys = [m["key"] for m in got.json()["models"] if m.get("user")]
    assert keys == ["user:my-sdxl"]

    store = training_dir(lib.config.data_dir)
    assert (store / usermodels.MODELS_FILE).is_file()
    assert [m.label for m in usermodels.read(store)] == ["My SDXL"]

    client.delete("/api/train/models/user:my-sdxl")
    assert usermodels.read(store) == []


def test_the_cli_can_create_a_job_on_a_user_added_model(tmp_path: Path,
                                                        monkeypatch):
    """`models.model_spec` answers from a module cache that
    `usermodels.refresh` fills, and the web side fills it from the
    `user_store` dependency on every request that touches models. The CLI had
    no equivalent, so a config naming a user model was rejected at validation
    with "unknown model 'user:tiny'" — the one place a headless box with a GPU
    is supposed to be able to start a run from.
    """
    from media_compost.train import cli, usermodels

    data = tmp_path / "lib"
    store = training_dir(data)
    store.mkdir(parents=True)
    usermodels.write(store, [usermodels.UserModel(
        key="user:tiny", label="Tiny", base="sd15",
        repo="someone/tiny", local=False, area=64)])
    # The cache starts EMPTY, which is the state a fresh process is in — the
    # bug is invisible in a test that has already published them.
    from media_compost.train.models import set_user_specs
    set_user_specs({})

    cfg = TrainingConfig().model_dump()
    cfg["model"] = "user:tiny"
    cfg["queries"] = [{"tree": None, "search": "", "weight": 1.0}]
    path = tmp_path / "job.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    uid_printed: list[str] = []
    monkeypatch.setattr(cli.console, "print",
                        lambda *a, **k: uid_printed.append(str(a[0]) if a else ""))
    rc = cli.main(["create", str(path), "-n", "cli job", "-d", str(data)])
    assert rc == 0, uid_printed
    assert uid_printed and len(uid_printed[0]) == 16, uid_printed


def test_an_added_model_is_EDITABLE_and_keeps_its_key(models_client):
    """A key is an identity, a label is what a thing is called.

    Every job configured with this model stores `user:<slug>`, so re-deriving
    the slug from a corrected name would strand all of them on a model that no
    longer exists.
    """
    client, lib = models_client
    made = client.post("/api/train/models", json={
        "label": "My SDXL", "base": "sdxl", "repo": "someone/my-sdxl",
        "local": False, "area": 768}).json()["models"]
    key = [m["key"] for m in made if m.get("user")][0]

    got = client.patch(f"/api/train/models/{key}", json={
        "label": "My better SDXL", "base": "sdxl",
        "repo": "someone/my-better-sdxl", "local": False, "area": 1024})
    assert got.status_code == 200, got.text
    mine = [m for m in got.json()["models"] if m.get("user")]
    assert len(mine) == 1
    assert mine[0]["key"] == key
    assert mine[0]["label"] == "My better SDXL"
    assert mine[0]["repo"] == "someone/my-better-sdxl"
    assert mine[0]["default_area"] == 1024

    # And the refusals the add form has.
    assert client.patch(f"/api/train/models/{key}", json={
        "label": "x", "base": "no-such-arch", "repo": "a/b",
        "local": False}).status_code == 400
    assert client.patch("/api/train/models/user:nobody", json={
        "label": "x", "base": "sdxl", "repo": "a/b",
        "local": False}).status_code == 404


def test_an_added_LORA_is_editable(models_client, tmp_path: Path):
    client, lib = models_client
    one = tmp_path / "one.safetensors"
    two = tmp_path / "two.safetensors"
    one.write_bytes(b"x")
    two.write_bytes(b"y")
    made = client.post("/api/train/user-loras", json={
        "label": "Mine", "base": "sd15", "repo": str(one),
        "local": True}).json()["models"]
    key = made[0]["key"]
    got = client.patch(f"/api/train/user-loras/{key}", json={
        "label": "Mine, renamed", "base": "sdxl", "repo": str(two),
        "local": True})
    assert got.status_code == 200, got.text
    assert got.json()["models"] == [{
        "key": key, "label": "Mine, renamed", "model": "sdxl",
        "path": str(two), "exists": True}]


def test_a_fresh_library_migrates_nothing(models_client):
    from media_compost.train import usermodels

    client, lib = models_client
    # The endpoint lists the USER's models; a fresh library has none.
    assert client.get("/api/train/models").json()["models"] == []
    store = training_dir(lib.config.data_dir)
    assert not (store / usermodels.MODELS_FILE).exists()
    assert not (store / usermodels.LORAS_FILE).exists()
    assert usermodels.read(store) == [] and usermodels.read_loras(store) == []


# ---- the model-cache paths call the hub cache by repo id ---------------------
#
# Both of these migrated off the plugin `ModelSource` API onto
# `media_compost.hub.cache`, whose functions take bare repo ids — and for one
# round each imported the new name while still CALLING the old one. Neither
# failure was visible from the code that had it: the delete route raised
# NameError into a 500 only when actually called, and `_repo_cached`'s blanket
# except swallowed its NameError into a permanent `cached: False`.


def test_deleting_a_base_models_cache_calls_the_hub_by_repo_id(
        models_client, monkeypatch):
    from media_compost.hub import cache as hub_cache

    client, _lib = models_client
    deleted: list[str] = []
    monkeypatch.setattr(hub_cache, "delete_repo",
                        lambda repo: deleted.append(repo) or True)

    client.post("/api/train/models", json={
        "label": "My SDXL", "base": "sdxl", "repo": "someone/my-sdxl"})
    got = client.delete("/api/train/models/user:my-sdxl/cache")
    assert got.status_code == 200 and got.json() == {"ok": True}
    assert deleted == ["someone/my-sdxl"]


def test_a_user_models_cached_flag_reads_the_hub_cache(
        models_client, monkeypatch):
    """A user-added Hugging Face model whose repo IS in the cache must say so —
    the broken probe answered False for every one, whatever was on disk."""
    from media_compost.hub import cache as hub_cache

    client, _lib = models_client
    asked: list[tuple[str, str]] = []

    def fake_repo_cached(repo, probe=hub_cache.DEFAULT_PROBE, local_path=""):
        asked.append((repo, probe))
        return repo == "someone/my-sdxl"

    monkeypatch.setattr(hub_cache, "repo_cached", fake_repo_cached)

    client.post("/api/train/models", json={
        "label": "My SDXL", "base": "sdxl", "repo": "someone/my-sdxl"})
    entries = client.get("/api/train/models").json()["models"]
    mine = [e for e in entries if e["key"] == "user:my-sdxl"]
    assert mine and mine[0]["cached"] is True
    # Probed by the diffusers pipeline manifest, which every one of these
    # repos has at its root (the default probe is a per-component file).
    assert ("someone/my-sdxl", "model_index.json") in asked


# ---- writing a tag as its comment ---------------------------------------------
#
# `captions.tag_text` writes a picked tag as its COMMENT (the one-liner in the
# tags list) or as the name with the comment after it. OUTPUT-ONLY, like the
# alias substitution: the returned list stays the names.


def _comment_cfg(**over) -> dict:
    cfg = {"source": "tags", "shuffle": False, "underscores_to_spaces": True,
           "tag_comments": {"1girl": "one girl in the picture"}}
    cfg.update(over)
    return cfg


def test_a_comment_replaces_the_name_or_rides_beside_it_and_never_reaches_the_list():
    item = {"tags": ["1girl", "red_hair"], "captions": []}
    text, used = compose.compose_caption_and_tags(
        item, _comment_cfg(tag_text="comment"), {}, random.Random(1))
    assert text == "one girl in the picture, red hair"
    assert used == ["1girl", "red_hair"], "the returned names stay names"
    text, _ = compose.compose_caption_and_tags(
        item, _comment_cfg(tag_text="both"), {}, random.Random(1))
    assert text == "1girl (one girl in the picture), red hair"


def test_writing_names_never_reads_the_comments():
    """The default is bit-identical to what ran before the setting existed,
    a map in the config or not."""
    item = {"tags": ["1girl", "red_hair"], "captions": []}
    with_map = compose.compose_caption_and_tags(
        item, _comment_cfg(tag_text="name"), {}, random.Random(3))
    without = compose.compose_caption_and_tags(
        item, _comment_cfg(tag_text="name", tag_comments={}), {}, random.Random(3))
    assert with_map == without == ("1girl, red hair", ["1girl", "red_hair"])


# ---- writing a tag as one of its aliases -------------------------------------
#
# A library's aliases are the other words for one thing ("cat" / "kitty"), and
# a model trained only on the canonical name answers only to that word. The
# substitution is OUTPUT-ONLY, which is the whole of what these pin.


def _alias_cfg(**over) -> dict:
    cfg = {"source": "tags", "alias_p": 1.0, "shuffle": False,
           "underscores_to_spaces": False}
    cfg.update(over)
    return cfg


def test_an_alias_never_reaches_the_returned_tag_list():
    """The list drives box-aware cropping and the inverse-frequency loss
    weight, both keyed on the canonical name. An alias has no box and no
    `tag_freq` entry, so it would crop nothing and read as maximally rare —
    the same reason a degraded entry's `force_tags` stay out of it."""
    item = {"tags": ["cat", "hat"], "captions": []}
    aliases = {"cat": ["kitty", "feline"]}
    text, used = compose.compose_caption_and_tags(
        item, _alias_cfg(), {}, random.Random(1), aliases)
    assert used == ["cat", "hat"], "the returned names stay canonical"
    assert "cat" not in text and "kitty" in text or "feline" in text


def test_a_tag_with_no_alias_is_written_as_itself():
    item = {"tags": ["cat", "hat"], "captions": []}
    text, _ = compose.compose_caption_and_tags(
        item, _alias_cfg(), {}, random.Random(1), {"cat": ["kitty"]})
    assert "hat" in text


def test_zero_probability_is_the_run_that_never_asked():
    """The default, and it must be bit-identical to what ran before aliases
    existed — no substitution AND no extra draw from the rng."""
    item = {"tags": ["cat", "hat"], "captions": []}
    aliases = {"cat": ["kitty", "feline"]}
    with_map = compose.compose_caption_and_tags(
        item, _alias_cfg(alias_p=0.0), {}, random.Random(7), aliases)
    without = compose.compose_caption_and_tags(
        item, _alias_cfg(alias_p=0.0), {}, random.Random(7), None)
    assert with_map == without == ("cat, hat", ["cat", "hat"])


def test_the_roll_is_per_tag_per_visit():
    """Not one alias per tag chosen once: the point is to spread the whole
    tag set across the run, so the same item drawn twice can read
    differently and two tags in one prompt are drawn independently."""
    item = {"tags": ["cat", "dog"], "captions": []}
    aliases = {"cat": ["kitty", "feline"], "dog": ["pup", "hound"]}
    seen = {compose.compose_caption_and_tags(
        item, _alias_cfg(), {}, random.Random(s), aliases)[0]
        for s in range(30)}
    assert len(seen) > 2, f"expected a spread of prompts, got {seen}"


def test_half_probability_leaves_the_canonical_name_in_play():
    item = {"tags": ["cat"], "captions": []}
    aliases = {"cat": ["kitty"]}
    got = {compose.compose_caption_and_tags(
        item, _alias_cfg(alias_p=0.5), {}, random.Random(s), aliases)[0]
        for s in range(40)}
    assert got == {"cat", "kitty"}


def test_grouped_prompts_take_aliases_too():
    """`group_tags` formats through its own path; without the writer threaded
    into it, turning grouping on would silently switch aliases off."""
    item = {"tags": ["cat"], "captions": [],
            "tag_groups": [{"tags": ["cat"], "meta_tags": [], "subjects": []}]}
    text, used = compose.compose_caption_and_tags(
        item, _alias_cfg(group_tags=True), {}, random.Random(1), {"cat": ["kitty"]})
    assert "kitty" in text and used == ["cat"]


# ---- where a tag's rarity is measured ----------------------------------------


def _freq_library(tmp_path, freq_base: str) -> dict:
    """`_tag_freq` over a two-picture library where one tag has an offset."""
    from media_compost import open_library
    from media_compost.testing import make_image
    from media_compost.train.dataset import build_manifest
    from media_compost.train.spec import (BucketConfig, DatasetQuery,
                                          TrainingConfig)

    data = tmp_path / f"lib-{freq_base}"
    data.mkdir()
    srcs = tmp_path / f"src-{freq_base}"
    srcs.mkdir()
    with open_library(data, source="cli") as lib:
        for i in (1, 2):
            lib.import_file(make_image(srcs / f"{i}.png", i, (64, 64)))
        for it in lib.query(""):
            it.tags.add("cat")
        # Two sites' figures — the highest is what freq_base reads, not
        # the sum: they count overlapping pictures.
        lib.tags["cat"].set_meta_tag_count("tumblr", 4000)
        lib.tags["cat"].set_meta_tag_count("twitter", 300)

    cfg = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                         buckets=BucketConfig(skip_upscale=False))
    cfg.captions.freq_base = freq_base
    job = tmp_path / f"job-{freq_base}"
    with open_library(data, source="cli") as lib:
        return build_manifest(lib, cfg.model_dump(mode="json"), job)["tag_freq"]


def test_the_count_offset_reaches_no_frequency_at_all(tmp_path):
    """The per-meta counts are the pictures a tag has where this library is
    not, and NOTHING adds them to a count — not one the app shows, and no
    longer a training frequency either. `freq_base = "library_offset"` was
    the one place they were read; it went with the tag-level offset it was
    named after."""
    assert _freq_library(tmp_path, "dataset")["cat"] == 2
    assert _freq_library(tmp_path, "library")["cat"] == 2, \
        "the library count must not gain the offset"

    from media_compost.train.spec import CaptionConfig
    import pytest as _pytest
    for gone in ("library_offset", "nonsense"):
        with _pytest.raises(Exception):
            CaptionConfig(freq_base=gone)


def test_start_now_can_preempt_the_job_holding_the_device(sim_mgr):
    """The job row's Start: run THIS one, now.

    Plain `start_now` refuses a busy device — that one the user can pause
    themselves. The row's button says the user already decided: the running
    job is paused, this one goes to the front, and the queue is left ON so the
    rest follows rather than the machine stopping after this single job.

    The ordering is the whole risk. A hand pause re-queues the paused job at
    the FRONT (it is what you want to come back to), so it and the job that
    displaced it both claim the front — and the tick's `_start_explicit`
    running before `_maybe_start` is what settles it in favour of the explicit
    one.
    """
    holding = sim_mgr.create("holding", _cfg(steps=800), "t")
    wanted = sim_mgr.create("wanted", _cfg(steps=20), "t")
    sim_mgr.start_now(holding)
    _wait(sim_mgr, holding, ("running",))

    # Without preempt this is refused, and says which job to pause.
    with pytest.raises(TrainingConflict):
        sim_mgr.start_now(wanted)

    sim_mgr.start_now(wanted, preempt=True, run_queue=True)
    rec = _wait(sim_mgr, wanted, ("completed",), timeout=90)
    assert rec["status"] == "completed", "the preempting job ran"
    # The one it displaced kept its work and is waiting, not lost or failed.
    assert sim_mgr.get(holding)["status"] in ("queued", "running", "paused")
    assert sim_mgr.queue_active(), "the queue was asked to keep going"
    for u in (holding, wanted):
        if sim_mgr.get(u)["status"] in ("running", "queued"):
            sim_mgr.cancel(u)


def test_start_now_puts_the_job_at_the_front_of_the_queue(sim_mgr):
    """"Start" says where the job goes as well as that it runs: at the front,
    so the answer survives a restart that loses the in-memory explicit-start
    set — the queue would then reach it first anyway."""
    first = sim_mgr.create("first", _cfg(steps=800), "t")
    second = sim_mgr.create("second", _cfg(steps=800), "t")
    third = sim_mgr.create("third", _cfg(steps=800), "t")
    for u in (first, second, third):
        sim_mgr.enqueue(u)
    sim_mgr.start_now(third, preempt=True, run_queue=True)
    order = sorted((j for j in sim_mgr.list_jobs() if j["status"] in ("queued", "running")),
                   key=lambda j: j["queued_at"])
    assert order[0]["uid"] == third, [j["name"] for j in order]
    for u in (first, second, third):
        if sim_mgr.get(u)["status"] in ("running", "queued", "pausing"):
            sim_mgr.cancel(u)


def test_a_new_job_never_takes_a_name_another_job_already_has(sim_mgr):
    """A uid is the identity, so names may repeat — and three rows called
    "Untitled training" is a sidebar you cannot pick from. The case that
    prompted it is Save as duplicate, which reuses the name exactly."""
    first = sim_mgr.create("style", _cfg(steps=5), "t")
    second = sim_mgr.create("style", _cfg(steps=5), "t")
    third = sim_mgr.create("style", _cfg(steps=5), "t")
    names = [sim_mgr.get(u)["name"] for u in (first, second, third)]
    assert names == ["style", "style 2", "style 3"], names

    # It counts past a gap rather than reusing a freed number blindly.
    sim_mgr.delete(second)
    assert sim_mgr.get(sim_mgr.create("style", _cfg(steps=5), "t"))["name"] == "style 2"
    # An unrelated name is untouched.
    assert sim_mgr.get(sim_mgr.create("other", _cfg(steps=5), "t"))["name"] == "other"


# ---- the sampler: shuffled passes, and where a weight is spent ---------------


def _sampler(pools, sizes, mode="sampling", seed=0, buckets=None):
    """A sampler over `sizes` entries per pool, weighted by `pools`."""
    n = sum(sizes)
    items = [{"bucket": (buckets[i] if buckets else 0)} for i in range(n)]
    groups, at = [], 0
    for w, size in zip(pools, sizes):
        groups.append({"weight": w, "items": list(range(at, at + size))})
        at += size
    return compose.Sampler(items, groups, random.Random(seed), weight_mode=mode), items


def test_a_pass_visits_every_entry_exactly_once():
    """What makes "epoch" a word worth using. Weighted draws WITH replacement
    could show a picture twice in one batch and not at all in the next pass,
    and "how many times has the model seen this" had no answer."""
    s, items = _sampler([1.0], [11])
    seen = collections.Counter()
    for _ in range(s.batches_per_epoch(2)):
        seen.update(s.batch(2)[1])
    assert sorted(seen.values()) == [1] * 11, seen


def test_a_batch_never_mixes_buckets():
    """The sizes have to match, so a pass is a shuffle WITHIN each bucket."""
    s, items = _sampler([1.0], [12], buckets=[0, 1] * 6)
    for _ in range(s.batches_per_epoch(3)):
        b, idx = s.batch(3)
        assert {items[i]["bucket"] for i in idx} == {b}


def test_a_short_bucket_still_trains():
    """The convention is to drop the remainder of a pass. With bucketed data
    that silently means a bucket holding fewer entries than one batch never
    trains AT ALL — so the tail is kept as a short batch instead."""
    s, items = _sampler([1.0], [5], buckets=[0, 0, 0, 0, 1])  # bucket 1 has one
    seen = collections.Counter()
    for _ in range(s.batches_per_epoch(4)):
        seen.update(s.batch(4)[1])
    assert seen[4] == 1, "the lone entry of its bucket was visited"


def test_sampling_mode_spends_a_weight_on_visits():
    """A weight-2 query's pictures are seen twice as often. The fraction is a
    coin flip per pass, so the RATIO holds over a run while a pass stays a
    pass — nothing appears 1.6 times in one of them."""
    s, _ = _sampler([2.0, 1.0], [6, 6], mode="sampling", seed=3)
    c = collections.Counter()
    for _ in range(600):
        c.update(s.batch(2)[1])
    heavy = sum(c[i] for i in range(6)) / 6
    light = sum(c[i] for i in range(6, 12)) / 6
    assert 1.8 < heavy / light < 2.2, (heavy, light)
    assert s.loss_scale(0) == 1.0, "visits are the lever; the loss is untouched"


def test_loss_mode_spends_it_on_the_gradient_instead():
    """Equal exposure, unequal influence: every picture is seen once a pass
    and a weighted one counts for more. The same ratio, bought with the same
    compute for every picture."""
    s, _ = _sampler([2.0, 1.0], [6, 6], mode="loss", seed=3)
    c = collections.Counter()
    for _ in range(600):
        c.update(s.batch(2)[1])
    heavy = sum(c[i] for i in range(6)) / 6
    light = sum(c[i] for i in range(6, 12)) / 6
    assert 0.9 < heavy / light < 1.1, ("exposure is equal", heavy, light)
    assert abs(s.loss_scale(0) / s.loss_scale(6) - 2.0) < 1e-9


def test_the_mean_entry_weighs_one_so_a_pass_stays_one_pass():
    """Both modes normalise the same way. Without it a heavily weighted query
    would make an "epoch" several passes long, and the word would stop
    meaning anything."""
    s, _ = _sampler([5.0, 1.0], [4, 4], mode="sampling")
    assert abs(sum(s.scale) - 8) < 1e-9, s.scale
    # 8 entries at batch 4, one bucket: two batches, however they are weighted.
    assert s.batches_per_epoch(4) == 2


# ---- an item with several captions -------------------------------------------


def _caption_lib(tmp_path, counts: list[int]):
    """A library whose i-th item carries `counts[i]` captions."""
    from media_compost import open_library
    from media_compost.testing import make_image

    data = tmp_path / "caplib"
    srcs = tmp_path / "capsrc"
    srcs.mkdir()
    with open_library(data, source="cli") as lib:
        for i, n in enumerate(counts):
            lib.import_file(make_image(srcs / f"{i}.png", i + 1, (64, 64)))
        for item, n in zip(sorted(lib.query(""), key=lambda x: x.id), counts):
            item.tags.add("photo")
            for c in range(n):
                item.add_caption(f"caption {c} of item {item.id}")
    return data


def _caption_manifest(tmp_path, counts, repeat):
    from media_compost import open_library
    from media_compost.train.dataset import build_manifest
    from media_compost.train.spec import (BucketConfig, DatasetQuery,
                                          TrainingConfig)

    data = _caption_lib(tmp_path, counts)
    cfg = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                         buckets=BucketConfig(skip_upscale=False))
    cfg.captions.source = "captions"
    cfg.captions.caption_repeat = repeat
    with open_library(data, source="cli") as lib:
        return build_manifest(lib, cfg.model_dump(mode="json"),
                              tmp_path / f"job-{repeat}")["items"]


def test_one_random_caption_a_visit_is_one_entry(tmp_path):
    """The default, and what every run did before the setting existed: an item
    counts once however many ways it has been described."""
    items = _caption_manifest(tmp_path, [3, 1], "random")
    assert len(items) == 2
    assert sorted(len(i["captions"]) for i in items) == [1, 3]
    assert all("loss_scale" not in i for i in items)


def test_every_caption_gets_its_own_visit(tmp_path):
    """One entry per caption, each carrying just that caption — so a pass uses
    all of them rather than trusting a long run to get round to it."""
    items = _caption_manifest(tmp_path, [3, 1], "each")
    assert len(items) == 4, [i["captions"] for i in items]
    assert all(len(i["captions"]) == 1 for i in items)
    assert all("loss_scale" not in i for i in items), "no share: ten captions is ten times the exposure"


def test_sharing_splits_one_item_worth_of_gradient(tmp_path):
    """Having been described ten ways is usually an accident of tooling — a
    machine draft, a rewrite, a translation — not a claim to ten times the
    influence. The visits stay; the gradient is divided."""
    items = _caption_manifest(tmp_path, [3, 1], "each_shared")
    assert len(items) == 4
    shares = sorted(round(i.get("loss_scale", 1.0), 3) for i in items)
    assert shares == [0.333, 0.333, 0.333, 1.0], shares
    # Each item contributes the same total, whatever its caption count.
    by_item = {}
    for i in items:
        by_item.setdefault(i["item_id"], []).append(i.get("loss_scale", 1.0))
    # 1e-5, not exact: the manifest rounds a share to six places to stay
    # readable, so three of them sum to 0.999999. A millionth of a loss
    # multiplier is not a thing anybody can measure.
    assert all(abs(sum(v) - 1.0) < 1e-5 for v in by_item.values()), by_item


def test_the_tags_half_of_a_both_run_never_repeats(tmp_path):
    """An item has one set of tags however many ways it has been described."""
    from media_compost import open_library
    from media_compost.train.dataset import build_manifest
    from media_compost.train.spec import (BucketConfig, DatasetQuery,
                                          TrainingConfig)

    data = _caption_lib(tmp_path, [3])
    cfg = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)],
                         buckets=BucketConfig(skip_upscale=False))
    cfg.captions.source = "both"
    cfg.captions.caption_repeat = "each"
    with open_library(data, source="cli") as lib:
        items = build_manifest(lib, cfg.model_dump(mode="json"),
                               tmp_path / "job-both")["items"]
    modes = [i["prompt_mode"] for i in items]
    assert modes.count("tags") == 1 and modes.count("caption") == 3, modes


def test_the_editor_is_told_which_reg_pool_will_be_empty(train_client):
    """The warning next to a regularization query, answered server-side.

    A reg query whose every picture is also matched by a training query
    contributes NOTHING — a training query wins — and the run only says so in
    its log, long after somebody queued it and walked away. The editor asks
    this endpoint instead.

    It is answered here rather than computed in the browser so the warning
    cannot disagree with what the run does: both go through
    `dataset.regularization_ids`.
    """
    c = train_client
    cfg = _api_cfg()

    # An "everything" reg query beside an "everything" training query: fully
    # overlapped, so it contributes nothing at all.
    cfg["queries"] = [
        {"search": "", "tree": None, "weight": 1.0},
        {"search": "", "tree": None, "weight": 1.0, "regularize": True},
    ]
    r = c.post("/api/train/queries/preview", json={"config": cfg})
    assert r.status_code == 200, r.text
    got = r.json()["queries"]
    assert got[0]["matched"] > 0 and got[0]["contributes"] == got[0]["matched"]
    assert got[1]["matched"] == got[0]["matched"], "it does match them"
    assert got[1]["contributes"] == 0, "…and contributes none of them"

    # The other extreme: nothing overlaps, so the reg query keeps everything.
    # (This fixture's two pictures carry the same tags, so a PARTIAL overlap
    # cannot be built here — the two ends are what pin the subtraction.)
    cfg["queries"] = [
        {"search": "nothing_has_this_tag",
         "tree": parse("nothing_has_this_tag").model_dump(mode="json"),
         "weight": 1.0},
        {"search": "", "tree": None, "weight": 1.0, "regularize": True},
    ]
    got = c.post("/api/train/queries/preview", json={"config": cfg}).json()["queries"]
    assert got[0]["matched"] == 0
    assert got[1]["contributes"] == got[1]["matched"] > 0

    # An ordinary query always contributes everything it matched, so the
    # frontend can read ONE field for both kinds.
    assert all(q["contributes"] == q["matched"]
               for q in c.post("/api/train/queries/preview",
                               json={"config": {**cfg, "queries": [
                                   {"search": "", "tree": None, "weight": 1.0}]}}
                               ).json()["queries"])


# ---- the four /api/train routes nothing was calling --------------------------
#
# `queue-order`, `queue/stop`, `loras` and `gpu/recheck` were the endpoints
# with no test at any level: the MANAGER's `reorder_queue`/`queue_stop` are
# exercised above through `sim_mgr`, but nothing asked whether the routes in
# front of them were wired to the right method — which is the half a drag in
# the sidebar depends on.


def test_the_queue_order_route_reorders_what_is_queued(train_client):
    c = train_client
    uids = []
    for name in ("first", "second", "third"):
        r = c.post("/api/train/jobs", json={"name": name,
                                            "config": _api_cfg(steps=20)})
        assert r.status_code == 200, r.text
        uids.append(r.json()["uid"])
        assert c.post(f"/api/train/jobs/{uids[-1]}/queue").status_code == 200

    def queued() -> list[str]:
        # The QUEUE's order is `queued_at`, not the listing's order — the
        # sidebar sorts "Up next" by it, and the route rewrites the stamps.
        jobs = [j for j in c.get("/api/train/jobs").json()["jobs"]
                if j["status"] == "queued"]
        return [j["uid"] for j in sorted(jobs, key=lambda j: j["queued_at"])]

    assert queued() == uids                       # placement order to start
    flipped = [uids[2], uids[0], uids[1]]
    assert c.post("/api/train/queue-order",
                  json={"uids": flipped}).status_code == 200
    assert queued() == flipped
    # …and it is PERSISTED as a stamp rather than held in memory: the order
    # survives a fresh read through the same route.
    assert queued() == flipped


def test_the_queue_stop_route_turns_the_run_switch_off(train_client):
    """Stop starting new jobs. The switch is persisted (`queue.json`), so the
    route has to move it rather than a flag on the request."""
    c = train_client
    r = c.post("/api/train/jobs", json={"name": "held",
                                        "config": _api_cfg(steps=800)})
    uid = r.json()["uid"]
    assert c.post(f"/api/train/jobs/{uid}/queue").status_code == 200

    assert c.post("/api/train/queue/run").status_code == 200
    assert c.get("/api/train/jobs").json()["queue_active"] is True
    assert c.post("/api/train/queue/stop").status_code == 200
    assert c.get("/api/train/jobs").json()["queue_active"] is False
    c.post(f"/api/train/jobs/{uid}/cancel")


def test_the_loras_route_lists_what_a_new_job_can_start_from(train_client):
    c = train_client
    # Nothing has finished yet, so the list is empty rather than absent — the
    # editor renders it directly as the "based on" options.
    assert c.get("/api/train/loras").json()["loras"] == []

    r = c.post("/api/train/jobs", json={"name": "src", "config": _api_cfg()})
    uid = r.json()["uid"]
    c.post(f"/api/train/jobs/{uid}/queue")
    c.post("/api/train/queue/run")
    end = time.time() + 40
    while time.time() < end:
        if c.get(f"/api/train/jobs/{uid}").json()["status"] in ("completed",
                                                               "failed"):
            break
        time.sleep(0.2)
    assert c.get(f"/api/train/jobs/{uid}").json()["status"] == "completed"

    sources = c.get("/api/train/loras").json()["loras"]
    assert sources, "a finished job's output should be startable from"
    mine = [s for s in sources if s["job_uid"] == uid]
    assert mine, [s["job_uid"] for s in sources]
    # Each carries the on-disk path the trainer loads, and the model it was
    # trained for — a LoRA only fits its own architecture.
    assert all(s["model"] == "sd15" for s in mine)
    assert all(Path(s["path"]).exists() for s in mine)


def test_the_gpu_recheck_route_clears_the_latched_refusal(train_client,
                                                          monkeypatch):
    """`powermetrics` is root-only and its refusal LATCHES for the life of the
    process, so the poll cannot re-ask on its own. This route is somebody
    saying they have just added the sudoers rule — so it must clear the latch
    and re-sample, not merely re-sample."""
    from media_compost.train import gpu as gputil

    c = train_client
    cleared: list[bool] = []
    monkeypatch.setattr(gputil, "clear_denied",
                        lambda: cleared.append(True))
    r = c.post("/api/train/gpu/recheck")
    assert r.status_code == 200, r.text
    assert cleared == [True], "recheck sampled without clearing the latch"
    assert isinstance(r.json(), list)
    # The plain poll must NOT clear it — that is the whole point of latching.
    assert c.get("/api/train/gpu").status_code == 200
    assert cleared == [True]


def test_an_epoch_cadence_reaches_the_app_as_the_steps_it_resolved_to(sim_mgr):
    """The countdowns in the phase strip need the cadence the RUN is keeping.

    An epoch cadence is a step count only once the built manifest has said
    how long a pass is — the trainer is the only place that knows, so it
    publishes what it resolved and the record mirrors it. Read off the config
    instead, a job set to "every 2 epochs" counted down to
    `checkpoint_every`, which is precisely the field the epoch setting
    overruled: a step nothing was going to happen at.
    """
    uid = sim_mgr.create(
        "epochs", _cfg(steps=30, checkpoint_every=500, checkpoint_epochs=1),
        "tester")
    sim_mgr.enqueue(uid)
    sim_mgr.queue_run()
    rec = _wait(sim_mgr, uid, ("completed", "failed"))
    assert rec["status"] == "completed", rec["message"]
    # Whatever the dataset came out as, it is the resolved figure and NOT
    # the step field the epoch setting overruled.
    assert rec["ckpt_every"] > 0
    assert rec["ckpt_every"] != 500
    # ... and it reaches the wire.
    from media_compost.train.web.routes import _job_out
    assert _job_out(rec).ckpt_every == rec["ckpt_every"]


def test_a_step_cadence_is_published_unchanged(sim_mgr):
    """The same channel with nothing to resolve: what the config says."""
    uid = sim_mgr.create("steps", _cfg(steps=30, checkpoint_every=10),
                         "tester")
    sim_mgr.enqueue(uid)
    sim_mgr.queue_run()
    rec = _wait(sim_mgr, uid, ("completed", "failed"))
    assert rec["status"] == "completed", rec["message"]
    assert rec["ckpt_every"] == 10
    # A run that renders no test samples reports no sample cadence, so the
    # app draws no dot counting down to a round that never comes.
    assert rec.get("sample_every", 0) == 0


def test_a_job_that_loads_from_a_path_is_never_refused_for_a_download(
        train_client, monkeypatch):
    """The guard that refuses a run needing a download while downloads are
    off must ask the JOB where its weights come from.

    A config carrying `local_path` loads from that path and downloads
    nothing — `build_manifest` puts it in the manifest's `repo` and marks it
    local — so judging it by the model KEY's hub repo refused a run that
    needed no hub at all. It sits on the queue route as well as the start
    one, so the job could be neither moved nor started, with a 400 the app
    was throwing away.
    """
    from media_compost.hub import hf
    from media_compost.train import models as train_models

    c = train_client
    # Both are resolved INSIDE the guard (`from ..models import repo_state`),
    # so the module attributes are what a patch has to reach.
    monkeypatch.setattr(hf, "offline_var", lambda: "HF_HUB_OFFLINE")
    monkeypatch.setattr(train_models, "repo_state", lambda repo: "none")

    # No local path: the refusal stands, and it says why.
    plain = c.post("/api/train/jobs", json={
        "name": "hub job", "config": _api_cfg()}).json()["uid"]
    r = c.post(f"/api/train/jobs/{plain}/queue")
    assert r.status_code == 400, r.text
    assert "downloads are switched off" in r.json()["detail"]

    # With one, both routes go through.
    local = c.post("/api/train/jobs", json={
        "name": "path job",
        "config": {**_api_cfg(), "local_path": "/models/sdxl"}}).json()["uid"]
    assert c.post(f"/api/train/jobs/{local}/queue").status_code == 200, \
        "a job loading from a path downloads nothing"
    # ... and the start route asks the same question.
    s = c.post(f"/api/train/jobs/{local}/start")
    assert s.status_code != 400, s.text


def test_a_job_on_a_model_ADDED_AS_A_PATH_is_never_refused_either(
        train_client, tmp_path: Path, monkeypatch):
    """The other way a run's weights are already here: a model the user added
    by pointing at a checkpoint on the disk.

    Such a model's `repo` IS that path, and `repo_state` answers "none" for
    anything that is not a hub id — so the guard read "not downloaded" and
    refused a custom SDXL that needed no hub at all. `usermodels.resolve`
    carries the `local` flag onto the spec; the guard reads it.
    """
    from media_compost.hub import hf
    from media_compost.train import models as train_models

    c = train_client
    ckpt = tmp_path / "my_sdxl.safetensors"
    ckpt.write_bytes(b"not really weights")
    added = c.post("/api/train/models", json={
        "label": "My SDXL", "base": "sdxl", "repo": str(ckpt),
        "local": True, "area": 1024})
    assert added.status_code == 200, added.text

    monkeypatch.setattr(hf, "offline_var", lambda: "HF_HUB_OFFLINE")
    monkeypatch.setattr(train_models, "repo_state", lambda repo: "none")

    uid = c.post("/api/train/jobs", json={
        "name": "local model job",
        "config": {**_api_cfg(), "model": "user:my-sdxl"}}).json()["uid"]
    q = c.post(f"/api/train/jobs/{uid}/queue")
    assert q.status_code == 200, q.text
    s = c.post(f"/api/train/jobs/{uid}/start")
    assert s.status_code != 400, s.text
