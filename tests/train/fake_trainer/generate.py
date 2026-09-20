"""TEST-ONLY fake evaluation generator (see train.py in this directory)."""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
from pathlib import Path

_CANCELED = False


def _on_term(_sig, _frame):
    global _CANCELED
    _CANCELED = True


def _write_state(run_dir: Path, phase: str, image: int = 0, total: int = 0,
                 error: str = "") -> None:
    tmp = run_dir / f"state.json.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "phase": phase, "image": image, "total": total,
            "pid": os.getpid(), "updated_at": time.time(), "error": error,
        }, f)
    os.replace(tmp, run_dir / "state.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    signal.signal(signal.SIGTERM, _on_term)
    with open(run_dir / "spec.json", encoding="utf-8") as f:
        spec = json.load(f)
    _write_state(run_dir, "starting")
    try:
        from PIL import Image

        n = int(spec.get("count", 1))
        rng = random.Random(int(spec.get("seed", 0)))
        for i in range(n):
            if _CANCELED:
                _write_state(run_dir, "canceled")
                return 0
            _write_state(run_dir, "generating", image=i + 1, total=n)
            time.sleep(0.4)
            img = Image.new("RGB", (32, 32),
                            tuple(rng.randrange(256) for _ in range(3)))
            # Through a temp name, like the real generator: the server lists
            # this folder while the run is going, and a picture written in
            # place is offered to a reader half-written.
            out = run_dir / "images" / f"p{i:02d}.png"
            tmp = out.with_name(f".{out.name}.tmp")
            img.save(tmp, "PNG")
            os.replace(tmp, out)
    except Exception as exc:  # noqa: BLE001
        _write_state(run_dir, "failed", error=str(exc))
        return 1
    _write_state(run_dir, "completed", image=n, total=n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
