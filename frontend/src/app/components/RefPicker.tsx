import React, { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { setRefPickerOpen } from "../dragState";
import { useT } from "../i18n";
import { Icon } from "../../shared/Icon";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";

/**
 * Modal picker for the color-reference image a reference-guided model needs
 * (example-based manga colorization). Shows the small rolling store of recent
 * references — uploads and "use as reference" snapshots of items — as
 * selectable thumbnails (each with a hover ✕ to remove it), plus an upload
 * tile. An image can also be dragged onto the overlay to add it (the global
 * import overlay stays out of the way while the picker is open). Confirm
 * hands the chosen ref id back to the action that opened the picker.
 */
export function RefPickerOverlay({
  onConfirm,
  onClose,
}: {
  onConfirm: (refId: string) => void;
  onClose: () => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["ml-refs"], queryFn: api.mlRefs });
  const refs = data?.refs ?? [];
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // While the picker is open, the window-level file-drag handler must not pop
  // the import overlay — drops belong to the picker.
  useEffect(() => {
    setRefPickerOpen(true);
    return () => setRefPickerOpen(false);
  }, []);

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const res = await api.mlRefUpload(file);
      qc.invalidateQueries({ queryKey: ["ml-refs"] });
      setSelected(res.id);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    await api.mlRefDelete(id);
    if (selected === id) setSelected(null);
    qc.invalidateQueries({ queryKey: ["ml-refs"] });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const file = Array.from(e.dataTransfer?.files ?? []).find((f) =>
      f.type.startsWith("image/")
    );
    if (file && !busy) void upload(file);
  };

  return (
    <Overlay
      icon="palette"
      title={t("Pick a color reference")}
      subtitle={t("The colors of this image are transferred onto the page.")}
      width={520}
      onClose={onClose}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={(e) => {
        // Only count leaving the overlay entirely, not moving between children.
        const rt = e.relatedTarget as Node | null;
        if (rt != null && (e.currentTarget as Node).contains(rt)) return;
        setDragOver(false);
      }}
      onDrop={onDrop}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary"
            icon="palette"
            disabled={!selected || busy}
            onClick={() => selected && onConfirm(selected)}
          >
            {t("Colorize")}
          </Button>
        </>
      }
    >
      <div style={{ padding: "16px 20px", overflowY: "auto", position: "relative" }}>
        {refs.length === 0 && (
          <div style={{ fontSize: "var(--fs-3)", color: "var(--muted)", marginBottom: 12 }}>
            {t("No recent reference images — upload or drop one, or use “Add as color reference” on a colored item.")}
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(104px, 1fr))", gap: 10 }}>
          {refs.map((r) => {
            const sel = r.id === selected;
            return (
              <div
                key={r.id}
                className="mc-ref-tile"
                onClick={() => setSelected(sel ? null : r.id)}
                title={t("Use this image as the color reference")}
                style={{
                  position: "relative", aspectRatio: "1", borderRadius: "var(--r-6)", overflow: "hidden",
                  border: sel ? "2px solid var(--accent)" : "1px solid var(--border-strong)",
                  cursor: "pointer", background: "var(--bg-deep)",
                }}
              >
                <img
                  src={`/api/ml/refs/${r.id}`}
                  alt=""
                  style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                />
                {sel && (
                  <span style={{ position: "absolute", bottom: 6, right: 6, width: 22, height: 22, borderRadius: "50%", background: "var(--accent)", color: "var(--on-accent)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <Icon name="check" size={15} />
                  </span>
                )}
                {/* Remove-from-store button (hover). */}
                <span
                  onClick={(e) => { e.stopPropagation(); void remove(r.id); }}
                  title={t("Remove this reference image")}
                  className="mc-ref-del"
                  style={{
                    position: "absolute", top: 5, right: 5, width: 22, height: 22,
                    borderRadius: "50%", background: "var(--scrim-3)", color: "var(--on-scrim)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}
                >
                  <Icon name="close" size={14} />
                </span>
              </div>
            );
          })}
          {/* Upload tile — adds a temporary image to the rolling store. */}
          <div
            onClick={() => !busy && fileInput.current?.click()}
            title={t("Upload a temporary reference image")}
            style={{
              aspectRatio: "1", borderRadius: "var(--r-6)", border: "1.5px dashed var(--border-strong)",
              display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
              gap: 5, color: "var(--muted)", cursor: "pointer", fontSize: "var(--fs-2)", fontWeight: 600,
            }}
          >
            <Icon name={busy ? "progress_activity" : "upload"} size={20}
                  spin={busy} />
            {t("Upload image")}
          </div>
        </div>
        <div style={{ marginTop: 12, fontSize: "var(--fs-2)", color: "var(--muted-2)", display: "flex", alignItems: "center", gap: 5 }}>
          <Icon name="place_item" size={14} />
          {t("Drop an image anywhere on this window to add it.")}
        </div>
        {dragOver && (
          <div
            style={{
              position: "absolute", inset: 6, borderRadius: "var(--r-7)", pointerEvents: "none",
              border: "2px dashed var(--accent)", background: "var(--accent-dim)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--accent)", fontSize: "var(--fs-4)", fontWeight: 700, gap: 7,
            }}
          >
            <Icon name="add_photo_alternate" size={20} />
            {t("Drop to add as reference")}
          </div>
        )}
        <input
          ref={fileInput}
          type="file"
          accept="image/*"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
            e.target.value = "";
          }}
        />
      </div>
    </Overlay>
  );
}
