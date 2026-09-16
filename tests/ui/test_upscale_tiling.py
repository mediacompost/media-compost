"""The upscalers' tiling (`plugins/impl/_tile.py`): a picture of any size
through a model whose memory grows with the pixel count, in overlapping
tiles whose interiors are pasted back — exact for a local operator."""
import numpy as np
import pytest

from media_compost.ui.plugins.impl import _tile


def _nearest(scale):
    """A LOCAL x`scale` operator (nearest neighbour): tiled and untiled
    must agree to the pixel."""
    def forward(tiles):
        return [np.repeat(np.repeat(t, scale, axis=0), scale, axis=1)
                for t in tiles]
    return forward


def _blur3(scale):
    """A 3x3 box blur then nearest x`scale`: needs ONE pixel of context on
    each side, which the overlap must supply."""
    def forward(tiles):
        out = []
        for t in tiles:
            f = t.astype(np.float32)
            p = np.pad(f, ((1, 1), (1, 1), (0, 0)), mode="edge")
            b = sum(p[dy:dy + f.shape[0], dx:dx + f.shape[1]]
                    for dy in range(3) for dx in range(3)) / 9.0
            out.append(np.repeat(np.repeat(b, scale, axis=0), scale, axis=1))
        return out
    return forward


@pytest.mark.parametrize("w,h", [(10, 10), (64, 64), (65, 64), (100, 37),
                                 (200, 129), (513, 511)])
def test_every_tile_fits_and_the_interiors_cover_the_picture_once(w, h):
    tiles = _tile.plan(w, h, tile=64, overlap=16)
    covered = np.zeros((h, w), dtype=int)
    for t in tiles:
        assert 0 <= t.x0 < t.x1 <= w and 0 <= t.y0 < t.y1 <= h
        assert t.w <= 64 and t.h <= 64
        assert t.x0 <= t.ix0 < t.ix1 <= t.x1
        assert t.y0 <= t.iy0 < t.iy1 <= t.y1
        # every kept pixel has the overlap's half of context on the cut
        # sides — the picture's own edges need none
        if t.x0 > 0:
            assert t.ix0 - t.x0 >= 8
        if t.x1 < w:
            assert t.x1 - t.ix1 >= 8
        covered[t.iy0:t.iy1, t.ix0:t.ix1] += 1
    assert covered.min() == 1 and covered.max() == 1
    if w <= 64 and h <= 64:
        assert len(tiles) == 1


def test_a_full_tile_is_the_common_shape_so_batches_are_uniform():
    tiles = _tile.plan(1000, 700, tile=256, overlap=32)
    shapes = {(t.h, t.w) for t in tiles}
    assert (256, 256) in shapes
    # the last tile of an axis is pulled back to the edge, never shortened
    assert all(t.w == 256 and t.h == 256 for t in tiles)


@pytest.mark.parametrize("scale", [2, 4])
@pytest.mark.parametrize("w,h", [(30, 20), (64, 64), (150, 97), (300, 260)])
def test_tiled_equals_untiled_for_a_local_operator(scale, w, h):
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    for fwd in (_nearest(scale), _blur3(scale)):
        whole = np.asarray(fwd([img])[0])
        tiled = _tile.upscale(img, scale, fwd, tile=64, overlap=16, batch=3)
        assert tiled.shape == (h * scale, w * scale, 3)
        assert tiled.dtype == whole.dtype
        np.testing.assert_array_equal(tiled, whole)


def test_tiles_of_one_shape_go_through_the_forward_together():
    seen: list[list[tuple]] = []

    def forward(tiles):
        seen.append([t.shape for t in tiles])
        return [np.repeat(np.repeat(t, 2, axis=0), 2, axis=1) for t in tiles]

    img = np.zeros((300, 300, 3), dtype=np.uint8)
    _tile.upscale(img, 2, forward, tile=128, overlap=32, batch=4)
    # 3x3 tiles of 128: nine same-shaped tiles in batches of four
    assert [len(b) for b in seen] == [4, 4, 1]
    assert all(s == (128, 128, 3) for b in seen for s in b)


def test_tile_zero_sends_the_whole_picture_once():
    calls = []

    def forward(tiles):
        calls.append(len(tiles))
        return [np.repeat(np.repeat(t, 2, axis=0), 2, axis=1) for t in tiles]

    img = np.zeros((900, 700, 3), dtype=np.uint8)
    out = _tile.upscale(img, 2, forward, tile=0)
    assert calls == [1] and out.shape == (1800, 1400, 3)


def test_settings_read_the_environment_with_defaults(monkeypatch):
    monkeypatch.delenv("MEDIA_COMPOST_UPSCALE_TILE", raising=False)
    monkeypatch.delenv("MEDIA_COMPOST_UPSCALE_OVERLAP", raising=False)
    monkeypatch.delenv("MEDIA_COMPOST_UPSCALE_BATCH", raising=False)
    assert _tile.settings() == (_tile.DEFAULT_TILE, _tile.DEFAULT_OVERLAP, 1)
    monkeypatch.setattr(_tile, "device_memory", lambda dev: 32 * 2**30)
    assert _tile.settings("cuda") == (_tile.DEFAULT_TILE,
                                      _tile.DEFAULT_OVERLAP,
                                      _tile.DEFAULT_BATCH)
    monkeypatch.setenv("MEDIA_COMPOST_UPSCALE_TILE", "256")
    monkeypatch.setenv("MEDIA_COMPOST_UPSCALE_BATCH", "nope")
    assert _tile.settings("cuda") == (256, _tile.DEFAULT_OVERLAP,
                                      _tile.DEFAULT_BATCH)
    monkeypatch.setenv("MEDIA_COMPOST_UPSCALE_BATCH", "4")
    assert _tile.settings("cuda")[2] == 4


def test_the_batch_follows_the_card():
    """Two 512 px tiles per forward peak at 6-8.4 GB allocated, which a
    16 GB card under Windows already spilled on: a 20 GB card takes the
    pair, a smaller one (or an unknown device) one tile at a time."""
    assert _tile.default_batch(None) == 1
    assert _tile.default_batch(16 * 2**30) == 1
    assert _tile.default_batch(20 * 2**30) == _tile.DEFAULT_BATCH
    assert _tile.default_batch(32 * 2**30) == _tile.DEFAULT_BATCH


def test_an_overlap_as_big_as_the_tile_is_refused():
    with pytest.raises(ValueError):
        _tile.plan(500, 500, tile=64, overlap=64)


def test_the_compiled_network_arrives_late_and_leaves_on_failure(monkeypatch):
    """`LazyCompiled`: eager for every odd-shaped batch and for the first
    `COMPILE_AFTER` full-tile batches (a single picture never pays the
    compile), compiled once past that, eager again for good after the
    compiled one fails."""
    compiled_calls: list = []
    monkeypatch.setattr(_tile, "_compile", lambda net: compiled_calls.append(net) or ("compiled", net))
    monkeypatch.setattr(_tile, "wants_compile", lambda dev: True)
    net = object()
    lazy = _tile.LazyCompiled(net, "cuda", tile=64)
    full = [np.zeros((64, 64, 3), np.uint8)] * 2
    odd = [np.zeros((30, 64, 3), np.uint8)]
    for _ in range(_tile.COMPILE_AFTER - 1):
        assert lazy.pick(full) is net
    assert lazy.pick(odd) is net                  # odd shapes never count
    assert lazy.pick(full) == ("compiled", net)   # the COMPILE_AFTER-th
    assert compiled_calls == [net]
    assert lazy.pick(full) == ("compiled", net)   # cached, not rebuilt
    assert compiled_calls == [net]
    lazy.give_up(RuntimeError("no triton"))
    assert lazy.pick(full) is net and not lazy.enabled


def test_compile_is_off_without_a_card_or_when_told(monkeypatch):
    monkeypatch.delenv("MEDIA_COMPOST_UPSCALE_COMPILE", raising=False)
    assert not _tile.wants_compile("mps")
    assert not _tile.wants_compile("cpu")
    monkeypatch.setenv("MEDIA_COMPOST_UPSCALE_COMPILE", "0")
    assert not _tile.wants_compile("cuda")
    monkeypatch.setenv("MEDIA_COMPOST_UPSCALE_COMPILE", "1")
    assert _tile.wants_compile("cpu")
    net = object()
    lazy = _tile.LazyCompiled(net, "cpu", tile=8)
    monkeypatch.setattr(_tile, "_compile", lambda n: (_ for _ in ()).throw(RuntimeError("boom")))
    full = [np.zeros((8, 8, 3), np.uint8)]
    for _ in range(_tile.COMPILE_AFTER):
        assert lazy.pick(full) is net           # a failing compile: eager
    assert not lazy.enabled


def test_settings_take_the_nets_own_tile_and_overlap_under_the_environment(monkeypatch):
    monkeypatch.delenv("MEDIA_COMPOST_UPSCALE_TILE", raising=False)
    monkeypatch.delenv("MEDIA_COMPOST_UPSCALE_OVERLAP", raising=False)
    tile, overlap, _ = _tile.settings("cpu", tile=1024, overlap=256)
    assert (tile, overlap) == (1024, 256)
    tile, overlap, _ = _tile.settings("cpu")
    assert (tile, overlap) == (_tile.DEFAULT_TILE, _tile.DEFAULT_OVERLAP)
    monkeypatch.setenv("MEDIA_COMPOST_UPSCALE_TILE", "300")
    monkeypatch.setenv("MEDIA_COMPOST_UPSCALE_OVERLAP", "40")
    assert _tile.settings("cpu", tile=1024, overlap=256)[:2] == (300, 40)


def _windowed(scale, window=8):
    """An operator with a WINDOW GRID anchored at the input's origin — every
    8x8 block replaced by its mean, then nearest x`scale` — the shape of a
    Swin net: a tile that starts off the grid sees different blocks and
    answers differently everywhere, not at the seams."""
    def forward(tiles):
        out = []
        for t in tiles:
            f = t.astype(np.float32)
            h, w = f.shape[:2]
            hh, ww = h - h % window, w - w % window
            g = f[:hh, :ww].reshape(hh // window, window, ww // window, window, -1)
            m = g.mean(axis=(1, 3), keepdims=True)
            r = f.copy()
            r[:hh, :ww] = np.broadcast_to(m, g.shape).reshape(hh, ww, -1)
            out.append(np.repeat(np.repeat(r, scale, axis=0), scale, axis=1))
        return out
    return forward


def test_a_windowed_net_needs_its_tile_origins_on_the_grid():
    """The defect the grid exists for: on a 96 px tall picture with 64 px
    tiles the pulled-back last row starts at y = 32 — on an 8 px grid by
    luck; on a 100 px one it starts at 36, off it, and the windowed
    operator's tiled result differs from the untiled one over the whole
    last row. With `grid=8` the caller pads to a multiple of 8, every
    origin lands on it, and the two agree to the pixel."""
    rng = np.random.default_rng(3)
    fwd = _windowed(2)
    img = rng.integers(0, 256, size=(100, 104, 3), dtype=np.uint8)
    whole = np.asarray(fwd([img])[0])
    off = _tile.upscale(img, 2, fwd, tile=64, overlap=16, batch=2)
    assert not np.array_equal(off, whole)                 # the defect
    padded = np.pad(img, ((0, 4), (0, 0), (0, 0)), mode="symmetric")
    ref = np.asarray(fwd([padded])[0])[:200, :208]
    on = _tile.upscale(padded, 2, fwd, tile=64, overlap=16, batch=2,
                       grid=8)[:200, :208]
    np.testing.assert_array_equal(on, ref)
    # every origin on the grid, the step rounded down to it
    for t in _tile.plan(104, 104, tile=64, overlap=20, grid=8):
        assert t.x0 % 8 == 0 and t.y0 % 8 == 0
    with pytest.raises(ValueError):
        _tile.plan(100, 104, tile=64, overlap=16, grid=8)   # not padded
    with pytest.raises(ValueError):
        _tile.plan(104, 104, tile=60, overlap=16, grid=8)   # tile off grid
