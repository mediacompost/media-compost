"""withoutBG background removal (open ONNX weights via onnxruntime)."""

from __future__ import annotations

import os

_ONNX = "withoutbg-open-weights.onnx"

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[ModelSpec(
            id="withoutbg", task="bg_removal", name="withoutBG (ONNX)",
            family="withoutBG", note="Open-weights ONNX background remover.")],
        sources=[ModelSource(
            key="withoutbg", label="withoutBG (ONNX)",
            repo="withoutbg/withoutbg-openweights-onnx",
            url="https://huggingface.co/withoutbg/withoutbg-openweights-onnx",
            onnx=True, probe=_ONNX,
            allow_patterns=(_ONNX, _ONNX + ".json"))],
        deps=("onnxruntime", "numpy"),
        url="https://huggingface.co/withoutbg/withoutbg-openweights-onnx",
        source_for_model={"withoutbg": "withoutbg"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def _weights(ctx) -> str:  # pragma: no cover - heavy optional dep
    p = ctx["sources"]["withoutbg"]  # local path override, or the default repo id
    if p and os.path.isfile(p):
        return p
    if p and os.path.isdir(p):
        for f in sorted(os.listdir(p)):
            if f.endswith(".onnx"):
                return os.path.join(p, f)
        raise RuntimeError("no .onnx file found in the withoutBG local path")
    from huggingface_hub import hf_hub_download
    return hf_hub_download(p, _ONNX,
                           local_files_only=bool(ctx.get("local_files_only", True)),
                           token=ctx.get("token") or None)


#: Used when the graph's spatial axes are dynamic and so say nothing.
_DEFAULT_CANVAS = 1024


def _canvas_size(shape) -> int:
    """The square input size an ONNX input shape asks for, else the default.

    Pure, so the fixed/dynamic cases are testable without the model.
    ``shape`` is NCHW; a fixed axis is an int, a dynamic one is a string
    (the symbolic name) or None.
    """
    for axis in list(shape)[2:4]:
        if isinstance(axis, int) and axis > 0:
            return axis
        if isinstance(axis, str) and axis.isdigit() and int(axis) > 0:
            return int(axis)
    return _DEFAULT_CANVAS


def _split_sigmoid_conv(path: str) -> bytes:  # pragma: no cover - heavy optional dep
    """The model's bytes with every `FusedConv` whose activation is not Relu
    split into the plain Conv (same inputs, same attributes) and its
    activation node — what onnxruntime's optimiser fused for the CPU and
    the CUDA kernel cannot take back. Everything else is left as it is."""
    import onnx
    from onnx import helper

    m = onnx.load(path)
    nodes = []
    for n in m.graph.node:
        act = next((a.s.decode() for a in n.attribute if a.name == "activation"), "")
        if n.op_type != "FusedConv" or act in ("", "Relu"):
            nodes.append(n)
            continue
        attrs = {a.name: helper.get_attribute_value(a) for a in n.attribute
                 if a.name not in ("activation", "activation_params")}
        conv_out = n.output[0] + "__conv"
        conv = helper.make_node("Conv", list(n.input[:3]), [conv_out],
                                name=(n.name or n.output[0]) + "_conv", **attrs)
        nodes.append(conv)
        src = conv_out
        if len(n.input) > 3:   # a summed input the fusion folded in
            added = n.output[0] + "__sum"
            nodes.append(helper.make_node("Add", [src, n.input[3]], [added],
                                          name=(n.name or n.output[0]) + "_add"))
            src = added
        nodes.append(helper.make_node(act, [src], [n.output[0]],
                                      name=(n.name or n.output[0]) + "_act"))
    del m.graph.node[:]
    m.graph.node.extend(nodes)
    return m.SerializeToString()


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import onnxruntime as ort

    from . import _ort

    # The card where there is one — this was `["CPUExecutionProvider"]`,
    # hardcoded: 2.1 s a picture on the 5090 box's cores with the card at 0%.
    providers, _ = _ort.providers()
    path = _weights(ctx)
    sess = None
    if providers[0] != "CPUExecutionProvider":
        # THE FILE CARRIES onnxruntime's OWN FUSIONS — it was exported
        # optimised: 234 `FusedConv` nodes, one of them Conv + Sigmoid,
        # and the CUDA kernel for `FusedConv` knows Relu alone
        # ("unsupported conv activation mode Sigmoid"): the session cannot
        # be built, on any card. `_split_sigmoid_conv` puts that one node
        # back as Conv followed by Sigmoid — the same arithmetic — and the
        # card takes the rest. Without the `onnx` package for the rewrite,
        # or a provider that still refuses, the CPU stands in with the
        # reason in the log rather than every picture failing.
        try:
            sess = ort.InferenceSession(_split_sigmoid_conv(path), providers=providers)
        except Exception as exc:  # noqa: BLE001 - the CPU always works
            print(f"bg removal: {providers[0]} refused the model "
                  f"({str(exc)[-160:]}); using the CPU", flush=True)
            providers = ["CPUExecutionProvider"]
    if sess is None:
        sess = ort.InferenceSession(path, providers=providers)
    got = _ort.session_providers([sess])
    print(f"bg removal: onnxruntime providers {providers}; session runs on "
          f"{got or ['?']}", flush=True)
    if got == ["CPUExecutionProvider"] and providers[0] == "CPUExecutionProvider" \
            and len(providers) == 1 and "CUDAExecutionProvider" not in ort.get_available_providers():
        _ort.say_cpu_only("bg removal")
    return sess


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import numpy as np
    from PIL import Image

    sess = handle
    inp = sess.get_inputs()[0]
    in_name = inp.name
    out_name = sess.get_outputs()[0].name
    # Square NCHW RGB canvas in [0,1]; letterbox (preserve aspect, pad), run,
    # then undo the padding and resize the alpha back.
    #
    # The canvas size is READ OFF THE GRAPH rather than hardcoded. It was a
    # literal 1024, and the published weights declare a fixed [1,3,448,448]
    # input — so onnxruntime rejected every call with "Got invalid dimensions
    # for input: rgb ... Got: 1024 Expected: 448" and this remover could not
    # run at all. A fixed axis is authoritative; a dynamic one (a string or
    # None) means the model will take what it is given, and 1024 stays the
    # default there.
    rgb = image.convert("RGB")
    w, h = rgb.size
    canvas = _canvas_size(inp.shape)
    scale = min(canvas / w, canvas / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    px, py = (canvas - nw) // 2, (canvas - nh) // 2
    board = Image.new("RGB", (canvas, canvas), (0, 0, 0))
    board.paste(rgb.resize((nw, nh), Image.LANCZOS), (px, py))
    arr = (np.asarray(board, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None]
    alpha = sess.run([out_name], {in_name: arr})[0][0, 0]  # H×W in [0,1]
    a = Image.fromarray((np.clip(alpha, 0, 1) * 255).astype("uint8"), "L")
    a = a.resize((canvas, canvas), Image.BILINEAR).crop((px, py, px + nw, py + nh))
    out = rgb.convert("RGBA")
    out.putalpha(a.resize((w, h), Image.BILINEAR))
    return {"image": out}
