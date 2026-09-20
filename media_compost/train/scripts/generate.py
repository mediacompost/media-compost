"""Evaluation image generator (runs in the dedicated training venv).

Reads ``spec.json`` from the run dir (written by the server's EvalManager):
base model, a stack of LoRA paths with weights, prompt/negative and sampler
settings. Writes ``images/p<i>.png``, streaming progress into ``state.json``.

Like train.py, this file never imports ``media_compost``.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

_CANCELED = False


def _on_term(_sig, _frame):
    global _CANCELED
    _CANCELED = True


# Process start: every elapsed figure is measured from here.
_T0 = time.time()


def _write_state(run_dir: Path, phase: str, image: int = 0, total: int = 0,
                 error: str = "", elapsed: float = 0.0,
                 step: int = 0, steps: int = 0) -> None:
    tmp = run_dir / f"state.json.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "phase": phase, "image": image, "total": total,
            # Denoising step within the current batch. Written from the
            # pipeline's own step callback, which is also what keeps `elapsed`
            # moving — it used to be stamped once per BATCH, so a single-batch
            # run showed a frozen timer for the whole generation.
            "step": step, "steps": steps,
            "pid": os.getpid(), "updated_at": time.time(), "error": error,
            # Wall time of the whole run — loading the model is part of what
            # you waited for, so it is part of what the card reports.
            "elapsed": round(elapsed, 1),
        }, f)
    # Retried: the manager polls this file, and on Windows os.replace cannot
    # swap a file another handle has open (see atomicio).
    import atomicio

    atomicio.replace(tmp, run_dir / "state.json")


def _check_canceled():
    if _CANCELED:
        raise KeyboardInterrupt()


def _pipeline_cls(engine: str, src: str = ""):
    """The diffusers pipeline class for an engine name.

    Read off the engine module rather than a table here: this used to be a
    second registry, and adding a model to `models.py` plus `engines/` left
    the Evaluate tab raising `KeyError: 'flux2'` at generation time.

    An engine that serves a FAMILY (FLUX.2 is Klein and dev over one
    transformer) also declares `PIPELINES`, and then the model's own snapshot
    decides which of them `src` is — the same rule the engine loads by, so
    the Evaluate tab and the trainer can never pick different classes for one
    model.
    """
    import importlib

    import diffusers

    try:
        mod = importlib.import_module(f"engines.{engine}")
    except ImportError as exc:
        raise ValueError(f"unknown training engine {engine!r}") from exc
    name = getattr(mod, "PIPELINE", "")
    if not name:
        raise ValueError(
            f"engine {engine!r} declares no PIPELINE, so there is no way to "
            "generate with it — add one to its module")
    family = getattr(mod, "PIPELINES", ())
    if family and src:
        from engines import common

        return common.pipeline_class(src, name, tuple(family))
    return getattr(diffusers, name)


def _attach_adapter(pipe, path: Path, adapter: str, meta: dict) -> None:
    """Re-attach an adapter that is not a diffusers LoRA — today, a LoKr.

    The pipeline's components are plain diffusers models here (no engine built
    them), so this does what `BaseEngine.attach_adapter` does: build the same
    PEFT config and load the saved parameters into it. The config comes from
    `adapter_config.json` and the LAYERS from the weights themselves, so an
    adapter trained with a layer filter re-attaches to exactly those layers.

    A part naming a component this pipeline does not have is skipped rather
    than raising: the same weights are offered for every release of an
    architecture, and a text-encoder adapter has nowhere to go on a pipeline
    whose encoder was never trained.
    """
    import adapters
    from peft.utils import set_peft_model_state_dict

    state = adapters.load_state(path)
    attached = []
    for part, tensors in state.items():
        module = getattr(pipe, part, None)
        if module is None or not hasattr(module, "add_adapter"):
            continue
        module.add_adapter(adapters.rebuild_config(meta, tensors), adapter)
        set_peft_model_state_dict(module, tensors, adapter_name=adapter)
        attached.append(part)
    if not attached:
        raise ValueError(
            f"{path} holds a {meta.get('network')} adapter for "
            f"{', '.join(sorted(state)) or 'nothing'}, which this pipeline "
            f"does not have — it was trained for a different model.")


def _attach_parts(pipe, path: Path, adapter: str, meta: dict) -> list[str]:
    """Attach the parts the PORTABLE file could not carry.

    A checkpoint's metadata says which parts its portable file holds
    (`portable_parts`, written by `BaseEngine.adapter_meta`); whatever else
    the trainer's own file holds is an adapter diffusers' loader has no slot
    for — FLUX.1's T5-XXL — and is attached here the way a LoKr is, from
    the PEFT-named weights. Without this the Evaluate tab loaded the
    portable file, applied the transformer's and CLIP's adapters and
    silently generated with an untrained T5.

    A checkpoint written before the metadata carried the list is left
    alone: nothing it holds was ever outside its portable file.

    AND A PART THE LOADER HAS ALREADY COVERED IS SKIPPED whatever the
    metadata claims. `portable_parts` is a claim ABOUT a file, written by
    the build that saved it — and SDXL's said its second text encoder was
    not in the portable file while `save_portable` was putting it there, so
    diffusers attached the adapter and this came back for it, which PEFT
    refuses outright ("Adapter with name l0 already exists"). The engine now
    declares it correctly, but every checkpoint already on disk still holds
    the old claim, and a metadata file cannot be re-read into the past. So
    the module itself is asked: it knows what is attached to it, and
    re-attaching over an existing adapter is never the right thing to do
    however the question arose.
    """
    import adapters

    carried = meta.get("portable_parts")
    if not isinstance(carried, list):
        return []
    wanted = []
    for part, tensors in adapters.load_state(path).items():
        if part in carried:
            continue
        module = getattr(pipe, part, None)
        if module is None or not hasattr(module, "add_adapter"):
            continue
        if adapter in (getattr(module, "peft_config", None) or {}):
            continue
        wanted.append((part, module, tensors))
    if not wanted:
        return []
    # PEFT below the guard, not above it: a checkpoint the loader has
    # already covered needs none of this, and reaching for the heavy import
    # first made that the one branch that could not run without it.
    from peft.utils import set_peft_model_state_dict

    attached = []
    for part, module, tensors in wanted:
        module.add_adapter(adapters.rebuild_config(meta, tensors), adapter)
        set_peft_model_state_dict(module, tensors, adapter_name=adapter)
        attached.append(part)
    if attached:
        print(f"attached {', '.join(attached)} from the trainer's own file",
              flush=True)
    return attached


def _load_lora(pipe, path: Path, adapter: str) -> None:
    """Load LoRA weights from any layout a training job has ever produced.

    Every checkpoint now carries the PORTABLE file
    (``pytorch_lora_weights.safetensors``, diffusers' own layout), so the
    first branch is the ordinary path for both a finished output and any step
    checkpoint. The rest is for weights written before that was true: the
    trainer's own state file, and the ``lora_weights.pt`` pickle before it —
    both keyed by pipeline component, and converted to the diffusers layout
    here with the component prefixes diffusers expects.
    """
    import adapters

    # NOT EVERY ADAPTER IS A DIFFUSERS LoRA. A LoKr has no portable file and
    # its parameters are Kronecker factors, so `load_lora_weights` cannot read
    # it — it fails with "Could not automatically infer state dict type",
    # which is what an offered-but-unusable checkpoint looked like. Re-attach
    # it the way the trainer does instead, from its own two files.
    meta = adapters.read_meta(path)
    if str(meta.get("network", "lora") or "lora") != "lora":
        _attach_adapter(pipe, path, adapter, meta)
        return
    if (path / adapters.PORTABLE_FILE).is_file():
        # NAME THE FILE — never hand `load_lora_weights` the folder alone.
        # Given a path with no `weight_name`, diffusers goes looking for the
        # weights itself (`_best_guess_weight_name`), and that guess is a HUB
        # operation: OFFLINE it refuses outright — "When using the offline
        # mode, you must specify a `weight_name`" — rather than reading the
        # directory it was handed. Which is the state every run here is in:
        # the trainer and this generator are spawned with `HF_HUB_OFFLINE`
        # set, and the machines that most need it have no network at all. So
        # every LoRA a training job produced failed to load there, naming a
        # hub argument no caller here has any business supplying — a failure
        # that never shows up on a machine allowed to reach the hub, where
        # the guess quietly succeeds. Naming it skips the guess entirely,
        # which is the more honest call in any case: a checkpoint folder
        # holds up to three `.safetensors` (the trainer's own copy, this
        # one, and a LyCORIS export) and only this one is in the layout
        # diffusers reads.
        pipe.load_lora_weights(str(path), weight_name=adapters.PORTABLE_FILE,
                               adapter_name=adapter)
        _attach_parts(pipe, path, adapter, meta)
        return
    from diffusers.utils import convert_state_dict_to_diffusers

    try:
        state = adapters.load_state(path)
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(
            f"{path} holds no LoRA weights (deleted checkpoint, or a "
            f"simulated run's marker): {exc}") from exc
    merged: dict = {}
    for part, tensors in state.items():
        for k, v in convert_state_dict_to_diffusers(tensors).items():
            merged[f"{part}.{k}"] = v
    if not merged:
        raise ValueError(f"unrecognized checkpoint layout in {path}")
    pipe.load_lora_weights(merged, adapter_name=adapter)


def _backbone_of(folder: Path) -> tuple[Path, str]:
    """`(component folder, its diffusers class name)` for a finetune.

    Split from the swap below so it can be read without torch in the room:
    everything that can be wrong with the DIRECTORY is decided here, and the
    caller only has the load left.
    """
    subs = [d for d in sorted(folder.iterdir())
            if d.is_dir() and (d / "config.json").is_file()] \
        if folder.is_dir() else []
    if not subs:
        raise RuntimeError(f"no finetuned weights in {folder}")
    if len(subs) > 1:
        raise RuntimeError(
            f"{folder} holds {len(subs)} components, not one backbone: "
            + ", ".join(d.name for d in subs))
    with open(subs[0] / "config.json", encoding="utf-8") as fh:
        return subs[0], str(json.load(fh).get("_class_name") or "")


def _swap_backbone(pipe, folder: Path, dtype) -> None:
    """Put a full finetune's weights into the pipeline it was trained from.

    A finetune is not a pipeline: `BaseEngine.save_full` writes the backbone
    alone, as ONE subfolder named after the component it is (`unet`,
    `transformer`), which is also the name that component has on the
    pipeline. So the folder says both what it holds and where it goes, and
    nothing here has to know the engines — which is just as well, since the
    engine classes are the trainer's and this file is the generator.

    Anything else raises: a run that quietly generated from the base model
    after being asked for a finetune would look exactly like a finetune that
    had learned nothing.
    """
    sub, name = _backbone_of(folder)
    import diffusers

    cls = getattr(diffusers, name, None)
    if cls is None:
        raise RuntimeError(f"unknown component class {name!r} in {sub}")
    print(f"finetune: {sub.name} from {folder}", flush=True)
    module = cls.from_pretrained(sub, torch_dtype=dtype)
    # `register_modules` is how a pipeline is told about a component — it
    # updates the pipeline's own config beside the attribute, which plain
    # assignment does not, and diffusers reads that config when it moves the
    # pipeline to a device or offloads it.
    pipe.register_modules(**{sub.name: module})


def _load_pipe(run_dir: Path, spec: dict):
    """Build the pipeline for `spec` and report progress into its run dir."""
    import torch
    import diffusers

    import pipeline_opts

    minfo = spec.get("model_info", {})
    cls = _pipeline_cls(minfo["engine"], minfo.get("local_dir") or "")

    device = ("cuda" if torch.cuda.is_available()
              else "mps" if torch.backends.mps.is_available() else "cpu")
    dtype = torch.bfloat16 if device != "cpu" else torch.float32
    if device == "mps":
        try:
            t = torch.zeros(2, dtype=torch.bfloat16, device="mps")
            (t + t).sum().item()
        except Exception:  # noqa: BLE001 - no bf16 on this MPS
            dtype = torch.float32

    print(f"device: {device}, dtype: {str(dtype).replace('torch.', '')}",
          flush=True)
    # The same ceiling the training loop arms, and for the same reason: a
    # generation holds a whole pipeline, and on unified memory an oversized
    # one pages instead of failing — which freezes the machine rather than the
    # run. A generation has no per-job setting, so this is always the
    # device-derived default (MEDIA_COMPOST_MEM_FRACTION overrides it).
    import membudget

    capped = membudget.arm(device)
    if capped:
        print(f"memory budget: {capped:.0f} GB", flush=True)
    _write_state(run_dir, "loading_model")
    repo = minfo.get("repo", "")
    if repo.endswith(".safetensors"):
        pipe = cls.from_single_file(repo, torch_dtype=dtype)
    else:
        # The cached snapshot directory when it is complete — loading by repo
        # id needs the hub even for a fully cached model (see the manifest's
        # `local_dir`).
        # The optional components are disabled, not just the safety checker:
        # the download skipped all of them, so asking diffusers to build one
        # looks for files that are not there (see pipeline_opts).
        pipe = cls.from_pretrained(minfo.get("local_dir") or repo,
                                   torch_dtype=dtype,
                                   **pipeline_opts.disabled_kwargs())
    pipe.set_progress_bar_config(disable=True)

    # BEFORE the adapters, which are deltas on whatever the backbone is now.
    fine = minfo.get("finetune")
    if fine:
        _write_state(run_dir, "loading_finetune")
        _swap_backbone(pipe, Path(fine), dtype)

    loras = spec.get("loras", [])
    if loras:
        _write_state(run_dir, "loading_loras")
        names, weights = [], []
        for i, lo in enumerate(loras):
            name = f"l{i}"
            _load_lora(pipe, Path(lo["path"]), name)
            names.append(name)
            weights.append(float(lo.get("weight", 1.0)))
        pipe.set_adapters(names, adapter_weights=weights)

    # Residency vs. shuttling. Measured on FLUX.2 (MPS, bf16, 512 px, 8 steps):
    # resident peaks at 16.9 GB and generates in 30.2 s; offloaded it peaks at
    # 1.1 GB and takes 36.1 s. So residency is ~20% faster when the machine has
    # the room, and catastrophic when it does not — the manager decides which
    # case this is (see evaluate._should_offload) and says so here.
    if minfo.get("offload") and device != "cpu":
        print("model kept on the CPU between steps (offloading) — this model "
              "is large for this machine", flush=True)
        pipe.enable_model_cpu_offload(device=device)
    else:
        pipe.to(device)
    return pipe


def _negative_kwargs(pipe, negative: str) -> dict:
    """How to hand this pipeline a negative prompt, if it takes one at all.

    Not every pipeline does: FLUX.2's takes only `negative_prompt_embeds`, and
    passing the string raised a TypeError on the first generation. Handing it
    embeddings instead is not worth it — with guidance on it encodes its own
    empty-string negative anyway, and pre-encoding one here has to match its
    internal layering exactly or the transformer fails on a batch mismatch.
    So: the string where it is accepted, and otherwise a line in the log
    saying the negative prompt was ignored, which beats appearing to honour it.

    Asked of the signature rather than tabled per model — the last table of
    that kind is what `_pipeline_cls` just replaced.
    """
    import inspect

    if not negative:
        return {}
    if "negative_prompt" in inspect.signature(pipe.__call__).parameters:
        return {"negative_prompt": negative}
    print(f"note: {type(pipe).__name__} takes no negative prompt — "
          f"ignoring {negative!r}", flush=True)
    return {}


def _render(run_dir: Path, spec: dict, pipe, t0: float) -> None:
    """Generate `spec`'s images with an already-loaded pipeline.

    `t0` is THIS run's start, not the process's: a warm process serves several
    runs in a row, so measuring from `_T0` made every run after the first
    report the time of all the runs before it too."""
    import torch

    n = int(spec.get("count", 1))
    seed = int(spec.get("seed", 0))
    # How many images go through the pipeline at once. Bigger batches share the
    # denoising work and finish sooner per image, at the cost of holding that
    # many latents in memory — so it is the user's dial, not ours.
    batch = max(1, min(int(spec.get("batch", 1) or 1), n))
    done = 0
    while done < n:
        _check_canceled()
        k = min(batch, n - done)
        _write_state(run_dir, "generating", image=done + k, total=n,
                     elapsed=time.time() - t0)
        # One generator per image, seeded seed+i, so an image lands on the same
        # seed whatever batch size it was generated in.
        gens = [torch.Generator("cpu").manual_seed(seed + done + j)
                for j in range(k)]
        steps = int(spec.get("steps", 25))

        def on_step(_pipe, i, _t, kw):
            # Per denoising step: keeps the elapsed time moving and says how
            # far into the batch this is. Cheap — a small JSON write next to
            # a full transformer pass — and it is the only thing that happens
            # during the minutes a single batch can take.
            _write_state(run_dir, "generating", image=done + k, total=n,
                         elapsed=time.time() - t0, step=i + 1, steps=steps)
            _check_canceled()
            return kw

        with torch.no_grad():
            imgs = pipe(
                # BY NAME: FLUX.2's pipeline takes `image` first (it also
                # edits), so a positional prompt lands in the wrong parameter
                # and the pipeline then reports having been given no prompt.
                prompt=spec.get("prompt", ""),
                **_negative_kwargs(pipe, spec.get("negative") or ""),
                num_inference_steps=steps,
                guidance_scale=float(spec.get("cfg", 6.0)),
                width=int(spec.get("width", 1024)),
                height=int(spec.get("height", 1024)),
                num_images_per_prompt=k,
                generator=gens if k > 1 else gens[0],
                callback_on_step_end=on_step,
            ).images
        out_dir = run_dir / "images"
        out_dir.mkdir(parents=True, exist_ok=True)   # never lose a finished
        for j, img in enumerate(imgs[:k]):           # image to a missing dir
            # Three digits: the listing sorts by NAME, and mixing widths would
            # put p100 before p99. Runs written before this stay internally
            # consistent — a run never mixes the two.
            _save_image(img, out_dir / f"p{done + j:03d}.png")
        done += k


def _save_image(img, path: Path) -> None:
    """One finished picture, ATOMICALLY.

    The run's folder is listed by the server WHILE the generation is still
    going (`EvalManager.readable` takes every `.png` in it) and the app asks
    for each name the moment it appears — so a picture written in place is
    offered to the browser while it is still being written. Measured: a
    1024 px PNG takes ~40 ms and grows in 128 KB steps, which is fifteen
    sizes a reader can catch it at. What that reader gets is a truncated
    file, and both halves of the path make it WORSE than an error: PIL
    refuses it, so the thumbnailer falls back to serving the raw bytes, and
    a browser decodes those happily — full width and height, pixels down to
    the row the file stopped at, white below. That is the "half the picture,
    the rest white" thumbnail, and it stays on screen because nothing asks
    for the image again once it has loaded.

    Written through a temp name and renamed, which is what the trainer's own
    sample writer has done since it met exactly this. The name is
    `.pNNN.png.tmp`: a leading dot AND a suffix that is not `.png`, so
    neither the listing nor the thumbnail glob can see it, and the rename
    makes the picture appear complete or not at all.
    """
    # Lazily, and deliberately: this module is also loaded BY PATH (the
    # tests do, `train.py`'s own state writer documents the same trap), and
    # there its directory is not on `sys.path`.
    import atomicio

    tmp = path.with_name(f".{path.name}.tmp")
    img.save(tmp, "PNG")   # the name has no usable extension for Pillow
    atomicio.replace(tmp, path)


# How long a loaded model waits for more work before the process exits. The
# model is the expensive part — loading SDXL costs about as much as eight
# denoising steps — so a second Generate click should not pay for it again.
_IDLE_TTL_SECONDS = 90.0


def _same_model(a: dict, b: dict) -> bool:
    """Whether two specs would build the identical pipeline."""
    if (a.get("model_info") or {}).get("repo") != \
            (b.get("model_info") or {}).get("repo"):
        return False
    if (a.get("model_info") or {}).get("engine") != \
            (b.get("model_info") or {}).get("engine"):
        return False
    # A finetune REPLACES the backbone of the pipeline built from that repo,
    # so two runs naming the same repo and different finetunes are two
    # different models — and one of them is holding the other's weights.
    if (a.get("model_info") or {}).get("finetune") != \
            (b.get("model_info") or {}).get("finetune"):
        return False
    key = lambda spec: [(lo.get("path"), float(lo.get("weight", 1.0)))
                        for lo in spec.get("loras", [])]
    return key(a) == key(b)


def _read_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _next_queued(root: Path):
    """The oldest run waiting to be generated, as `(dir, spec)` or None."""
    if not root.is_dir():
        return None
    waiting = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        state = _read_json(d / "state.json") or {}
        if state.get("phase") != "queued":
            continue
        spec = _read_json(d / "spec.json")
        if spec is not None:
            waiting.append((spec.get("created_at", 0), d, spec))
    if not waiting:
        return None
    waiting.sort(key=lambda w: w[0])
    return waiting[0][1], waiting[0][2]


def _run_one(run_dir: Path, spec: dict, pipe, t0: float) -> tuple[int, object]:
    """Generate one run. Returns `(exit_code_or_-1, pipe)`; -1 means "carry on"."""
    try:
        if pipe is None:
            pipe = _load_pipe(run_dir, spec)
        _render(run_dir, spec, pipe, t0)
    except KeyboardInterrupt:
        _write_state(run_dir, "canceled")
        return 0, pipe
    except Exception as exc:  # noqa: BLE001 - report, then fail
        import traceback
        traceback.print_exc()
        import failure

        _write_state(run_dir, "failed",
                     error=failure.explain(f"{type(exc).__name__}: {exc}",
                                           spec if isinstance(spec, dict) else {},
                                           training=False),
                     elapsed=time.time() - t0)
        return 1, None       # a broken pipeline is not worth keeping warm
    _write_state(run_dir, "completed",
                 image=int(spec.get("count", 1)), total=int(spec.get("count", 1)),
                 elapsed=time.time() - t0)
    return -1, pipe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    signal.signal(signal.SIGTERM, _on_term)

    spec = _read_json(run_dir / "spec.json")
    if spec is None:
        return 1
    _write_state(run_dir, "starting")
    pipe = None
    t0 = _T0
    while True:
        code, pipe = _run_one(run_dir, spec, pipe, t0)
        if code >= 0:
            return code
        if pipe is None:
            return 0
        # Stay alive with the model resident and take the next queued run
        # itself. The manager treats this process as busy while it lives, so
        # there is no second process to race with — and a run it cannot serve
        # (a different model) ends the wait at once, so the manager can spawn
        # the right one without waiting out the whole TTL.
        deadline = time.time() + _IDLE_TTL_SECONDS
        nxt = None
        while time.time() < deadline:
            if _CANCELED:
                return 0
            found = _next_queued(run_dir.parent)
            if found is not None:
                if not _same_model(spec, found[1]):
                    return 0
                nxt = found
                break
            time.sleep(0.4)
        if nxt is None:
            return 0
        run_dir, spec = nxt
        t0 = time.time()
        # Claim it before generating: the manager reads phases to decide what
        # is still waiting.
        _write_state(run_dir, "starting")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
