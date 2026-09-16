"""A stat carries a ceiling only where the HARDWARE states one.

The Train footer draws a bar for anything with a maximum, and a bar is a
claim: it says the value is a share of something real. So the rule is that
`max` is present only where the device reports it, and absent where the
honest answer is "nobody said" — a bar drawn against a guessed ceiling is a
number the reader cannot check.

Two ceilings are exact and need no probing at all: a fan reported as a
PERCENTAGE is already a share of its own maximum, and GPU utilisation is the
same. A power limit is enforced by the driver and is read from it. GPU
temperature is the interesting one: NVML gives an absolute slowdown
threshold, while nvidia-smi on a current driver reports MARGINS instead
("GPU Shutdown T.Limit Temp: -5 C" beside a current temperature of 43), so
the temperature bar exists on one path and honestly does not on the other.
"""

from __future__ import annotations

from media_compost.train import gpu


def test_a_ceiling_the_device_states_is_carried():
    s = gpu._stat("power", "Power", 11.4, "W", 600)
    assert s["max"] == 600.0


def test_no_ceiling_means_no_key_rather_than_a_zero():
    """A 0 would be a ceiling of zero, which divides badly and draws a full
    bar; the frontend keys the bar on the field's PRESENCE."""
    assert "max" not in gpu._stat("temp", "Temp", 43, "°C", None)
    assert "max" not in gpu._stat("temp", "Temp", 43, "°C", 0)


def test_a_percentage_fan_is_its_own_ceiling():
    stats = {s["key"]: s for s in
             gpu._gpu_stats(10, 2.0, 32.0, 43, 11.4, fan=37, power_max=600)}
    assert stats["fan"]["unit"] == "%" and stats["fan"]["max"] == 100
    assert stats["util"]["max"] == 100
    assert stats["power"]["max"] == 600.0


def test_a_temperature_with_no_stated_threshold_gets_no_bar():
    stats = {s["key"]: s for s in
             gpu._gpu_stats(10, 2.0, 32.0, 43, 11.4, power_max=600)}
    assert "max" not in stats["temp"]


def test_nvidia_smi_reads_the_enforced_power_limit(monkeypatch):
    """The extra column is the whole point — the draw means little without
    the limit it is a share of (11 W reads very differently against 600 W
    than against 70)."""
    row = ("NVIDIA GeForce RTX 5090, 0, 733, 32607, 43, 11.39, 0, 600.00")
    monkeypatch.setattr(gpu.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(gpu, "_run", lambda *a, **k: row + "\n")
    devices = gpu._gpus_via_nvidia_smi()
    stats = {s["key"]: s for s in devices[0]["stats"]}
    assert stats["power"]["value"] == 11.4
    assert stats["power"]["max"] == 600.0
    assert stats["fan"]["max"] == 100


def test_a_card_that_reports_no_limit_still_reports_its_draw(monkeypatch):
    """"[N/A]" is what a card without a readable limit gives, and losing the
    power reading over it would be worse than losing the bar."""
    row = "NVIDIA T400, 0, 100, 2048, 40, 5.00, [N/A], [N/A]"
    monkeypatch.setattr(gpu.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(gpu, "_run", lambda *a, **k: row + "\n")
    stats = {s["key"]: s for s in gpu._gpus_via_nvidia_smi()[0]["stats"]}
    assert stats["power"]["value"] == 5.0
    assert "max" not in stats["power"]
    assert "fan" not in stats
