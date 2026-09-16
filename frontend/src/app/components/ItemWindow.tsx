/**
 * THE ITEM WINDOW — one window per set of items, holding both halves of what
 * you can do to one: **annotate** it (tags, boxes, people, captions) or
 * **edit** it (its pixels, or its cuts).
 *
 * They were two windows with a button in each pointing at the other, which
 * meant opening the same picture from the library twice — once by Annotate,
 * once by Edit — left two windows over it, each with its own tab strip and its
 * own idea of which items were open. The mode is a state you are in, so it is
 * a segmented control, and it is per TAB: a window can hold a page you are
 * labelling and a photograph you are retouching.
 *
 * **It is an OVERLAY over the library, not a browser window.** It was one, and
 * being a second document is what everything awkward about it came from: a
 * query cache of its own (so every write had to be broadcast back over a
 * `BroadcastChannel`, and the list of keys to invalidate drifted — naming a
 * face here once left the library's sidebar stale), a store of its own (so the
 * grid order and the tag to focus were handed over through `localStorage`,
 * the only channel a different document had), and a walk up the `opener` chain
 * to find the library again, with a Safari quirk of its own. None of that has
 * anything left to do.
 *
 * What it cost: a second monitor. That is the real thing a window is for, and
 * it is gone.
 *
 * The address is `?item=<ids>&mode=<mode>` on whatever view is behind it —
 * a parameter, like the settings overlay, because that is what an overlay is
 * (`location.ts`). Every address it had as a window still opens it.
 */
import React from "react";
import { Button } from "../../shared/Button";
import { useQuery } from "@tanstack/react-query";
import { AnnotationOverlay } from "./AnnotationOverlay";
import { EditorOverlay } from "./EditorOverlay";
import { VideoEditorOverlay } from "./VideoEditorOverlay";
import { api } from "../api";
import { ItemMode, useUI } from "../store";
import { useT } from "../i18n";
import { LAYER } from "../../shared/layers";

export function ItemWindow() {
  const t = useT();
  const editorItemId = useUI((s) => s.editorItemId);
  const tabs = useUI((s) => s.editorTabs);
  const modes = useUI((s) => s.editorModes);
  const fallback = useUI((s) => s.editorMode);
  const shown = editorItemId ?? tabs[0] ?? null;
  const active: ItemMode = (shown != null ? modes[shown] : undefined) ?? fallback;
  // `App` renders this only with tabs open, so `shown` is never null in
  // practice; the guard is what makes that readable rather than assumed.
  if (shown == null) return null;
  return <ItemWindowBody shown={shown} mode={active} t={t} />;
}

/** Split out so the hooks below sit under an unconditional `shown`. */
function ItemWindowBody({ shown, mode: active, t }:
    { shown: number; mode: ItemMode; t: (s: string) => string }) {

  // Which editor the edit half is follows the ITEM: a film gets the video
  // editor. A pending crop tab (a negative id) has no item yet and is always
  // the image editor's.
  const { data: detail, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["item", shown],
    queryFn: () => api.item(shown),
    enabled: shown >= 0,
    // Hold the previous item while the next loads, so a tab switch never
    // empties the window (the rule both overlays already follow).
    placeholderData: (prev) => prev,
  });

  // A WINDOW MUST NEVER SIT BLANK. Both of the gates below used to be
  // `return null`, and a `null` here is a white browser window with no chrome,
  // no message and no way out — the least debuggable failure there is, and
  // the one somebody hit: the editor opened blank, and opening other items
  // later worked, which is the signature of a detail request that failed
  // (a five-second `/api/items/{id}` against a database another job was
  // holding is enough) and then had its three retries run out. Nothing
  // re-triggers it, so the window stays empty for as long as it is open.
  //
  // So the load says it is loading and the failure says what failed, with the
  // way to ask again. Whatever the transient was, the window now reports it
  // rather than looking broken.
  if (isError) {
    return (
      <WindowNotice
        title={t("This item could not be loaded")}
        detail={error instanceof Error ? error.message : String(error)}
        retryLabel={isFetching ? t("Trying…") : t("Try again")}
        onRetry={() => void refetch()}
        retrying={isFetching}
      />
    );
  }
  if (shown >= 0 && !detail) {
    return <WindowNotice title={t("Loading…")} />;
  }
  return (
    // Over EVERYTHING the library has, Quick Look included — this is a
    // window, in the sense that matters: nothing behind it is being worked on.
    // Under every dialog, and the update banner, which is about the server
    // and outranks whatever you are doing (`shared/layers.ts`).
    <div style={{ position: "fixed", inset: 0, zIndex: LAYER.itemWindow }}>
      {active === "annotate" ? (
        <AnnotationOverlay />
      ) : detail?.kind === "video" ? (
        <VideoEditorOverlay itemId={shown} />
      ) : (
        <EditorOverlay />
      )}
    </div>
  );
}

/** What the window shows instead of an item: a sentence, and a way on. */
function WindowNotice({ title, detail, onRetry, retrying, retryLabel }: {
  title: string; detail?: string; onRetry?: () => void; retrying?: boolean;
  retryLabel?: string;
}) {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: LAYER.itemWindow, background: "var(--bg)",
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", gap: 10, padding: 24, textAlign: "center" }}>
      <div style={{ fontSize: "var(--fs-4)", fontWeight: 600, color: "var(--text-2)" }}>
        {title}
      </div>
      {detail && (
        <div style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", maxWidth: 520,
          color: "var(--muted-2)", wordBreak: "break-word" }}>
          {detail}
        </div>
      )}
      {onRetry && (
        <Button variant="primary" size="sm"
     onClick={onRetry}
     disabled={retrying}>
          {retryLabel}
        </Button>
      )}
    </div>
  );
}
