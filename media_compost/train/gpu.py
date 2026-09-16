"""Best-effort live system stats for the Train tab's stats boxes.

Returns a list of DEVICES — one per GPU (all of them, on multi-GPU hosts),
plus CPU and RAM — each ``{key, label, stats: [{key, label, value, unit}]}``.
The frontend renders one box per device and only the stats that arrive, so
platforms simply omit what they can't measure:

- NVIDIA: name, utilization, VRAM used/total, temperature, power and fan for
  every GPU via ``pynvml`` when importable, else one ``nvidia-smi`` CSV query.
- AMD: the same stats via one ``rocm-smi --json`` query, parsed by key
  SUBSTRING because the key names drift across ROCm releases
  ("Temperature (Sensor edge) (C)", "Average Graphics Package Power (W)").
- Apple Silicon: chip name, GPU busy % and GPU-allocated memory ("In use
  system memory" — unified, so the total is system RAM) from IORegistry
  (``ioreg``), plus FAN rpm read straight off the SMC through IOKit, which
  needs no privileges at all. Temperature and power are ROOT-ONLY on macOS
  (``powermetrics``): a non-interactive ``sudo -n powermetrics`` is attempted
  and used when the admin granted passwordless sudo for it; otherwise those
  stats are omitted rather than faked (the refusal is latched, so no repeated
  sudo attempts, and ``clear_denied()`` is how the UI's Try again re-asks
  once the rule has been added).
- CPU: model name + utilization (%). RAM: used / total GB.

No third-party deps: sysctl / vm_stat / ioreg on macOS, /proc on Linux.
Sampling is cached for ~1 s so a 2 s UI poll costs one probe at most.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import threading
import time

_lock = threading.Lock()
_cached: list[dict] = []
_cached_at = 0.0
_TTL = 1.0


def _stat(key: str, label: str, value: float, unit: str,
          maximum: float | None = None) -> dict:
    """One metric. `maximum` is what the HARDWARE says the ceiling is.

    Present only where the device actually reports one — a bar drawn against
    a guessed ceiling is a number the reader cannot check, and the two that
    matter are exact: a fan is reported as a PERCENTAGE of its own maximum,
    and the power limit is a value the driver enforces. GPU temperature is
    deliberately absent on the nvidia-smi path: this driver reports its
    thresholds as MARGINS ("GPU Shutdown T.Limit Temp: -5 C" beside a current
    temperature of 43), which cannot be turned into an absolute limit.
    """
    out = {"key": key, "label": label, "value": round(value, 1), "unit": unit}
    if maximum is not None and maximum > 0:
        out["max"] = round(float(maximum), 1)
    return out


def _device(key: str, label: str, stats: list[dict], hint: str = "") -> dict:
    """One stats box. ``hint`` is a KEY, never a sentence — see
    `POWERMETRICS_HINT`; the words live in the frontend's catalogs."""
    return {"key": key, "label": label, "stats": stats, "hint": hint}


def _run(cmd: list[str], timeout: float = 3) -> str:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout).stdout


# ---- GPUs ---------------------------------------------------------------


def _gpu_stats(util, mem_used_gb, mem_total_gb, temp, power,
               fan=None, power_max=None, temp_max=None) -> list[dict]:
    out = [
        _stat("util", "GPU", util, "%", 100),
        _stat("vram", "VRAM", mem_used_gb, "GB"),
        _stat("vram_total", "of", mem_total_gb, "GB"),
        _stat("temp", "Temp", temp, "°C", temp_max),
        _stat("power", "Power", power, "W", power_max),
    ]
    if fan is not None:
        # A percentage IS a share of its own maximum, so this one needs no
        # probing — unlike the rpm reading the Apple and ROCm paths give,
        # which has no stated ceiling and so gets no bar.
        out.append(_stat("fan", "Fan", fan, "%", 100))
    return out


def _gpus_via_pynvml() -> list[dict] | None:
    try:
        import pynvml  # type: ignore
    except ImportError:
        return None
    try:
        pynvml.nvmlInit()
        out = []
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode()
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            try:
                # mW -> W. The enforced limit, not the board maximum.
                power_max = pynvml.nvmlDeviceGetEnforcedPowerLimit(h) / 1000.0
            except Exception:  # noqa: BLE001 - not every card reports one
                power_max = None
            try:
                # NVML gives the SLOWDOWN threshold as an absolute
                # temperature, which nvidia-smi on this driver does not — it
                # reports margins instead. So a temperature bar exists on the
                # NVML path and honestly does not on the other.
                temp_max = float(pynvml.nvmlDeviceGetTemperatureThreshold(
                    h, pynvml.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN))
            except Exception:  # noqa: BLE001
                temp_max = None
            try:
                fan = float(pynvml.nvmlDeviceGetFanSpeed(h))
            except Exception:  # noqa: BLE001 - fanless (or no sensor)
                fan = None
            out.append(_device(f"gpu{i}", name, _gpu_stats(
                pynvml.nvmlDeviceGetUtilizationRates(h).gpu,
                mem.used / 2**30, mem.total / 2**30,
                pynvml.nvmlDeviceGetTemperature(
                    h, pynvml.NVML_TEMPERATURE_GPU),
                pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0,
                fan, power_max=power_max, temp_max=temp_max,
            )))
        pynvml.nvmlShutdown()
        return out or None
    except Exception:  # noqa: BLE001 - no NVML device / driver hiccup
        return None


def _gpus_via_nvidia_smi() -> list[dict] | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        lines = _run([
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,"
            "temperature.gpu,power.draw,fan.speed,power.limit",
            "--format=csv,noheader,nounits",
        ]).strip().splitlines()
        out = []
        for i, line in enumerate(lines):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 6:
                continue
            name = parts[0]
            util, used, total, temp, power = [
                float(x) for x in parts[1:6]
            ]
            try:
                fan = float(parts[6])  # "[N/A]" on fanless cards
            except (IndexError, ValueError):
                fan = None
            try:
                # The limit the driver ENFORCES, which is what the draw is a
                # share of. "[N/A]" where the card does not report one.
                power_max = float(parts[7])
            except (IndexError, ValueError):
                power_max = None
            out.append(_device(f"gpu{i}", name, _gpu_stats(
                util, used / 1024, total / 1024, temp, power, fan,
                power_max=power_max)))
        return out or None
    except Exception:  # noqa: BLE001 - parse/timeout -> no stats
        return None


_ROCM_CARD_RE = re.compile(r"^card(\d+)$")

# Monkeypatchable in tests; there is no AMD hardware in CI, so the sysfs
# fallback is exercised against a fabricated tree.
_KFD_PATH = "/dev/kfd"
_DRM_DIR = "/sys/class/drm"


def _rocm_cards(data: dict) -> list[dict]:
    """The per-card records of a ``rocm-smi --json`` payload, in card order
    (numeric — a lexical sort puts card10 before card2). The payload also
    carries non-card keys ("system") on some versions; only ``cardN`` dicts
    count."""
    cards = []
    for key, vals in data.items():
        m = _ROCM_CARD_RE.match(key)
        if m and isinstance(vals, dict):
            cards.append((int(m.group(1)), vals))
    return [vals for _, vals in sorted(cards, key=lambda c: c[0])]


def _rocm_value(vals: dict, *needles: str) -> float | None:
    """The first numeric value whose key contains every needle
    (case-insensitive). rocm-smi's key names drift across ROCm releases —
    "Average Graphics Package Power (W)" became "Current Socket Graphics
    Package Power (W)" on some parts — so exact key names are a parser that
    breaks on the next driver."""
    for k, v in vals.items():
        lk = k.lower()
        if all(n in lk for n in needles):
            try:
                return float(str(v).strip().rstrip("%"))
            except ValueError:
                continue
    return None


def _rocm_name(vals: dict) -> str:
    for needle in ("card series", "device name", "card model"):
        for k, v in vals.items():
            if needle in k.lower() and str(v).strip():
                return str(v).strip()
    return "AMD GPU"


def _parse_rocm_smi_stats(text: str) -> list[dict] | None:
    """``rocm-smi --json`` → stats boxes. Every stat is optional — the
    platform contract at the top of this file is "omit what can't be
    measured", and which keys a given ROCm version emits varies."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    out = []
    for i, vals in enumerate(_rocm_cards(data)):
        stats: list[dict] = []
        util = _rocm_value(vals, "gpu use")
        if util is not None:
            stats.append(_stat("util", "GPU", util, "%"))
        used = _rocm_value(vals, "vram total used")
        total = _rocm_value(vals, "vram total memory")
        if used is not None and total is not None and total > 0:
            stats.append(_stat("vram", "VRAM", used / 2**30, "GB"))
            stats.append(_stat("vram_total", "of", total / 2**30, "GB"))
        # Edge is the sensor comparable to what nvidia-smi reports; junction
        # runs hotter and would read as an alarming number beside it.
        temp = _rocm_value(vals, "temperature", "edge")
        if temp is None:
            temp = _rocm_value(vals, "temperature", "junction")
        if temp is not None:
            stats.append(_stat("temp", "Temp", temp, "°C"))
        power = _rocm_value(vals, "power (w)")
        if power is not None:
            stats.append(_stat("power", "Power", power, "W"))
        fan = _rocm_value(vals, "fan speed (%)")
        if fan is not None:
            stats.append(_stat("fan", "Fan", fan, "%"))
        if stats:
            out.append(_device(f"gpu{i}", _rocm_name(vals), stats))
    return out or None


def _gpus_via_rocm_smi() -> list[dict] | None:
    if not shutil.which("rocm-smi"):
        return None
    try:
        return _parse_rocm_smi_stats(_run([
            "rocm-smi", "--showproductname", "--showuse", "--showmeminfo",
            "vram", "--showtemp", "--showpower", "--showfan", "--json"]))
    except Exception:  # noqa: BLE001 - parse/timeout -> no stats
        return None


def _parse_rocm_smi_names(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    return [_rocm_name(vals) for vals in _rocm_cards(data)]


def _amd_names() -> list[str]:
    """Names of the AMD GPUs ROCm can drive — torch-free, `_nvidia_names`'s
    shape. rocm-smi where present; else the DRM sysfs vendor ids, gated on
    ``/dev/kfd`` (the kernel's compute interface, which ROCm cannot run
    without — the torch ROCm wheel bundles its own runtime libraries, so an
    absent CLI does not mean torch will not work). The sysfs walk cannot
    name a card, and neither enumeration is guaranteed to be HIP's device
    order — on a mixed multi-GPU box a label may name a sibling card, but
    the pin still lands on a real GPU."""
    if shutil.which("rocm-smi"):
        try:
            names = _parse_rocm_smi_names(
                _run(["rocm-smi", "--showproductname", "--json"]))
            if names:
                return names
        except Exception:  # noqa: BLE001 - parse/timeout
            pass
    if not os.path.exists(_KFD_PATH):
        return []
    names = []
    try:
        entries = sorted(
            (int(m.group(1)), e) for e in os.listdir(_DRM_DIR)
            if (m := _ROCM_CARD_RE.match(e)))
    except OSError:
        return []
    for _, entry in entries:
        try:
            with open(os.path.join(_DRM_DIR, entry, "device", "vendor"),
                      encoding="ascii") as f:
                if f.read().strip().lower() == "0x1002":  # AMD's PCI id
                    names.append("AMD GPU")
        except OSError:
            continue
    return names


def _gpus_via_ioreg() -> list[dict] | None:
    """Apple Silicon: busy % + GPU-allocated (unified) memory from IORegistry,
    the fan straight off the SMC, and temperature/power when passwordless
    powermetrics is available."""
    if not shutil.which("ioreg"):
        return None
    try:
        out = _run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"])
        utils = [int(x) for x in
                 re.findall(r'"Device Utilization %"\s*=\s*(\d+)', out)]
        if not utils:
            return None
        # No VRAM stat here: memory is unified on Apple Silicon, so a
        # dedicated-GPU-memory bar would be misleading — the system card's
        # RAM bar already covers it.
        stats = [_stat("util", "GPU", float(max(utils)), "%")]
        stats.extend(_apple_powermetrics_stats())
        # The fan needs no privileges, so it is asked for whatever the sudo
        # question answered — and only when powermetrics did not already
        # report one (an older macOS whose `smc` sampler still exists).
        if not any(s["key"] == "fan" for s in stats):
            stats.extend(_apple_fan_stats())
        # Say why temperature and power are absent — the box otherwise just
        # looks thinner here than on an NVIDIA machine, with nothing anywhere
        # connecting that to a sudoers rule nobody has heard of.
        hint = POWERMETRICS_HINT if powermetrics_denied() else ""
        return [_device("gpu0", _apple_chip_name(), stats, hint)]
    except Exception:  # noqa: BLE001
        return None


# ---- the fan: SMC, and it needs NO privileges at all -------------------------
#
# THE FAN IS THE ONE OF THE THREE THAT NEVER NEEDED SUDO. It arrived here as
# part of powermetrics' `smc` sampler — root-only, and gone from powermetrics
# altogether on current macOS — but the SMC itself is an IOKit service any
# user may open: `IOServiceOpen(AppleSMC)` and the `kSMCHandleYPCEvent` struct
# call are what every fan-speed menu-bar app has always done. Verified on a
# Mac16,11 as an ordinary user: `FNum` = 1, `F0Ac` = 1001 rpm, `F0Mx` = 4900.
#
# So the fan is read directly and is reported whether or not the sudoers rule
# is in place, which is also why the hint no longer claims a fan is waiting on
# it. ctypes and IOKit only — no third-party dependency, the rule the rest of
# this module follows.
#
# TWO ENCODINGS, because a key says its own type: Apple Silicon answers
# `flt ` (a LITTLE-endian float32 — the 4CC key is big-endian, the payload is
# not) and Intel Macs answer `fpe2`, a big-endian 16-bit fixed point with two
# fractional bits. Reading one as the other is not an error, it is a plausible
# wrong number, so the type is honoured rather than assumed.
#
# ONE LATCH, like powermetrics': a Mac with no readable SMC (or a future one
# that closes the interface) must not pay for an IOKit open per sample.
_SMC_TYPE_FLT = 0x666C7420    # "flt "
_SMC_TYPE_FPE2 = 0x66706532   # "fpe2"
_SMC_TYPE_UI8 = 0x75693820    # "ui8 "
_SMC_TYPE_UI16 = 0x75693136   # "ui16"
_SMC_READ_KEY = 5
_SMC_GET_KEY_INFO = 9

_smc_conn: int | None = None
_smc_failed = False


class _SMCVers(ctypes.Structure):
    _fields_ = [("major", ctypes.c_ubyte), ("minor", ctypes.c_ubyte),
                ("build", ctypes.c_ubyte), ("reserved", ctypes.c_ubyte),
                ("release", ctypes.c_ushort)]


class _SMCPLimit(ctypes.Structure):
    _fields_ = [("version", ctypes.c_ushort), ("length", ctypes.c_ushort),
                ("cpuPLimit", ctypes.c_uint32), ("gpuPLimit", ctypes.c_uint32),
                ("memPLimit", ctypes.c_uint32)]


class _SMCKeyInfo(ctypes.Structure):
    _fields_ = [("dataSize", ctypes.c_uint32), ("dataType", ctypes.c_uint32),
                ("dataAttributes", ctypes.c_ubyte)]


class _SMCKeyData(ctypes.Structure):
    """The one struct `kSMCHandleYPCEvent` takes and returns (80 bytes)."""

    _fields_ = [("key", ctypes.c_uint32), ("vers", _SMCVers),
                ("pLimitData", _SMCPLimit), ("keyInfo", _SMCKeyInfo),
                ("result", ctypes.c_ubyte), ("status", ctypes.c_ubyte),
                ("data8", ctypes.c_ubyte), ("data32", ctypes.c_uint32),
                ("bytes", ctypes.c_ubyte * 32)]


def _smc_open() -> int | None:
    """The AppleSMC connection, opened once and kept."""
    global _smc_conn, _smc_failed
    if _smc_failed:
        return None
    if _smc_conn is not None:
        return _smc_conn
    try:
        iokit = ctypes.CDLL(ctypes.util.find_library("IOKit"))
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        iokit.IOServiceMatching.restype = ctypes.c_void_p
        iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]
        iokit.IOServiceGetMatchingService.restype = ctypes.c_uint
        iokit.IOServiceGetMatchingService.argtypes = [ctypes.c_uint,
                                                     ctypes.c_void_p]
        iokit.IOServiceOpen.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                        ctypes.c_uint,
                                        ctypes.POINTER(ctypes.c_uint)]
        iokit.IOConnectCallStructMethod.argtypes = [
            ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
        service = iokit.IOServiceGetMatchingService(
            0, iokit.IOServiceMatching(b"AppleSMC"))
        if not service:
            raise OSError("no AppleSMC service")
        conn = ctypes.c_uint(0)
        if iokit.IOServiceOpen(service, libc.mach_task_self(), 0,
                               ctypes.byref(conn)) != 0:
            raise OSError("AppleSMC refused the connection")
        _smc_iokit_cache[0] = iokit
        _smc_conn = conn.value
        return _smc_conn
    except Exception:  # noqa: BLE001 - no IOKit, no SMC, a closed interface
        _smc_failed = True
        return None


_smc_iokit_cache: list = [None]


def _smc_read(name: str) -> float | None:
    """One SMC key as a number, or None for absent/unreadable/unknown type."""
    conn = _smc_open()
    if conn is None:
        return None
    iokit = _smc_iokit_cache[0]
    try:
        key = int.from_bytes(name.encode("ascii"), "big")

        def call(inp: _SMCKeyData) -> _SMCKeyData | None:
            out = _SMCKeyData()
            size = ctypes.c_size_t(ctypes.sizeof(_SMCKeyData))
            rc = iokit.IOConnectCallStructMethod(
                conn, 2, ctypes.byref(inp), ctypes.sizeof(_SMCKeyData),
                ctypes.byref(out), ctypes.byref(size))
            return None if rc != 0 or out.result != 0 else out

        info = _SMCKeyData()
        info.key, info.data8 = key, _SMC_GET_KEY_INFO
        got = call(info)
        if got is None:
            return None
        size, dtype = got.keyInfo.dataSize, got.keyInfo.dataType
        read = _SMCKeyData()
        read.key, read.data8 = key, _SMC_READ_KEY
        read.keyInfo.dataSize = size
        got = call(read)
        if got is None:
            return None
        raw = bytes(got.bytes[:size])
        if dtype == _SMC_TYPE_FLT and len(raw) == 4:
            return struct.unpack("<f", raw)[0]
        if dtype == _SMC_TYPE_FPE2 and len(raw) == 2:
            return int.from_bytes(raw, "big") / 4.0
        if dtype in (_SMC_TYPE_UI8, _SMC_TYPE_UI16):
            return float(int.from_bytes(raw, "big"))
    except Exception:  # noqa: BLE001
        return None
    return None


def _apple_fan_stats() -> list[dict]:
    """Fan speed in rpm — the FASTEST fan where a machine has several, which
    is what "how hard is it working" means; a Mac with none (a Mac mini M4,
    an iMac, a thermally passive laptop) reports `FNum` 0 and gets no row,
    which is the whole reason the count is read rather than assumed."""
    count = _smc_read("FNum")
    if not count:
        return []
    speeds = [s for s in (_smc_read(f"F{i}Ac") for i in range(int(count)))
              if s is not None and s >= 0]
    if not speeds:
        return []
    return [_stat("fan", "Fan", max(speeds), " rpm")]


# macOS exposes GPU temperature and power to ROOT ONLY (`powermetrics`), and
# there is no way to ask for that at runtime: a signed privileged helper
# (SMJobBless) is the only mechanism, which a locally-run Python server is
# not. So the one real answer is a sudoers rule the admin adds once, and all
# this can do is try `sudo -n` (which never prompts and never hangs) and then
# say how to enable it.
#
# ONE AUTOMATIC ATTEMPT PER PROCESS. It used to retry every five minutes,
# which is a failed sudo — and an auth-log entry — every five minutes for as
# long as the Train tab is open, on every machine without the rule, which is
# nearly all of them. The retry could never pay off either: whether the rule
# exists is not something that changes while the server runs BY ITSELF. So
# `_pm_denied` latches, and the answer travels to the UI as a HINT KEY so the
# sentence explaining it can live in the frontend's catalogs with every other
# translated string, rather than being English prose shipped from here.
#
# WHAT SOMEBODY ASKS FOR IS NOT AN AUTOMATIC RETRY, and that is the exception
# the latch always had room for: the hint tells you to add the sudoers rule,
# and the one thing that changes the answer is you doing exactly that. So
# `clear_denied()` re-arms the probe for the NEXT sample — the Try again
# button beside the command — and what the latch still forbids is what it was
# written for, a poll asking over and over on its own. Without it the only way
# to pick the rule up is restarting the server, which is a strange thing to
# demand of a machine whose configuration has just been fixed.
POWERMETRICS_HINT = "powermetrics"

_pm_denied = False


def powermetrics_denied() -> bool:
    """Whether the one `sudo -n powermetrics` attempt was refused."""
    return _pm_denied


def clear_denied() -> None:
    """Re-arm the probe, so the next sample tries `sudo -n` once more.

    The 1 s SAMPLE CACHE is dropped with it, or the very sample this exists
    to produce is answered from the reading that was taken while the answer
    was still no — found by running it: with the rule freshly added, Try
    again went on reporting the hint, and only the poll a second later
    picked the figures up.
    """
    global _pm_denied, _samplers_available, _cached_at
    _pm_denied = False
    _samplers_available = None  # a re-ask is a re-ask: re-read what it has
    _cached_at = 0.0


# WHICH SAMPLERS EXIST IS THE BINARY'S ANSWER, NOT A CONSTANT. `smc` (GPU die
# temperature and fan) is absent from powermetrics on this macOS — and asking
# for a sampler it does not have fails the WHOLE invocation, rc 64, "powermetrics:
# unrecognized sampler: smc", so `gpu_power` was never sampled either. Read
# through the latch above that is indistinguishable from a refused sudo: the
# admin adds the rule the hint names, nothing changes, and the hint goes on
# asking for it. Verified on a Mac16,11 whose sudoers rule was in place and
# working — the app measured nothing and said the rule was missing.
#
# `--help` NEEDS NO SUDO (verified), so the question costs no auth-log entry
# and is asked once. Unparseable output means asking for everything, which is
# exactly the old behaviour.
_SAMPLERS = ("smc", "gpu_power")  # temperature + fan; power

_samplers_available: tuple[str, ...] | None = None


def _powermetrics_samplers() -> str:
    global _samplers_available
    if _samplers_available is None:
        found: tuple[str, ...] = _SAMPLERS
        try:
            out = _run(["/usr/bin/powermetrics", "--help"])
            body = out.split("supported by --samplers:", 1)
            if len(body) == 2:
                listed = set(re.findall(r"^\s{2,}(\w+)\s{2,}\S",
                                        body[1].split("sampler groups")[0],
                                        re.M))
                have = tuple(s for s in _SAMPLERS if s in listed)
                if have:
                    found = have
        except Exception:  # noqa: BLE001 - no powermetrics, or odd output
            pass
        _samplers_available = found
    return ",".join(_samplers_available)


def _apple_powermetrics_stats() -> list[dict]:
    """Temperature, power and — on an older macOS that still has the `smc`
    sampler — the fan. The fan is read off the SMC directly these days."""
    global _pm_denied
    if _pm_denied:
        return []
    try:
        proc = subprocess.run(
            ["sudo", "-n", "/usr/bin/powermetrics", "-n", "1", "-i", "300",
             "--samplers", _powermetrics_samplers()],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0:
            _pm_denied = True
            return []
        out = proc.stdout
        stats: list[dict] = []
        m = re.search(r"GPU die temperature:\s*([\d.]+)\s*C", out)
        if m:
            stats.append(_stat("temp", "Temp", float(m.group(1)), "°C"))
        m = re.search(r"GPU Power:\s*([\d.]+)\s*mW", out)
        if m:
            stats.append(_stat("power", "Power", float(m.group(1)) / 1000.0,
                               "W"))
        m = re.search(r"Fan:\s*([\d.]+)\s*rpm", out)
        if m:
            stats.append(_stat("fan", "Fan", float(m.group(1)), " rpm"))
        if not stats:
            # It ran and said nothing useful — a Mac whose SMC reports none of
            # these. Latch too: asking again will produce the same silence.
            _pm_denied = True
        return stats
    except Exception:  # noqa: BLE001 - sudo missing, or the 5 s timeout
        _pm_denied = True
        return []


def _apple_chip_name() -> str:
    name = _sysctl("machdep.cpu.brand_string")
    return name or "GPU"


# ---- training devices -------------------------------------------------------

_train_devices: list[dict] | None = None


def train_devices() -> list[dict]:
    """The devices a training job can be pinned to: ``[{"id", "label"}, …]``.

    Ids are torch device strings ("cuda:0", "mps", "cpu"); the manager uses
    them as scheduling slots (one running job per id) and the job editor
    offers them in its GPU dropdown. Enumerated without torch (the main venv
    is torch-free): pynvml / nvidia-smi for NVIDIA, rocm-smi or the DRM
    sysfs for AMD, the platform for Apple. The hardware doesn't change while
    the server runs, so the probe runs once.

    AMD GPUs get "cuda:N" ids TOO, and that is correct rather than sloppy:
    the ROCm build of torch drives them through the ``torch.cuda`` API, so
    the trainer's pick_device, the visible-devices pin and every
    ``device == "cuda"`` branch hold unchanged. NVIDIA is probed first — one
    torch build drives one vendor, and on a mixed box the CUDA build is what
    the env setup installs.
    """
    global _train_devices
    if _train_devices is None:
        names = _nvidia_names() or _amd_names()
        if names:
            _train_devices = [
                {"id": f"cuda:{i}", "label": n} for i, n in enumerate(names)
            ]
        elif platform.system() == "Darwin" and platform.machine() == "arm64":
            _train_devices = [{"id": "mps", "label": _apple_chip_name()}]
        else:
            _train_devices = [{"id": "cpu", "label": "CPU"}]
    return _train_devices


def _nvidia_names() -> list[str]:
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        try:
            names = []
            for i in range(pynvml.nvmlDeviceGetCount()):
                name = pynvml.nvmlDeviceGetName(
                    pynvml.nvmlDeviceGetHandleByIndex(i))
                names.append(name.decode() if isinstance(name, bytes)
                             else str(name))
            if names:
                return names
        finally:
            pynvml.nvmlShutdown()
    except Exception:  # noqa: BLE001 - no NVML / no device
        pass
    if shutil.which("nvidia-smi"):
        try:
            out = _run(["nvidia-smi", "--query-gpu=name",
                        "--format=csv,noheader"])
            return [ln.strip() for ln in out.splitlines() if ln.strip()]
        except Exception:  # noqa: BLE001 - parse/timeout
            pass
    return []


# ---- CPU ------------------------------------------------------------------


def _sysctl(key: str) -> str:
    try:
        return _run(["sysctl", "-n", key]).strip()
    except Exception:  # noqa: BLE001
        return ""


def _cpu_name() -> str:
    if platform.system() == "Darwin":
        return _sysctl("machdep.cpu.brand_string") or "CPU"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "CPU"


# /proc/stat needs a delta between two reads to yield a utilization; keep the
# previous snapshot between polls.
_prev_proc_stat: tuple[float, float] | None = None


def _cpu_percent() -> float | None:
    if platform.system() == "Darwin":
        try:
            # Sum of per-process CPU over all cores -> whole-machine percent.
            total = sum(
                float(x) for x in _run(["ps", "-A", "-o", "%cpu="]).split()
            )
            return min(100.0, total / max(1, os.cpu_count() or 1))
        except Exception:  # noqa: BLE001
            return None
    global _prev_proc_stat
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            parts = f.readline().split()[1:]
        vals = [float(x) for x in parts]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals)
        prev = _prev_proc_stat
        _prev_proc_stat = (idle, total)
        if prev is None or total <= prev[1]:
            return None  # first sample: no delta yet
        didle, dtotal = idle - prev[0], total - prev[1]
        return max(0.0, min(100.0, 100.0 * (1.0 - didle / max(1.0, dtotal))))
    except OSError:
        return None


# ---- RAM ------------------------------------------------------------------


def system_memory() -> tuple[float, float] | None:
    """(used_gb, total_gb) of system RAM, or None. Public because the Evaluate
    manager sizes its offload decision against the machine, not a fixed
    number — the same model is comfortable on 64 GB and hopeless on 16."""
    return _ram_stats()


def _ram_stats() -> tuple[float, float] | None:
    """(used_gb, total_gb), or None when unavailable."""
    used_gb = total_gb = None
    if platform.system() == "Darwin":
        try:
            total_gb = int(_sysctl("hw.memsize")) / 2**30
            page = int(_sysctl("vm.pagesize") or 16384)
            counts: dict[str, int] = {}
            for line in _run(["vm_stat"]).splitlines():
                m = re.match(r"([A-Za-z -]+):\s+(\d+)\.", line)
                if m:
                    counts[m.group(1).strip()] = int(m.group(2))
            used_pages = (
                counts.get("Pages active", 0)
                + counts.get("Pages wired down", 0)
                + counts.get("Pages occupied by compressor", 0)
            )
            used_gb = used_pages * page / 2**30
        except Exception:  # noqa: BLE001
            return None
    else:
        try:
            info: dict[str, float] = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    info[k.strip()] = float(v.strip().split()[0])  # kB
            total_gb = info["MemTotal"] / 2**20
            used_gb = (info["MemTotal"] - info["MemAvailable"]) / 2**20
        except (OSError, KeyError):
            return None
    if used_gb is None or total_gb is None:
        return None
    return used_gb, total_gb


def _system_device(data_dir=None) -> dict | None:
    """CPU + RAM (+ the library volume's disk) in ONE box, titled with the
    CPU model. The disk row is the volume holding ``data_dir`` — where the
    library and its training runs actually land, not the boot volume.

    The disk is reported as FREE and total, never as used and total, and that
    is the whole of why this row and the library sidebar's used to disagree.
    On Linux ``shutil.disk_usage`` derives ``used`` from ``f_bfree`` (blocks
    nobody has written) while ``free`` is ``f_bavail`` (blocks THIS user may
    write) — the gap is the filesystem's root reserve, 5% by default, i.e.
    ~200 GB on a 4 TB volume. So ``total - used`` is not free space, and the
    Train tab, which computed it that way, promised room a training run could
    never use. macOS is why it went unnoticed: APFS reports the two as equal.
    ``free`` is the same figure `routers/stats._disk_space` serves the
    library and Settings → Storage, so the three now say one number."""
    stats: list[dict] = []
    pct = _cpu_percent()
    if pct is not None:
        stats.append(_stat("util", "CPU", pct, "%"))
    ram = _ram_stats()
    if ram is not None:
        used_gb, total_gb = ram
        stats.append(_stat("mem", "RAM", used_gb, "GB"))
        stats.append(_stat("mem_total", "of", total_gb, "GB"))
    if data_dir is not None:
        try:
            du = shutil.disk_usage(str(data_dir))
            stats.append(_stat("disk_free", "Disk", du.free / 2**30, "GB"))
            stats.append(_stat("disk_total", "of", du.total / 2**30, "GB"))
        except OSError:
            pass
    if not stats:
        return None
    return _device("system", _cpu_name(), stats)


# ---- entry ------------------------------------------------------------------


def sample(data_dir=None) -> list[dict]:
    global _cached, _cached_at
    with _lock:
        now = time.monotonic()
        if now - _cached_at < _TTL:
            return _cached
        # The combined CPU + RAM box first, then one box per GPU (utilization,
        # VRAM, and temperature/power/fan where the platform exposes them all
        # share the GPU's box).
        devices: list[dict] = []
        system = _system_device(data_dir)
        if system:
            devices.append(system)
        devices += _gpus_via_pynvml() or _gpus_via_nvidia_smi() \
            or _gpus_via_rocm_smi() or _gpus_via_ioreg() or []
        _cached, _cached_at = devices, now
        return devices
