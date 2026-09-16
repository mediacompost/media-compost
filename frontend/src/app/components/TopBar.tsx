import React, { useEffect, useState } from "react";
import { Chip } from "../../shared/Chip";
import { IconButton } from "../../shared/IconButton";
import { useQuery } from "@tanstack/react-query";
import { Icon } from "../../shared/Icon";
import { useUI } from "../store";
import { TrainingTabs } from "../training";
import { loadThemePref, setThemePref, ThemePref } from "../theme";
import { useT } from "../i18n";
import { api } from "../api";
import { ThemeMenu, type ThemeOption } from "./shared/ThemeMenu";

// The app's theme: light, dark or the system's — the item window's own
// `ThemeMenu` with these as its options, so one menu shape serves both.
const APP_THEMES: ThemeOption<ThemePref>[] = [
  { value: "light", label: "Light", icon: "light_mode" },
  { value: "dark", label: "Dark", icon: "dark_mode" },
  { value: "system", label: "System", icon: "brightness_auto" },
];

function ThemeToggle() {
  const t = useT();
  const [pref, setPref] = useState<ThemePref>(() => loadThemePref());
  return (
    <ThemeMenu<ThemePref> t={t} value={pref} options={APP_THEMES}
      title={t("Theme")}
      onChange={(v) => { setPref(v); setThemePref(v); }}
      buttonStyle={() => ({
        width: 32, height: 32, borderRadius: "var(--r-4)", border: "1px solid var(--border)",
        background: "transparent", color: "var(--muted)",
      })} />
  );
}

// The signed-in user (from the upstream auth layer). Hidden entirely on a
// single-user/anonymous install where auth isn't required, so the default UI is
// unchanged; shown as a compact chip once a user is known or auth is enforced.
function WhoAmI() {
  const t = useT();
  const { data } = useQuery({ queryKey: ["whoami"], queryFn: api.whoami });
  if (!data) return null;
  if (!data.username && !data.require_auth) return null;
  const name = data.username || t("anonymous");
  return (
    <Chip size="lg" round bordered icon={data.username ? "person" : "person_off"}
          title={data.username ? t("Signed in as {name}", { name: data.username }) : t("Not signed in")}
          style={{ maxWidth: 180, gap: 5, color: "var(--muted)", background: "var(--bg)" }}>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {name}
      </span>
    </Chip>
  );
}

export function TopBar() {
  const { view, setView, setOverlay, setHistoryFilter } = useUI();
  const { data: uiPrefs } = useQuery({
    queryKey: ["settings"], queryFn: api.getSettings });
  const facesHidden = uiPrefs?.hide_faces_tab ?? false;
  const t = useT();
  const tab = (active: boolean): React.CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: 6,
    height: 26,
    padding: "0 12px",
    borderRadius: "var(--r-3)",
    border: "none",
    background: active ? "var(--border)" : "transparent",
    color: active ? "var(--text)" : "var(--muted)",
    fontWeight: active ? 600 : 500,
    fontSize: "var(--fs-3)",
    cursor: "pointer",
  });
  return (
    <div
      style={{
        height: 48,
        flex: "0 0 48px",
        background: "var(--topbar)",
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        padding: "0 14px",
        gap: 16,
        position: "relative",
        zIndex: 5,
      }}
    >
      {/* The mark never shrinks (a flex item does, and a narrow window
          squeezed it into a sliver); the NAME is what yields, ellipsising. */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
        <div
          style={{
            width: 22,
            height: 22,
            flex: "0 0 auto",
            borderRadius: "var(--r-2)",
            background: "linear-gradient(135deg,var(--accent),var(--accent-bright))",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Icon name="compost" size={15} color="var(--on-accent)" />
        </div>
        <span style={{ fontWeight: 600, fontSize: "var(--fs-4)", letterSpacing: "-0.01em", minWidth: 0,
                       overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          Media Compost
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 2,
          background: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-5)",
          padding: 3,
        }}
      >
        <button onClick={() => setView("library")} style={tab(view === "library")}>
          <Icon name="grid_view" size={17} />
          {t("Library")}
        </button>
        <button onClick={() => setView("tags")} style={tab(view === "tags")}>
          <Icon name="sell" size={17} />
          {t("Tags")}
        </button>
        {/* ABSENT, NOT DISABLED, when it is hidden (Settings → Faces) — the
            training tabs' rule: a tab you cannot press says the app is
            broken, a tab that is not there says this deployment does not do
            that. `?? false` keeps it showing while the query is in flight,
            so it never flashes away on a slow load. */}
        {!facesHidden && (
          <button onClick={() => setView("faces")} style={tab(view === "faces")}>
            <Icon name="face" size={17} />
            {t("Faces")}
          </button>
        )}
        <button onClick={() => { setHistoryFilter([]); setView("history"); }} style={tab(view === "history")}>
          <Icon name="history" size={17} />
          {t("History")}
        </button>
      </div>
      {/* Training lives in its own pill box, set apart from the browsing
          tabs — and the whole box goes when this deployment does not train.
          It comes through the lazy training door because its pollers speak
          the trainer's API (see app/training.tsx). */}
      <TrainingTabs view={view} setView={setView} tabStyle={tab} />
      <div style={{ flex: 1 }} />
      <WhoAmI />
      <ThemeToggle />
      <IconButton icon="settings" size={32} tone="muted" bordered
        onClick={() => setOverlay("settings")}
        title="Settings" />
    </div>
  );
}
