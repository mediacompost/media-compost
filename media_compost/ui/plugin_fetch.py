"""Downloading weights that do not come from Hugging Face.

``hub.download.Download`` fetches a HF repo into the shared cache, which is
how almost every model here arrives. Two do not: InsightFace's buffalo_l pack
is a zip on its own GitHub release, and the OpenComic descreen graphs are files
on theirs. Both libraries fetch on first use — which means the first face
detection someone runs stalls for minutes with nothing on screen to explain it.

So a plugin may define ``fetch_weights()`` (download them now) and
``weights_ready()`` (are they here), and the Settings page grows a Download
button for it. A plugin may have BOTH kinds — RAM++ declares its checkpoint
as a Hugging Face source and pulls a tokenizer from a second repo through the
`ram` package — which is what :class:`ChainedFetch` is for.

``PluginFetch`` runs that hook in a SUBPROCESS: the fetch imports the plugin's
heavy dependencies, and the server process is deliberately kept clear of them.

The surface matches ``hub.download.Download`` so the endpoints can treat the
two the same way — the byte counters are always zero because these downloaders
report no progress worth relaying.
"""

from __future__ import annotations

import multiprocessing as mp
import subprocess
import sys
import threading
import time

from media_compost.hub.download import DONE, ERROR, RUNNING

_CTX = mp.get_context("spawn")


class PluginFetch:
    """Runs one plugin's ``fetch_weights()`` in a child interpreter."""

    def __init__(self, module: str, python: str | None = None):
        self.module = module
        self.python = python or sys.executable
        self._status = _CTX.Value("i", RUNNING)
        self._error = ""
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        code = (
            "import importlib, sys;"
            f"m = importlib.import_module({self.module!r});"
            "m.fetch_weights()"
        )
        self._proc = subprocess.Popen(
            [self.python, "-c", code],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self._thread = threading.Thread(target=self._wait, daemon=True)
        self._thread.start()

    def _wait(self) -> None:
        proc = self._proc
        if proc is None:
            return
        out = proc.communicate()[0] or ""
        if proc.returncode == 0:
            self._status.value = DONE
        else:
            self._status.value = ERROR
            # The last line of a traceback is the sentence worth showing; the
            # frames above it are about our subprocess, not about their problem.
            lines = [ln for ln in out.strip().split("\n") if ln.strip()]
            self._error = lines[-1] if lines else "download failed"

    def cancel(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        self._status.value = ERROR
        self._error = "canceled"

    def status(self) -> int:
        return int(self._status.value)

    @property
    def progress(self) -> int:
        return -1          # these fetchers report none

    @property
    def error(self) -> str:
        return self._error

    @property
    def done_bytes(self) -> int:
        return 0

    @property
    def total_bytes(self) -> int:
        return 0


class ChainedFetch:
    """Two downloads under one key: the hub source, then the plugin's own.

    A model row is ONE row with ONE button, and its readiness is now the AND of
    both halves (`registry.source_weights_ready`). Starting only the first half
    from that button would leave a row that says "Download", downloads, and
    still says "Download" — the dead end that a stuck cache probe produces, in
    a new shape.

    Same surface as the two it wraps, so the endpoints treat all three alike.
    The bytes and the percentage are the FIRST one's: it is the multi-GB half,
    and a bar resetting to nothing near the end to report a 700 KB tail would
    read as a download starting over.

    **A THREAD advances it, never `status()`.** Hanging the handover off the
    poll would make it depend on somebody watching the page — the same "start
    five, close the tab, come back to two finished" failure the download queue
    grew its pump thread for.
    """

    def __init__(self, first, second):
        self.first, self.second = first, second
        self._second_started = False
        self._canceled = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.first.start()
        self._thread = threading.Thread(target=self._chain, name="mc-chained-fetch",
                                        daemon=True)
        self._thread.start()

    def _chain(self) -> None:
        while True:
            if self._canceled:
                return
            st = self.first.status()
            if st == DONE:
                break
            if st != RUNNING:
                return          # error/canceled: the second half is moot
            time.sleep(0.5)
        self._second_started = True
        self.second.start()

    def status(self) -> int:
        if self._canceled:
            return ERROR
        st = self.first.status()
        if st != DONE:
            return st
        # Between the first finishing and the thread noticing, the whole thing
        # is still RUNNING — reporting DONE there would have the caller drop
        # the entry and forget the half that has not started.
        return self.second.status() if self._second_started else RUNNING

    def cancel(self) -> None:
        self._canceled = True
        self.first.cancel()
        if self._second_started:
            self.second.cancel()

    @property
    def queued(self) -> bool:
        return bool(getattr(self.first, "queued", False))

    @property
    def progress(self) -> int:
        return -1 if self._second_started else self.first.progress

    @property
    def error(self) -> str:
        return self.first.error or (self.second.error if self._second_started else "")

    @property
    def done_bytes(self) -> int:
        return self.first.done_bytes

    @property
    def total_bytes(self) -> int:
        return self.first.total_bytes
