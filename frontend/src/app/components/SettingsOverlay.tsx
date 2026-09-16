import React, { useEffect, useRef, useState } from "react";
import { rowBackground } from "../../shared/Row";
import { chipStyle } from "../../shared/Chip";
import { SECTION_LABEL } from "../../shared/SectionHeading";
import { IconButton } from "../../shared/IconButton";
import { PrefRow, Section, ToggleRow } from "../../shared/SettingsRows";
import { Select } from "../../shared/Select";
import { Switch } from "../../shared/Switch";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppSettings, ModelCacheInfo, api } from "../api";
// The ONE byte formatter (decimal): a private 1024-based copy here read the
// same model-cache footprint smaller than every other view of the same number.
import { formatBytes } from "../format";
import { Icon } from "../../shared/Icon";
import { useUI } from "../store";
import { tagFieldInput } from "../tags";
import { Overlay } from "../../shared/Overlay";
import { ModelHelpOverlay } from "./ModelHelp";
import { StoragePage } from "./SettingsStorage";
import {
  SplitDownloadButton, downloadDetail, splitMainStyle as mainBtn,
} from "../../shared/ModelDownloadButton";
import { OfflineWarning, TokenWarning } from "../../shared/HfWarnings";
import { DATE_FORMAT_OPTIONS, renderDate } from "../../shared/time";
import { LANGUAGES, useT, useLang } from "../i18n";

/** The three tag namespaces, in the order the Tags tab lists their sub-tabs.
 *  Keyed by the settings field so the row and the value cannot drift apart. */
const PREFIXES: { key: "subject_tag_prefix" | "place_tag_prefix" | "event_tag_prefix";
                  label: string; example: string }[] = [
  { key: "subject_tag_prefix", label: "Default tag prefix for subjects",
    example: "albert_einstein" },
  { key: "place_tag_prefix", label: "Default tag prefix for places",
    example: "berlin_hauptbahnhof" },
  { key: "event_tag_prefix", label: "Default tag prefix for events",
    example: "san_diego_comic_con_2014" },
];

const EMPTY: AppSettings = { model_paths: {}, dblclick_image: "quicklook", dblclick_video: "quicklook", florence_model: "florence2_base", language: "en", date_format: DATE_FORMAT_OPTIONS[0], time_24h: false, hide_unready_actions: false, hide_faces_tab: false, subject_tag_prefix: "subject:", place_tag_prefix: "place:", event_tag_prefix: "event:", face_match_threshold: 0.9, watermark_tag: "watermark", text_tag: "" };


// Date-format dropdown options, labelled with a live example. The sample is
// August 19 (like macOS): the day (19) exceeds 12, so day/month order is never
// ambiguous. The year is the current one.
const _DATE_SAMPLE = new Date(new Date().getFullYear(), 7, 19);
const DATE_FORMAT_CHOICES: [string, string][] = DATE_FORMAT_OPTIONS.map(
  (p) => [p, renderDate(_DATE_SAMPLE, p)]
);

// The Florence-2 checkpoints; only the selected one is used for actions. Each
// maps to a dropdown label (fine-tuned and plain base/large variants).
const FLORENCE_OPTIONS: [string, string][] = [
  ["florence2_base", "Base (fine-tuned)"],
  ["florence2_base_plain", "Base"],
  ["florence2_large", "Large (fine-tuned)"],
  ["florence2_large_plain", "Large"],
];
const FLORENCE_KEYS = FLORENCE_OPTIONS.map(([k]) => k);

/** App settings overlay (opened from the gear button in the top bar). */
export function SettingsOverlay() {
  const qc = useQueryClient();
  const setOverlay = useUI((s) => s.setOverlay);
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const { data: cache } = useQuery({
    queryKey: ["model-cache"],
    queryFn: api.modelCache,
    refetchInterval: (q) => {
      const models = (q.state.data as { models: ModelCacheInfo[] } | undefined)?.models ?? [];
      return models.some((m) => m.downloading) ? 1200 : false;
    },
  });

  // The visible page is remembered across opens (and set to Actions when opened
  // via a model download from the Actions menu).
  const page = useUI((s) => s.settingsPage);
  const setPage = useUI((s) => s.setSettingsPage);
  // A model to scroll into view when the Actions page opens (set when a download
  // is started from the Actions menu).
  const focusModel = useUI((s) => s.settingsFocusModel);
  const setFocusModel = useUI((s) => s.setSettingsFocusModel);
  const focusWarning = useUI((s) => s.settingsFocusWarning);
  const setFocusWarning = useUI((s) => s.setSettingsFocusWarning);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const warnRef = useRef<HTMLDivElement | null>(null);
  // The model card to visually highlight after being focused from a download /
  // enable-downloads chip. Lingers briefly (independent of the scroll target,
  // which may be the warning banner) so the user can spot which model it was.
  const [highlight, setHighlight] = useState<string | null>(null);
  const t = useT();
  // Seed the form from the (usually warm) settings cache synchronously, so the
  // first paint already shows real values — no toggle flip, and no window where
  // a quick edit would save the EMPTY defaults over the stored prefs. Until the
  // server data has arrived (`form` still null), saving is disabled entirely.
  const [form, setForm] = useState<AppSettings | null>(() =>
    data ? { ...data, model_paths: { ...data.model_paths } } : null);
  useEffect(() => { if (data) setForm({ ...data, model_paths: { ...data.model_paths } }); }, [data]);
  // Scroll the focus target into view once it has rendered, then clear the focus
  // (keeping a short-lived highlight on the model's card). When the focus came
  // from an "Enable downloads" chip, scroll to the warning banner that holds that
  // button rather than the model card.
  useEffect(() => {
    if (page !== "actions" || !focusModel) return;
    const el = (focusWarning && warnRef.current) ? warnRef.current : cardRefs.current[focusModel];
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      setHighlight(focusModel);
      setFocusModel(null);
      setFocusWarning(false);
    }
  }, [page, focusModel, focusWarning, cache, setFocusModel, setFocusWarning]);
  // Fade the highlight out after it has had time to be noticed.
  useEffect(() => {
    if (!highlight) return;
    const id = setTimeout(() => setHighlight(null), 2600);
    return () => clearTimeout(id);
  }, [highlight]);
  // The model whose setup instructions are shown in the help overlay.
  const [help, setHelp] = useState<{ label: string; url: string; setup_key?: string } | null>(null);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["settings"] });
    qc.invalidateQueries({ queryKey: ["model-cache"] });
  };
  // Always PUT the full settings so one field's update never resets the others.
  //: THE CONTROL ANSWERS FIRST, THE SERVER CONFIRMS. Every write here used
  //  to set the form from the RESPONSE, so a control showed the old value
  //  until the round trip landed — invisible on a switch, and on the
  //  threshold SLIDER it meant the thumb ran a request behind the pointer.
  const save = async (next: AppSettings) => {
    setForm(next);
    const saved = await api.updateSettings(next);
    setForm({ ...saved, model_paths: { ...saved.model_paths } });
    invalidate();
  };
  // Both writers are no-ops until the stored settings have loaded — saving on
  // top of the EMPTY placeholder would silently reset every other preference.
  const commitPath = (key: string, value: string) => {
    if (!form) return;
    save({ ...form, model_paths: { ...form.model_paths, [key]: value } });
  };
  const setPref = (patch: Partial<AppSettings>) => {
    if (!form) return;
    save({ ...form, ...patch });
  };
  //: A CONTROL THAT MOVES CONTINUOUSLY EDITS, THEN COMMITS. A drag of the
  //  similarity slider is sixty `PUT /api/settings` in a second, each one
  //  followed by a sweep of every settings query — the thumb stuttered and
  //  the number lagged. `preview` moves it (state only), `commit` writes
  //  once when it is let go. The ref is what `commit` reads: the handler
  //  that fires on release closes over the form as it was when the drag
  //  began.
  const formRef = useRef<AppSettings | null>(form);
  formRef.current = form;
  const previewPref = (patch: Partial<AppSettings>) =>
    setForm((cur) => (cur ? { ...cur, ...patch } : cur));
  const commitPref = () => {
    const cur = formRef.current;
    if (cur) void save(cur);
  };
  // What the controls render before the query resolves (read-only defaults).
  const f = form ?? EMPTY;

  const tokenAvailable = cache?.token_available ?? false;
  const envOffline = cache?.env_offline ?? "";
  const models = cache?.models ?? [];
  // Only warn while the warning still matters — i.e. while something is still
  // to be fetched. Both apply to any download: offline mode blocks them, and a
  // token speeds every download up (unauthenticated fetches are rate-limited)
  // and is required outright for the few gated ones.
  // …and only about models that actually download something: a row with no repo
  // is waiting on a pip install, which neither offline mode nor a token affects.
  const pending = models.some((m) => !m.cached && !!m.repo);
  // What "Download all" can actually start, for one section's rows. It was
  // one predicate over the whole page; the rule is unchanged, only its scope.
  const downloadable = (rows: ModelCacheInfo[]) => rows.filter((m) =>
    !m.cached && !m.downloading && !m.local_path && m.deps_ok
    // Something to fetch: a hub repo, or a plugin that fetches its own. A row
    // with neither has nothing "Download all" can do.
    && (!!m.repo || !!m.fetchable)
    // The hub's gates only apply to the hub.
    && (!m.repo || (!(m.gated && !tokenAvailable) && !envOffline)));
  const showOffline = !!envOffline && pending;
  const showToken = !tokenAvailable && pending;
  // Only the selected Florence checkpoint is shown; the other checkpoints are
  // hidden (still downloadable by switching the selector).
  const visibleModels = models.filter(
    (m) => !(FLORENCE_KEYS.includes(m.key) && m.key !== f.florence_model),
  );
  // Group the models by type (Upscaling, Captioning, …) for the list, keeping
  // categories in the order they first appear (which follows the plugin registry
  // order). Uncategorised models fall into a trailing "Other" group.
  const modelGroups = (() => {
    const order: string[] = [];
    const byCat: Record<string, ModelCacheInfo[]> = {};
    for (const m of visibleModels) {
      const cat = m.category || "Other";
      if (!byCat[cat]) { byCat[cat] = []; order.push(cat); }
      byCat[cat].push(m);
    }
    return order.map((cat) => ({ cat, items: byCat[cat] }));
  })();

  return (
    <Overlay icon="settings" title={t("Settings")} width={720} onClose={() => setOverlay(null)}>
      {/* Fixed height (the taller Actions page's cap) so switching pages never
          resizes the overlay — otherwise the left nav items jump under the
          pointer. Each page scrolls internally. */}
      <div style={{ display: "flex", height: "72vh", minHeight: 360 }}>
        {/* Page navigation sidebar. */}
        <div style={{ flex: "0 0 150px", borderRight: "1px solid var(--border-soft)", padding: "14px 10px", display: "flex", flexDirection: "column", gap: 2 }}>
          {/* Tagging: both of its settings END IN A TAG — the prefix on a tag
              the app invents, and how alike two faces must be before it puts a
              person's tag on a picture by itself. That is what makes the face
              threshold a tagging setting rather than a face one: what it
              decides is whether a tag lands. */}
          {([["general", t("General"), "tune"],
             ["tagging", t("Tagging"), "sell"],
             // "Actions" rather than "Models": the page exists to make the
             // grid's and sidebar's Actions work, and that is the word both
             // already use — the models are how, not what. The GLYPH says it
             // twice: `auto_awesome` is what the two context menus put beside
             // their own Actions row, so the page that sets one up and the
             // menus that run it look like the same thing.
             // Beside Tagging, because both pages are about what ends up
             // ATTACHED TO A PICTURE; Actions and Storage below are about
             // the machine. `face` is the heavy glyph of the pair this font
             // ships — right here, where nothing sits beside it having to
             // mean "a subject" (the tag lists use `person` for that).
             ["faces", t("Faces"), "face"],
             ["actions", t("Actions"), "auto_awesome"],
             // Last: it is the page you come to when something is wrong
             // (the disk is full), not one you set anything on.
             ["storage", t("Storage"), "hard_drive"]] as const).map(([id, label, icon]) => (
            <div
              key={id}
              className="hoverable"
              onClick={() => setPage(id)}
              style={{
                display: "flex", alignItems: "center", gap: 8, padding: "7px 10px",
                borderRadius: "var(--r-3)", cursor: "pointer", fontSize: "var(--fs-3)",
                background: rowBackground(page === id, "transparent"),
                color: page === id ? "var(--text-bright)" : "var(--text-2)",
                fontWeight: page === id ? 600 : 400,
              }}
            >
              <Icon name={icon} size={16} color={page === id ? "var(--accent)" : "var(--muted-2)"} />
              {label}
            </div>
          ))}
        </div>

        {/* Active page. */}
        {page === "storage" ? (
          <StoragePage />
        ) : page === "general" ? (
          <div className="mc-settings-page" style={{ flex: 1, padding: 20, display: "flex", flexDirection: "column", gap: 16, overflowY: "auto" }}>
            <Section title={t("Language & Region")}>
              <PrefRow
                label={t("Language")}
                value={f.language}
                onChange={(v) => setPref({ language: v })}
                options={LANGUAGES.map((l) => [l.value, l.label] as [string, string])}
              />
              <PrefRow
                label={t("Date format")}
                value={f.date_format}
                onChange={(v) => setPref({ date_format: v })}
                options={DATE_FORMAT_CHOICES}
              />
              <ToggleRow
                label={t("24-hour time")}
                checked={f.time_24h}
                onChange={(v) => setPref({ time_24h: v })}
                last
              />
            </Section>

            <Section title={t("Double-click an item")}>
              <PrefRow
                label={t("Images")}
                value={f.dblclick_image}
                onChange={(v) => setPref({ dblclick_image: v })}
                options={[["quicklook", t("Quick Look preview")], ["annotate", t("Annotate tags")], ["editor", t("Open image editor")], ["none", t("Do nothing")]]}
              />
              <PrefRow
                label={t("Videos")}
                value={f.dblclick_video}
                onChange={(v) => setPref({ dblclick_video: v })}
                options={[["quicklook", t("Quick Look preview")], ["annotate", t("Annotate tags")], ["editor", t("Open video editor")], ["none", t("Do nothing")]]}
                last
              />
            </Section>

          </div>
        ) : page === "faces" ? (
          <div className="mc-settings-page" style={{ flex: 1, padding: 20, display: "flex", flexDirection: "column", gap: 16, overflowY: "auto" }}>
            {/* THE TAB FIRST, THEN WHAT IT IS FOR. Whether the queue is
                offered at all is the larger question, and somebody who has
                come here to put the tab away should not have to read past a
                threshold to find the switch.

                HIDING THE TAB TURNS NOTHING OFF: detection still runs, its
                findings still land, Pending → Faces still fills and the
                annotator still asks who somebody is. That is why the
                threshold below stays live and un-dimmed with the tab
                hidden — it decides whether a name lands, which happens
                whether or not anybody is looking at a queue. */}
            <Section title={t("The Faces tab")}>
              <ToggleRow
                label={t("Hide the Faces tab")}
                checked={f.hide_faces_tab}
                onChange={(v) => setPref({ hide_faces_tab: v })}
                last
              />
            </Section>

            {/* "Naming", not "Faces": the page is already called that, and a
                section repeating its page's title says nothing. What this one
                number decides is when the app puts a name on by itself. */}
            <Section title={t("Naming")}>
              <div style={{ padding: "12px 16px" }}>
                <div className="mc-copy" style={{ fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
                  {t("Minimum face similarity")}
                </div>
                {/* Three facts and no more: what the number means, which way
                    to move it, and where its answers turn up. */}
                <div className="mc-copy" style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 3, lineHeight: 1.45 }}>
                  {t("How alike two faces must be before the app names one by itself. Higher is stricter: fewer names, fewer wrong ones. Each one waits for you under Pending → Faces.")}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10 }}>
                  <input
                    type="range" min={30} max={99} step={1}
                    value={Math.round(f.face_match_threshold * 100)}
                    // EDIT WHILE DRAGGING, WRITE ON RELEASE. `onChange` fires
                    // per pixel; the keyboard gets `onKeyUp` and the pointer
                    // `onPointerUp`, and `onBlur` catches a drag that ended
                    // off the control.
                    onChange={(e) => previewPref({
                      face_match_threshold: Number(e.target.value) / 100 })}
                    onPointerUp={commitPref}
                    onKeyUp={commitPref}
                    onBlur={commitPref}
                    style={{ flex: 1, maxWidth: 260, accentColor: "var(--accent)" }}
                  />
                  <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-3)", color: "var(--text-2)",
                                 width: 44, textAlign: "right" }}>
                    {`${Math.round(f.face_match_threshold * 100)}%`}
                  </span>
                  {/* DIMMED at the default rather than hidden: a control that
                      comes and going as you drag the slider beside it is one
                      you cannot aim at, and this one has a number to say. */}
                  {(() => {
                    const atDefault =
                      Math.round(f.face_match_threshold * 100)
                      === Math.round(EMPTY.face_match_threshold * 100);
                    return (
                      <IconButton icon="restart_alt" size={26} glyph={15} color={atDefault ? "var(--muted-3)" : "var(--text-2)"} bordered disabled={atDefault}
                        onClick={() => setPref({
                          face_match_threshold: EMPTY.face_match_threshold })}
                        title={t("Reset to {v}", {
                          v: `${Math.round(EMPTY.face_match_threshold * 100)}%` })} style={{ flex: "0 0 auto" }} />
                    );
                  })()}
                </div>
              </div>
            </Section>
          </div>
        ) : page === "tagging" ? (
          <div className="mc-settings-page" style={{ flex: 1, padding: 20, display: "flex", flexDirection: "column", gap: 16, overflowY: "auto" }}>
            <Section title={t("Prefixes")}>
              {/* One row per kind, the same shape three times: each gets a
                  namespace of its own so `place:berlin` can sit beside a plain
                  `berlin` that means something else entirely. Search keywords
                  are UPPERCASE, so a prefix can never be read as one. */}
              {PREFIXES.map((row, i) => (
                <div key={row.key} style={{
                  padding: "12px 16px",
                  ...(i > 0 ? { borderTop: "1px solid var(--border)" } : {}),
                }}>
                  <div className="mc-copy" style={{ fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
                    {t(row.label)}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
                    <input
                      value={f[row.key]}
                      // A PREFIX IS THE FRONT OF A TAG NAME, so it takes the
                      // tag field's rule: whitespace to underscores, and
                      // lowercase, because every tag this app mints from a
                      // typed name is lowercase and `Subject:alice` beside
                      // `subject:alice` is two namespaces nobody meant. It is
                      // `tagFieldInput`, the per-keystroke rule: this field is
                      // not a tag name but the head of one, and the trailing
                      // ':' that makes it a prefix has to survive typing.
                      onChange={(e) => setPref({ [row.key]: tagFieldInput(e.target.value) })}
                      placeholder={t("none")}
                      spellCheck={false}
                      style={{
                        width: 160, height: 30, padding: "0 9px", background: "var(--bg)",
                        border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)",
                        color: "var(--text)", fontFamily: "var(--mono)", fontSize: "var(--fs-3)",
                        outline: "none",
                      }}
                    />
                    {/* What it will actually mint — a prefix is easy to get
                        almost right, and the example says so before a tag
                        catalog is full of them. */}
                    <span className="mc-copy" style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted-2)",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {`${f[row.key]}${row.example}`}
                    </span>
                  </div>
                </div>
              ))}
            </Section>

            {/* The detectors' tag names: where "detect watermarks" files
                what it finds, and (optionally) where an OCR run also records
                its regions as boxes. Tag NAMES rather than prefixes, so a
                trailing colon here would just be a half-typed namespace. */}
            <Section title={t("Detection")}>
              {([["watermark_tag", t("Tag for detected watermarks"),
                  "watermark"],
                 ["text_tag", t("Tag for detected text"),
                  t("empty — text regions only")]] as const
              ).map(([key, label, ph], i) => (
                <div key={key} style={{
                  padding: "12px 16px",
                  ...(i > 0 ? { borderTop: "1px solid var(--border)" } : {}),
                }}>
                  <div className="mc-copy" style={{ fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
                    {label}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <input
                      value={f[key]}
                      onChange={(e) => setPref({ [key]: tagFieldInput(e.target.value) })}
                      placeholder={ph}
                      spellCheck={false}
                      style={{
                        width: 200, height: 30, padding: "0 9px", background: "var(--bg)",
                        border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)",
                        color: "var(--text)", fontFamily: "var(--mono)", fontSize: "var(--fs-3)",
                        outline: "none",
                      }}
                    />
                  </div>
                </div>
              ))}
            </Section>


            {/* THE TAG SETS WERE A SECTION HERE (owner 2026-09) and are the
                Tags tab's now, behind the pencil in the shelf of pills.
                Settings is for preferences; a tag set is library CONTENT,
                and the place to manage the row of them is the row of them. */}
          </div>
        ) : (
      <div className="mc-settings-page" style={{ flex: 1, padding: 20, display: "flex", flexDirection: "column", gap: 16, overflowY: "auto" }}>
        {/* Warnings first, above everything else on the Actions page. */}
        {showOffline && (
          <OfflineWarning variable={envOffline} onChanged={invalidate} boxRef={(el) => { warnRef.current = el; }} />
        )}
        {showToken && <TokenWarning onChanged={invalidate} />}

        {/* THE ACTIONS TOGGLE SITS WITH THE MODELS IT IS ABOUT. It was a
            section of General, one toggle away from the page that says what
            there is to set up — and what it hides is exactly the rows below.
            There is no "Models" heading above it any more: with its intro
            gone that was a title, a rule and a button over nothing, and the
            categories under it are the page's real sections. */}
        {/* SET UP ALL — one run over every plugin still needing setup, one
            restart at the end (the restart lives at the end of a run's
            command list, so chaining the scripts into one run is what buys
            the single restart). It rides the Actions section's HEADER, the
            same slot a category's Download all uses and in its quiet style —
            a row of its own left the width beside one button empty, which is
            the very shape DownloadAll's comment records removing. Hidden
            when nothing needs it. */}
        <Section
          title={t("Actions")}
          action={(() => {
            const needSetup = new Set(models
              .filter((m) => !m.deps_ok && m.setup_key)
              .map((m) => m.setup_key));
            if (needSetup.size === 0) return undefined;
            return (
              <button
                onClick={() => setHelp({
                  label: "all models", url: "", setup_key: "all" })}
                title={t("Run every model's setup in one go, with a single restart at the end")}
                style={{
                  flex: "0 0 auto", display: "flex", alignItems: "center", gap: 5,
                  height: 24, padding: "0 8px", borderRadius: "var(--r-3)",
                  border: "1px solid var(--border-strong)", background: "transparent",
                  color: "var(--accent)", fontSize: "var(--fs-2)", fontWeight: 600,
                  fontFamily: "inherit", cursor: "pointer",
                }}
              >
                <Icon name="terminal" size={14} />
                {`${t("Set up all")} (${needSetup.size})`}
              </button>
            );
          })()}
        >
          <ToggleRow
            label={t("Hide actions that need setting up")}
            checked={f.hide_unready_actions}
            onChange={(v) => setPref({ hide_unready_actions: v })}
            last
          />
        </Section>

        {/* One bordered list per model type (Upscaling, Captioning, …), each
            with a small category heading. Each model is a row (not its own card),
            like the General page's preference panels. `flexShrink: 0` keeps a
            panel at its content height: with `overflow: hidden` a flex item's
            min-height collapses to 0, which would let it compress and clip the
            bottom rows instead of letting the page scroll. */}
        {modelGroups.map(({ cat, items }) => (
          <Section
            key={cat}
            title={cat}
            action={
              <DownloadAll
                models={downloadable(items)}
                onStarted={() => setTimeout(invalidate, 300)}
                label={t("Download all")}
              />
            }
          >
              {items.map((m, i) => {
                const isFlorence = FLORENCE_KEYS.includes(m.key);
                // For the (single) Florence row, the checkpoint selector sits in
                // the row's header, alongside the download button.
                const florenceSelector = isFlorence ? (
                  <Select value={f.florence_model} options={FLORENCE_OPTIONS}
                          onChange={(v) => setPref({ florence_model: v })}
                          height={30} minWidth={0} title="Florence-2 checkpoint"
                          style={{ padding: "0 26px 0 10px" }} />
                ) : undefined;
                return (
                  <ModelCard
                    key={isFlorence ? "florence" : m.key} info={m} tokenAvailable={tokenAvailable}
                    offlineBlocked={!!envOffline}
                    highlighted={highlight === m.key}
                    last={i === items.length - 1}
                    containerRef={(el) => { cardRefs.current[m.key] = el; }}
                    path={f.model_paths[m.key] ?? ""}
                    onCommitPath={(v) => commitPath(m.key, v)}
                    onSetup={() => setHelp(m)}
                    headerExtra={florenceSelector}
                    onDownload={async () => { try { await api.downloadModel(m.key); invalidate(); } catch { /* shown in card */ } }}
                    onCancel={async () => { await api.cancelDownload(m.key); invalidate(); }}
                    onDelete={async () => { await api.deleteModelCache(m.key); invalidate(); }}
                  />
                );
              })}
          </Section>
        ))}
      </div>
        )}
      </div>
      {help && (
        <ModelHelpOverlay
          model={{ name: help.label, url: help.url, setup_key: help.setup_key }}
          onClose={() => setHelp(null)}
        />
      )}
    </Overlay>
  );
}



function ModelCard({
  info, path, tokenAvailable, offlineBlocked, highlighted, last, onCommitPath, onSetup, headerExtra, onDownload, onCancel, onDelete, containerRef,
}: {
  info: ModelCacheInfo;
  path: string;
  tokenAvailable: boolean;
  offlineBlocked: boolean;
  // Briefly highlighted after the Actions page was opened for this model (from a
  // download / enable-downloads chip), so the user can spot which one it was.
  highlighted?: boolean;
  // Last row in the list — no separator below it.
  last?: boolean;
  onCommitPath: (value: string) => void;
  onSetup: () => void;
  // Optional control rendered in the header row (e.g. the Florence checkpoint
  // selector), just left of the split download button.
  headerExtra?: React.ReactNode;
  onDownload: () => void;
  onCancel: () => void;
  onDelete: () => void;
  // Ref to the card's root, so Settings can scroll a just-triggered download
  // into view.
  containerRef?: (el: HTMLDivElement | null) => void;
}) {
  const t = useT();
  const lang = useLang();
  const [pathMode, setPathMode] = useState(!!path);
  const [pathVal, setPathVal] = useState(path);
  useEffect(() => { setPathVal(path); if (path) setPathMode(true); }, [path]);

  // No repo AND no fetcher = nothing to download: the model arrives with its
  // packages (Canny is OpenCV). Everything download-shaped is meaningless for
  // such a row. A plugin that fetches its own weights is NOT that: it has a
  // real download, just not from Hugging Face.
  const nothingToFetch = !info.repo && !info.fetchable;
  const cachedHub = info.cached && !info.local_path && !nothingToFetch;
  const gatedBlocked = info.gated && !tokenAvailable;
  // Downloading is blocked entirely while the environment forces offline —
  // except for a plugin fetching its own weights, which never goes near the hub.
  const blocked = (offlineBlocked || gatedBlocked) && !!info.repo;
  // The message shown left of the button when a download is blocked (only when a
  // download would be the relevant action: idle, deps present, not cached).
  // …and only for a hub download: offline mode and tokens are the hub's, and a
  // plugin fetching its own weights is subject to neither.
  const blockedMsg = (!pathMode && !info.cached && !info.downloading && info.deps_ok
                      && !!info.repo)
    ? (offlineBlocked ? "Enable downloads first" : gatedBlocked ? "Access token required" : "")
    // While it runs, the same slot carries the byte figures — a percentage
    // alone doesn't say whether "8%" is a minute away or an hour.
    : info.downloading ? downloadDetail(info.done_bytes, info.total_bytes, t, lang)
    : "";

  // The visual tone of the button's main (left) part by state; the chevron on
  // the right matches it.
  const tone = pathMode ? { bg: "transparent", color: "var(--muted)" }
    : info.downloading ? { bg: "transparent", color: "var(--accent)" }
    : !info.deps_ok ? { bg: "transparent", color: "var(--accent)" }
    : info.cached ? { bg: "transparent", color: "var(--green-text)" }
    : blocked ? { bg: "transparent", color: "var(--muted-2)" }
    : { bg: "var(--accent)", color: "var(--on-accent)" };  // ready to download

  // The main (left) part of the split button when not in local-path mode.
  const mainButton = () => {
    if (info.downloading)
      return <span style={{ ...mainBtn, cursor: "default", color: "var(--accent)" }}>
        <Icon name="progress_activity" size={15} spin />
        {info.queued ? "Waiting…"
          : info.progress >= 0 ? `${info.progress}%` : "Downloading…"}
      </span>;
    if (!info.deps_ok)
      // Not runnable yet (packages / dedicated env missing) — offer the setup
      // instructions instead of a dead "Unavailable" label. BEFORE the cached
      // branch: a model that is downloaded but not set up still cannot run,
      // and "Downloaded" was hiding the one button that gets it there.
      return <button
        onClick={onSetup}
        title="Show setup instructions for this model"
        style={{ ...mainBtn, cursor: "pointer", color: "var(--accent)" }}
      >
        <Icon name="help" size={15} /> Set up
      </button>;
    if (info.cached)
      return <span style={{ ...mainBtn, cursor: "default", color: "var(--green-text)" }}>
        <Icon name="check_circle" size={15} /> {nothingToFetch ? "Ready" : "Downloaded"}
      </span>;
    if (blocked)
      // Can't download right now (offline, or gated without a token) — dim it.
      return <span style={{ ...mainBtn, cursor: "default", color: "var(--muted-2)" }}
                   title={offlineBlocked ? "Enable downloads first" : "Set a Hugging Face token first"}>
        <Icon name="download" size={15} /> Download
      </span>;
    return <button
      onClick={onDownload}
      title="Download this model"
      style={{ ...mainBtn, cursor: "pointer", color: "var(--on-accent)", background: "var(--accent)" }}
    >
      <Icon name="download" size={15} /> Download
    </button>;
  };

  return (
    <div
      style={{
        ...card,
        borderBottom: last ? "none" : "1px solid var(--border-soft)",
        background: highlighted ? "var(--accent-dim)" : "transparent",
        boxShadow: highlighted ? "inset 0 0 0 2px var(--accent)" : "none",
        transition: "background 0.4s ease, box-shadow 0.4s ease",
      }}
      ref={containerRef}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {/* Name + optional blocked-status subtitle. The status is a subtitle here
            (not inline at the right) because a row with a picker + download button
            has no room for it — e.g. the Florence row. */}
        <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: "var(--fs-4)", fontWeight: 600, color: "var(--text-bright)" }}>{info.label}</span>
            {info.gated && <span style={badgeGated}>gated</span>}
            <a href={info.url} target="_blank" rel="noreferrer" title="Open model page" style={{ ...link, display: "flex", alignItems: "center" }}>
              <Icon name="open_in_new" size={14} />
            </a>
          </div>
          {/* VRAM chip sits under the name, in front of the subtitle (the minimum
              GPU memory to run the model — not its download size). */}
          {(info.vram || blockedMsg) && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
              {info.vram && <span style={badgeVram} title="Minimum GPU memory to run this model (not the download size)">{info.vram} VRAM</span>}
              {blockedMsg && <span className="mc-copy" style={{ fontSize: "var(--fs-2)", color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{blockedMsg}</span>}
            </div>
          )}
        </div>
        {/* Spacer pushes the button right; in path mode the field fills instead. */}
        {!pathMode && <span style={{ flex: 1 }} />}
        {headerExtra && <span style={{ marginLeft: 10, flex: "0 0 auto" }}>{headerExtra}</span>}

        {/* Split button: download / status / path field + chevron menu. When a
            picker (headerExtra) precedes it, drop the extra left margin so the
            two controls sit one row-gap apart and read as a single group. */}
        <SplitDownloadButton
          tone={tone}
          flex={pathMode ? 1 : "0 0 auto"}
          marginLeft={headerExtra ? 0 : 10}
          main={pathMode ? (
            <input
              value={pathVal}
              onChange={(e) => setPathVal(e.target.value)}
              onBlur={() => pathVal !== path && onCommitPath(pathVal.trim())}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
              placeholder={`Local path · e.g. ${info.repo}`}
              style={{ flex: 1, minWidth: 0, height: 30, padding: "0 10px", border: "none", outline: "none", background: "transparent", color: "var(--text)", fontFamily: "var(--mono)", fontSize: "var(--fs-2)" }}
            />
          ) : mainButton()}
          items={[
            info.downloading && { label: "Cancel download", icon: "close", onClick: onCancel },
            // Missing packages/env: the main button says "Set up" whether or
            // not the weights are cached, so the instructions are reachable
            // from the menu as well.
            !info.deps_ok && { label: "Setup instructions", icon: "help", onClick: onSetup },
            // Only a HUB-backed row: a plugin that fetches its own weights
            // (no `repo`) keeps them outside the cache, so a local path would
            // be written to a setting nothing reads and a delete would 404.
            !info.downloading && !nothingToFetch && !!info.repo && (pathMode
              ? { label: "Use downloaded model", icon: "cloud_download", onClick: () => { setPathMode(false); if (path) onCommitPath(""); } }
              : { label: "Use local path", icon: "folder_open", onClick: () => setPathMode(true) }),
            cachedHub && !!info.repo && !info.downloading && { label: "Delete download", icon: "delete", onClick: onDelete, danger: true },
            cachedHub && !!info.repo && !info.downloading && info.size > 0
              && { note: t("{size} on disk", { size: formatBytes(info.size, lang) }) },
          ]}
        />
      </div>

      {info.download_error && (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--red-text)", whiteSpace: "pre-wrap", overflowWrap: "anywhere", userSelect: "text", WebkitUserSelect: "text" }}>
          {info.download_error}
        </div>
      )}
    </div>
  );
}

const sectionLabel: React.CSSProperties = {
  ...SECTION_LABEL,
  // Copyable like every other name here — see `.mc-copy` in tokens.css. Spelled
  // out rather than classed because this is a style OBJECT several rows spread.
  userSelect: "text", WebkitUserSelect: "text",
};

// The section and its rows are the shared family (`shared/SettingsRows`).
const hint: React.CSSProperties = {
  fontSize: "var(--fs-2)", color: "var(--muted)", lineHeight: 1.55,
  userSelect: "text", WebkitUserSelect: "text",
};
const mono: React.CSSProperties = { fontFamily: "var(--mono)" };
const link: React.CSSProperties = { color: "var(--accent)", textDecoration: "none" };
// One row in the Models list (the surrounding panel supplies the frame; the
// per-row bottom border is applied inline so the last row can omit it).
const card: React.CSSProperties = {
  display: "flex", flexDirection: "column", gap: 9, padding: "13px 16px",
};
const warnBox: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "11px 12px",
  background: "var(--yellow-dim)", border: "1px solid var(--yellow-border)",
  borderRadius: "var(--r-6)", fontSize: "var(--fs-2)", lineHeight: 1.5, color: "var(--text-2)",
};
const warnBtn: React.CSSProperties = {
  flex: "0 0 auto", height: 32, padding: "0 12px", borderRadius: "var(--r-4)", border: "none",
  background: "var(--accent)", color: "var(--on-accent)", fontWeight: 600,
  fontSize: "var(--fs-3)", cursor: "pointer", whiteSpace: "nowrap",
};
const badgeGated: React.CSSProperties = chipStyle({ tone: "warn", size: "sm", upper: true });
// The estimated-VRAM badge sits right after the model name — a neutral chip so it
// reads as an informational spec, not a warning.
const badgeVram: React.CSSProperties = {
  fontSize: "var(--fs-0)", fontWeight: 600, letterSpacing: "0.02em",
  color: "var(--muted)", background: "var(--panel-3)",
  border: "1px solid var(--border)",
  padding: "1px 6px", borderRadius: "var(--r-1)", whiteSpace: "nowrap",
};

/** A section's "Download all", shown only while that section has something it
 *  could start.
 *
 *  It was ONE button for the page, in a heading row of its own above every
 *  category. Per section it is a different kind of control — you are looking
 *  at Captioning and want its four models, not the other thirty — so it is
 *  quiet rather than accent-filled: eight filled buttons down a page make the
 *  page look like a list of things to press. HIDDEN when the section has
 *  nothing left, since a dimmed button on every finished section is a column
 *  of dead controls saying what the rows beside them already say. */
function DownloadAll({ models, onStarted, label }: {
  models: ModelCacheInfo[];
  onStarted: () => void;
  label: string;
}) {
  if (models.length === 0) return null;
  return (
    <button
      onClick={() => {
        for (const m of models) void api.downloadModel(m.key).catch(() => undefined);
        onStarted();
      }}
      style={{
        flex: "0 0 auto", display: "flex", alignItems: "center", gap: 5,
        height: 24, padding: "0 8px", borderRadius: "var(--r-3)",
        border: "1px solid var(--border-strong)", background: "transparent",
        color: "var(--accent)", fontSize: "var(--fs-2)", fontWeight: 600,
        fontFamily: "inherit", cursor: "pointer",
      }}
    >
      <Icon name="download" size={14} />
      {`${label} (${models.length})`}
    </button>
  );
}
