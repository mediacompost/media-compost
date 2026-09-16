"""The torch-free GPU probe (`media_compost/train/gpu.py`) — the AMD half.

No AMD hardware runs these tests, so they hold the PARSERS to captured
rocm-smi output shapes and the enumeration wiring to its fallbacks; the
live-subprocess halves stay best-effort by design. The key names in the
fixtures are real ones — rocm-smi renames them across ROCm releases, which
is exactly why the parser matches substrings and these fixtures deliberately
use two different vintages.
"""

from __future__ import annotations

import json

from media_compost.train import gpu

# A ROCm 5/6-era payload: "Card Series" names the card, edge temperature
# present, "Average Graphics Package Power". The "system" key and the
# memory-sensor temperature are the classic parser traps: one is not a card,
# the other contains the word "memory" without being a VRAM figure.
ROCM_STATS_V5 = {
    "card0": {
        "GPU use (%)": "7",
        "VRAM Total Memory (B)": "25753026560",
        "VRAM Total Used Memory (B)": "1057456128",
        "Temperature (Sensor edge) (C)": "41.0",
        "Temperature (Sensor junction) (C)": "44.0",
        "Temperature (Sensor memory) (C)": "46.0",
        "Average Graphics Package Power (W)": "35.0",
        "Fan speed (%)": "20",
        "Card Series": "AMD Radeon RX 7900 XTX",
        "Card Model": "0x744c",
        "Card Vendor": "Advanced Micro Devices, Inc. [AMD/ATI]",
    },
    "system": {"Driver version": "6.7.0"},
}

# A newer vintage: "Device Name" instead of "Card Series", junction-only
# temperature, "Current Socket Graphics Package Power" (APU spelling).
ROCM_STATS_V6 = {
    "card0": {
        "GPU use (%)": "12",
        "VRAM Total Memory (B)": "17163091968",
        "VRAM Total Used Memory (B)": "2147483648",
        "Temperature (Sensor junction) (C)": "52.0",
        "Current Socket Graphics Package Power (W)": "18.5",
        "Device Name": "AMD Radeon RX 9070",
    },
}


def _stat_map(device: dict) -> dict[str, float]:
    return {s["key"]: s["value"] for s in device["stats"]}


def test_parse_rocm_smi_stats_v5_shape():
    out = gpu._parse_rocm_smi_stats(json.dumps(ROCM_STATS_V5))
    assert out is not None and len(out) == 1
    dev = out[0]
    assert dev["key"] == "gpu0"
    assert dev["label"] == "AMD Radeon RX 7900 XTX"
    stats = _stat_map(dev)
    assert stats["util"] == 7.0
    assert stats["vram"] == round(1057456128 / 2**30, 1)
    assert stats["vram_total"] == round(25753026560 / 2**30, 1)
    # Edge, not junction and not the memory sensor.
    assert stats["temp"] == 41.0
    assert stats["power"] == 35.0
    assert stats["fan"] == 20.0


def test_parse_rocm_smi_stats_v6_shape():
    out = gpu._parse_rocm_smi_stats(json.dumps(ROCM_STATS_V6))
    assert out is not None
    dev = out[0]
    assert dev["label"] == "AMD Radeon RX 9070"
    stats = _stat_map(dev)
    # Junction is the fallback when no edge sensor reports.
    assert stats["temp"] == 52.0
    assert stats["power"] == 18.5
    assert "fan" not in stats  # omitted, never faked


def test_parse_rocm_smi_stats_card_order_is_numeric():
    # card10 must not sort before card2 (a lexical sort does exactly that).
    payload = {}
    for n in (10, 0, 2):
        payload[f"card{n}"] = {"GPU use (%)": str(n), "Card Series": f"GPU {n}"}
    out = gpu._parse_rocm_smi_stats(json.dumps(payload))
    assert [d["label"] for d in out] == ["GPU 0", "GPU 2", "GPU 10"]
    # Keys are positional, matching the cuda:N ids train_devices hands out.
    assert [d["key"] for d in out] == ["gpu0", "gpu1", "gpu2"]


def test_parse_rocm_smi_stats_rejects_garbage():
    assert gpu._parse_rocm_smi_stats("not json at all") is None
    assert gpu._parse_rocm_smi_stats(json.dumps(["a", "list"])) is None
    assert gpu._parse_rocm_smi_stats(json.dumps({"system": {}})) is None


def test_parse_rocm_smi_names():
    assert gpu._parse_rocm_smi_names(json.dumps(ROCM_STATS_V5)) == [
        "AMD Radeon RX 7900 XTX"]
    # No recognised name key at all still yields a row per card — the
    # device exists whether or not it can be named.
    assert gpu._parse_rocm_smi_names(json.dumps(
        {"card0": {"GPU use (%)": "1"}})) == ["AMD GPU"]
    assert gpu._parse_rocm_smi_names("garbage") == []


def test_amd_names_sysfs_fallback(tmp_path, monkeypatch):
    """No rocm-smi: /dev/kfd plus the DRM vendor ids answer, unnamed."""
    drm = tmp_path / "drm"
    kfd = tmp_path / "kfd"
    kfd.write_text("")
    for card, vendor in (("card0", "0x1002"), ("card1", "0x10de")):
        d = drm / card / "device"
        d.mkdir(parents=True)
        (d / "vendor").write_text(vendor + "\n")
    (drm / "renderD128").mkdir()  # not a cardN entry; must be ignored
    monkeypatch.setattr(gpu.shutil, "which", lambda name: None)
    monkeypatch.setattr(gpu, "_KFD_PATH", str(kfd))
    monkeypatch.setattr(gpu, "_DRM_DIR", str(drm))
    # Only the AMD card counts; the NVIDIA one belongs to the other probe.
    assert gpu._amd_names() == ["AMD GPU"]


def test_amd_names_requires_kfd(tmp_path, monkeypatch):
    """A DRM card without /dev/kfd is a display driver, not a compute stack —
    ROCm torch cannot use it, so it must not become a schedulable device."""
    drm = tmp_path / "drm"
    d = drm / "card0" / "device"
    d.mkdir(parents=True)
    (d / "vendor").write_text("0x1002\n")
    monkeypatch.setattr(gpu.shutil, "which", lambda name: None)
    monkeypatch.setattr(gpu, "_KFD_PATH", str(tmp_path / "no-kfd"))
    monkeypatch.setattr(gpu, "_DRM_DIR", str(drm))
    assert gpu._amd_names() == []


def test_train_devices_offers_amd_as_cuda(monkeypatch):
    """ROCm torch drives AMD GPUs through the torch.cuda API, so the ids the
    manager schedules on — and pins via CUDA_VISIBLE_DEVICES — are cuda:N."""
    monkeypatch.setattr(gpu, "_train_devices", None)
    monkeypatch.setattr(gpu, "_nvidia_names", lambda: [])
    monkeypatch.setattr(gpu, "_amd_names",
                        lambda: ["AMD Radeon RX 7900 XTX", "AMD Radeon RX 9070"])
    assert gpu.train_devices() == [
        {"id": "cuda:0", "label": "AMD Radeon RX 7900 XTX"},
        {"id": "cuda:1", "label": "AMD Radeon RX 9070"},
    ]


def test_train_devices_nvidia_wins_a_mixed_box(monkeypatch):
    """One torch build drives one vendor, and the env setup installs the CUDA
    build when an NVIDIA driver is present."""
    monkeypatch.setattr(gpu, "_train_devices", None)
    monkeypatch.setattr(gpu, "_nvidia_names", lambda: ["RTX 5070 Ti"])
    monkeypatch.setattr(gpu, "_amd_names", lambda: ["AMD Radeon RX 9070"])
    assert gpu.train_devices() == [{"id": "cuda:0", "label": "RTX 5070 Ti"}]


def test_gpus_via_rocm_smi_wiring(monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which",
                        lambda name: "/usr/bin/rocm-smi"
                        if name == "rocm-smi" else None)
    monkeypatch.setattr(gpu, "_run",
                        lambda cmd, timeout=3: json.dumps(ROCM_STATS_V5))
    out = gpu._gpus_via_rocm_smi()
    assert out is not None
    assert out[0]["label"] == "AMD Radeon RX 7900 XTX"


def test_gpus_via_rocm_smi_absent_cli(monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda name: None)
    assert gpu._gpus_via_rocm_smi() is None


# ---- powermetrics: one attempt, then a hint ---------------------------------
#
# macOS keeps GPU temperature/power/fan behind root and offers no way to ask
# for it at runtime, so the probe is `sudo -n` — which cannot prompt — and the
# only thing left to get right is how often it gives up.


class _Refused:
    """`sudo -n` with no passwordless rule: immediate non-zero, no prompt."""

    returncode = 1
    stdout = ""


def _count_attempts(monkeypatch) -> list:
    calls: list = []

    def run(cmd, **kw):
        calls.append(cmd)
        return _Refused()

    monkeypatch.setattr(gpu.subprocess, "run", run)
    monkeypatch.setattr(gpu, "_pm_denied", False)
    # The sampler list is asked for once per process and cached; pin it so a
    # test measuring sudo attempts is not also measuring that question.
    monkeypatch.setattr(gpu, "_samplers_available", ("smc", "gpu_power"))
    return calls


def test_a_refused_powermetrics_is_attempted_once_per_process(monkeypatch):
    """It retried every five minutes, which on a machine without the sudoers
    rule — nearly all of them — is a failed sudo and an auth-log entry every
    five minutes for as long as the Train tab is open, polling at 2 s. The
    retry could never pay off BY ITSELF: whether the rule exists does not
    change while the server runs unless somebody adds it, which is what the
    Try again button (`clear_denied`) is for."""
    calls = _count_attempts(monkeypatch)
    for _ in range(50):
        assert gpu._apple_powermetrics_stats() == []
    assert len(calls) == 1, "one attempt, however often the bar polls"
    assert calls[0][:2] == ["sudo", "-n"], "never a prompting sudo"
    assert gpu.powermetrics_denied()


def test_try_again_re_arms_the_probe(monkeypatch):
    """The latch stops the POLL asking over and over; it must not stop the
    person who has just added the sudoers rule the hint told them to add.
    Without this the only way to pick the rule up is restarting the server."""
    calls = _count_attempts(monkeypatch)
    sudos = lambda: [c for c in calls if c[0] == "sudo"]  # noqa: E731
    assert gpu._apple_powermetrics_stats() == []
    assert gpu._apple_powermetrics_stats() == []
    assert len(sudos()) == 1
    gpu.clear_denied()
    assert not gpu.powermetrics_denied()
    assert gpu._apple_powermetrics_stats() == []
    assert len(sudos()) == 2, "asking again asks again"


_HELP = """\
The following samplers are supported by --samplers:

    cpu_power         cpu power and frequency info
    gpu_power         gpu power and frequency info

and the following sampler groups are supported by --samplers:

    all           cpu_power,gpu_power
"""


def test_only_the_samplers_this_powermetrics_HAS_are_asked_for(monkeypatch):
    """`smc` (die temperature and fan) is gone from powermetrics on current
    macOS, and an unknown sampler fails the WHOLE invocation — rc 64,
    "unrecognized sampler: smc" — so `gpu_power` was never sampled either.
    That is indistinguishable from a refused sudo: measured on a Mac16,11
    whose sudoers rule WAS in place and working, the app reported nothing and
    went on telling its owner to add the rule they already had."""
    monkeypatch.setattr(gpu, "_samplers_available", None)
    monkeypatch.setattr(gpu, "_run", lambda cmd, timeout=3: _HELP)
    assert gpu._powermetrics_samplers() == "gpu_power"


def test_an_unreadable_help_asks_for_everything(monkeypatch):
    """The question is best-effort: a powermetrics that answers something
    unexpected must not lose the samplers it may well have."""
    monkeypatch.setattr(gpu, "_samplers_available", None)
    monkeypatch.setattr(gpu, "_run", lambda cmd, timeout=3: "???")
    assert gpu._powermetrics_samplers() == "smc,gpu_power"


def test_a_refusal_tells_the_box_to_explain_itself(monkeypatch):
    """Without the hint the Apple box is simply thinner than an NVIDIA one,
    with nothing connecting that to a sudoers rule nobody has heard of. The
    value is a KEY — the sentence lives in the frontend's catalogs."""
    _count_attempts(monkeypatch)
    monkeypatch.setattr(gpu.shutil, "which", lambda name: "/usr/bin/ioreg")
    monkeypatch.setattr(gpu, "_run",
                        lambda cmd, timeout=3: '"Device Utilization %" = 42')
    monkeypatch.setattr(gpu, "_sysctl", lambda name: "Apple M4 Pro")
    monkeypatch.setattr(gpu, "_apple_fan_stats", list)  # a fanless Mac
    out = gpu._gpus_via_ioreg()
    assert out is not None
    assert out[0]["hint"] == gpu.POWERMETRICS_HINT
    assert [s["key"] for s in out[0]["stats"]] == ["util"]


def test_the_fan_needs_no_sudo_and_is_reported_anyway(monkeypatch):
    """The fan came in as part of powermetrics' root-only `smc` sampler and
    never belonged there: the SMC is an IOKit service any user may open. So a
    machine with no sudoers rule at all still reports its fan — and the hint
    beside it no longer claims otherwise."""
    _count_attempts(monkeypatch)  # sudo refused throughout
    monkeypatch.setattr(gpu.shutil, "which", lambda name: "/usr/bin/ioreg")
    monkeypatch.setattr(gpu, "_run",
                        lambda cmd, timeout=3: '"Device Utilization %" = 42')
    monkeypatch.setattr(gpu, "_sysctl", lambda name: "Apple M4 Pro")
    monkeypatch.setattr(gpu, "_smc_read",
                        lambda key: {"FNum": 2.0, "F0Ac": 1001.0,
                                     "F1Ac": 1980.0}.get(key))
    out = gpu._gpus_via_ioreg()
    assert out is not None
    got = {s["key"]: s["value"] for s in out[0]["stats"]}
    assert got["fan"] == 1980.0, "the fastest fan, not whichever came first"


def test_a_mac_with_no_fan_reports_none(monkeypatch):
    """`FNum` 0 is a Mac mini, an iMac, a passively cooled laptop — which is
    the whole reason the count is read rather than assumed."""
    monkeypatch.setattr(gpu, "_smc_read",
                        lambda key: 0.0 if key == "FNum" else 1001.0)
    assert gpu._apple_fan_stats() == []


def test_an_unreadable_smc_is_not_asked_twice(monkeypatch):
    """A Mac whose SMC cannot be opened must not pay for an IOKit open per
    sample — the same reasoning as the powermetrics latch, without the
    auth-log entry."""
    monkeypatch.setattr(gpu, "_smc_conn", None)
    monkeypatch.setattr(gpu, "_smc_failed", False)
    opens = []

    def cdll(name):
        opens.append(name)
        raise OSError("no IOKit here")

    monkeypatch.setattr(gpu.ctypes, "CDLL", cdll)
    assert gpu._apple_fan_stats() == []
    assert gpu._apple_fan_stats() == []
    assert len(opens) == 1


def test_a_granted_powermetrics_reports_and_leaves_no_hint(monkeypatch):
    """The other side: with the rule in place the figures parse and the box
    has nothing to explain."""
    sample = ("GPU die temperature: 47.30 C\n"
              "GPU Power: 1234 mW\n"
              "Fan: 1980 rpm\n")
    monkeypatch.setattr(gpu, "_pm_denied", False)
    monkeypatch.setattr(gpu.subprocess, "run",
                        lambda cmd, **kw: type("P", (), {"returncode": 0,
                                                         "stdout": sample})())
    monkeypatch.setattr(gpu.shutil, "which", lambda name: "/usr/bin/ioreg")
    monkeypatch.setattr(gpu, "_run",
                        lambda cmd, timeout=3: '"Device Utilization %" = 42')
    monkeypatch.setattr(gpu, "_sysctl", lambda name: "Apple M4 Pro")
    out = gpu._gpus_via_ioreg()
    assert out is not None and out[0]["hint"] == ""
    got = {s["key"]: s["value"] for s in out[0]["stats"]}
    assert got == {"util": 42.0, "temp": 47.3, "power": 1.2, "fan": 1980.0}
    assert not gpu.powermetrics_denied()
