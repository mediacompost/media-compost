"""TEST-ONLY fake trainer.

The product ships no training simulation — the real trainer lives in
``media_compost/train/scripts/`` and needs the dedicated torch env. The pytest
suite still has to exercise the manager's full lifecycle (spawn, progress,
pause/resume, set_steps, checkpoints, samples, events), so the test fixtures
monkeypatch the module-level ``TRAIN_SCRIPTS`` constant (defined in
``paths.py``, imported into BOTH ``manager`` and ``evaluate`` — each holds its
own binding) to THIS directory: a drop-in stand-in
that speaks the exact same job-dir protocol at ~20 steps/s using only
stdlib + Pillow. It reuses the real protocol classes (JobIO, the control
file, atomic state writes) by importing the real ``train`` module.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

# Reuse the real protocol implementation (JobIO & friends), by putting the
# real scripts FIRST on the path — `train.py` there also imports `atomicio`
# from beside it, so the directory has to be importable, not just the file.
#
# The depth matters and got this wrong once: a stale `parents[2]` pointed at a
# directory that no longer exists, the insert silently did nothing, and
# `import train` found THIS file (its own directory is `sys.path[0]` for a
# script). The symptom was `module 'train' has no attribute 'JobIO'` — a
# missing attribute, not a missing module, which reads like a version skew.
_REAL = (Path(__file__).resolve().parents[3]
         / "media_compost" / "train" / "scripts")
assert (_REAL / "train.py").is_file(), f"real trainer not at {_REAL}"
sys.path.insert(0, str(_REAL))
import train as _train  # noqa: E402  (the real module, not this file)


def _load_step(io) -> int:
    last = io.last_checkpoint()
    if last is None:
        return 0
    try:
        with open(last / "checkpoint.json", encoding="utf-8") as f:
            return int(json.load(f).get("step", 0))
    except (OSError, ValueError):
        return 0


def _save_checkpoint(io, step: int) -> None:
    staged = io.checkpoints() / "last.staging"
    staged.mkdir(parents=True, exist_ok=True)
    with open(staged / "checkpoint.json", "w", encoding="utf-8") as f:
        json.dump({"step": step, "fake": True}, f)
    io.publish_last(staged)


def _snapshot(io, step: int, keep: int) -> None:
    d = io.snapshot_step(step, keep)
    with open(d / "checkpoint.json", "w", encoding="utf-8") as f:
        json.dump({"step": step, "fake": True}, f)


def _make_sample(path, prompt: str, step: int, seed: int) -> None:
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    hue = rng.randint(0, 255)
    img = Image.new("RGB", (64, 64))
    px = img.load()
    for y in range(64):
        for x in range(64):
            px[x, y] = ((hue + x * 4) % 256, (255 - y * 4 + hue) % 256,
                        (x * 2 + y * 2) % 256)
    ImageDraw.Draw(img).text((2, 2), f"{step}:{prompt[:8]}", fill=(255,) * 3)
    img.save(path)


def run(io, config: dict, resume: bool = False) -> None:
    hyper = config.get("hyper", {})
    sampling = config.get("sampling", {})
    total = int(hyper.get("steps", 100))
    ckpt_every = int(hyper.get("checkpoint_every", 0))
    ckpt_keep = int(hyper.get("checkpoint_keep", 2))
    sample_every = int(sampling.get("every_n_steps", 0))
    # Prompts are {prompt, negative} pairs (plain strings in old configs).
    prompts = [
        p if isinstance(p, str) else p.get("prompt", "")
        for p in sampling.get("prompts", [])
    ]
    seed = int(hyper.get("seed", 42))
    grad_accum = max(1, int(hyper.get("grad_accum", 1)))
    batch_size = max(1, int(hyper.get("batch_size", 1)))
    m_items = io.load_manifest().get("items", [])
    io.total_steps = total

    # EPOCH cadences resolve in the trainer, because only the built manifest
    # knows how long a pass is — the real loop's rule, and the app reads the
    # answer off the state file rather than off the config.
    ckpt_epochs = int(hyper.get("checkpoint_epochs", 0) or 0)
    sample_epochs = int(sampling.get("every_n_epochs", 0) or 0)
    if ckpt_epochs > 0 or sample_epochs > 0:
        per_epoch = max(1, -(-len(m_items) // (batch_size * grad_accum)))
        if ckpt_epochs > 0:
            ckpt_every = ckpt_epochs * per_epoch
        if sample_epochs > 0:
            sample_every = sample_epochs * per_epoch
    io.ckpt_every = ckpt_every
    io.sample_every = sample_every if prompts else 0

    start = _load_step(io) if resume else 0
    rng = random.Random(seed + start)
    io.write_state("caching_latents", step=start)
    time.sleep(0.3)

    if sampling.get("at_start") and prompts and start == 0:
        io.write_state("sampling", step=0)
        d = io.sample_dir(0)
        for i, prompt in enumerate(prompts):
            _make_sample(d / f"p{i:02d}.png", prompt, 0, seed=seed * 1000 + i)

    lr = float(hyper.get("lr", 1e-4))
    tau = max(1.0, total / 3.0)
    # What the cadences have already done for a step, so the finish below
    # does not do it twice — the real loop's `snap_at` / `sampled_at`.
    snap_at = sampled_at = -1
    step = start
    while step < io.total_steps:
        step += 1
        try:
            io.check_control()
        except _train.PauseRequested:
            _save_checkpoint(io, step - 1)
            raise
        loss = 1.2 * math.exp(-step / tau) + 0.05 + rng.uniform(-0.03, 0.03)
        # Simulate the per-step micro-batch spread + per-visit inspector data.
        micros = [max(0.001, loss + rng.uniform(-0.05, 0.05))
                  for _ in range(grad_accum)]
        step_visits = []
        for mi, ml in enumerate(micros):
            for bi in range(batch_size):
                it = m_items[(step + mi + bi) % len(m_items)] if m_items else {}
                cropped = rng.random() < 0.5
                step_visits.append({
                    "file_id": it.get("file_id"),
                    "prompt": ", ".join(it.get("tags", [])[:6]) or "an image",
                    "flip": rng.random() < 0.3,
                    "crop": [0.1, 0.1, 0.8, 0.8] if cropped else None,
                    "img": [it.get("width", 0), it.get("height", 0)],
                    "bucket": [64, 64],
                    "loss": round(ml, 6),
                })
        io.append_metric(step, max(0.001, loss), lr,
                         lo=min(micros) if grad_accum > 1 else None,
                         hi=max(micros) if grad_accum > 1 else None)
        io.append_visits(step, step_visits)
        if step % 25 == 0 or step >= io.total_steps:
            io.write_state("training", step=step)
        if ckpt_every and step % ckpt_every == 0 and step < io.total_steps:
            _snapshot(io, step, ckpt_keep)
            _save_checkpoint(io, step)
            snap_at = step
        if sample_every and prompts and step % sample_every == 0:
            io.write_state("sampling", step=step)
            d = io.sample_dir(step)
            for i, prompt in enumerate(prompts):
                _make_sample(d / f"p{i:02d}.png", prompt, step,
                             seed=seed * 1000 + i)
            sampled_at = step
            io.write_state("training", step=step)
        time.sleep(0.05)

    _save_checkpoint(io, io.total_steps)
    with open(io.output_dir() / "model.safetensors", "wb") as f:
        f.write(b"fake-lora-weights")
    # A FINISHED RUN HAS A CHECKPOINT AND A SAMPLE ROUND AT ITS LAST STEP,
    # whatever the cadences worked out to — `loop._finish_run`, mirrored
    # here for the same reason the cadences above are: a manager or API test
    # asking what a completed job left behind must see what the product
    # leaves behind.
    if ckpt_every and snap_at != io.total_steps:
        _snapshot(io, io.total_steps, ckpt_keep)
    if sample_every and prompts and sampled_at != io.total_steps:
        io.write_state("sampling", step=io.total_steps)
        d = io.sample_dir(io.total_steps)
        for i, prompt in enumerate(prompts):
            _make_sample(d / f"p{i:02d}.png", prompt, io.total_steps,
                         seed=seed * 1000 + i)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    io = _train.JobIO(Path(args.job_dir))
    io.write_state("starting")
    try:
        run(io, io.load_config(), resume=args.resume)
    except _train.PauseRequested:
        io.write_state("paused")
        return 0
    except _train.Cancelled:
        io.write_state("canceled")
        return 0
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        io.write_state("failed", error=f"{type(exc).__name__}: {exc}")
        return 1
    io.write_state("completed", step=io.total_steps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
