"""Test package marker.

Makes ``tests`` a regular package so the three suites import as
``tests.core.*`` / ``tests.ui.*`` / ``tests.train.*`` — namespaced, so two
suites may share a test basename — and so ``from tests.core.conftest import
...`` resolves to this directory (cwd-first) rather than a same-named package
a dependency may have left in site-packages (e.g. ultralytics ships a
top-level ``tests``).
"""
