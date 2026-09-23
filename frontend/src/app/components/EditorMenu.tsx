import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, JobKind, ModelInfo } from "../api";
import { evalExpr } from "../mathExpr";
import { Icon } from "../../shared/Icon";
import { ConfirmModal } from "../../shared/ConfirmModal";
import { RowMenu, type RowAction } from "../../shared/RowMenu";

/**
 * The image editor's action-bar menus: an **Image** menu (rotate, image /
 * canvas size dialogs, the three live effects — adjustments, blur and
 * sharpen) plus one menu button per buffer-level AI action —
 * Upscale, Colorize, Remove artifacts, Remove screen tones, Remove
 * background, each with its models under it — and a **Select**
 * menu (detector-driven text/watermark selection). Only models that are
 * ready to run (deps + downloaded weights) are clickable; reference-guided
 * models are excluded — there's no reference flow inside the editor.
 */

// A 3×3 anchor: where the existing content sits inside the new canvas.
export type CanvasAnchor = [number, number]; // 0 | 0.5 | 1 each

export function EditorMenus({
  dims,
  busy,
  hasSelection,
  inpaintReady,
  animeInpaintReady,
  onRotate,
  onResizeImage,
  onResizeCanvas,
  onAdjust,
  onBlurImage,
  onSharpenImage,
  onApplyBackground,
  onApplyModel,
  onSelectRegions,
  onCropToSelection,
  onFillSelection,
  onGrowSelection,
  onShrinkSelection,
  onBlurSelection,
  onInvertSelection,
  onTransformSelection,
  onClearSelection,
  onInpaintSelection,
}: {
  dims: { w: number; h: number };
  busy: boolean;
  hasSelection: boolean;
  inpaintReady: boolean;
  animeInpaintReady: boolean;
  onRotate: (dir: 1 | -1) => void;
  onResizeImage: (w: number, h: number) => void;
  onResizeCanvas: (w: number, h: number, anchor: CanvasAnchor) => void;
  /** Open the live brightness/contrast/hue/saturation panel. */
  onAdjust: () => void;
  /** Open the live blur panel. */
  onBlurImage: () => void;
  /** Open the live sharpen panel. */
  onSharpenImage: () => void;
  /** Put the background color behind the picture (asks for one if the
   *  background is transparent). */
  onApplyBackground: () => void;
  // needsReference marks a reference-guided model — the editor opens the
  // reference picker before applying.
  onApplyModel: (kind: JobKind, model: string, needsReference?: boolean) => void;
  onSelectRegions: (kind: "text" | "watermark") => void;
  onCropToSelection: () => void;
  onFillSelection: () => void;
  onGrowSelection: () => void;
  onShrinkSelection: () => void;
  onBlurSelection: () => void;
  onInvertSelection: () => void;
  onTransformSelection: () => void;
  onClearSelection: () => void;
  onInpaintSelection: (model: "big_lama" | "anime_lama") => void;
}) {
  const [dialog, setDialog] = useState<null | "image" | "canvas">(null);
  const { data: models } = useQuery({ queryKey: ["ml-models"], queryFn: api.mlModels });
  const { data: prefs } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const hideUnready = prefs?.hide_unready_actions ?? false;
  const { data: cache } = useQuery({ queryKey: ["model-cache"], queryFn: api.modelCache });

  const cachedKeys = new Set((cache?.models ?? []).filter((m) => m.cached).map((m) => m.key));
  const ready = (m: ModelInfo) =>
    m.available && !m.needs_reference && m.family_keys.every((k) => cachedKeys.has(k));
  // Selecting text is an OCR engine reading the buffer — the same engines the
  // Text tab uses; the watermark detector still rides on its removal task's
  // default model. (Text removal detects nothing any more: it paints out what
  // the library has already read, so there is no detector on that task to ask.)
  const detectorReady = (kind: "text" | "watermark") => {
    const list = (models?.tasks ?? []).find(
      (t) => t.kind === (kind === "text" ? "ocr" : "watermark_removal"))?.models ?? [];
    const first = list.filter((m) => !m.id.endsWith(":boxes"))[0];
    return !!first && ready(first);
  };

  // "Hide actions that need setting up" (per-user setting): an unready row is
  // dropped rather than greyed. One gate here covers every entry — models,
  // detectors and tools alike all come through `row()`. A greyed row's hint
  // says what it is waiting for.
  const NOT_READY = "Not ready — set up / download this model in Settings → Actions";
  const row = (o: { icon?: string; label: string; note?: string; enabled: boolean;
                    onClick: () => void; disabledTitle?: string; separated?: boolean }): RowAction[] =>
    hideUnready && !o.enabled ? [] : [{
      icon: o.icon, label: o.label, separated: o.separated,
      hint: o.enabled ? o.note : (o.disabledTitle ?? NOT_READY),
      disabled: !o.enabled || busy,
      onClick: o.onClick,
    }];
  const modelRows = (kind: JobKind, opts: { withReference?: boolean } = {}): RowAction[] => {
    // Reference-guided models are normally excluded (no reference flow); the
    // Colorize submenu opts in — picking one opens the reference picker.
    const list = (models?.tasks ?? []).find((t) => t.kind === kind)?.models
      .filter((m) => opts.withReference || !m.needs_reference) ?? [];
    if (list.length === 0) {
      return [{ label: "No models available.", disabled: true, onClick: () => {} }];
    }
    return list.flatMap((m) => row({
      label: m.family || m.name, note: m.variant || m.note || undefined,
      enabled: m.available && m.family_keys.every((k) => cachedKeys.has(k)),
      onClick: () => onApplyModel(kind, m.id, m.needs_reference),
    }));
  };
  const menuBtn: React.CSSProperties = {
    width: "auto", height: 32, gap: 5, padding: "0 10px", borderRadius: "var(--r-4)",
    color: "var(--text-2)", fontSize: "var(--fs-3)", fontWeight: 600, whiteSpace: "nowrap",
  };
  const chevron = <Icon name="expand_more" size={14} style={{ opacity: 0.7 }} />;

  const imageActions: RowAction[] = [
    ...row({ icon: "rotate_left", label: "Rotate left", note: "90° counter-clockwise", enabled: true, onClick: () => onRotate(-1) }),
    ...row({ icon: "rotate_right", label: "Rotate right", note: "90° clockwise", enabled: true, onClick: () => onRotate(1) }),
    ...row({ icon: "photo_size_select_large", label: "Image size…", note: `${dims.w}×${dims.h} px — resample the image`, enabled: true, onClick: () => setDialog("image"), separated: true }),
    ...row({ icon: "aspect_ratio", label: "Canvas size…", note: "Grow or trim the canvas without scaling", enabled: true, onClick: () => setDialog("canvas") }),
    // Beside Canvas size…, because it is the other half of that thought: you
    // grow the canvas and it comes up transparent, and this is what puts
    // something there. (It is not the Fill tool either — that paints OVER
    // what it covers; this goes UNDER, so the picture is untouched and only
    // its transparency changes.)
    ...row({ icon: "wallpaper", label: "Apply background color",
             note: hasSelection
               ? "Place the background color behind the selection"
               : "Place the background color behind the picture",
             enabled: true, onClick: onApplyBackground }),
    ...row({ icon: "tune", label: "Adjustments…",
             note: hasSelection
               ? "Brightness, contrast, hue, saturation — on the selection"
               : "Brightness, contrast, hue and saturation",
             enabled: true, onClick: onAdjust, separated: true }),
    // Beside Adjustments, because it is the same kind of thing: a number you
    // judge by looking, previewed live on the picture and applied as one
    // undoable step. (The Selection menu's **Blur selection…** is a different
    // verb — it softens the MASK's edge, and touches no pixel of the picture.)
    ...row({ icon: "lens_blur", label: "Blur…",
             note: hasSelection
               ? "Gaussian blur — on the selection"
               : "Gaussian blur the whole picture",
             enabled: true, onClick: onBlurImage }),
    ...row({ icon: "deblur", label: "Sharpen…",
             note: hasSelection
               ? "Unsharp mask — on the selection"
               : "Unsharp mask: lift the picture's own detail",
             enabled: true, onClick: onSharpenImage }),
    // The AI actions, a submenu each.
    { icon: "photo_size_select_large", label: "Upscale", separated: true, onClick: () => {},
      children: modelRows("upscale" as JobKind) },
    { icon: "palette", label: "Colorize", onClick: () => {},
      children: modelRows("colorize" as JobKind, { withReference: true }) },
    // The three removals stand BESIDE Upscale and Colorize, not under a
    // **Remove** of their own: each is one buffer-level action with a list of
    // models under it, exactly as those two are, and the grouping row bought
    // nothing — every child said "Remove …" already, so the word appeared
    // twice on the way to a model and each of the three sat two flyouts deep
    // where the neighbours it belongs with sat one.
    // `healing` rather than `deblur`: that glyph is dots resolving into a
    // sharp grid, which is Sharpen above and was never what removing
    // compression artifacts looks like — and two rows of one menu drawn with
    // one glyph say they are the same kind of thing.
    { icon: "healing", label: "Remove artifacts", onClick: () => {},
      children: modelRows("restore" as JobKind) },
    { icon: "texture", label: "Remove screen tones", onClick: () => {},
      children: modelRows("descreen" as JobKind) },
    { icon: "background_replace", label: "Remove background", onClick: () => {},
      children: modelRows("bg_removal" as JobKind) },
  ];
  const selectActions: RowAction[] = [
    ...row({ icon: "abc", label: "Select text", note: "Detect text regions and select them", enabled: detectorReady("text"), onClick: () => onSelectRegions("text") }),
    ...row({ icon: "branding_watermark", label: "Select watermark", note: "Detect watermarks/logos and select them", enabled: detectorReady("watermark"), onClick: () => onSelectRegions("watermark") }),
    { icon: "auto_fix_high", label: "Inpaint selection", separated: true, onClick: () => {}, children: [
      ...row({
        label: "Photo (big-lama)",
        note: "Fill the selected area from its surroundings",
        enabled: hasSelection && inpaintReady, onClick: () => onInpaintSelection("big_lama"),
        disabledTitle: !inpaintReady ? "Download the big-lama model in Settings → Actions" : "Make a selection first",
      }),
      ...row({
        label: "Anime / illustration",
        note: "Line-art & screentone fine-tune",
        enabled: hasSelection && animeInpaintReady, onClick: () => onInpaintSelection("anime_lama"),
        disabledTitle: !animeInpaintReady ? "Download the Anime LaMa model in Settings → Actions" : "Make a selection first",
      }),
    ] },
    ...row({ icon: "format_color_fill", label: "Fill selection", note: "Fill the selected area with the foreground color", enabled: hasSelection, onClick: onFillSelection, disabledTitle: "Make a selection first" }),
    ...row({ icon: "open_in_full", label: "Grow selection…", note: "Expand the selection outward by N pixels", enabled: hasSelection, onClick: onGrowSelection, disabledTitle: "Make a selection first" }),
    ...row({ icon: "close_fullscreen", label: "Shrink selection…", note: "Contract the selection inward by N pixels", enabled: hasSelection, onClick: onShrinkSelection, disabledTitle: "Make a selection first" }),
    ...row({ icon: "blur_on", label: "Blur selection…", note: "Soften the selection's own edge, so what you do next fades out across it", enabled: hasSelection, onClick: onBlurSelection, disabledTitle: "Make a selection first" }),
    ...row({ icon: "flip", label: "Invert selection", note: "Select everything that is not selected", enabled: hasSelection, onClick: onInvertSelection, disabledTitle: "Make a selection first" }),
    ...row({ icon: "transform", label: "Transform selection", note: "Lift the selected pixels to move, scale and rotate them", enabled: hasSelection, onClick: onTransformSelection, disabledTitle: "Make a selection first" }),
    ...row({ icon: "crop", label: "Crop to selection", note: "Crop the image to the selection's bounding box", enabled: hasSelection, onClick: onCropToSelection, disabledTitle: "Make a selection first" }),
    ...row({ icon: "deselect", label: "Clear selection", enabled: hasSelection, onClick: onClearSelection, disabledTitle: "Make a selection first" }),
  ];

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <RowMenu always icon="tune" title="Image" disabled={busy} minWidth={280}
        buttonStyle={menuBtn} label={<>Image{chevron}</>} actions={imageActions} />
      <RowMenu always icon="select" title="Selection" disabled={busy} minWidth={280}
        buttonStyle={menuBtn} label={<>Selection{chevron}</>} actions={selectActions} />
      {dialog === "image" && (
        <ImageSizeDialog dims={dims} onClose={() => setDialog(null)}
          onApply={(w, h) => { setDialog(null); onResizeImage(w, h); }} />
      )}
      {dialog === "canvas" && (
        <CanvasSizeDialog dims={dims} onClose={() => setDialog(null)}
          onApply={(w, h, a) => { setDialog(null); onResizeCanvas(w, h, a); }} />
      )}
    </div>
  );
}

/** The editor's two size dialogs draw through the one confirm sheet; the
 *  editor is deliberately English, so the sheet's `t` is the identity. */
function DialogShell({ title, onClose, children, apply }: {
  title: string; onClose: () => void; children: React.ReactNode;
  apply: { label: string; onClick: () => void };
}) {
  return (
    <ConfirmModal t={(x) => x} title={title} body={children}
      answer={{ label: apply.label }}
      onResult={(r) => { if (r === "answer") apply.onClick(); else onClose(); }} />
  );
}

function NumField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  // Text field with a local draft: plain numbers commit live (so the linked
  // aspect field follows while typing), and arithmetic expressions
  // ("500+10") evaluate when the field commits on blur/Enter.
  const [draft, setDraft] = useState(String(value));
  useEffect(() => { setDraft(String(value)); }, [value]);
  const clamp = (n: number) => Math.max(1, Math.min(16384, Math.round(n)));
  const commitDraft = () => {
    const n = evalExpr(draft);
    if (n != null) {
      const v = clamp(n);
      setDraft(String(v)); // explicit — committing the current value again never re-renders
      onChange(v);
    } else {
      setDraft(String(value));
    }
  };
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
      <span style={{ width: 52 }}>{label}</span>
      <input
        type="text" inputMode="decimal" value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value.trim() !== "" && Number.isFinite(n)) onChange(clamp(n));
        }}
        onBlur={commitDraft}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitDraft(); } }}
        style={{ width: 90, height: 28, borderRadius: "var(--r-3)", border: "1px solid var(--border-strong)", background: "var(--bg-deep)", color: "var(--text-2)", padding: "0 8px", fontSize: "var(--fs-3)" }}
      />
      <span style={{ color: "var(--muted-2)" }}>px</span>
    </label>
  );
}


function ImageSizeDialog({ dims, onApply, onClose }: {
  dims: { w: number; h: number };
  onApply: (w: number, h: number) => void;
  onClose: () => void;
}) {
  const [w, setW] = useState(dims.w);
  const [h, setH] = useState(dims.h);
  const [linked, setLinked] = useState(true);
  const setWidth = (v: number) => { setW(v); if (linked) setH(Math.max(1, Math.round((v * dims.h) / dims.w))); };
  const setHeight = (v: number) => { setH(v); if (linked) setW(Math.max(1, Math.round((v * dims.w) / dims.h))); };
  return (
    <DialogShell
      title="Image size"
      onClose={onClose}
      apply={{ label: "Resize", onClick: () => onApply(w, h) }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <NumField label="Width" value={w} onChange={setWidth} />
        <NumField label="Height" value={h} onChange={setHeight} />
        <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: "var(--fs-3)", color: "var(--text-2)", cursor: "pointer" }}>
          <input type="checkbox" checked={linked} onChange={(e) => setLinked(e.target.checked)} />
          Keep aspect ratio
        </label>
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          Resamples the pixels to the new size (bicubic-quality browser scaling).
        </div>
      </div>
    </DialogShell>
  );
}

function CanvasSizeDialog({ dims, onApply, onClose }: {
  dims: { w: number; h: number };
  onApply: (w: number, h: number, anchor: CanvasAnchor) => void;
  onClose: () => void;
}) {
  const [w, setW] = useState(dims.w);
  const [h, setH] = useState(dims.h);
  const [anchor, setAnchor] = useState<CanvasAnchor>([0.5, 0.5]);
  const cells: CanvasAnchor[] = ([0, 0.5, 1] as const).flatMap((ay) =>
    ([0, 0.5, 1] as const).map((ax) => [ax, ay] as CanvasAnchor));
  return (
    <DialogShell
      title="Canvas size"
      onClose={onClose}
      apply={{ label: "Resize canvas", onClick: () => onApply(w, h, anchor) }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <NumField label="Width" value={w} onChange={setW} />
        <NumField label="Height" value={h} onChange={setH} />
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ width: 52, fontSize: "var(--fs-3)", color: "var(--text-2)" }}>Anchor</span>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 26px)", gap: 3 }}>
            {cells.map(([ax, ay]) => {
              const active = anchor[0] === ax && anchor[1] === ay;
              return (
                <button
                  key={`${ax}-${ay}`}
                  onClick={() => setAnchor([ax, ay])}
                  title="Where the existing image sits in the new canvas"
                  style={{ width: 26, height: 26, borderRadius: "var(--r-1)", border: `1px solid ${active ? "var(--accent)" : "var(--border-strong)"}`, background: active ? "var(--accent)" : "var(--bg-deep)", cursor: "pointer" }}
                />
              );
            })}
          </div>
        </div>
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          Grows the canvas with transparent pixels, or trims it — the image is
          never scaled.
        </div>
      </div>
    </DialogShell>
  );
}
