"""The trainer's TENSOR arithmetic: masked loss, and the latent cache.

Split out of `test_training.py`, which is a 4700-line file covering four
unrelated subsystems and — the part that mattered here — imports **fastapi and
the app** at module level. These nine tests need only torch and a couple of
trainer-script modules loaded by file path, but that one import meant they
could run in exactly one place: a venv holding torch AND the whole server,
which is neither the main venv (torch-free by contract, and CI asserts it) nor
`.venv-training` (the trainer's, which carries no server). So they skipped
everywhere and had never executed once.

They still `importorskip("torch")`, so the main venv skips them exactly as
before. What runs them is the training venv, plus five packages that are there
for two unrelated reasons: `pytest` is the RUNNER (the `[dev]` extra — nothing
to do with the library, it is simply what `python -m pytest` needs in the
interpreter it runs in), and `sqlalchemy pydantic imagehash rich` are what
`import media_compost` reaches, because `tests/train/conftest.py` reads a
library through the public API and so every test in this directory imports the
package. numpy and pillow come with the torch stack already.

    .venv-training/bin/pip install pytest sqlalchemy pydantic imagehash rich
    .venv-training/bin/python -m pytest tests/train/test_engine_math.py

(`media_compost.train.paths` for one path constant is the only app import
here, the same one `test_adapters.py` and `test_ema.py` already make. What is
gone is the server.)

What each guards is a silent failure — a loss that quietly changes scale with
the mask, a weight map landing on the wrong cells, or a "compressed" cache
entry that is bigger than the tensor it holds, which is a state this format
actually shipped in once.
"""

from __future__ import annotations

import importlib.util
import random

import pytest

from media_compost.train.paths import TRAIN_SCRIPTS
from tests.train.conftest import loop_module as _loop_module


def _engine_common():
    p = (TRAIN_SCRIPTS / "engines"
         / "common.py")
    spec = importlib.util.spec_from_file_location("engine_common_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_masked_mean_keeps_the_loss_on_the_same_scale():
    """The mask must reweight the average, never rescale it: a learning rate
    tuned without masking has to still mean the same thing with it."""
    torch = pytest.importorskip("torch")
    masked_mean = _engine_common().masked_mean

    loss = torch.ones((2, 4, 8, 8))
    # No mask, and an all-ones mask, are the plain mean.
    assert torch.allclose(masked_mean(loss, None), torch.ones(2))
    ones = torch.ones((2, 1, 8, 8))
    assert torch.allclose(masked_mean(loss, ones), torch.ones(2))
    # A mask covering a quarter of the frame still averages to 1 — it does not
    # shrink to a quarter (which a sum-based version would).
    quarter = torch.zeros((2, 1, 8, 8))
    quarter[:, :, :4, :4] = 1.0
    assert torch.allclose(masked_mean(loss, quarter), torch.ones(2))

def test_masked_mean_ignores_error_where_the_mask_is_zero():
    torch = pytest.importorskip("torch")
    masked_mean = _engine_common().masked_mean

    loss = torch.zeros((1, 1, 2, 2))
    loss[0, 0, 0, 0] = 4.0            # all the error sits in one cell
    visible = torch.tensor([[[[0.0, 1.0], [1.0, 1.0]]]])
    assert float(masked_mean(loss, visible)) == 0.0
    # …and a background weight lets a fraction of it back in.
    partial = torch.tensor([[[[0.5, 1.0], [1.0, 1.0]]]])
    assert abs(float(masked_mean(loss, partial)) - (2.0 / 3.5)) < 1e-6

class _StubEngine:
    """Stands in for a real engine: latents of the right SHAPE, no VAE.

    It carries `latent_scale` for the same reason it carries `device` and
    `dtype`: the loop reads it off the engine, and a stub that leaves out a
    member of the contract only proves the loop still runs without it."""

    latent_scale = 8

    def __init__(self, torch):
        self.torch = torch
        self.device = "cpu"
        self.dtype = torch.float32

    def encode_image(self, img):
        w, h = img.size
        return self.torch.zeros((1, 4, h // 8, w // 8))

def _mask_source(tmp_path, torch, cache: bool, bg=0.1):
    """A LatentSource over one 64×64 image whose left half is transparent."""
    from PIL import Image

    loop = _loop_module()
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    img.paste((200, 60, 60, 255), (32, 0, 64, 64))     # opaque RIGHT half
    path = tmp_path / "cutout.png"
    img.save(path)

    manifest = {"items": [{"path": str(path), "width": 64, "height": 64,
                           "bucket": 0}]}

    class _IO:
        dir = tmp_path

        def check_control(self):
            pass

    return loop.LatentSource(
        _StubEngine(torch), _IO(), manifest, [(64, 64)],
        {"random_crop": False, "flip_p": 0.0, "cache_latents": cache,
         "alpha_mask": True, "alpha_bg_weight": bg},
        random.Random(0),
    )

@pytest.mark.parametrize("cache", [False, True])
def test_alpha_mask_lines_up_with_the_latent(tmp_path, cache):
    """The weight map must land on the same cells as the pixels it came from —
    cached or not, it is the half of the frame that was actually visible."""
    torch = pytest.importorskip("torch")
    src = _mask_source(tmp_path, torch, cache)
    if cache:
        src.prepare()

    lat, weights = src.batch_latents([0], (64, 64))
    assert lat.shape == (1, 4, 8, 8)
    assert weights.shape == (1, 1, 8, 8)
    row = weights[0, 0, 4]
    assert float(row[0]) == pytest.approx(0.1)   # transparent -> background
    assert float(row[7]) == pytest.approx(1.0)   # opaque -> full weight

def test_alpha_mask_off_produces_no_weights(tmp_path):
    torch = pytest.importorskip("torch")
    src = _mask_source(tmp_path, torch, cache=False)
    src.alpha_mask = False
    assert src.batch_latents([0], (64, 64))[1] is None

def test_background_weight_of_one_disables_masking(tmp_path):
    """A weight of 1 IS the unmasked loss, so the run should not pay for the
    mask at all — including the separate latent cache."""
    torch = pytest.importorskip("torch")
    src = _mask_source(tmp_path, torch, cache=False, bg=1.0)
    assert src.alpha_mask is False
    assert src.batch_latents([0], (64, 64))[1] is None

def test_cached_masked_latent_round_trips_as_a_dict(tmp_path):
    """Masked entries carry the mask next to the latent, and both halves are
    the packed record `latentio` writes rather than a bare tensor."""
    torch = pytest.importorskip("torch")
    src = _mask_source(tmp_path, torch, cache=True)
    src.prepare()
    blob = torch.load(src._path(0, False), map_location="cpu")
    assert isinstance(blob, dict) and set(blob) == {"lat", "mask"}
    assert blob["mask"]["shape"] == [1, 1, 8, 8]
    # A uint8 TENSOR, never bytes — see the file-size test below for why.
    assert torch.is_tensor(blob["mask"]["z"])
    assert blob["mask"]["z"].dtype is torch.uint8
    lat, mask = src._read(src._path(0, False))
    assert lat.shape == (1, 4, 8, 8) and mask.shape == (1, 1, 8, 8)

def test_A_CACHE_ENTRY_IS_SMALLER_ON_DISK_THAN_THE_TENSOR_IT_HOLDS(tmp_path):
    """The point of the whole format, asserted where it can actually fail:
    the FILE, not the payload.

    Compression that shrinks the payload can still grow the file, and it did.
    `torch.save` pickles at protocol 2, which stores `bytes` latin-1 escaped
    at ~1.5x, so a first build of this packed 1324 real latents to a genuine
    72.6% and wrote 108.6% of the old format to disk. Every check that read
    `len(rec["z"])` passed.
    """
    torch = pytest.importorskip("torch")
    loop = _loop_module()
    # Noise is the WORST case for a compressor, so this is a floor rather
    # than the ~73% real latents reach — what it catches is a container that
    # inflates, which no amount of incompressibility can explain.
    lat = (torch.randn(1, 16, 64, 64) * 0.9).half()
    raw, packed = tmp_path / "raw.pt", tmp_path / "packed.pt"
    torch.save(lat, raw)
    torch.save(loop.LatentSource._blob(lat, None), packed)

    assert packed.stat().st_size < raw.stat().st_size
    assert torch.equal(loop.LatentSource._read(packed)[0], lat)

def test_latent_caching_reports_progress(tmp_path: Path):
    """`prepare` drives the note above; it reports as it goes, not at the end."""
    loop = _loop_module()
    torch = pytest.importorskip("torch")
    from PIL import Image

    items = []
    for i in range(7):
        p = tmp_path / f"i{i}.png"
        Image.new("RGB", (64, 64), (i * 20, 0, 0)).save(p)
        items.append({"path": str(p), "width": 64, "height": 64, "bucket": 0,
                      "tags": []})

    class _IO:
        dir = tmp_path
        def check_control(self): pass

    src = loop.LatentSource(_StubEngine(torch), _IO(),
                            {"items": items, "groups": [], "buckets": [[64, 64]]},
                            [(64, 64)], {"cache_latents": True}, random.Random(0))
    seen: list[tuple[int, int]] = []
    src.prepare(on_progress=lambda done, total: seen.append((done, total)))
    assert seen, "no progress reported"
    assert seen[0][0] < len(items)          # reported while going, not only after
    assert seen[-1] == (len(items), len(items))


def test_a_FULL_finetune_can_sample_at_all(tmp_path):
    """A full finetune's backbone is fp32 master weights while everything
    around it stays `self.dtype`, so a sample round with no autocast hands an
    fp32 Linear a bf16 activation:

        RuntimeError: mat1 and mat2 must have the same dtype,
                      but got BFloat16 and Float

    `train_step` has always wrapped; the sample round did not, and with
    `sampling.at_start` on that round is the FIRST thing a run does — so a
    full finetune died before its first step. `BaseEngine.sampling()` is the
    one place all three sampling contexts live now.

    Driven against a real (tiny) UNet rather than a stub: what is being
    checked is torch's own dtype rule, which only a real matmul can state.
    """
    torch = pytest.importorskip("torch")
    # The main venv is torch-free by contract and has no diffusers either;
    # this one runs from `.venv-training` like the rest of this module's
    # tensor tests (see the module docstring).
    diffusers = pytest.importorskip("diffusers")
    UNet2DConditionModel = diffusers.UNet2DConditionModel

    common = _engine_common()
    unet = UNet2DConditionModel(
        sample_size=8, in_channels=4, out_channels=4, layers_per_block=1,
        block_out_channels=(32, 64),
        down_block_types=("DownBlock2D", "CrossAttnDownBlock2D"),
        up_block_types=("CrossAttnUpBlock2D", "UpBlock2D"),
        cross_attention_dim=32, norm_num_groups=32, attention_head_dim=8,
    ).to(dtype=torch.bfloat16)

    class _Engine(common.BaseEngine):
        def load(self):  # pragma: no cover - never called
            raise NotImplementedError

    def build(method):
        e = _Engine({"method": method, "hyper": {}, "model_params": {}},
                    {"repo": "tiny", "local": False}, "cpu", torch.bfloat16)
        e.unet = e.transformer = unet
        e.vae = None
        e.trained_text_encoders = lambda: {}
        return e

    lat = torch.randn(1, 4, 8, 8, dtype=torch.bfloat16)
    hid = torch.randn(1, 5, 32, dtype=torch.bfloat16)
    step = torch.tensor([5])

    full = build("full")
    unet.requires_grad_(True)
    full.upcast_trainable()
    assert next(unet.parameters()).dtype is torch.float32

    # As it stands, and as it stood: the same call with none of the sampling
    # contexts around it is the failure this test is named for.
    with pytest.raises(RuntimeError, match="same dtype"):
        with torch.no_grad():
            unet(lat, step, encoder_hidden_states=hid)
    # …and inside `sampling()` it goes through.
    with full.sampling(unet), torch.no_grad():
        unet(lat, step, encoder_hidden_states=hid)

    # A LoRA run gets NO autocast from it: its backbone already is
    # `self.dtype`, and casting the fp32 adapter down for the matmul would
    # change every sample image ever rendered in exchange for nothing.
    unet.requires_grad_(False)
    unet.to(dtype=torch.bfloat16)
    with build("lora").sampling(unet):
        assert not torch.is_autocast_enabled("cpu")


def _kahan():
    import importlib.util as ilu

    p = TRAIN_SCRIPTS / "kahan.py"
    spec = ilu.spec_from_file_location("kahan_under_test", p)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_HALF_PRECISION_MASTERS_ACTUALLY_MOVE():
    """Master weights at bf16, updated through the Kahan wrapper, must
    actually train — and land where fp32 masters would.

    Plain bf16 masters do NOT move: a step is far below one bf16 ulp, so
    rounded to nearest every update vanishes. That is the whole reason
    `upcast_trainable` exists and the whole reason this wrapper does, so the
    check is the pair — the same optimizer over the same steps, with the
    carry and without it.
    """
    torch = pytest.importorskip("torch")
    sr = _kahan()

    def run(wrapped: bool) -> float:
        w = torch.nn.Parameter(torch.full((256,), 1.0, dtype=torch.bfloat16))
        opt = torch.optim.SGD([w], lr=1e-4)
        if wrapped:
            opt = sr.KahanMasters(opt, torch.bfloat16)
        for _ in range(2000):
            w.grad = torch.full_like(w, -1.0)
            opt.step()
        return w.detach().float().mean().item()

    # 2000 steps of +1e-4 is +0.2 exactly.
    assert run(False) == pytest.approx(1.0, abs=1e-6), (
        "bf16 masters moved without the carry — the premise is gone")
    # Within one bf16 ulp of the exact answer, and DETERMINISTIC — where
    # stochastic rounding's spread over seeds was 20% of the progress made.
    assert run(True) == pytest.approx(1.2, abs=0.005)
    assert run(True) == run(True)


def test_NOTHING_IS_LOST_ONLY_DEFERRED():
    """A hundred updates each a tenth of an ulp move the weight on the tenth
    step rather than never. That is what the carry buys over rounding: a step
    too small to store is held, not spent."""
    torch = pytest.importorskip("torch")
    sr = _kahan()

    w = torch.nn.Parameter(torch.full((1,), 1.0, dtype=torch.bfloat16))
    opt = sr.KahanMasters(torch.optim.SGD([w], lr=1e-3), torch.bfloat16)
    ulp = 0.0078125  # one bf16 ulp at |w| = 1
    moved_at = []
    for i in range(1, 25):
        w.grad = torch.full_like(w, -1.0)
        opt.step()
        moved_at.append(w.detach().float().item())
    # It steps in whole ulps, about every eighth update (1e-3 against
    # 7.8e-3), and after 24 steps it is where 24 x 1e-3 says it should be.
    assert sorted(set(moved_at)) == [1.0 + k * ulp for k in range(0, 4)]
    assert moved_at[-1] == pytest.approx(1.024, abs=ulp)


def test_the_carry_rides_in_the_checkpoint():
    """It is part of the run's state. Dropping it at a resume loses at most
    one ulp per weight — nothing — but it is free to keep, and a resumed run
    should be the run it was. A state written before it existed still
    loads."""
    torch = pytest.importorskip("torch")
    sr = _kahan()

    def fresh():
        w = torch.nn.Parameter(torch.full((8,), 1.0, dtype=torch.bfloat16))
        return w, sr.KahanMasters(torch.optim.SGD([w], lr=1e-4),
                                  torch.bfloat16)

    w, opt = fresh()
    for _ in range(30):
        w.grad = torch.full_like(w, -1.0)
        opt.step()
    saved = opt.state_dict()
    assert saved["carry"], "the carry is not in the state"

    w2, opt2 = fresh()
    opt2.load_state_dict(saved)
    assert opt2.carry[0].dtype is torch.bfloat16
    assert torch.equal(opt2.carry[0], opt.carry[0])

    # An older checkpoint holds the inner optimizer's state on its own.
    w3, opt3 = fresh()
    opt3.load_state_dict(saved["inner"])
    assert opt3.carry == {}


def test_the_VAE_DECODES_IN_ITS_OWN_DTYPE_under_an_ambient_autocast():
    """`decode_samples` exists to keep the VAE out of the latents' dtype, and
    casting the latents is only half of that: an AMBIENT autocast casts every
    conv INSIDE the VAE too.

    `sampling()` wraps a full finetune's whole sample block — the denoising
    needs the autocast, the decode must not have it — and SDXL's VAE is
    deliberately fp32 because it does not survive sixteen bits. Without the
    guard a full SDXL finetune rendered a round of flat grey squares: the
    decode ran in bf16, and the non-finite check catches nothing there,
    because mush is finite.
    """
    torch = pytest.importorskip("torch")
    diffusers = pytest.importorskip("diffusers")
    common = _engine_common()

    torch.manual_seed(0)
    vae = diffusers.AutoencoderKL(
        block_out_channels=(32,), in_channels=3, out_channels=3,
        down_block_types=("DownEncoderBlock2D",),
        up_block_types=("UpDecoderBlock2D",), latent_channels=4,
        norm_num_groups=32, sample_size=32).to(torch.float32)

    class _Pipe:
        class image_processor:
            @staticmethod
            def postprocess(x, output_type):
                return x

    lat = torch.randn(1, 4, 8, 8)
    plain = common.decode_samples(_Pipe, vae, lat)
    with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
        inside = common.decode_samples(_Pipe, vae, lat)
    assert plain.dtype is torch.float32 and inside.dtype is torch.float32
    # The same numbers, not merely the same dtype — the cast back would hide
    # a decode that had run entirely in bf16, which is what it did.
    assert torch.equal(plain, inside)
