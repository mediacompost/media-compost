"""Example-based manga/comic colorization (Color2Embed cGAN).

Transfers the palette of a user-picked **reference image** onto a grayscale
manga/comic page: a VGG-based encoder squeezes the reference into a 512-d
color embedding, and a UNet generator predicts the page's a/b channels from
its lightness + that embedding (Color2Embed, 2021; weights trained on manga by
the Example_Based_Manga_Colorization project). The two small networks are
vendored below (the upstream repo is code-only, not a package) from
linshys/Example_Based_Manga_Colorization---cGAN, **Apache-2.0** — inference
layers only, so the published state dict loads unchanged; see
THIRD-PARTY-NOTICES.md. The trained checkpoint (~180 MB) downloads from its
Hugging Face mirror like any other model.

This model **requires a reference image** (``needs_reference``): the UI opens
the reference picker before enqueueing and the job's options carry the chosen
image's path.
"""

from __future__ import annotations

import os

_CKPT_FILE = "experiments/Color2Manga_gray/074000_gray.pt"
_VGG_FILE = "experiments/VGG19/vgg19-dcbb9e9d.pth"
_REPO = "Keiser41/Example_Based_Manga_Colorization"

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(
                id="color2manga_gray", task="colorize",
                name="Example-based (manga)",
                family="Example-based (manga & comics)",
                note="Colors a grayscale page like a reference image you pick "
                     "(Color2Embed cGAN).",
                needs_reference=True),
        ],
        sources=[
            ModelSource(
                key="color2manga", label="Color2Manga (example-based)",
                repo=_REPO,
                url="https://huggingface.co/" + _REPO,
                probe=_CKPT_FILE,
                allow_patterns=("experiments/Color2Manga_gray/*",
                                "experiments/VGG19/*")),
        ],
        deps=("torch", "torchvision", "cv2", "numpy"),
        url="https://github.com/linshys/Example_Based_Manga_Colorization---cGAN",
        source_for_model={"color2manga_gray": "color2manga"},
    )
except (ImportError, ValueError):
    MANIFEST = None


# ---- vendored networks (Color2Embed; upstream models.py / vgg_model.py) ----


def _build_modules():  # pragma: no cover - heavy optional dep
    import math

    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torchvision import models as tv_models

    class Vgg19Features(nn.Module):
        """torchvision VGG19 run up to relu5_2 (upstream vgg_model.vgg19 with
        its ImageNet normalization). ``vgg_feature`` aliases the features
        stack under the same attribute name the upstream class registered, so
        the published checkpoint's ``vgg.vgg_feature.*`` keys map cleanly."""

        def __init__(self):
            super().__init__()
            self.vgg_model = tv_models.vgg19()
            self.vgg_feature = self.vgg_model.features

        def forward(self, x):
            mean = x.new_tensor([0.485, 0.456, 0.406]).view(-1, 1, 1)
            std = x.new_tensor([0.229, 0.224, 0.225]).view(-1, 1, 1)
            x = (x - mean) / std
            # relu5_2 = feature index 31: run layers 0..31 inclusive.
            for layer in self.vgg_feature[:32]:
                x = layer(x)
            return [x]

    class DoubleConv(nn.Module):
        def __init__(self, in_ch, out_ch, mid_ch=None):
            super().__init__()
            mid_ch = mid_ch or out_ch
            self.double_conv = nn.Sequential(
                nn.Conv2d(in_ch, mid_ch, kernel_size=3, padding=1),
                nn.BatchNorm2d(mid_ch), nn.LeakyReLU(0.1, True),
                nn.Conv2d(mid_ch, out_ch, kernel_size=3, padding=1),
                nn.BatchNorm2d(out_ch), nn.LeakyReLU(0.1, True))

        def forward(self, x):
            return self.double_conv(x)

    class ResBlock(nn.Module):
        def __init__(self, in_ch, out_ch):
            super().__init__()
            self.bottle_conv = nn.Conv2d(in_ch, out_ch, 1, 1, 0)
            self.double_conv = nn.Sequential(
                nn.Conv2d(out_ch, out_ch, kernel_size=3, padding=1),
                nn.BatchNorm2d(out_ch), nn.LeakyReLU(0.2, True),
                nn.Conv2d(out_ch, out_ch, kernel_size=3, padding=1))

        def forward(self, x):
            x = self.bottle_conv(x)
            return (self.double_conv(x) + x) / math.sqrt(2)

    class Down(nn.Module):
        def __init__(self, in_ch, out_ch):
            super().__init__()
            self.main = nn.Sequential(
                nn.Conv2d(in_ch, in_ch, 4, 2, 1), nn.LeakyReLU(0.1, True),
                ResBlock(in_ch, out_ch))

        def forward(self, x):
            return self.main(x)

    class SDFT(nn.Module):
        """Style-modulated conv (StyleGAN2-style weight (de)modulation)."""

        def __init__(self, color_dim, channels, kernel_size=3):
            super().__init__()
            fan_in = channels * kernel_size ** 2
            self.kernel_size = kernel_size
            self.padding = kernel_size // 2
            self.scale = 1 / math.sqrt(fan_in)
            self.modulation = nn.Conv2d(color_dim, channels, 1)
            self.weight = nn.Parameter(
                torch.randn(1, channels, channels, kernel_size, kernel_size))

        def forward(self, fea, color_style):
            b, c, h, w = fea.size()
            style = self.modulation(color_style).view(b, 1, c, 1, 1)
            weight = self.scale * self.weight * style
            demod = torch.rsqrt(weight.pow(2).sum([2, 3, 4]) + 1e-8)
            weight = (weight * demod.view(b, c, 1, 1, 1)).view(
                b * c, c, self.kernel_size, self.kernel_size)
            fea = fea.view(1, b * c, h, w)
            fea = F.conv2d(fea, weight, padding=self.padding, groups=b)
            return fea.view(b, c, h, w)

    class UpBlock(nn.Module):
        def __init__(self, color_dim, in_ch, out_ch, kernel_size=3):
            super().__init__()
            self.up = nn.Upsample(scale_factor=2, mode="bilinear",
                                  align_corners=False)
            self.conv_cat = nn.Sequential(
                nn.Conv2d(in_ch // 2 + in_ch // 8, out_ch, 1, 1, 0),
                nn.LeakyReLU(0.2, True),
                nn.Conv2d(out_ch, out_ch, kernel_size=3, padding=1),
                nn.LeakyReLU(0.2, True))
            self.conv_s = nn.Conv2d(in_ch // 2, out_ch, 1, 1, 0)
            self.SDFT = SDFT(color_dim, out_ch, kernel_size)

        def forward(self, x1, x2, color_style):
            x1 = self.up(x1)
            x1_s = self.conv_s(x1)
            x = torch.cat([x1, x2[:, ::4, :, :]], dim=1)
            x = self.conv_cat(x)
            x = self.SDFT(x, color_style)
            return x + x1_s

    class ColorEncoder(nn.Module):
        def __init__(self, color_dim=512):
            super().__init__()
            self.vgg = Vgg19Features()
            self.feature2vector = nn.Sequential(
                nn.Conv2d(color_dim, color_dim, 4, 2, 2),
                nn.LeakyReLU(0.2, True),
                nn.Conv2d(color_dim, color_dim, 3, 1, 1),
                nn.LeakyReLU(0.2, True),
                nn.Conv2d(color_dim, color_dim, 4, 2, 2),
                nn.LeakyReLU(0.2, True),
                nn.Conv2d(color_dim, color_dim, 3, 1, 1),
                nn.LeakyReLU(0.2, True),
                nn.AdaptiveAvgPool2d((1, 1)),
                nn.Conv2d(color_dim, color_dim // 2, 1),
                nn.LeakyReLU(0.2, True),
                nn.Conv2d(color_dim // 2, color_dim // 2, 1),
                nn.LeakyReLU(0.2, True),
                nn.Conv2d(color_dim // 2, color_dim, 1))

        def forward(self, x):
            return self.feature2vector(self.vgg(x)[-1])

    class ColorUNet(nn.Module):
        def __init__(self, n_channels=1):
            super().__init__()
            self.inc = DoubleConv(n_channels, 64)
            self.down1 = Down(64, 128)
            self.down2 = Down(128, 256)
            self.down3 = Down(256, 512)
            self.down4 = Down(512, 512)
            self.up1 = UpBlock(512, 1024, 256, 3)
            self.up2 = UpBlock(512, 512, 128, 3)
            self.up3 = UpBlock(512, 256, 64, 5)
            self.up4 = UpBlock(512, 128, 64, 5)
            self.outc = nn.Sequential(
                nn.Conv2d(64, 64, 3, 1, 1), nn.LeakyReLU(0.2, True),
                nn.Conv2d(64, 2, 3, 1, 1), nn.Tanh())

        def forward(self, x):
            gray, color_vec = x
            x1 = self.inc(gray)
            x2 = self.down1(x1)
            x3 = self.down2(x2)
            x4 = self.down3(x3)
            x5 = self.down4(x4)
            x6 = self.up1(x5, x4, color_vec)
            x7 = self.up2(x6, x3, color_vec)
            x8 = self.up3(x7, x2, color_vec)
            x9 = self.up4(x8, x1, color_vec)
            return self.outc(x9)

    return ColorEncoder, ColorUNet


def _fetch(ctx, filename: str) -> str:  # pragma: no cover - heavy optional dep
    p = ctx["sources"]["color2manga"]
    if p and os.path.isdir(p):
        cand = os.path.join(p, filename)
        if os.path.isfile(cand):
            return cand
        raise RuntimeError(f"{filename} not found in {p}")
    from huggingface_hub import hf_hub_download

    return hf_hub_download(p, filename,
                           local_files_only=bool(ctx.get("local_files_only", True)),
                           token=ctx.get("token") or None)


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import argparse

    import torch

    ColorEncoder, ColorUNet = _build_modules()
    from . import _accel

    device = _accel.device("MEDIA_COMPOST_COLORIZE_DEVICE")   # was CUDA or the CPU: never MPS
    # The published checkpoint stores its training args as an
    # argparse.Namespace next to the state dicts; allowlist exactly that type
    # so torch's weights-only unpickler (the 2.6+ default) accepts the file
    # without falling back to full unpickling.
    with torch.serialization.safe_globals([argparse.Namespace]):
        ckpt = torch.load(_fetch(ctx, _CKPT_FILE), map_location="cpu")
    encoder = ColorEncoder()
    # The checkpoint carries the encoder incl. its VGG submodule; the separate
    # VGG19 file backfills those weights for checkpoints saved without them.
    try:
        vgg_sd = torch.load(_fetch(ctx, _VGG_FILE), map_location="cpu")
        encoder.vgg.vgg_model.load_state_dict(vgg_sd)
    except Exception:  # noqa: BLE001 - ckpt may already contain the weights
        pass
    encoder.load_state_dict(ckpt["colorEncoder"], strict=False)
    unet = ColorUNet()
    unet.load_state_dict(ckpt["colorUNet"], strict=False)
    return encoder.to(device).eval(), unet.to(device).eval(), device


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import cv2
    import numpy as np
    import torch
    import torch.nn.functional as F
    from PIL import Image

    ref_path = (options or {}).get("reference", "")
    if not ref_path or not os.path.isfile(ref_path):
        raise RuntimeError("this model needs a color reference image — pick "
                           "one when starting the action")
    encoder, unet, device = handle

    page = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    ref = Image.open(ref_path)
    ref = np.asarray(ref.convert("RGB"), dtype=np.float32) / 255.0
    h, w = page.shape[:2]

    page_lab = cv2.cvtColor(page, cv2.COLOR_RGB2Lab)  # L 0..100
    l_full = torch.from_numpy(page_lab[:, :, 0])[None, None]   # [1,1,H,W]
    l_rs = F.interpolate(l_full / 50.0 - 1.0, size=(256, 256),
                         mode="bilinear", align_corners=False)
    ref_t = torch.from_numpy(ref.transpose(2, 0, 1))[None]     # [1,3,H,W] 0..1
    ref_rs = F.interpolate(ref_t, size=(256, 256), mode="bilinear",
                           align_corners=False)

    with torch.no_grad():
        color_vec = encoder(ref_rs.to(device))
        ab = unet((l_rs.to(device), color_vec)).cpu()          # [-1, 1]
    ab = F.interpolate(ab * 110.0, size=(h, w), mode="bilinear",
                       align_corners=False)[0].numpy().transpose(1, 2, 0)

    out_lab = np.concatenate((page_lab[:, :, :1], ab), axis=2)
    out = cv2.cvtColor(out_lab.astype(np.float32), cv2.COLOR_Lab2RGB)
    out = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    return {"image": Image.fromarray(out)}
