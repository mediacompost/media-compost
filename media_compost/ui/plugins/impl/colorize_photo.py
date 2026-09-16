"""B&W / sepia photograph colorization (Colorful Image Colorization).

Zhang et al.'s SIGGRAPH 2017 interactive-colorization network, run in its
fully-automatic mode: the image's L (lightness) channel goes in, plausible
a/b color channels come out, and the original-resolution L is recombined with
the upsampled a/b — so the output keeps every pixel of detail and only gains
color. The compact generator (~130 MB) is vendored below (the upstream repo is
not pip-installable) and the official weights download from the authors' S3
bucket on first use (cached in the torch-hub checkpoint cache).

Sepia/toned photos are handled by taking only their lightness, which discards
the tint before colorizing.
"""

from __future__ import annotations

_WEIGHTS_URL = "https://colorizers.s3.us-east-2.amazonaws.com/siggraph17-df00044c.pth"

try:
    from ..framework import ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(
                id="colorful_siggraph17", task="colorize",
                name="Colorful Colorization (photos)",
                family="Colorful Colorization (photos)",
                note="For black-and-white or sepia photographs "
                     "(Zhang et al., SIGGRAPH'17). Weights download on first run."),
        ],
        sources=[],  # weights auto-download via torch.hub, not the HF cache
        deps=("torch", "numpy", "cv2"),
        url="https://github.com/richzhang/colorization",
    )
except (ImportError, ValueError):
    MANIFEST = None


def _build_generator():  # pragma: no cover - heavy optional dep
    """The SIGGRAPH'17 generator, vendored from richzhang/colorization
    (colorizers/siggraph17.py, BSD-2) — layer for layer, so the published
    state dict loads unchanged."""
    import torch
    import torch.nn as nn

    class SIGGRAPHGenerator(nn.Module):
        # Lab normalization constants (upstream BaseColor).
        l_cent, l_norm, ab_norm = 50.0, 100.0, 110.0

        def __init__(self, norm_layer=nn.BatchNorm2d, classes=529):
            super().__init__()
            relu = lambda: nn.ReLU(True)  # noqa: E731
            conv = lambda i, o, **kw: nn.Conv2d(  # noqa: E731
                i, o, kernel_size=3, stride=1, padding=1, bias=True, **kw)
            dil = lambda i, o: nn.Conv2d(  # noqa: E731
                i, o, kernel_size=3, dilation=2, stride=1, padding=2, bias=True)
            self.model1 = nn.Sequential(conv(4, 64), relu(), conv(64, 64),
                                        relu(), norm_layer(64))
            self.model2 = nn.Sequential(conv(64, 128), relu(), conv(128, 128),
                                        relu(), norm_layer(128))
            self.model3 = nn.Sequential(conv(128, 256), relu(), conv(256, 256),
                                        relu(), conv(256, 256), relu(),
                                        norm_layer(256))
            self.model4 = nn.Sequential(conv(256, 512), relu(), conv(512, 512),
                                        relu(), conv(512, 512), relu(),
                                        norm_layer(512))
            self.model5 = nn.Sequential(dil(512, 512), relu(), dil(512, 512),
                                        relu(), dil(512, 512), relu(),
                                        norm_layer(512))
            self.model6 = nn.Sequential(dil(512, 512), relu(), dil(512, 512),
                                        relu(), dil(512, 512), relu(),
                                        norm_layer(512))
            self.model7 = nn.Sequential(conv(512, 512), relu(), conv(512, 512),
                                        relu(), conv(512, 512), relu(),
                                        norm_layer(512))
            self.model8up = nn.Sequential(nn.ConvTranspose2d(
                512, 256, kernel_size=4, stride=2, padding=1, bias=True))
            self.model3short8 = nn.Sequential(conv(256, 256))
            self.model8 = nn.Sequential(relu(), conv(256, 256), relu(),
                                        conv(256, 256), relu(), norm_layer(256))
            self.model9up = nn.Sequential(nn.ConvTranspose2d(
                256, 128, kernel_size=4, stride=2, padding=1, bias=True))
            self.model2short9 = nn.Sequential(conv(128, 128))
            self.model9 = nn.Sequential(relu(), conv(128, 128), relu(),
                                        norm_layer(128))
            self.model10up = nn.Sequential(nn.ConvTranspose2d(
                128, 128, kernel_size=4, stride=2, padding=1, bias=True))
            self.model1short10 = nn.Sequential(conv(64, 128))
            self.model10 = nn.Sequential(relu(), conv(128, 128),
                                         nn.LeakyReLU(negative_slope=0.2))
            self.model_class = nn.Sequential(nn.Conv2d(
                256, classes, kernel_size=1, padding=0, stride=1, bias=True))
            self.model_out = nn.Sequential(nn.Conv2d(
                128, 2, kernel_size=1, padding=0, stride=1, bias=True), nn.Tanh())
            self.upsample4 = nn.Sequential(
                nn.Upsample(scale_factor=4, mode="bilinear"))
            self.softmax = nn.Sequential(nn.Softmax(dim=1))

        def forward(self, input_A, input_B=None, mask_B=None):
            import torch as _t

            if input_B is None:
                input_B = _t.cat((input_A * 0, input_A * 0), dim=1)
            if mask_B is None:
                mask_B = input_A * 0
            norm_l = (input_A - self.l_cent) / self.l_norm
            norm_ab = input_B / self.ab_norm
            conv1_2 = self.model1(_t.cat((norm_l, norm_ab, mask_B), dim=1))
            conv2_2 = self.model2(conv1_2[:, :, ::2, ::2])
            conv3_3 = self.model3(conv2_2[:, :, ::2, ::2])
            conv4_3 = self.model4(conv3_3[:, :, ::2, ::2])
            conv5_3 = self.model5(conv4_3)
            conv6_3 = self.model6(conv5_3)
            conv7_3 = self.model7(conv6_3)
            conv8_3 = self.model8(self.model8up(conv7_3)
                                  + self.model3short8(conv3_3))
            conv9_3 = self.model9(self.model9up(conv8_3)
                                  + self.model2short9(conv2_2))
            conv10_2 = self.model10(self.model10up(conv9_3)
                                    + self.model1short10(conv1_2))
            return self.model_out(conv10_2) * self.ab_norm

    model = SIGGRAPHGenerator()
    import torch.utils.model_zoo as model_zoo

    model.load_state_dict(model_zoo.load_url(
        _WEIGHTS_URL, map_location="cpu", check_hash=True))
    return model.eval()


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch

    model = _build_generator()
    from . import _accel

    device = _accel.device("MEDIA_COMPOST_COLORIZE_DEVICE")   # was CUDA or the CPU: never MPS
    return model.to(device), device


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import cv2
    import numpy as np
    import torch
    import torch.nn.functional as F

    model, device = handle
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2Lab)   # L 0..100, ab ±127
    l_orig = torch.from_numpy(lab[:, :, 0])[None, None]
    l_rs = F.interpolate(l_orig, size=(256, 256), mode="bilinear",
                         align_corners=False)
    with torch.no_grad():
        ab = model(l_rs.to(device)).cpu()
    ab = F.interpolate(ab, size=l_orig.shape[2:], mode="bilinear",
                       align_corners=False)
    out_lab = torch.cat((l_orig, ab), dim=1)[0].numpy().transpose(1, 2, 0)
    out = cv2.cvtColor(out_lab.astype(np.float32), cv2.COLOR_Lab2RGB)
    out = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    from PIL import Image

    return {"image": Image.fromarray(out)}
