// The Degradation section of the job editor's Dataset page.
//
// A run can carry a list of variants — one method, its parameter RANGES, some
// tags — and each one adds an EXTRA sample beside the clean picture rather than
// replacing it. What the section has to make legible is therefore not "what
// does this do to a picture" (the preview answers that) but "how much of the
// run is this", which is why the footer states the resulting mix in visits.
import { useEffect, useRef, useState } from "react";
import { storage } from "../shared/storage";
import { Select } from "../shared/Select";
import { useMenuDismiss } from "../shared/useMenuDismiss";
import { AnchoredDropdown, useAnchorRect } from "../shared/AnchoredDropdown";
import { useInlineEdit } from "../shared/useInlineEdit";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";

import { api, type TrainDegradeVariant, type TrainingConfig } from "./api";
import { useT } from "./i18n";
import { Icon } from "../shared/Icon";
import {
  NumRow, RangeRow, Section, SelectRow, TextRow, inputStyle,
} from "./FormRows";
import { defaultDegradeVariant, degradeFileCount, degradeMix } from "./util";
import { LAYER } from "../shared/layers";
import { Lightbox } from "./Lightbox";
// The ⓘ texts are compiled from `docs/training/fields/*.md` — the docs
// are the source, `scripts/gen_field_help.py` is the compiler.
import { HELP } from "./fieldHelp";

const SETS_KEY = "mc.trainDegradeSets";

type DegradeSet = { id: string; name: string; variants: TrainDegradeVariant[] };

function loadSets(): DegradeSet[] {
  try {
    const v = JSON.parse(storage.get(SETS_KEY) || "[]");
    if (!Array.isArray(v)) return [];
    return v.filter((s) => s && typeof s.name === "string"
                      && Array.isArray(s.variants));
  } catch { return []; }
}

function storeSets(sets: DegradeSet[]) {
  try { storage.set(SETS_KEY, JSON.stringify(sets)); } catch { /* ignore */ }
}

const btn: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 5, height: 26,
  padding: "0 10px", borderRadius: "var(--r-3)", border: "1px solid var(--border-strong)",
  background: "transparent", color: "var(--text-2)", fontSize: "var(--fs-2)",
  fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
};

const splitTags = (v: string) =>
  v.split(",").map((s) => s.trim()).filter(Boolean);

/** A named part of a variant card that opens on demand, CLOSED to start with.
 *
 *  A variant is a method and its ranges — that is what the card is read for —
 *  and everything else on it is a refinement most of them never carry: which
 *  tags the copy gains and loses, which pictures it applies to, what it looks
 *  like. Spelled out, three variants filled a page with fields that were
 *  mostly empty, and the ranges that decide the whole thing were the part you
 *  scrolled past. The heading is the row's uppercase sub-heading, made into
 *  the control that opens it — a separate triangle beside a label is two
 *  targets for one job. */
function Fold({ title, children }: {
  title: string;
  children: React.ReactNode;
}) {
  // No "start open" case: every one of these is closed, so a card is the same
  // height however it was reached. The one that had it (Tags, on an untagged
  // variant) opened on every variant ever added, since a fresh one has no
  // tags — a default dressed up as a condition.
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          display: "flex", alignItems: "center", gap: 3, width: "100%",
          margin: "10px 0 4px", padding: "2px 2px", border: "none",
          background: "transparent", cursor: "pointer",
          fontSize: "var(--fs-1)", fontWeight: 600, letterSpacing: "0.06em",
          textTransform: "uppercase", color: "var(--muted-2)",
          fontFamily: "inherit", textAlign: "left",
        }}
      >
        <Icon name={open ? "expand_more" : "chevron_right"} size={14} />
        {title}
      </button>
      {open && children}
    </>
  );
}

/** THE PICTURE ITSELF AND THE TWO ENDS OF THE VARIANT'S RANGES, side by side.
 *
 *  The two ends are deliberately not a random draw from the middle: what has to
 *  be judged before committing a run is the gentlest and the harshest thing it
 *  can produce, and a sample from between answers neither question — nor the
 *  same way twice. The ORIGINAL is beside them because "is this too much" is a
 *  comparison, and holding the untouched picture in your head while looking at
 *  a JPEG of it is exactly what nobody can do. It comes from the same endpoint,
 *  so it took the same downscale and the same PNG write: what differs between
 *  the three is the degradation and nothing else. */
const ENDS = ["clean", "low", "high"] as const;
const END_LABEL: Record<typeof ENDS[number], (t: (s: string) => string) => string> = {
  clean: (t) => t("original"),
  low: (t) => t("gentlest"),
  high: (t) => t("harshest"),
};

/** What a preview is captioned with: which end it is, and — for the two that
 *  were actually degraded — the values the variant DREW for it. The clean one
 *  has nothing drawn, so it would read "original · original". */
const captionOf = (end: typeof ENDS[number], key: string,
                   t: (s: string) => string) =>
  (end === "clean" ? END_LABEL[end](t) : `${END_LABEL[end](t)} · ${key}`);

function VariantPreview({ variant, itemId, onAnother }: {
  variant: TrainDegradeVariant; itemId: number | null;
  /** Draw a different picture from the dataset to render on. */
  onAnother: () => void;
}) {
  const t = useT();
  const [shots, setShots] = useState<Record<string, { url: string; key: string }>>({});
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  /** Which of the three pictures is open full size, if any. */
  const [big, setBig] = useState<number | null>(null);
  // Object URLs are revoked when they are replaced and when the row unmounts —
  // a preview per keystroke would otherwise leak a blob per keystroke.
  const live = useRef<string[]>([]);
  useEffect(() => () => { live.current.forEach(URL.revokeObjectURL); }, []);
  // Renders can overlap — a range dragged while one is still encoding — so the
  // LATEST request wins rather than whichever finishes last. Without this a
  // slow first render lands after a fast second one and puts the settings you
  // have moved on from back on the screen.
  const seq = useRef(0);

  const render = async () => {
    if (itemId == null) return;
    const mine = ++seq.current;
    setBusy(true);
    setErr("");
    try {
      const next: Record<string, { url: string; key: string }> = {};
      for (const end of ENDS) {
        next[end] = await api.trainDegradePreview(itemId, variant, end, 420);
        live.current.push(next[end].url);
      }
      if (seq.current !== mine) return;
      setShots((old) => {
        Object.values(old).forEach((s) => URL.revokeObjectURL(s.url));
        return next;
      });
    } catch (e) {
      if (seq.current === mine) setErr((e as Error).message || t("The preview failed"));
    } finally {
      if (seq.current === mine) setBusy(false);
    }
  };

  // THE PREVIEW IS THE SECTION, so opening it renders — there is no button.
  // One existed and it made the fold a place you went to press something,
  // which for a picture of the settings right in front of you is a step with
  // no decision in it; worse, once pressed the picture stayed as it was while
  // the ranges above it moved, so the answer on screen was silently about
  // settings you had already left behind.
  //
  // DEBOUNCED, because the settings are dragged and typed: what is wanted is
  // the value you stopped on, and every value passed through on the way is
  // two encodes of a full-size picture on the server.
  const settings = JSON.stringify([
    variant.method, variant.quality, variant.subsampling, variant.codec,
    variant.crf, variant.scale, variant.resample, variant.passes,
  ]);
  useEffect(() => {
    if (itemId == null) return;
    const id = setTimeout(() => { void render(); }, 350);
    return () => clearTimeout(id);
    // `render` closes over this render's variant and itemId, which is exactly
    // what should be drawn; listing it would re-arm the timer every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings, itemId]);

  if (itemId == null) {
    return (
      <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", padding: "2px 0 8px" }}>
        {t("Select an item in the library to preview this on.")}
      </div>
    );
  }
  const shown = ENDS.filter((e) => shots[e]);
  return (
    <div style={{ padding: "2px 0 8px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    flexWrap: "wrap" }}>
        {/* The picture is whichever one the dataset's query happens to answer
            with, and one picture answers "what does this do" for one KIND of
            picture: a photograph and a line drawing come out of a JPEG at
            quality 20 looking nothing alike. */}
        <button style={{ ...btn, height: 24 }} onClick={onAnother}>
          <Icon name="casino" size={14} />
          {t("Another picture")}
        </button>
        {busy && (
          <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
            {t("Rendering…")}
          </span>
        )}
      </div>
      {err && (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--red)", marginTop: 6 }}>{err}</div>
      )}
      {shown.length > 0 && (
        // The old pictures stay while the next set renders — a strip that
        // emptied itself on every change of a range would flash more than it
        // showed, and what is on screen is still an answer, just a stale one.
        // ONE ROW, whatever the width: these three are read by comparing them,
        // and a picture that has wrapped to the next line is being compared
        // across a caption and a gap. So they share the width equally
        // (`flex: 1 1 0` on a `minWidth: 0` column) and get smaller together
        // rather than one of them going somewhere else — full size is a click
        // away for when small is not enough.
        <div style={{ display: "flex", gap: 10, marginTop: 8,
                      flexWrap: "nowrap", alignItems: "flex-start",
                      opacity: busy ? 0.55 : 1 }}>
          {shown.map((end, i) => (
            <figure key={end}
                    style={{ margin: 0, flex: "1 1 0", minWidth: 0 }}>
              <button
                onClick={() => setBig(i)}
                title={t("Show this at full size")}
                style={{ display: "block", padding: 0, border: "none",
                         background: "transparent", cursor: "zoom-in",
                         width: "100%" }}
              >
                <img src={shots[end].url} alt=""
                     style={{ width: "100%", borderRadius: "var(--r-2)", display: "block",
                              border: "1px solid var(--border)" }} />
              </button>
              {/* The caption is the one thing here that cannot shrink with
                  its column, so it ellipsises rather than widening the
                  column it sits under — which would break the row into
                  unequal thirds over a string nobody reads twice. */}
              <figcaption
                title={captionOf(end, shots[end].key, t)}
                style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)",
                         marginTop: 3, fontFamily: "var(--mono)",
                         whiteSpace: "nowrap", overflow: "hidden",
                         textOverflow: "ellipsis" }}>
                {captionOf(end, shots[end].key, t)}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      {/* Portalled and layered like every other popover in this package: the
          lightbox is `position: fixed` with a z-index of its own, which
          inside the job editor's dialog would put it behind the dialog. */}
      {big != null && shown.length > 0 && createPortal(
        <div style={{ position: "fixed", inset: 0, zIndex: LAYER.popover }}>
          <Lightbox
            images={shown.map((end) => ({
              url: shots[end].url,
              label: END_LABEL[end](t),
              sublabel: end === "clean" ? "" : shots[end].key,
            }))}
            index={Math.min(big, shown.length - 1)}
            onIndex={setBig}
            onClose={() => setBig(null)}
          />
        </div>, document.body)}
    </div>
  );
}

function VariantRow({ variant, previewItem, onAnotherItem, onChange, onRemove }: {
  variant: TrainDegradeVariant;
  previewItem: number | null;
  onAnotherItem: () => void;
  onChange: (patch: Partial<TrainDegradeVariant>) => void;
  onRemove: () => void;
}) {
  const t = useT();
  const untagged = variant.tags.length === 0;
  return (
    <div style={{
      border: "1px solid var(--border)", borderRadius: "var(--r-6)", padding: "10px 12px",
      marginBottom: 10, background: "var(--panel)",
    }}>
      {/* A NAME and an ORDER were both things to fill in that changed nothing.
          The name was optional and only ever labelled a log line, which falls
          back to the method (`dataset.py`: `variant.name.strip() or
          variant.method`) — so the field asked for a word to be told back to
          you. The order was worse: variants are independent extra samples, all
          of them applied to every matching picture, so "up" and "down" moved a
          card and nothing else. The method row below identifies the card. */}
      {/* THE METHOD IS THE CARD'S TITLE, so it sits in the header rather than
          in a row of its own — it is what the card IS, and as a labelled row
          under an empty header bar it was a line of chrome above it saying
          nothing. Its hint went with the move: the three options name
          themselves, and a sentence explaining that JPEG re-encodes is the
          kind of help text that is only ever read once. */}
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    marginBottom: 4 }}>
        <Select
          value={variant.method}
          ariaLabel={t("Method")}
          onChange={(v) => onChange({ method: v as TrainDegradeVariant["method"] })}
          height={28} minWidth={0} wrapStyle={{ flex: "0 1 auto" }}
          style={{ padding: "0 30px 0 10px", fontWeight: 600 }}
          options={[["jpeg", t("JPEG re-encode")],
                    ["video", t("Video codec (h264 / h265)")],
                    ["resize", t("Resolution loss")]]} />
        <div style={{ flex: 1 }} />
        <button style={{ ...btn, height: 28, padding: "0 8px", color: "var(--red)" }}
                title={t("Remove this variant")} onClick={onRemove}>
          <Icon name="close" size={14} />
        </button>
      </div>

      {variant.method === "jpeg" && (<>
        <RangeRow label={t("Quality")} lo={variant.quality.lo} hi={variant.quality.hi}
          min={1} max={100}
          hint={t("Drawn per picture from this range. Lower is worse — below about 30 the blocking is unmistakable.")}
          onChange={(lo, hi) => onChange({ quality: { lo, hi } })} />
        <SelectRow label={t("Chroma subsampling")} value={variant.subsampling}
          hint={t("How much color detail is thrown away. 4:2:0 is what almost every real JPEG uses.")}
          options={[["4:4:4", "4:4:4"], ["4:2:2", "4:2:2"], ["4:2:0", "4:2:0"]] as const}
          onChange={(v) => onChange({ subsampling: v as TrainDegradeVariant["subsampling"] })} />
      </>)}

      {variant.method === "video" && (<>
        <SelectRow label={t("Codec")} value={variant.codec}
          options={[["h264", "h264"], ["h265", "h265"]] as const}
          onChange={(v) => onChange({ codec: v as TrainDegradeVariant["codec"] })} />
        <RangeRow label={t("CRF")} lo={variant.crf.lo} hi={variant.crf.hi}
          min={0} max={63}
          hint={t("The codec's quality number, counting the other way round: HIGHER is worse. Above about 32 a frame visibly falls apart.")}
          onChange={(lo, hi) => onChange({ crf: { lo, hi } })} />
      </>)}

      {variant.method === "resize" && (<>
        <RangeRow label={t("Scale")} lo={variant.scale.lo} hi={variant.scale.hi}
          min={0.05} max={1} step={0.05} decimals={2}
          hint={t("Scaled down by this much and back up to the original size. The picture keeps its dimensions — what it loses is detail.")}
          onChange={(lo, hi) => onChange({ scale: { lo, hi } })} />
        <SelectRow label={t("Filter")} value={variant.resample}
          hint={t("Nearest gives the hard, blocky look of a badly upscaled screenshot; bilinear the soft one.")}
          options={[["nearest", t("Nearest")], ["bilinear", t("Bilinear")],
                    ["bicubic", t("Bicubic")], ["lanczos", t("Lanczos")]] as const}
          onChange={(v) => onChange({ resample: v as TrainDegradeVariant["resample"] })} />
      </>)}

      <RangeRow label={t("Passes")} lo={variant.passes.lo} hi={variant.passes.hi}
        min={1} max={10}
        hint={t("Re-apply the whole thing this many times — a re-save of a re-save, which is what a picture reposted a dozen times looks like.")}
        onChange={(lo, hi) => onChange({ passes: { lo, hi } })} />

      <NumRow label={t("Visits per clean visit")} value={variant.weight}
        min={0} max={4} step={0.05}
        hint={t("How often this variant is drawn beside the picture it was made from. 0.25 = one degraded visit per four clean ones.")}
        details={t(HELP["degraded-copies.visits-per-clean-visit"])}
        onChange={(v) => onChange({ weight: v })} />
      <NumRow label={t("Cached variations per picture")} value={variant.variations}
        min={1} max={8} step={1}
        hint={t("How many separately-drawn values each picture gets. 1 already spreads the range across the dataset; more spreads it within one picture, and multiplies the cache.")}
        details={t(HELP["degraded-copies.cached-variations-per-picture"])}
        onChange={(v) => onChange({ variations: v })} />

      {/* The two tag lists are one decision — what this sample SAYS about
          itself — so they are one fold, closed like the others. It opened by
          itself on an untagged variant for a round, on the argument that a
          variant with no tags is skipped and this is where you fix that; but
          a fresh variant is ALWAYS untagged, so what that actually did was
          open the section every time one was added, which is the state the
          folds exist to avoid. The hint inside still says the variant is
          skipped without a tag. */}
      <Fold title={t("Tags")}>
      <TextRow label={t("Add tags")} wide
        value={variant.tags.join(", ")}
        placeholder={t("jpeg_artifacts, low_quality")}
        hint={untagged
          ? t("Required. Without a tag the degraded copy is an unmarked bad picture in the dataset — so an untagged variant is simply skipped.")
          : t("Always in this sample's prompt: never dropped by the random tag pick, the tag cap, or caption dropout.")}
        details={t(HELP["degraded-copies.add-tags"])}
        onChange={(v) => onChange({ tags: splitTags(v) })} />
      <TextRow label={t("Remove tags if present")} wide
        value={variant.remove_tags.join(", ")}
        placeholder={t("masterpiece, absurdres")}
        hint={t("Quality claims the degraded copy no longer supports. Only on this sample — the clean one keeps them.")}
        details={t(HELP["degraded-copies.remove-tags-if-present"])}
        onChange={(v) => onChange({ remove_tags: splitTags(v) })} />
      {/* The same three rules by what the LIBRARY says about a tag, so the
          claim ("this is a resolution claim") is made once in the Tags tab
          rather than listed per variant. */}
      <TextRow label={t("Remove tags marked")} wide
        value={variant.remove_tag_meta_tags.join(", ")}
        hint={t("Comma-separated META tags. Any tag the library marks with one of these comes off this sample.")}
        details={t(HELP["degraded-copies.remove-tags-marked"])}
        onChange={(v) => onChange({ remove_tag_meta_tags: splitTags(v) })} />
      </Fold>

      <Fold title={t("Which pictures")}>
      <TextRow label={t("Only pictures tagged")} wide
        value={variant.require_tags.join(", ")}
        hint={t("Left empty, every picture. Otherwise a picture must carry at least one of these — e.g. only degrade what is marked high quality.")}
        onChange={(v) => onChange({ require_tags: splitTags(v) })} />
      <TextRow label={t("Only pictures whose tags are marked")} wide
        value={variant.require_tag_meta_tags.join(", ")}
        hint={t("Comma-separated META tags — the same rule as the line above, said once in the library rather than tag by tag here.")}
        details={t(HELP["degraded-copies.only-pictures-whose-tags-are-marked"])}
        onChange={(v) => onChange({ require_tag_meta_tags: splitTags(v) })} />
      <TextRow label={t("Never pictures tagged")} wide
        value={variant.skip_tags.join(", ")}
        hint={t("Wins over the line above. Use it to leave pictures alone that are already marked as poor.")}
        details={t(HELP["degraded-copies.never-pictures-tagged"])}
        onChange={(v) => onChange({ skip_tags: splitTags(v) })} />
      <TextRow label={t("Never pictures whose tags are marked")} wide last
        value={variant.skip_tag_meta_tags.join(", ")}
        hint={t("Comma-separated META tags. Wins over both lines above.")}
        details={t(HELP["degraded-copies.never-pictures-whose-tags-are-marked"])}
        onChange={(v) => onChange({ skip_tag_meta_tags: splitTags(v) })} />
      </Fold>

      <Fold title={t("Preview")}>
        <VariantPreview variant={variant} itemId={previewItem}
                        onAnother={onAnotherItem} />
      </Fold>
    </div>
  );
}

/** Save / load named variant lists — the same menu shape as the test-prompt
 *  sets, because it is the same kind of thing one page away. */
function DegradeSetsRow({ variants, onLoad }: {
  variants: TrainDegradeVariant[];
  onLoad: (v: TrainDegradeVariant[]) => void;
}) {
  const t = useT();
  const [sets, setSets] = useState<DegradeSet[]>(loadSets);
  const [menu, setMenu] = useState(false);
  const menuAnchor = useRef<HTMLButtonElement>(null);
  const menuRect = useAnchorRect(menuAnchor, menu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(menu, () => setMenu(false), { within: [menuAnchor] });
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const renameRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (renameId) renameRef.current?.select(); }, [renameId]);

  const commit = (next: DegradeSet[]) => { setSets(next); storeSets(next); };
  const commitRename = () => {
    if (!renameId) return;
    const v = renameVal.trim();
    if (v) commit(sets.map((s) => (s.id === renameId ? { ...s, name: v } : s)));
    setRenameId(null);
  };
  const renameKeys = useInlineEdit({ commit: commitRename,
                                     cancel: () => setRenameId(null) });
  const saveSet = () => {
    const taken = new Set(sets.map((s) => s.name));
    let n = sets.length + 1;
    while (taken.has(`${t("Set")} ${n}`)) n++;
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const name = `${t("Set")} ${n}`;
    commit([{ id, name, variants: variants.map((v) => ({ ...v })) }, ...sets]);
    setRenameId(id);
    setRenameVal(name);
  };
  const hasContent = variants.length > 0;

  return (
    <div>
      <button ref={menuAnchor} style={btn} onClick={() => setMenu((v) => !v)} title={t("Save the current variants, or load a saved set")}>
        <Icon name="bookmarks" size={15} />{t("Variants")}
        <Icon name="expand_more" size={13} style={{ opacity: 0.7 }} />
      </button>
      {menu && (
          <AnchoredDropdown rect={menuRect} minWidth={250} focusable>
            <div className={hasContent ? "hoverable" : undefined}
              title={hasContent
                ? t("Remember the current variants — name the set in this list afterwards")
                : t("Add a variant first")}
              onClick={() => { if (hasContent) saveSet(); }}
              style={{
                display: "flex", alignItems: "center", gap: 8, padding: "6px 9px",
                borderRadius: "var(--r-3)", fontSize: "var(--fs-3)", color: "var(--text-2)",
                opacity: hasContent ? 1 : 0.45,
                cursor: hasContent ? "pointer" : "default",
              }}>
              <Icon name="bookmark_add" size={14} color="var(--muted)" />
              <span style={{ flex: 1 }}>{t("Save current variants")}</span>
            </div>
            {sets.length > 0 && (
              <div style={{ height: 1, background: "var(--menu-border)", margin: "4px 2px" }} />
            )}
            {sets.map((s) => (
              <div key={s.id} style={{
                display: "flex", alignItems: "center", gap: 2, minHeight: 34,
                borderRadius: "var(--r-3)",
              }}>
                {renameId === s.id ? (
                  <input ref={renameRef} value={renameVal}
                    onChange={(e) => setRenameVal(e.target.value)}
                    onBlur={renameKeys.onBlur}
                    onKeyDown={renameKeys.onKeyDown}
                    style={{ ...inputStyle, height: 26, flex: 1, margin: "0 4px" }} />
                ) : (<>
                  <div className="hoverable" style={{
                    flex: 1, padding: "6px 9px", borderRadius: "var(--r-3)", fontSize: "var(--fs-3)",
                    cursor: "pointer", color: "var(--text-2)",
                  }}
                    title={t("Load this set, replacing the variants in this job")}
                    onClick={() => { onLoad(s.variants.map((v) => ({ ...v }))); setMenu(false); }}>
                    {s.name}
                    <span style={{ color: "var(--muted-2)", marginLeft: 6 }}>
                      {s.variants.length}
                    </span>
                  </div>
                  <button style={{ ...btn, border: "none", height: 24, padding: "0 6px" }}
                    title={t("Rename")}
                    onClick={() => { setRenameId(s.id); setRenameVal(s.name); }}>
                    <Icon name="edit" size={13} />
                  </button>
                  <button style={{ ...btn, border: "none", height: 24, padding: "0 6px",
                                   color: "var(--red)" }}
                    title={t("Delete this set")}
                    onClick={() => commit(sets.filter((x) => x.id !== s.id))}>
                    <Icon name="close" size={13} />
                  </button>
                </>)}
              </div>
            ))}
          </AnchoredDropdown>
        
)}
    </div>
  );
}

export function DegradeSection({ config, onChange }: {
  config: TrainingConfig;
  onChange: (d: TrainingConfig["degrade"]) => void;
}) {
  const t = useT();
  const variants = config.degrade?.variants ?? [];
  const set = (next: TrainDegradeVariant[]) => onChange({ variants: next });
  // A variant's own name if it has one, else the method's — translated here,
  // because `degradeMix` is pure and must stay loadable under `node --test`.
  const METHOD_LABEL: Record<string, string> = {
    jpeg: t("JPEG"), video: t("video codec"), resize: t("resolution loss"),
  };
  const mix = degradeMix(config);
  mix.parts.forEach((p) => { p.label = METHOD_LABEL[p.label] ?? p.label; });

  // One real picture out of the job's OWN dataset to preview on, and the
  // dataset's size for the cache estimate — both from the first query, so what
  // is judged is a picture the run will actually degrade rather than whatever
  // happened to be selected in the library. Only asked for once a variant
  // exists: an empty section has nothing to preview.
  //
  // WHICH picture is a page NUMBER at page size 1, so drawing another one is
  // one more query of the same shape rather than a list of the dataset held in
  // the browser — the dataset is the whole library often enough that a picture
  // has to be reachable without paging to it. Page 1 to start with: the
  // question "what does this do" wants an answer before it wants variety.
  const [pick, setPick] = useState(1);
  const queryKey = JSON.stringify(config.queries?.[0]?.tree ?? null);
  const { data: sample } = useQuery({
    queryKey: ["degrade-sample", queryKey, pick],
    enabled: variants.length > 0,
    queryFn: () => api.itemsQuery({
      query: config.queries?.[0]?.tree ?? null,
      kind: "image", page: pick, page_size: 1,
    }),
    // A different page of the same dataset is the same KIND of answer, so the
    // old picture stays on screen while the new one is fetched rather than the
    // preview blanking between draws.
    placeholderData: (prev) => prev,
  });
  const previewItem = sample?.items?.[0]?.id ?? null;
  const files = degradeFileCount(config, sample?.total ?? 0);
  // The count comes back with the picture, so the first draw is uniform over
  // whatever the dataset turned out to hold; with nothing fetched yet there is
  // nothing to draw from and the button simply stays where it is.
  const another = () => {
    const total = sample?.total ?? 0;
    if (total < 2) return;
    let next = pick;
    while (next === pick) next = 1 + Math.floor(Math.random() * total);
    setPick(next);
  };
  // A query edited under a pick past the end of the new dataset would answer
  // with no items at all, which reads as "there is nothing to preview on".
  useEffect(() => { setPick(1); }, [queryKey]);

  return (
    <Section label={t("Degradation")}
      hint={t("Teach the model what bad looks like. Each variant adds an extra sample beside the clean picture — the same image, spoiled, carrying tags that say so. The clean picture is never replaced.")}>
      <div style={{ padding: "10px 12px" }}>
        {variants.length === 0 && (
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginBottom: 10 }}>
            {t("No variants — the dataset trains on the pictures as they are.")}
          </div>
        )}
        {variants.map((v, i) => (
          <VariantRow key={i} variant={v}
            previewItem={previewItem} onAnotherItem={another}
            onChange={(patch) => set(variants.map(
              (x, j) => (j === i ? { ...x, ...patch } : x)))}
            onRemove={() => set(variants.filter((_, j) => j !== i))} />
        ))}
        <div style={{ display: "flex", alignItems: "center", gap: 8,
                      flexWrap: "wrap" }}>
          <button style={btn}
                  onClick={() => set([...variants, defaultDegradeVariant()])}>
            <Icon name="add" size={15} />{t("Add variant")}
          </button>
          {variants.length > 0 && (
            <button style={btn} onClick={() => set([])}
                    title={t("Remove every variant from this job")}>
              <Icon name="delete_sweep" size={15} />{t("Remove all")}
            </button>
          )}
          <div style={{ flex: 1 }} />
          <DegradeSetsRow variants={variants} onLoad={set} />
        </div>

        {/* Per ELIGIBLE picture, never over the dataset: a variant with a tag
            gate applies to a subset nobody can count without running the
            query, so a whole-dataset figure would simply be wrong. */}
        {mix.parts.length > 0 && (
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 10,
                        lineHeight: 1.6 }}>
            {/* One whole sentence with the numbers filled in, not a frame with
                fragments slotted into it: the words around a value move
                between languages, and a phrase keyed on its own cannot be
                translated into a sentence that reads. */}
            <div>{t(
              "Of every 100 visits to a picture this applies to, {clean} are clean and the rest are degraded: {parts}.",
              { clean: mix.clean, parts: mix.parts.map(
                  (p) => `${p.visits} × ${p.label}`).join(", ") })}
            </div>
            {mix.parts.some((p) => p.gated) && (
              <div>{t("A variant with a tag filter applies to fewer pictures than the queries select, so its share is of those.")}</div>
            )}
            {files > 0 && (
              <div>{t("About {n} degraded files will be cached.", { n: files })}</div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}
