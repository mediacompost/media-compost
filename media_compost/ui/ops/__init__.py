"""The app's own service-layer ops: the ones core cannot hold.

``media_compost.ops`` is the library's service layer and these two are shaped
exactly like its modules — same ``Ctx``, same ``OpError``s, same "never
commit" rule (held by a sweep of their own,
``tests/ui/test_ops_ratchet.py:test_the_apps_own_ops_never_commit`` — core's
grep test cannot see this package). They
live in this package because of what they IMPORT, not what they are:
``editor`` wraps the pixel-editing engine (``media_compost.ui.editor``) and
``video`` renders cutlists through the job queue's ffmpeg plumbing — both
firmly the app's business, and a base install has no use for either.

Their action strings stay pinned in ``media_compost.ops.actions`` with
everyone else's: a history event outlives any package layout.
"""

from __future__ import annotations
