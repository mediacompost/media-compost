// A small map of the model being trained: one tile per top-level block, in
// the order data flows through them, sized by how much of the model each one
// holds. The shape comes from the trainer reading the loaded weights — nothing
// here knows what an SDXL or a Chroma looks like, so a model this app has
// never seen draws itself correctly.
//
// It is a picture of the model, not a live probe: there is deliberately no
// "which block is running now" highlight. On an async backend the hooks that
// would answer that fire at QUEUE time, so the answer was never more than
// "somewhere near the end", and paying for it in the forward path of every
// step was the wrong trade.
import { useState } from "react";
import { SectionHeading } from "../shared/SectionHeading";
import { api, TrainArchitectureBlock } from "./api";
import { useQuery } from "@tanstack/react-query";
import { useT } from "./i18n";

const KIND_COLOR: Record<string, string> = {
  down: "var(--accent)",
  mid: "var(--magenta-text)",
  up: "var(--green-text)",
  stack: "var(--accent)",
  embed: "var(--muted-2)",
  other: "var(--muted-2)",
};

function fmtParams(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${Math.round(n / 1e6)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}K`;
  return String(n);
}

export function ArchitectureMap({ uid, running }: {
  uid: string;
  running: boolean;
}) {
  const t = useT();
  const { data } = useQuery({
    queryKey: ["train-architecture", uid],
    queryFn: () => api.trainArchitecture(uid),
    // Written when the model loads and rewritten after the first step, once
    // the run has seen which order the blocks execute in — so keep looking
    // while it runs, lazily, and stop entirely when it isn't.
    refetchInterval: (q) => (running
      ? ((q.state.data?.blocks?.length ?? 0) === 0 ? 4000 : 15000)
      : false),
  });
  const blocks: TrainArchitectureBlock[] = data?.blocks ?? [];
  // Which tile the pointer is on — shown IMMEDIATELY in the header line
  // (a system tooltip needs a second of hovering, which makes comparing
  // blocks by waving across the strip impossible).
  const [hover, setHover] = useState<{
    name: string; params: number; count?: number;
  } | null>(null);
  if (blocks.length === 0) return null;

  const total = blocks.reduce((s, b) => s + (b.params || 0), 0) || 1;
  return (
    <div style={{ marginBottom: 16 }}>
      <SectionHeading style={{ display: "flex", alignItems: "center", gap: 8, margin: "0 2px 6px" }}>
        {t("Model")}
        <span style={{
          fontWeight: 400, letterSpacing: 0, textTransform: "none",
          color: "var(--muted-2)",
        }}>
          {fmtParams(total)} {t("parameters")}
        </span>
        {hover && (
          <span style={{
            marginLeft: "auto", fontWeight: 400, letterSpacing: 0,
            textTransform: "none", color: "var(--text-2)",
            whiteSpace: "nowrap", overflow: "hidden",
            textOverflow: "ellipsis", fontVariantNumeric: "tabular-nums",
          }}>
            <span style={{ color: "var(--text)", fontWeight: 600 }}>
              {hover.name}
            </span>
            {hover.count ? ` · ${hover.count} ${t("blocks")}` : ""}
            {` · ${fmtParams(hover.params)} ${t("parameters")}`}
          </span>
        )}
      </SectionHeading>
      <div style={{
        display: "flex", gap: 2, height: 34, alignItems: "stretch",
        background: "var(--panel)", border: "1px solid var(--border)",
        borderRadius: "var(--r-6)", padding: 3, overflow: "hidden",
      }}>
        {blocks.map((b) => {
          const share = (b.params || 0) / total;
          const color = KIND_COLOR[b.kind] ?? KIND_COLOR.other;
          const kids = b.children ?? [];
          const dim = (name: string) =>
            (hover && hover.name !== name ? 0.45 : 0.8);
          if (kids.length > 1) {
            const kidTotal = kids.reduce((s2, k) => s2 + (k.params || 0), 0) || 1;
            return (
              <div
                key={b.name}
                style={{
                  flex: `${Math.max(share, 0.02)} 1 0`, minWidth: 12,
                  display: "flex", gap: 1, borderRadius: "var(--r-3)", overflow: "hidden",
                }}
              >
                {/* A stack shows its actual repeated blocks, each at its own
                    size — a UNet's deepest down block holds most of the
                    parameters, and drawing that is what makes this a picture
                    of the architecture rather than a label saying ×3. */}
                {kids.map((k) => (
                  <div
                    key={k.name}
                    onMouseEnter={() => setHover({
                      name: k.name, params: k.params,
                    })}
                    onMouseLeave={() => setHover(null)}
                    style={{
                      flex: `${Math.max((k.params || 0) / kidTotal, 0.06)} 1 0`,
                      minWidth: 3,
                      background: color,
                      opacity: dim(k.name),
                      transition: "opacity 0.15s ease",
                    }}
                  />
                ))}
              </div>
            );
          }
          return (
            <div
              key={b.name}
              onMouseEnter={() => setHover({ name: b.name, params: b.params })}
              onMouseLeave={() => setHover(null)}
              style={{
                // Share of the model by parameters, with a floor so the small
                // blocks (embeddings, the input convolution) stay visible.
                flex: `${Math.max(share, 0.02)} 1 0`,
                minWidth: 6, borderRadius: "var(--r-3)",
                background: color,
                opacity: dim(b.name),
                transition: "opacity 0.15s ease",
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
