"""Media Compost's app: the web server, the editors, and the AI actions.

This package is everything you need a BROWSER for — the FastAPI server and the
SPA it serves, the image and video editors' backends, the AI-action plugins
with their out-of-process model host, and the background job queue. It is
installed by the ``[full]`` extra and drives the library through
``media_compost``, whose internals it may use freely: the two ship and version
together, in one distribution.

What it is NOT is a dependency of anything. ``media_compost`` never names this
package; ``media_compost.train`` never names it either — the app reaches the
TRAINER through one guarded import (``server/app.py``), and nothing goes the
other way.
"""

from __future__ import annotations
