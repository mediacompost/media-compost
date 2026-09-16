"""`os.replace` that survives Windows.

On POSIX, rename(2) is atomic and always possible: it works even while other
processes hold the destination open. On Windows it is neither. A file cannot
be replaced while any other handle has it open, so `os.replace` raises
``PermissionError: [WinError 5]`` — and the trainer's destinations are read
constantly by the server (the manager tick reads `state.json` roughly once a
second, and the app polls it while a job is on screen).

That is not theoretical: it killed a real run mid-training. `JobIO.write_state`
raised out of the trainer's own error handler, so a job that had merely lost a
race reported a `PermissionError` traceback instead of its actual state, and
the run ended.

The parent process solves the reader side of this by opening with
FILE_SHARE_DELETE (`media_compost.train/paths.py`), but `train/scripts/` (the trainer)
is standalone — it runs in its own venv and must never import media_compost —
and it cannot control who else has the file open anyway. So here the answer is
to retry: the window is microseconds, and a destination that is genuinely
locked for a quarter of a second is a real failure worth raising.
"""

from __future__ import annotations

import os
import time

#: Attempts, and the first pause between them; each retry waits twice as long
#: as the last, so eight attempts span roughly 250 ms.
_RETRIES = 8
_BACKOFF = 0.002


def replace(src, dst) -> None:
    """`os.replace(src, dst)`, retrying while the destination is locked."""
    for attempt in range(_RETRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _RETRIES - 1:
                raise
            time.sleep(_BACKOFF * (2 ** attempt))
