// Live system stats in the Train sidebar's footer: one box per device — every
// GPU (with its model name; temperature and power draw where the platform
// exposes them), the CPU and RAM. Missing metrics simply don't appear.
import React, { useRef, useState } from "react";
import { Collapse } from "../shared/Collapse";
import { storage } from "../shared/storage";
import { ProgressBar } from "../shared/ProgressBar";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, SystemDevice } from "./api";
import { Icon } from "../shared/Icon";
import { useT } from "./i18n";
import { barColor } from "./gpuStats";

const OPEN_KEY = "mc.trainStatsOpen";

function iconFor(device: SystemDevice): string {
  if (device.key === "system") return "developer_board"; // CPU + RAM box
  return "memory"; // GPU
}

function Bar({ pct, color }: { pct: number; color: string }) {
  // A step darker/lighter than the card so the track reads as a track.
  return <ProgressBar value={pct} height={11} color={color} track="var(--bg-deep)"
                      bordered floor={0} transitionMs={500} />;
}

/** One metric as a stacked block: label (left) and value (right-aligned) on
 *  one line ABOVE the bar. Blocks sit two per row in the card. */
function MetricBlock({ statKey, label, pct, value }: {
  statKey: string;
  label: string;
  pct: number | null; // null = no ceiling reported, so no bar
  value: string;
}) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{
        display: "flex", alignItems: "baseline", justifyContent: "space-between",
        gap: 8, marginBottom: 4,
      }}>
        <span style={{ color: "var(--muted)", fontSize: "var(--fs-1)" }}>{label}</span>
        <span style={{
          fontSize: "var(--fs-2)", fontVariantNumeric: "tabular-nums",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {value}
        </span>
      </div>
      {pct !== null && <Bar pct={pct} color={barColor(statKey, pct)} />}
    </div>
  );
}

function DeviceBox({ device }: { device: SystemDevice }) {
  const t = useT();
  const util = device.stats.find((s) => s.key === "util");
  const mem = device.stats.find((s) => s.key === "vram" || s.key === "mem");
  const memTotal = device.stats.find(
    (s) => s.key === "vram_total" || s.key === "mem_total");
  const diskFree = device.stats.find((s) => s.key === "disk_free");
  const diskTotal = device.stats.find((s) => s.key === "disk_total");
  const rest = device.stats.filter(
    (s) => !["util", "vram", "vram_total", "mem", "mem_total",
             "disk_free", "disk_total"].includes(s.key));

  const blocks: { key: string; label: string; pct: number | null; value: string }[] = [];
  if (util) {
    blocks.push({ key: "util", label: util.label, pct: util.value,
                  value: `${util.value}%` });
  }
  if (mem && memTotal && memTotal.value > 0) {
    blocks.push({
      key: "mem", label: mem.label,
      pct: (100 * mem.value) / memTotal.value,
      value: `${mem.value} / ${memTotal.value} ${mem.unit}`,
    });
  }
  if (diskFree && diskTotal && diskTotal.value > 0) {
    // The volume the library (and its training runs) lives on. The number
    // people act on is what is LEFT, so the backend reports FREE and this
    // derives the fullness from it — never the other way round: on Linux
    // "total minus used" counts the filesystem's root reserve as available
    // and overstates free space by ~5% of the volume (see gpu._system_device),
    // which is what made this box disagree with the library sidebar.
    blocks.push({
      key: "disk", label: t("Disk"),
      pct: (100 * (diskTotal.value - diskFree.value)) / diskTotal.value,
      value: `${diskFree.value.toFixed(1)} ${diskFree.unit} ${t("free")}`,
    });
  }
  for (const s of rest) {
    // Temperature, power and fan used to be bare numbers because nothing said
    // what they were a share OF. Where the device reports a ceiling they get
    // a bar like everything else; where it does not — an rpm fan reading, or
    // a temperature on a driver that reports margins rather than absolute
    // thresholds — they stay bare rather than being drawn against a guess.
    const pct = s.max && s.max > 0 ? (100 * s.value) / s.max : null;
    blocks.push({
      key: s.key, label: s.label, pct,
      value: pct !== null
        ? `${s.value} / ${s.max}${s.unit}`
        : `${s.value}${s.unit}`,
    });
  }

  return (
    <div
      style={{
        padding: "8px 12px 10px", marginBottom: 8,
        background: "var(--panel)", border: "1px solid var(--border)",
        borderRadius: "var(--r-7)", fontSize: "var(--fs-2)", color: "var(--text-2)",
      }}
    >
      <div style={{
        display: "flex", alignItems: "center", gap: 7, marginBottom: 7,
        color: "var(--muted)", fontSize: "var(--fs-1)", fontWeight: 600,
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      }}>
        <Icon name={iconFor(device)} size={14} />
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
          {device.label}
        </span>
      </div>
      <div style={{
        // A lone metric (e.g. Apple GPU utilization) fills the whole row.
        display: "grid",
        gridTemplateColumns: blocks.length > 1 ? "1fr 1fr" : "1fr",
        columnGap: 12, rowGap: 8,
      }}>
        {blocks.map((b, i) => (
          // An odd block count leaves the last one alone in its row — let
          // it use the full width (the Disk row under CPU + RAM).
          <div key={b.key} style={blocks.length > 1 && blocks.length % 2 === 1
              && i === blocks.length - 1
            ? { gridColumn: "1 / -1" } : undefined}>
            <MetricBlock statKey={b.key} label={b.label} pct={b.pct}
                         value={b.value} />
          </div>
        ))}
      </div>
      {device.hint === "powermetrics" && <PowermetricsHint />}
    </div>
  );
}

/** The hint's two small buttons — one shape, so Copy and Try again cannot
 *  drift apart the way two hand-spelled buttons in one row do. */
function HintBtn({ icon, label, title, onClick }: {
  icon: string; label: string; title?: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        display: "flex", alignItems: "center", gap: 4, flex: "0 0 auto",
        padding: "3px 7px", background: "transparent",
        border: "1px solid var(--border)", borderRadius: "var(--r-2)",
        color: "var(--muted)", fontSize: "var(--fs-1)", cursor: "pointer",
        whiteSpace: "nowrap",
      }}
    >
      <Icon name={icon} size={12} />
      {label}
    </button>
  );
}

/** Why this box has no temperature, power or fan.
 *
 *  macOS gates those behind root and offers no way to ask for it at runtime,
 *  so the server tries `sudo -n` ONCE and then stops. Without this line the
 *  box simply looks thinner than it does on an NVIDIA machine, with nothing
 *  anywhere connecting that to a sudoers rule nobody has heard of — and the
 *  command is the whole point, so it is shown rather than described.
 *
 *  IT IS A SELECTABLE COMMAND WITH A COPY BUTTON, not a click-to-copy block.
 *  The block was the whole target: `body` sets `user-select: none` and the
 *  override said `user-select` WITHOUT the WebKit spelling, so on the one
 *  platform this hint can ever appear the text could not be selected at all —
 *  and the only way out, a click, silently did nothing wherever
 *  `navigator.clipboard` is absent (it needs a secure context, and this
 *  server is routinely reached over plain http on a LAN). So: both spellings
 *  of the selection rule, a text cursor that says so, and a button that
 *  copies — falling back to SELECTING the command and naming the key that
 *  finishes it, rather than failing quietly.
 *
 *  TRY AGAIN IS BESIDE IT because the refusal is LATCHED, not permanent
 *  (`gpu.clear_denied`): the probe gives up once per process so a 2 s poll
 *  cannot spend a failed sudo — and an auth-log entry — every tick, and the
 *  one thing that changes its answer is you running the command above. This
 *  is how you say you have, without restarting a server whose configuration
 *  was just fixed. The hint disappears on its own when the answer changes,
 *  since it hangs off `device.hint`. */
function PowermetricsHint() {
  const t = useT();
  const qc = useQueryClient();
  const cmd = 'echo "$(id -un) ALL=(root) NOPASSWD: /usr/bin/powermetrics" '
    + '| sudo tee /etc/sudoers.d/media-compost-powermetrics';
  const cmdRef = useRef<HTMLElement | null>(null);
  const [said, setSaid] = useState<"" | "copied" | "select">("");

  const selectCmd = () => {
    const el = cmdRef.current;
    if (!el) return;
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);
    setSaid("select"); // stays: the selection it names is still on screen.
  };
  const copy = () => {
    const done = navigator.clipboard?.writeText(cmd);
    if (!done) { selectCmd(); return; }
    void done.then(() => {
      setSaid("copied");
      window.setTimeout(() => setSaid((v) => (v === "copied" ? "" : v)), 2000);
    }, selectCmd);
  };

  return (
    <div style={{ marginTop: 8, fontSize: "var(--fs-1)", color: "var(--muted-2)",
                  lineHeight: 1.5 }}>
      {t("macOS keeps GPU temperature and power for root only. To see them here, allow this one command without a password, then press Try again:")}
      <code
        ref={cmdRef}
        style={{
          display: "block", marginTop: 5, padding: "5px 7px",
          background: "var(--bg-deep)", border: "1px solid var(--border)",
          borderRadius: "var(--r-2)", fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
          color: "var(--text-2)", cursor: "text",
          overflowWrap: "anywhere",
          // BOTH spellings: `body` suppresses selection app-wide and WebKit
          // — the only engine that ever renders this hint — reads its own.
          userSelect: "text", WebkitUserSelect: "text",
        }}
      >
        {cmd}
      </code>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                    marginTop: 4 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {said === "select" && t("Press ⌘C to copy it")}
        </div>
        <HintBtn
          icon={said === "copied" ? "check" : "content_copy"}
          label={said === "copied" ? t("Copied") : t("Copy")}
          onClick={copy}
        />
        <HintBtn
          icon="refresh"
          label={t("Try again")}
          title={t("Check again — no restart needed once the rule is in")}
          onClick={() => {
            void api.trainGpuRecheck().then(
              (d) => qc.setQueryData(["train-gpu"], d));
          }}
        />
      </div>
    </div>
  );
}

/** One number per device for the collapsed footer line — the GPU's load and
 *  the machine's memory, which is what you glance at while a run is going. */
function summary(devices: SystemDevice[]): string {
  const bits: string[] = [];
  for (const d of devices) {
    const util = d.stats.find((s) => s.key === "util");
    const mem = d.stats.find((s) => s.key === "vram" || s.key === "mem");
    const total = d.stats.find((s) => s.key === "vram_total" || s.key === "mem_total");
    if (d.key === "system") {
      if (mem && total && total.value > 0) {
        bits.push(`RAM ${mem.value} / ${total.value} ${mem.unit}`);
      }
    } else if (util) {
      bits.push(`GPU ${util.value}%`);
    }
  }
  return bits.join(" · ");
}

/** Live system stats, pinned to the bottom of the Train tab's sidebar and
 *  collapsed by default — the same footer treatment as the library statistics
 *  and Quick Assign: one summary line you can always see, the full boxes when
 *  you ask for them. They are a background reading, not the point of the page,
 *  and at the top they pushed the job list down. */
export function GpuStatsBar() {
  const t = useT();
  const [open, setOpen] = useState(
    () => storage.get(OPEN_KEY) === "1"
  );
  const { data } = useQuery({
    queryKey: ["train-gpu"],
    queryFn: api.trainGpu,
    // Only while the panel is open — a collapsed footer that polls twice a
    // second is a background cost for a line nobody is reading.
    refetchInterval: open ? 2000 : 10000,
  });
  if (!data || data.length === 0) return null;
  const toggle = () => setOpen((v) => {
    storage.set(OPEN_KEY, v ? "0" : "1");
    return !v;
  });
  return (
    <div style={{ flex: "0 0 auto", borderTop: "1px solid var(--border-soft)" }}>
      {/* Animated open/close: grid-rows 0fr→1fr with the body clipped, exactly
          as the library-statistics footer does it. */}
      <Collapse open={open}>
          <div style={{ padding: "10px 14px 2px" }}>
            {/* GPUs first: they are what a training run is waiting on, and
                the machine's CPU/RAM box is the background reading below
                them. The backend reports the system box first. */}
            {[...data]
              .sort((a, b) => Number(a.key === "system")
                - Number(b.key === "system"))
              .map((d) => <DeviceBox key={d.key} device={d} />)}
          </div>
        </Collapse>
      <div
        onClick={toggle}
        title={open ? t("Hide system statistics") : t("Show system statistics")}
        style={{
          padding: "9px 14px", display: "flex", alignItems: "center", gap: 8,
          color: "var(--muted-2)", fontSize: "var(--fs-2)", cursor: "pointer",
        }}
      >
        <Icon name="monitoring" size={16} />
        <span style={{ fontFamily: "var(--mono)" }}>{summary(data)}</span>
        <div style={{ flex: 1 }} />
        <Icon name={open ? "expand_more" : "expand_less"} size={16} />
      </div>
    </div>
  );
}
