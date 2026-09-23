# Media Compost Documentation

Media Compost is a self-hosted web app for organizing and annotating images and videos for AI training. It deduplicates everything you import, organizes items with groups, tags, and captions, includes full image and annotation editors, runs AI models locally (tagging, captioning, face detection, background removal, and more), and can train LoRAs on your own library.

## Getting set up

- [Features](features.md) — a tour of the app, one screen at a time.
- [Installation](installation.md) — requirements, building, and running the server.
- [Getting started](getting-started.md) — core concepts: items, groups, tags, sequences, and how the library is stored on disk.
- [Compatibility](compatibility.md) — what a library's format version promises across app updates.

## Everyday use

- [Importing files](import.md) — the import overlay, deduplication, archives, videos, and reorientation detection.
- [Browsing the library](library.md) — the group tree, the item grid, selection, Quick Look, sequences, Hidden, and Trash.
- [Searching](search.md) — the query builder and the query language.
- [The item panel](item-properties.md) — tags, captions, source files, links, metadata, AI actions, and Quick Assign.

## Editing and annotating

- [Image editor](image-editor.md) — a full raster editor with selections, brushes, transforms, inpainting, and AI-assisted tools.
- [Annotation editor](annotation-editor.md) — tag bounding boxes and face boxes.
- [Video editor](video-editor.md) — the cutlist: trim, split, move, rotate, crop, and render.

## Organizing your tag set

- [Tags](tags.md) — the Tags tab, implications, aliases, merging, and meta tags.
- [Tag sets](tag-sets.md) — imported tag lists that advise every tag field.
- [Subjects and faces](subjects-and-faces.md) — people, face detection, the Faces page, and name suggestions.
- [Places](places.md) — location data on tags, GPS import, and address forms.
- [Events](events.md) — time spans, venues, suggestions, and capture dates.
- [Rankings and batch sessions](rankings.md) — rating pictures on an axis, and the three full-window sessions.
- [History](history.md) — the modification log and undo.

## AI and training

- [Settings](settings.md) — general preferences, tagging defaults, and the AI model manager.
- [Training](training.md) — training LoRAs on your library from the Train tab.
- [Evaluate](evaluate.md) — generating test images with your trained LoRAs.

## Automation

- [Command line](cli.md) — bulk import and library maintenance with the `media-compost` CLI.
- [Python API](python-api.md) — reading and editing the library from Python: querying, tags, subjects, faces, importing, history, and the paths of the files on disk.
- [Translating](translating.md) — writing or revising a UI dictionary.
- [API reference](api/index.md) — the generated per-module reference behind the guide.

## When something goes wrong

- [Troubleshooting](troubleshooting.md) — error screens, library repair, and common issues.

---

These pages are also published as the project website (with a landing page and
a feature tour on top of them) — see `website/mkdocs.yml` and the *The website*
section of `SETUP.md`.
