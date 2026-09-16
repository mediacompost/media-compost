"""The pipeline components this trainer and generator run WITHOUT.

`media_compost/pipeline_files.py` decides which files a base model's download
fetches, and it deliberately drops these components — requiring their weights
would report Stable Diffusion 1.5 as incomplete forever, since its cached
`safety_checker/` holds a config and no weights.

That makes this list half of a contract: whatever the download skips, the
LOAD must also disable, or diffusers looks for a component whose files were
never fetched. Only `safety_checker` was being passed as None, so a freshly
downloaded SD 1.5 died at

    OSError: Can't load image processor for '<snapshot>' ...
    is the correct path to a directory containing a preprocessor_config.json

— diffusers still constructs `feature_extractor` from `model_index.json`
when only the safety checker is disabled. It went unnoticed because a
machine that had ever pulled the full snapshot by hand had the file anyway;
a first run on a clean cache is what finds it.

This module is duplicated knowledge ON PURPOSE: the trainer is
standalone and must never import `media_compost` (it runs in its own venv,
where that package is not installed). `tests/test_pipeline_files.py` asserts
the two sets are equal, so the copy cannot drift.
"""

from __future__ import annotations

#: Must equal `media_compost.pipeline_files.OPTIONAL_COMPONENTS`.
OPTIONAL_COMPONENTS = frozenset({
    "safety_checker", "feature_extractor", "image_encoder", "watermarker",
    "safety_feature_extractor",
})


def disabled_kwargs(index: dict | None = None) -> dict:
    """`{component: None}` for every optional component, to pass to
    `from_pretrained` so diffusers does not try to build one.

    Pass a pipeline's parsed `model_index.json` as ``index`` to name only the
    components it actually declares. Naming one a pipeline does not have is
    accepted by diffusers as an unused kwarg, but staying to what the index
    declares keeps the call honest and the warnings quiet.
    """
    if index is None:
        return {name: None for name in OPTIONAL_COMPONENTS}
    return {name: None for name in OPTIONAL_COMPONENTS if name in index}
