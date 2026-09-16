"""ModelHost out-of-process worker lifecycle: warm reuse, evict-on-switch and
idle-TTL, exercised with the dependency-free `_echo` plugin (no heavy models)."""

from __future__ import annotations

import time

import pytest
from PIL import Image

from media_compost.ui.plugins.host import ModelHost
from media_compost.ui.plugins.impl import _echo
from media_compost.ui.plugins.registry import LoadedPlugin


#: THE ONE FILE THAT WANTS REAL WORKERS. The app suite refuses to spawn them
#: (`tests/ui/conftest.py`), which is exactly what this file is about.
pytestmark = pytest.mark.real_worker


def _resolver():
    lp = LoadedPlugin(_echo)
    return lambda model_id: lp if model_id in ("echo_a", "echo_b") else None


def _pid(text: str) -> str:
    # "echo_a|pid=12345" -> "12345"
    return text.split("pid=", 1)[1]


def test_warm_reuse_same_model():
    host = ModelHost(resolve=_resolver(), ttl=30)
    img = Image.new("RGB", (8, 8))
    try:
        a = host.run("caption", "echo_a", img)
        b = host.run("caption", "echo_a", img)
        # Same model -> same worker process reused (no reload).
        assert a == b
        assert _pid(a) == _pid(b)
    finally:
        host.shutdown()


def test_switch_model_respawns():
    host = ModelHost(resolve=_resolver(), ttl=30)
    img = Image.new("RGB", (8, 8))
    try:
        a = host.run("caption", "echo_a", img)
        b = host.run("caption", "echo_b", img)  # different model -> new worker
        assert _pid(a) != _pid(b)
        # Switching back spawns yet another fresh worker.
        a2 = host.run("caption", "echo_a", img)
        assert _pid(a2) != _pid(a)
    finally:
        host.shutdown()


def test_idle_ttl_evicts():
    host = ModelHost(resolve=_resolver(), ttl=0.4)
    img = Image.new("RGB", (8, 8))
    try:
        a = host.run("caption", "echo_a", img)
        time.sleep(0.9)  # exceed the idle TTL -> worker stopped
        b = host.run("caption", "echo_a", img)  # must spawn a fresh worker
        assert _pid(a) != _pid(b)
    finally:
        host.shutdown()


def test_unknown_model_raises():
    host = ModelHost(resolve=_resolver(), ttl=30)
    img = Image.new("RGB", (8, 8))
    try:
        with pytest.raises(RuntimeError):
            host.run("caption", "nope", img)
    finally:
        host.shutdown()


def test_an_image_survives_the_wire_in_BOTH_directions():
    """The IPC format has to hold what it is handed, both ways.

    Every image a model sees crosses a process boundary as a temp file, so
    the format is hours of wall clock on a large batch job — 35.6 ms a
    round trip as PNG against 2.0 ms as uncompressed TIFF, on 1.9 MP RGBA.
    BMP is faster still and is the trap: Pillow writes RGBA to it as RGB,
    SILENTLY, so the alpha channel would just stop arriving. Hence a
    gradient alpha here, compared pixel for pixel.
    """
    src = Image.new("RGBA", (37, 23))
    src.putpixel((0, 0), (12, 34, 56, 78))
    src.putalpha(Image.linear_gradient("L").resize(src.size))

    host = ModelHost(resolve=_resolver(), ttl=30)
    try:
        got = host.run("bg_removal", "echo_a", src)
    finally:
        host.shutdown()

    assert got.mode == src.mode == "RGBA"
    assert got.size == src.size
    assert list(got.getdata()) == list(src.getdata())


def test_a_batch_crosses_the_wire_intact_and_in_order():
    """`run_batch` is the path every 1M-item job takes, one file per item."""
    srcs = [Image.new("RGBA", (9, 7), (i, i * 2 % 256, 3, 200 - i))
            for i in range(5)]
    host = ModelHost(resolve=_resolver(), ttl=30)
    try:
        out = host.run_batch("bg_removal", "echo_a", srcs)
    finally:
        host.shutdown()

    assert len(out) == len(srcs)
    for got, src in zip(out, srcs):
        assert got.mode == "RGBA" and got.size == src.size
        assert list(got.getdata()) == list(src.getdata())


def test_paths_go_to_the_worker_and_answers_come_back_in_order(tmp_path):
    """`submit_paths` is the batch job's path: the worker opens the library's
    files itself, and the host reads nothing but the answer. The echo plugin
    answers with text, so the wire's order is what is checked."""
    files = []
    for i in range(4):
        p = tmp_path / f"p{i}.png"
        Image.new("RGB", (8 + i, 6), (i, 0, 0)).save(p)
        files.append(str(p))
    host = ModelHost(resolve=_resolver(), ttl=30)
    try:
        first = host.submit_paths("caption", "echo_a", files[:2], max_dim=512,
                                  prefetch=files[2:])
        # A second chunk on the wire before the first is collected — the
        # pipeline the batch loop keeps full — and each answer is its own.
        second = host.submit_paths("caption", "echo_a", files[2:], max_dim=512)
        a = first.result()
        b = second.result()
        assert len(a) == 2 and len(b) == 2
        assert first.errors == [] and second.errors == []
        # Each answer names its own picture: the echo plugin's `prepare`
        # hands `run` the size, so the wire's order is visible.
        assert [x.split("|")[2] for x in a + b] == ["8x6", "9x6", "10x6", "11x6"]
        # And `prepare` ran in a DECODE PROCESS, not the worker: the plugin
        # declares it, so the worker's pool is processes (see
        # `worker._DECODE_PROCS`), each with the plugin's own light handle.
        worker_pid = a[0].split("|")[1]
        decoded_in = {x.split("decoded_in=")[1] for x in a + b}
        assert worker_pid.startswith("pid=")
        assert worker_pid[4:] not in decoded_in, "decoded in the worker itself"
        # Collected: the lock is free, and an ordinary call finds the same
        # warm worker (and, as a picture, takes the plain path).
        plain = host.run("caption", "echo_a", Image.new("RGB", (4, 4)))
        assert plain == f"echo_a|{worker_pid}"
    finally:
        host.shutdown()


def test_a_picture_that_cannot_be_read_is_its_own_slot_and_nothing_else(tmp_path):
    """A selection of a million must not end on one file: the unreadable
    one answers None with its error, and its neighbours are answered."""
    good = tmp_path / "ok.png"
    Image.new("RGB", (8, 6)).save(good)
    bad = tmp_path / "missing.png"
    host = ModelHost(resolve=_resolver(), ttl=30)
    try:
        h = host.submit_paths("caption", "echo_a", [str(good), str(bad), "", str(good)])
        out = h.result()
    finally:
        host.shutdown()
    assert out[0] is not None and out[3] is not None
    assert out[1] is None and out[2] is None
    assert [k for k, _ in h.errors] == [1, 2]
    assert "missing.png" in h.errors[0][1]


def test_collecting_a_later_handle_first_collects_the_earlier_one(tmp_path):
    p = tmp_path / "p.png"
    Image.new("RGB", (8, 6)).save(p)
    host = ModelHost(resolve=_resolver(), ttl=30)
    try:
        first = host.submit_paths("caption", "echo_a", [str(p)])
        second = host.submit_paths("caption", "echo_a", [str(p), str(p)])
        assert len(second.result()) == 2
        assert len(first.result()) == 1
    finally:
        host.shutdown()


def test_a_picture_comes_back_over_the_path_request(tmp_path):
    """`submit_paths(images=True)` is the per-item kinds' path: the plugin
    answers with a PICTURE, written to a file in the worker's scratch and
    read back here — the other direction across the wire, where a format
    that cannot hold what it was given loses it silently."""
    src = Image.new("RGBA", (9, 7), (10, 20, 30, 200))
    p = tmp_path / "p.png"
    src.save(p)
    host = ModelHost(resolve=_resolver(), ttl=30)
    try:
        h = host.submit_paths("bg_removal", "echo_a", [str(p)], images=True)
        out = h.result()
    finally:
        host.shutdown()
    assert h.errors == []
    got = out[0]
    assert got.mode == "RGBA" and got.size == src.size
    assert list(got.getdata()) == list(src.getdata())


def test_default_ttl_reads_the_environment(monkeypatch):
    """Ten minutes by default (a model costs 1-7 s to bring up; a person
    clicks minutes apart), `MEDIA_COMPOST_MODEL_TTL` in seconds."""
    from media_compost.ui.plugins import host as h

    monkeypatch.delenv("MEDIA_COMPOST_MODEL_TTL", raising=False)
    assert h.default_ttl() == h.DEFAULT_TTL == 600.0
    assert ModelHost(resolve=_resolver())._ttl == 600.0
    monkeypatch.setenv("MEDIA_COMPOST_MODEL_TTL", "45")
    assert h.default_ttl() == 45.0
    monkeypatch.setenv("MEDIA_COMPOST_MODEL_TTL", "nope")
    assert h.default_ttl() == h.DEFAULT_TTL


def test_release_idle_drops_a_warm_worker_and_leaves_a_busy_one():
    """A training run asks the host for the card back: an idle worker is
    stopped (the next call spawns afresh), one mid-call is left alone."""
    host = ModelHost(resolve=_resolver(), ttl=30)
    img = Image.new("RGB", (8, 8))
    try:
        assert host.release_idle() is False          # nothing loaded yet
        a = host.run("caption", "echo_a", img)
        assert host.release_idle() is True
        assert host._worker is None
        b = host.run("caption", "echo_a", img)
        assert _pid(a) != _pid(b)
        # busy: answers still to collect (a batch mid-flight); left alone
        host._inflight.append(object())
        try:
            assert host.release_idle() is False
            assert host._worker is not None
        finally:
            host._inflight.clear()
    finally:
        host.shutdown()
