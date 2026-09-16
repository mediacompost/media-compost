"""ML plugin architecture.

A small, fixed set of *tasks* (background removal, watermark removal, tagging,
captioning) is served by pluggable *models*. Each model is one self-contained
file under :mod:`media_compost.ui.plugins.impl` — a lightweight manifest (metadata
only, importable without heavy deps) plus ``load``/``run`` functions whose heavy
imports are lazy and execute only inside a worker subprocess.

Every model runs **out-of-process** via :class:`~media_compost.ui.plugins.host.ModelHost`,
which keeps a single loaded model resident for a short TTL (reused across
consecutive jobs, evicted when a different model is requested or after idle) —
the process-level generalization of the old in-process model cache.

Add/remove a model by adding/removing its file and one line in
:mod:`media_compost.ui.plugins.registry`.
"""
