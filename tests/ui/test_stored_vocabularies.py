"""The names and values that are already written down in somebody's library.

None of these live in the database schema, so no migration covers them and the
format number says nothing about them — but each is a string that a previous
build persisted and a later build reads back, which makes every one of them a
compatibility surface with exactly the same failure mode: the reader does not
recognise what it finds, so it quietly substitutes something else.

Each list below is APPEND-ONLY, and each is regenerated with
``MEDIA_COMPOST_UPDATE_GOLDEN=1`` — which is fine for an addition and is the
moment to stop and think for a removal.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parent / "golden" / "stored_vocabularies.json"
# The query corpus lives with core's tests — querystring.py owns the grammar.
CORE_GOLDEN = Path(__file__).resolve().parents[1] / "core" / "golden"
UPDATE = bool(os.environ.get("MEDIA_COMPOST_UPDATE_GOLDEN"))


def _collect() -> dict[str, list[str]]:
    from media_compost import prefs
    from media_compost.ui.server.routers import settings as sr
    from media_compost.train import models as tm
    from media_compost.train.manager import JOB_DEFAULTS
    from media_compost.train.spec import TrainingConfig

    return {
        # Stored in every `config.json`; an unknown one makes the config
        # refuse to validate, so the job can no longer even be opened.
        "training model keys": sorted(m.key for m in tm.REGISTRY),
        # The shape of that same file.
        "training config fields": sorted(TrainingConfig.model_fields),
        # The shape of every `job.json`.
        "training job fields": sorted(JOB_DEFAULTS),
        # Rows in the `settings` table.
        "settings keys": sorted([
            prefs.MODEL_PATHS, prefs.PREFS, prefs.PREFS_GLOBAL,
            prefs.SAVED_SEARCHES, prefs.TAG_SET_ORDER,
        ]),
        # Values inside those rows. Dropping one does not fail — it silently
        # rewrites that preference to the first entry on the next save.
        "pref values: dblclick_image": sorted(sr._DBLCLICK_IMAGE),
        "pref values: dblclick_video": sorted(sr._DBLCLICK_VIDEO),
        "pref values: language": sorted(sr._LANGUAGES),
        "pref values: florence model": sorted(sr._FLORENCE_MODELS),
        "pref values: date format": sorted(sr._DATE_FORMATS),
        # A saved search is a query STRING, so the grammar is persisted too.
        "query corpus": sorted(
            row["query"] for row in json.loads(
                (CORE_GOLDEN / "query_corpus.json")
                .read_text("utf-8"))["rows"]),
    }


def test_every_stored_vocabulary_is_append_only():
    got = _collect()
    if UPDATE:
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
        pytest.skip("golden regenerated")

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for what, values in golden.items():
        missing = sorted(set(values) - set(got.get(what, ())))
        assert not missing, (
            f"{what}: {missing} no longer exist(s), and existing libraries "
            f"have them written down. What happens next depends on which "
            f"list this is — a training model key makes its jobs refuse to "
            f"validate, a preference value is silently rewritten to the "
            f"first entry the next time anything saves, a settings key is "
            f"simply forgotten. If it must go, keep the name readable and "
            f"regenerate with MEDIA_COMPOST_UPDATE_GOLDEN=1, saying in the "
            f"commit what happens to a library that still holds it.")


def test_a_training_model_that_is_retired_is_kept_readable():
    """A registry key is an identifier stored in every job that used it, so
    removing one strands those jobs: `model_spec` returns None and
    `TrainingConfig._check` refuses the config, which means the job cannot be
    opened, edited or even read — not merely that it cannot be re-run."""
    from media_compost.train.models import REGISTRY, model_spec
    from media_compost.train.spec import TrainingConfig

    for key in (m.key for m in REGISTRY):
        assert model_spec(key) is not None, key
        # And each still validates as a config, which is the thing that
        # actually breaks.
        TrainingConfig(model=key)


def test_the_query_corpus_only_ever_grows():
    """Saved searches store a query STRING, so the grammar is a persisted
    format like any other. The corpus already pins parse and serialize from
    both the Python and the TypeScript side; what it did not say is that a
    row may never LEAVE it — and a row leaving is exactly what would happen
    if a piece of syntax somebody has saved were dropped."""
    corpus = json.loads(
        (CORE_GOLDEN / "query_corpus.json")
        .read_text(encoding="utf-8"))["rows"]
    queries = [row["query"] for row in corpus]
    assert len(queries) == len(set(queries)), "a corpus row is duplicated"
    got = {q for q in queries}
    golden = set(json.loads(GOLDEN.read_text(encoding="utf-8"))
                 .get("query corpus", [])) if GOLDEN.exists() else set()
    missing = sorted(golden - got)
    assert not missing, (
        f"these queries left the corpus: {missing}. Somebody may have them "
        f"saved; a search that silently stops parsing is a search that "
        f"silently matches nothing.")


def test_config_paths_are_where_they_have_always_been(tmp_path):
    """The data directory's layout is a contract too — a library is a folder
    somebody backs up, syncs and points a second machine at."""
    from media_compost.ui.config import UiConfig

    cfg = UiConfig(data_dir=tmp_path)
    assert cfg.db_path == tmp_path / "media.db"
    assert cfg.items_dir == tmp_path / "items"
    assert cfg.thumbs_dir == tmp_path / "thumbs"
    # `training/` is still part of the folder's shape — a library somebody
    # backs up carries its jobs — but the trainer owns the answer now, so
    # `UiConfig` no longer knows it and this asks the package that does.
    from media_compost.train import training_dir

    assert training_dir(tmp_path) == tmp_path / "training"
    assert cfg.refs_dir == tmp_path / "tmp" / "refs"
    assert cfg.import_stage_dir == tmp_path / "tmp" / "import"
    assert cfg.backup_dir == tmp_path / "backups"
