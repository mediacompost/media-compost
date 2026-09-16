"""The latent cache's on-disk format.

`latentio` is numpy + zlib only, so it is loaded by file path and exercised
from the main backend venv — like `compose.py` and `images.py`, and for the
same reason: the trainer scripts are standalone and cannot be imported.

The headline is LOSSLESSNESS. Everything else here (the byte-shuffle, the
level) is a choice about size and speed that may move; that a decoded latent is
the encoded one bit for bit is the contract, because a latent is a training
TARGET and a lossy one produces a slightly worse LoRA with nothing saying so.
"""

from __future__ import annotations

import importlib.util
import pickle
import zlib

import numpy as np
import pytest

from media_compost.train.paths import TRAIN_SCRIPTS


def _latentio():
    p = TRAIN_SCRIPTS / "latentio.py"
    spec = importlib.util.spec_from_file_location("latentio_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


latentio = _latentio()


def _latent(shape=(1, 4, 40, 24), seed: int = 0) -> np.ndarray:
    """Something with a VAE latent's statistics: roughly unit-normal, and
    SPATIALLY SMOOTH — which is where the compressibility comes from, so white
    noise would understate every ratio below."""
    rng = np.random.default_rng(seed)
    a = rng.standard_normal(shape)
    for axis in (-1, -2):                      # a cheap two-tap blur per axis
        a = (a + np.roll(a, 1, axis=axis)) / 1.5
    return a.astype(np.float16)


# ---- the contract -----------------------------------------------------------


@pytest.mark.parametrize("shape", [
    (1, 4, 40, 24),        # sd15 / sdxl
    (1, 16, 48, 32),       # chroma, FLUX.1
    (1, 128, 24, 16),      # FLUX.2 Klein, patchified into channels
    (1, 1, 32, 36),        # a mask
    (1, 4, 1, 1),          # degenerate, but a bucket this small is legal
])
def test_a_latent_survives_the_round_trip_BIT_FOR_BIT(shape):
    arr = _latent(shape)
    back = latentio.decode(latentio.encode(arr))
    assert back.dtype == arr.dtype
    assert back.shape == arr.shape
    assert np.array_equal(back, arr)           # not allclose: exactly equal


def test_every_dtype_the_cache_could_hold_round_trips():
    """fp16 is what the trainer writes today. The packing is written for any
    itemsize rather than for two bytes, so an engine whose latents are not
    fp16 gets a correct entry rather than a silently corrupt one."""
    for dtype in ("float16", "float32", "uint8", "int8", "float64"):
        arr = _latent().astype(dtype)
        back = latentio.decode(latentio.encode(arr))
        assert back.dtype == arr.dtype and np.array_equal(back, arr), dtype


def test_a_decoded_latent_is_writable():
    """`torch.from_numpy` on a read-only array warns, once per latent per
    step — a training log full of numpy advice about the internals of the
    cache. `frombuffer` hands back exactly such an array, so the unpacking
    has to copy."""
    back = latentio.decode(latentio.encode(_latent()))
    assert back.flags.writeable
    back[0, 0, 0, 0] = 1                        # would raise otherwise


def test_a_record_carries_only_what_torch_load_will_read_back():
    """The record is saved inside a `torch.save` blob and read under
    `torch.load`'s `weights_only` default, which accepts primitives and
    refuses arbitrary objects. Keeping it to bytes/ints/strs is what stops a
    future torch (or a stricter default) from refusing the whole cache."""
    rec = latentio.encode(_latent())
    assert set(rec) == {"z", "shape", "dtype"}
    assert isinstance(rec["z"], bytes)
    assert isinstance(rec["dtype"], str)
    assert all(isinstance(v, int) for v in rec["shape"])


def test_decode_reads_a_payload_that_is_not_bytes():
    """The caller stores `z` as a uint8 TENSOR (see the module docstring) and
    hands it back as a numpy array, so `decode` has to take any buffer. This
    is the contract that keeps `latentio` free of torch."""
    rec = latentio.encode(_latent())
    for wrapped in (bytearray(rec["z"]), memoryview(rec["z"]),
                    np.frombuffer(rec["z"], dtype=np.uint8)):
        assert np.array_equal(latentio.decode({**rec, "z": wrapped}),
                              latentio.decode(rec))


def test_PICKLE_PROTOCOL_2_INFLATES_BYTES_which_is_why_z_travels_as_a_tensor():
    """The trap this format was shipped with once, made executable.

    `torch.save` pickles at protocol 2, which has NO opcode for `bytes`:
    Python 3 falls back to a latin-1 string, so every byte above 0x7f becomes
    two. Compressed data is about half such bytes, so a payload handed
    straight to `torch.save` lands ~1.5x its own size — which took a genuine
    72.6% packing to an 8.6% GROWTH on disk, invisible to anything that
    measures the payload rather than the file.

    What rescues it is NOT that a tensor pickles better — a numpy array at
    protocol 2 inflates just as badly, which this asserts, because assuming
    otherwise is the obvious wrong fix. It is that `torch.save` writes tensor
    STORAGE as its own raw record in the zip container, outside the pickle
    altogether, where no protocol reaches it.

    Nothing here can stop a caller handing over bytes; what this pins is the
    reason, so it reads as a measured fact rather than a superstition about
    pickle. `tests/train/test_training.py` holds the file-size end of it.
    """
    z = latentio.encode(_latent((1, 16, 64, 64)))["z"]
    assert len(pickle.dumps(z, protocol=2)) > len(z) * 1.3
    assert len(pickle.dumps(np.frombuffer(z, dtype=np.uint8), 2)) > len(z) * 1.3
    # Protocol 4 is where `bytes` got an opcode — the fix that was rejected
    # for being a keyword on every save that anybody may forget.
    assert len(pickle.dumps(z, protocol=4)) < len(z) * 1.05


# ---- the choices ------------------------------------------------------------


def test_the_byte_shuffle_is_what_earns_the_compression():
    """fp16 values sit in about ±4, so the high byte of each carries a few
    distinct exponents while the low byte is nearly random. Interleaved, the
    compressor sees one alternating stream; split into planes, the redundant
    half compresses on its own. Measured on the demo library's real latents
    the split is worth 3–6 points, so a comfortable margin is asserted here
    rather than the exact figure."""
    arr = _latent((1, 4, 96, 96))
    packed = len(latentio.encode(arr)["z"])
    plain = len(zlib.compress(arr.tobytes(), latentio.LEVEL))
    assert packed < plain
    assert packed < arr.nbytes                  # it compresses at all


def test_the_shuffle_is_a_permutation_of_the_bytes():
    """Whatever the planes do to the ORDER, no byte is invented or lost —
    which is the half of losslessness that survives a change of level or of
    compressor."""
    arr = _latent()
    shuffled = latentio._shuffle(arr)
    assert sorted(shuffled) == sorted(arr.tobytes())
