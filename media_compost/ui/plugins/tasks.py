"""The fixed set of AI-action *tasks*.

This is the **only** place the action kinds are enumerated. Each task carries the
UI metadata (label + Material Symbol icon) so the frontend can render the action
buttons data-driven — models and actions are no longer hardcoded in the UI. The
set is fixed; plugins attach to a task by its ``kind``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    kind: str
    label: str
    icon: str            # Material Symbols Rounded name
    result: str          # "image" | "caption" | "tags" | "artifact" | "items"
                         #  | "faces" | "ocr" | "vector" | "boxes"
    # The `panels` task's own switch: gather the panels it cuts out into a
    # SEQUENCE of their own, beside the linked items it makes either way.
    #
    # The one extra output any action still offers. Every image task used to
    # carry a "Create new item for result" toggle beside it — the result
    # became its own item linked back instead of a source file on the item
    # the action ran on — and an action's result lands on its own item now,
    # full stop. Two places to put an answer is two places to look for one.
    sequence_option: bool = False


# Order is not significant for layout — each sidebar call site renders its own
# task(s) next to the relevant section — but is kept stable for the catalog.
TASKS: list[Task] = [
    Task("bg_removal", "Remove background", "background_replace", "image"),
    Task("watermark_removal", "Remove watermark", "ink_eraser", "image"),
    Task("text_removal", "Remove text", "format_clear", "image"),
    Task("upscale", "Upscale image", "photo_size_select_large", "image"),
    # "Clean" rather than "Remove": the action repairs compression damage in
    # place, it does not take an element out of the picture the way the
    # removal actions above do.
    Task("restore", "Clean artifacts", "deblur", "image"),
    Task("colorize", "Colorize", "palette", "image"),
    Task("descreen", "Remove screen tones", "texture", "image"),
    Task("tag", "Generate tags", "new_label", "tags"),
    Task("caption", "Generate caption", "add_comment", "caption"),
    # Auxiliary image outputs stored *nested under the source file* (not a
    # source of the item). These are ControlNet-style control images: depth
    # maps, OpenPose skeletons, Canny edges and line art.
    Task("depth", "Estimate depth", "lens_blur", "artifact"),
    Task("pose", "Estimate pose", "accessibility_new", "artifact"),
    # "Generate", not "Detect": it MAKES a control image out of the picture,
    # the way its three neighbours do, and nothing it produces is a finding
    # about the picture the way a face or a line of text is. The old wording
    # was the one label in this group that read as the other kind of action.
    Task("canny", "Generate Canny edges", "line_style", "artifact"),
    Task("lineart", "Estimate line art", "draw", "artifact"),
    # Comic/manga panel detection: each detected panel becomes its own item,
    # linked back to the source page.
    Task("panels", "Split comic panels", "manga", "items",
         sequence_option=True),
    # Face detection. The result is neither an image nor a new item: it is rows
    # in the `faces` table, reconciled against what is already there so a re-run
    # never undoes a name given by hand.
    Task("faces", "Detect faces", "face", "faces"),
    # Watermark detection. The result is neither an image nor a record table
    # of its own: the found regions land as BOXES on the configured watermark
    # tag (Settings → Tagging), which is exactly what the box-driven
    # watermark REMOVAL reads — detect writes what remove consumes.
    Task("watermark_detect", "Detect watermarks", "branding_watermark",
         "boxes"),
    # OCR. The same kind of result as faces — rows in `text_regions`,
    # reconciled so a re-run never undoes a correction — and NOT the same task
    # as `text_removal` above, which finds text in order to paint it out.
    Task("ocr", "Detect text", "document_scanner", "ocr"),
    # Feature indexing for the tag-batch overlay's smart ordering. The result
    # is a row in `item_embeddings` — derived, regenerable, no history event.
    # No sidebar action menu renders this task (each call site names its own
    # tasks explicitly); the overlay's "Index" button is its one caller.
    Task("embed", "Index for tag sorting", "network_node", "vector"),
]

#: Background-job kinds that are NOT AI actions — no model, no plugin, no menu
#: entry — but which do appear as rows in the background-task list and so need
#: a label and an icon like everything else there.
#:
#: They live BESIDE `TASKS` rather than in it: the list above is what the AI
#: action menus are built from, and a video render put in it would offer itself
#: as one. What they share is the one file where a kind gets its words, so the
#: task list can be served with them and the job list needs no second lookup.
OTHER_JOB_KINDS: list[Task] = [
    Task("video_edit", "Save video", "movie_edit", "image"),
    # Taking a still every N seconds across a film.
    Task("stills", "Take stills", "photo_camera", "items"),
    # Writing what a ranking's estimate claims over a whole scope. The one
    # job kind that is about no picture at all.
    Task("estimate", "Assign ratings", "query_stats", "tags"),
]


_BY_KIND = {t.kind: t for t in TASKS}


def task(kind: str) -> Task | None:
    return _BY_KIND.get(kind)


def task_kinds() -> set[str]:
    return set(_BY_KIND)
