# Third-party notices

Media Compost itself is licensed under the GNU Affero General Public License,
version 3 or later — see [LICENSE](LICENSE).

This file covers everything **redistributed inside the wheel**: the fonts, the
world map, the built web app's JavaScript, and the third-party model code
vendored into `media_compost/`. Each entry names its upstream and its licence, and the full
text of every distinct licence is either in `licenses/` or beside the files it
covers.

Two things are deliberately **not** here, because they are not redistributed:

- **Python dependencies** (`sqlalchemy`, `pillow`, `fastapi`, …) are installed
  by pip from their own distributions, each carrying its own licence.
- **Model weights**, which are downloaded from Hugging Face or a project's own
  release page at setup time and never ship in the wheel. Their licences are
  the model publisher's; the ones this app can fetch are listed at the end for
  information.

---

## Map data

The world outline the app draws a coordinate on — `frontend/src/shared/
worldLand.ts`, compiled into the served bundle.

| What | Copyright | Licence |
| --- | --- | --- |
| World map (Robinson projection) | © 2020 Pareto Software, LLC DBA Simplemaps.com | MIT — `licenses/MIT-simplemaps.txt` |

**It is a derived work**: `scripts/build_worldmap.py` merges the upstream
SVG's 470 country paths into one silhouette and drops islands smaller than a
pixel at the size it is drawn. The MIT notice travels INSIDE the generated
module as a `/*! */` comment — the one comment form a minifier keeps — because
what reaches the user is the bundle, and a notice that does not survive the
build is not a notice.

Nothing is fetched to render it: there is no tile service and no geocoder in
this app, and where a picture was taken never leaves the machine.

## Fonts

Shipped in `media_compost/ui/_web_dist/fonts/`, with their licence text in
that same directory.

| Font | Copyright | Licence |
| --- | --- | --- |
| IBM Plex Sans, IBM Plex Mono | © 2017 IBM Corp., with Reserved Font Name "Plex" | SIL Open Font License 1.1 — `LICENSE-IBM-Plex.txt`, also `licenses/OFL-1.1-IBM-Plex.txt` |
| Material Symbols Rounded | © Google LLC | Apache License 2.0 — `LICENSE-Material-Symbols.txt`, also `licenses/Apache-2.0.txt` |

Each text appears twice on purpose: once in `licenses/` (which
`[project] license-files` puts in the wheel's `dist-info`) and once in the
fonts directory itself, because those files are served to a browser and
nothing on that path ever sees `dist-info`.

**These are subset builds**, obtained from Google Fonts: each family is split
by `unicode-range` into per-script `.woff2` files so a browser fetches only the
scripts a page uses. The OFL treats subsetting as producing a Modified Version,
and IBM Plex carries a Reserved Font Name; the files are served here under the
original family names, as Google Fonts serves them. No glyph outline has been
altered. The upstream, unmodified fonts are at
<https://github.com/IBM/plex> and <https://github.com/google/material-design-icons>.

The app loads these from its own server and never contacts a font CDN — that
is why they are vendored at all. Nothing in the web app depends on an online
resource.

---

## Web app bundle (JavaScript)

Compiled into `media_compost/ui/_web_dist/assets/index-*.js`. **All twelve are
MIT**; the licence text follows the list once. (`@types/*` and `csstype` are
type-only and contribute no code to the bundle — they are listed for
completeness.)

| Package | Copyright |
| --- | --- |
| `@tanstack/query-core` | Copyright (c) 2021-present Tanner Linsley |
| `@tanstack/react-query` | Copyright (c) 2021-present Tanner Linsley |
| `@types/prop-types` | Copyright (c) Microsoft Corporation. |
| `@types/react` | Copyright (c) Microsoft Corporation. |
| `csstype` | Copyright (c) 2017-2018 Fredrik Nicol |
| `js-tokens` | Copyright (c) 2014, 2015, 2016, 2017, 2018 Simon Lydell |
| `loose-envify` | Copyright (c) 2015 Andres Suarez \<zertosh@gmail.com\> |
| `react` | Copyright (c) Facebook, Inc. and its affiliates. |
| `react-dom` | Copyright (c) Facebook, Inc. and its affiliates. |
| `scheduler` | Copyright (c) Facebook, Inc. and its affiliates. |
| `use-sync-external-store` | Copyright (c) Meta Platforms, Inc. and affiliates. |
| `zustand` | Copyright (c) 2019 Paul Henschel |

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

---

## Vendored model code (Python)

Model architectures whose upstreams are not pip-installable, copied into this
repository so the published weights load without a separate clone. Each file's
own header records its provenance; this table is the summary.

| File | Upstream | Licence |
| --- | --- | --- |
| `media_compost/ui/vendor/joytag_models.py` | [fpgaminer/joytag](https://github.com/fpgaminer/joytag) | Apache-2.0 — `licenses/Apache-2.0.txt` |
| `media_compost/ui/plugins/impl/colorize_photo.py` (network only) | [richzhang/colorization](https://github.com/richzhang/colorization) | BSD-2-Clause — `licenses/BSD-2-Clause-colorization.txt` |
| `media_compost/ui/plugins/impl/colorize_manga.py` (networks only) | [linshys/Example_Based_Manga_Colorization---cGAN](https://github.com/linshys/Example_Based_Manga_Colorization---cGAN) | Apache-2.0 — `licenses/Apache-2.0.txt` |
| `media_compost/ui/plugins/impl/ram_plus.py` (`prune_linear_layer` helper) | [huggingface/transformers](https://github.com/huggingface/transformers) | Apache-2.0 — `licenses/Apache-2.0.txt` |

**Modifications**, as Apache-2.0 §4(b) requires them to be stated: each file
keeps only the layers needed for inference and carries a header naming its
source. `joytag_models.py` is byte-for-byte upstream apart from that header.
`ram_plus.py`'s helper is a copy of a function transformers removed in 5.x.

Not vendored, and deliberately so: **Manga Colorization v2**
([qweasdd/manga-colorization-v2](https://github.com/qweasdd/manga-colorization-v2))
publishes no licence at all, so its network code is fetched at setup time
rather than redistributed here. See `colorize_mangav2.py`.

---

## Models downloaded at setup time

Not redistributed — listed so you know what you are fetching. The licence is
the publisher's, and it applies to you as the person who downloads it.

| Model | Source | Licence |
| --- | --- | --- |
| OpenComic descreen graphs | [ollm/opencomic-ai-training](https://github.com/ollm/opencomic-ai-training) | MIT (weights CC BY 4.0) |
| Manga Colorization v2 (code + weights) | qweasdd / `vergil1000/manga-colorization-v2` | **none published** |
| Real-ESRGAN x2plus | [xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) release v0.2.1, fetched from the mirror `2kpr/Real-ESRGAN` (same SHA-256) | BSD-3-Clause |
| SCUNet (real-image, GAN) | [cszn/SCUNet](https://github.com/cszn/SCUNet) via the KAIR v1.0 release, fetched from the mirror `krnl/ScuNET` (same SHA-256; the mirror states no licence of its own) | Apache-2.0 |

Everything else comes from a Hugging Face repository that states its own
licence on its model page; the app's Settings → Models panel links to each.
