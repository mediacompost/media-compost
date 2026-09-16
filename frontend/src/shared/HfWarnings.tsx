// The two Hugging Face environment warnings, shared by every page that offers
// model downloads (Settings → Actions, and the Train tab's Models page). They
// live here for the same reason the download button does: the pages must say
// the same thing about the same environment, and a copy would drift.
import React, { useState } from "react";
import { api } from "./api";
import { Icon } from "./Icon";
import { useT } from "./i18n";

const warnBox: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "11px 12px",
  background: "var(--yellow-dim)", border: "1px solid var(--yellow-border)",
  borderRadius: "var(--r-6)", fontSize: "var(--fs-2)", lineHeight: 1.5, color: "var(--text-2)",
};
const warnBtn: React.CSSProperties = {
  flex: "0 0 auto", height: 32, padding: "0 12px", borderRadius: "var(--r-4)", border: "none",
  background: "var(--accent)", color: "var(--on-accent)", fontWeight: 600,
  fontSize: "var(--fs-3)", cursor: "pointer", whiteSpace: "nowrap", fontFamily: "inherit",
};
const link: React.CSSProperties = { color: "var(--accent)", textDecoration: "none" };

/** Downloads are switched off by the environment — say which variable did it,
 *  and offer to switch them back on for this server. */
export function OfflineWarning({ variable, onChanged, boxRef }: {
  variable: string;
  onChanged: () => void;
  boxRef?: (el: HTMLDivElement | null) => void;
}) {
  const t = useT();
  return (
    <div ref={boxRef} style={warnBox}>
      <Icon name="warning" size={16} color="var(--yellow-text)" />
      <div style={{ flex: 1, userSelect: "text", WebkitUserSelect: "text" }}>
        {t("Your environment sets")}{" "}
        <b style={{ fontFamily: "var(--mono)" }}>{variable}</b>
        {t(", which forces Hugging Face into offline mode — model downloads will fail.")}
      </div>
      <button
        onClick={() => { void api.clearOffline().then(onChanged); }}
        style={warnBtn}
      >
        {t("Enable downloads")}
      </button>
    </div>
  );
}

/** No Hugging Face token for this session. Worth saying wherever a download is
 *  still ahead — and the reason that applies to EVERY download comes first:
 *  unauthenticated fetches are rate-limited, which is what people actually
 *  hit. Gated models are the rarer case and read as "not my problem" to
 *  anyone downloading an open one, which is why leading with them made the
 *  whole warning easy to skip. */
export function TokenWarning({ onChanged }: { onChanged: () => void }) {
  const t = useT();
  const [token, setToken] = useState("");
  const apply = async (value: string) => {
    await api.setHfToken(value);
    setToken("");
    onChanged();
  };
  return (
    <div style={{ ...warnBox, flexDirection: "column", alignItems: "stretch", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 9 }}>
        <Icon name="key_off" size={16} color="var(--yellow-text)" />
        <div style={{ flex: 1, userSelect: "text", WebkitUserSelect: "text" }}>
          {t("No Hugging Face access token found. Downloads without one are")}{" "}
          <b>{t("rate-limited and much slower")}</b>
          {t(" — a multi-gigabyte model is where you notice. A few models are gated and need one at all. Create a token on the")}{" "}
          <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer" style={link}>
            {t("access tokens page")}
          </a>{t(". Setting it here applies to this server session only (never saved to disk) — run")}{" "}
          <b style={{ fontFamily: "var(--mono)" }}>hf auth login</b>
          {t(" in a terminal to store one on this machine instead, so a restart does not quietly go back to downloading anonymously.")}
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          type="password" autoComplete="off" spellCheck={false}
          value={token}
          onChange={(e) => setToken(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && token.trim()) void apply(token.trim()); }}
          placeholder="hf_…"
          style={{
            flex: 1, height: 34, padding: "0 12px", background: "var(--panel)",
            border: "1px solid var(--border-strong)", borderRadius: "var(--r-5)",
            color: "var(--text)", fontSize: "var(--fs-3)", outline: "none",
            fontFamily: "var(--mono)",
          }}
        />
        <button
          onClick={() => token.trim() && void apply(token.trim())}
          disabled={!token.trim()}
          style={{ ...warnBtn, opacity: token.trim() ? 1 : 0.5 }}
        >
          {t("Set token")}
        </button>
      </div>
    </div>
  );
}
