// The Models tab: which base models Train and Evaluate can choose from.
//
// The three built-ins are the architectures the trainer has engines for; a
// user model is *more weights for one of those* — a community finetune from
// Hugging Face, or a folder/checkpoint on disk. It inherits its base's engine,
// native resolution and hyperparameters, so adding one needs only a name, the
// base it follows, and where the weights are.
import React, { useMemo, useState } from "react";
import { Chip } from "../shared/Chip";
import { IconButton } from "../shared/IconButton";
import { Button } from "../shared/Button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, TrainLoraSource, TrainModelSpec, UserLoraOut } from "./api";
import { Icon } from "../shared/Icon";
import { ask } from "../shared/ConfirmModal";
import { useLang, useT, useTn, type TnFn } from "./i18n";

/** The translator these row components take, like the rest of the chrome. */
type TFn = (s: string, vars?: Record<string, string>) => string;
import { inputStyle, Section } from "./FormRows";
import {
  SplitDownloadButton, SplitTone, downloadDetail, downloadSize, splitMainStyle,
} from "../shared/ModelDownloadButton";
import { OfflineWarning, TokenWarning } from "../shared/HfWarnings";
import { FieldLabel as Label, Overlay, fieldStyle as field } from "../shared/Overlay";
import {
  architectureLabel, byArchitectureLabel, groupByArchitecture, hubUrl,
  looksLikeLocalPath, nestUserModels,
} from "./util";

export function ModelsView() {
  const t = useT();
  const [mode, setMode] = useState<"models" | "loras">("models");
  // ADDING IS A BUTTON, NOT A SECTION. The form used to be the first thing on
  // the page — a permanently-open box of four fields above the list it adds
  // to, on a page you mostly come to in order to READ what is installed. It
  // is a dialog now, opened from the corner, and the same dialog is what a
  // row's pencil opens: one form, one set of rules, and the list is the page.
  const [adding, setAdding] = useState(false);
  return (
    <div style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "18px 22px" }}>
      <div style={{ maxWidth: 760, margin: "0 auto" }}>
        {/* Base models and LoRAs are both "weights you can pick later", but
            they are chosen in different places, so they get their own list. */}
        <div style={{ display: "flex", alignItems: "center", gap: 10,
                      marginBottom: 16 }}>
        <div style={{
          display: "flex", gap: 2, padding: 3,
          background: "var(--bg)", border: "1px solid var(--border)",
          borderRadius: "var(--r-5)", width: "fit-content",
        }}>
          {([["models", "Base models"], ["loras", "LoRAs"]] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setMode(k)}
              style={{
                display: "flex", alignItems: "center", gap: 6, height: 28,
                padding: "0 12px", borderRadius: "var(--r-3)", border: "none",
                fontSize: "var(--fs-3)", fontWeight: 600, cursor: "pointer",
                fontFamily: "inherit",
                background: mode === k ? "var(--accent-dim)" : "transparent",
                color: mode === k ? "var(--accent)" : "var(--muted)",
              }}
            >
              <Icon name={k === "models" ? "deployed_code" : "layers"} size={16} />
              {t(label)}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <Button variant="primary" size="md"
     onClick={() => setAdding(true)} style={{ flex: "0 0 auto" }}>
          <Icon name="add" size={16} />
          {mode === "models" ? t("Add model") : t("Add LoRA")}
        </Button>
        </div>
        {mode === "models"
          ? <BaseModels adding={adding} onCloseAdd={() => setAdding(false)} />
          : <LoraLists adding={adding} onCloseAdd={() => setAdding(false)} />}
      </div>
    </div>
  );
}

/** The repo id under a model's name — a link to its model page when it is
 *  one. The id IS the link text: an extra icon beside it would be a second
 *  thing to aim at for the same destination. */
function RepoLine({ repo, local }: { repo: string; local?: boolean }) {
  const t = useT();
  const url = hubUrl(repo, local);
  const style: React.CSSProperties = {
    fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 2,
    fontFamily: "var(--mono)", overflow: "hidden",
    textOverflow: "ellipsis", whiteSpace: "nowrap",
  };
  if (!url) return <div style={style}>{repo}</div>;
  return (
    <div style={style}>
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        title={t("Open this model's page on Hugging Face")}
        style={{ color: "inherit", textDecoration: "none" }}
        onMouseEnter={(e) => {
          e.currentTarget.style.textDecoration = "underline";
          e.currentTarget.style.color = "var(--accent)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.textDecoration = "none";
          e.currentTarget.style.color = "inherit";
        }}
      >
        {repo}
      </a>
    </div>
  );
}

function BaseModels({ adding, onCloseAdd }: {
  /** The page's Add button was pressed. */
  adding: boolean;
  onCloseAdd: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ["train-status"], queryFn: api.trainStatus,
    // Only while something is actually downloading — otherwise this page is
    // static and has no reason to poll.
    refetchInterval: (q) =>
      (q.state.data?.models ?? []).some((m) => m.downloading) ? 1200 : false,
  });
  const models = status?.models ?? [];
  // Only for the "Based on" dropdown: a user model declares which built-in
  // architecture its weights are. The LIST itself is grouped by architecture
  // rather than split built-in/user.
  const builtin = models.filter((m) => !m.user);

  const [label, setLabel] = useState("");
  const [base, setBase] = useState("sd15");
  const [repo, setRepo] = useState("");
  // Read off what was typed rather than asked with a dropdown — see
  // `looksLikeLocalPath`. Derived, so it cannot disagree with the field.
  const local = looksLikeLocalPath(repo);
  // Blank means "the architecture's own", which is what the placeholder shows.
  const [area, setArea] = useState("");
  const [error, setError] = useState("");
  // WHICH entry the form is editing, or null while it is adding one. The same
  // form does both: a second one alongside it would be four fields and their
  // rules written twice, and this way what you type into is the thing you
  // already know.
  const [editing, setEditing] = useState<string | null>(null);
  // The dialog is up while either is true. `editing` also SAYS which entry,
  // and `adding` is the page's button — one form, two ways in.
  const open = adding || editing != null;
  const startEdit = (m: TrainModelSpec) => {
    setEditing(m.key);
    setLabel(m.label || "");
    setBase(m.base || "sd15");
    setRepo(m.repo || "");
    setArea(m.default_area ? String(m.default_area) : "");
    setError("");
  };
  const stopEdit = () => {
    setEditing(null);
    onCloseAdd();
    setLabel(""); setBase("sd15"); setRepo(""); setArea("");
    setError("");
  };

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["train-status"] });
    qc.invalidateQueries({ queryKey: ["train-models"] });
  };
  const onChanged = invalidate;
  // What the picked architecture trains at, shown as the resolution field's
  // placeholder so "leave it empty" has a visible meaning.
  const baseArea = builtin.find((m) => m.key === base)?.default_area ?? 1024;
  const add = useMutation({
    mutationFn: () => api.trainAddModel({
      label, base, repo, local, area: Number(area) || 0,
    }),
    // Closes on success, as the edit does: a dialog that stayed open over an
    // empty form after adding one model reads as an add that did not happen.
    onSuccess: () => { stopEdit(); invalidate(); },
    onError: (e: unknown) => setError(String(e).replace(/^Error:\s*/, "")),
  });
  const save = useMutation({
    mutationFn: () => api.trainEditModel(editing as string, {
      label, base, repo, local, area: Number(area) || 0,
    }),
    onSuccess: () => { stopEdit(); invalidate(); },
    onError: (e: unknown) => setError(String(e).replace(/^Error:\s*/, "")),
  });
  const submit = () => (editing ? save.mutate() : add.mutate());
  const remove = useMutation({
    mutationFn: (key: string) => api.trainDeleteModel(key),
    onSuccess: invalidate,
  });
  const deleteWeights = useMutation({
    mutationFn: (key: string) => api.trainDeleteModelCache(key),
    onSuccess: invalidate,
  });

  /** Taking a model off the list ASKS, and asks the second question too.
   *
   *  Removing the entry and deleting the gigabytes it downloaded are two
   *  different acts: one is tidying a dropdown, the other is throwing away a
   *  download. Doing the first silently took the only handle on the second
   *  away — the weights stayed in the hub cache with nothing in the app
   *  listing them. So: confirm the removal, and when there is something on
   *  disk, offer to delete it as part of the same decision. */
  const removeUserModel = async (m: TrainModelSpec) => {
    // A local model's weights are wherever the user put them — this app did
    // not download them and has no business deleting them.
    const cached = m.cached && !m.local && !!m.repo;
    // ONE sheet with both answers where there is something on disk, rather
    // than two questions in a row: the second one used to be asked after the
    // first had already been said yes to.
    const r = await ask({
      title: t("Remove “{name}” from the model list?", { name: m.label || m.repo }),
      body: cached ? t("Its downloaded weights can go with it, or stay in the cache for a later download to find.") : undefined,
      plain: cached ? { label: t("Remove") } : undefined,
      answer: cached
        ? { label: t("Remove and delete weights"), danger: true }
        : { label: t("Remove"), danger: true },
    });
    if (r === null) return;
    const alsoWeights = cached && r === "answer";
    // THE CACHE GOES FIRST. Both endpoints are keyed on the model, so
    // removing the entry first takes the key the second one needs with it —
    // and the answer would be a 404 on weights nobody can see any more.
    const run = async () => {
      if (alsoWeights) await deleteWeights.mutateAsync(m.key);
      await remove.mutateAsync(m.key);
    };
    void run();
  };

  const offline = status?.env_offline ?? "";
  const tokenAvailable = status?.token_available ?? false;
  // A warning about downloading is only worth showing while something still
  // has to be downloaded (a local model's weights are already wherever the
  // user put them).
  const needsDownload = models.some((m) => !m.cached && !m.local);
  const row = (m: TrainModelSpec, child = false) => (
    <div key={m.key} style={{
      display: "flex", alignItems: "center", gap: 10,
      // A user model sits UNDER the built-in it is based on, indented, so
      // which parent it belongs to is visible rather than matched by eye —
      // and one line shorter, since it has no `note` of its own to carry.
      padding: child ? "7px 16px 7px 34px" : "10px 16px",
      borderBottom: "1px solid var(--border-soft)",
    }}>
      <Icon name={m.user ? (m.local ? "folder" : "cloud") : "deployed_code"}
            size={17} color="var(--muted)" />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)", display: "flex", alignItems: "center", gap: 6 }}>
          {m.label}
          {/* GATED: a licence to accept and a token to download with. The
              same chip the Settings model list shows, because it is the same
              fact — and without it the only sign was a download that failed
              with an authorization error. */}
          {m.gated && (
            <Chip tone="warn" size="sm" upper title={t("This model's repository is gated: accept its license on the model page and set a Hugging Face access token, or the download will fail.")} style={{ cursor: "help" }}>
              {t("gated")}
            </Chip>
          )}
          {m.lora_only && (
            <Chip size="sm" title={t("This architecture can only be trained as an adapter (LoRA or LoKr) alongside the frozen model. The \"Full finetune\" method, which rewrites the model's own weights, is not offered for it.")} style={{ cursor: "help" }}>
              {t("No full finetune")}
            </Chip>
          )}
        </div>
        <RepoLine repo={m.repo} local={m.local} />
        {/* What this one IS. With two releases of an architecture side by
            side (Chroma HD and Base) the labels alone do not say which to
            pick, and that is the question the page is being read to answer. */}
        {m.note && !child && (
          <div style={{
            fontSize: "var(--fs-2)", color: "var(--muted)", marginTop: 3, lineHeight: 1.45,
          }}>
            {t(m.note)}
          </div>
        )}
      </div>
      {/* No size here. The registry's `full_gb` is a full-finetune weight
          estimate, not what a download costs — it read "1.7 GB" beside a
          button that fetches 4.3 GB. The download itself reports its real
          size while it runs. */}
      <DownloadCell m={m} onChanged={onChanged} offline={offline}
                    tokenAvailable={tokenAvailable} />
      {m.user && (
        <IconButton icon="edit" size={26} glyph={15} color={editing === m.key ? "var(--accent)" : "var(--muted)"}
          title={t("Edit this model")}
          onClick={() => startEdit(m)} style={{ flex: "0 0 auto" }} />
      )}
      {m.user && (
        <IconButton icon="close" size={26} glyph={15} tone="muted"
          title={t("Remove this model")}
          onClick={() => removeUserModel(m)} style={{ flex: "0 0 auto" }} />
      )}
    </div>
  );

  return (
    <>
        {/* The same environment warnings the Settings models page shows —
            they are about the machine, not about one page's model list. */}
        {offline && needsDownload && (
          <div style={{ marginBottom: 14 }}>
            <OfflineWarning variable={offline} onChanged={invalidate} />
          </div>
        )}
        {!tokenAvailable && needsDownload && (
          <div style={{ marginBottom: 14 }}>
            <TokenWarning onChanged={invalidate} />
          </div>
        )}
        {/* THE FORM IS A DIALOG. It used to be the first thing on the page:
            a permanently-open box of four fields above the list it adds to,
            on a page whose job is mostly to say what is installed. The same
            dialog is what a row's pencil opens, so there is one form and one
            set of rules rather than a second copy for editing. */}
        {open && (
          <Overlay
            icon="deployed_code"
            title={editing ? t("Edit model") : t("Add model")}
            width={560}
            onClose={stopEdit}
            unsaved={{ dirty: !!repo.trim() || !!label.trim() || !!area.trim(),
                       onSave: submit, t }}
            footer={
              <>
                <Button variant="ghost" onClick={stopEdit}>{t("Cancel")}</Button>
                <Button variant="primary"
                  icon={editing ? "check" : "add"}
                  onClick={submit}
                  disabled={!repo.trim() || add.isPending || save.isPending}
                >
                  {editing ? t("Save") : t("Add model")}
                </Button>
              </>
            }
          >
          <div style={{ padding: 18, display: "flex", flexDirection: "column",
            gap: 16 }}>
            {/* A LABEL over a full-width field, the shape every other overlay
                in the app uses. What was here instead: two fields sharing a
                row with their questions in their placeholders, and the other
                two folded behind a "More" chevron — on the argument that a
                name is optional and the resolution has an answer already. But
                a collapsed field is one nobody finds while typing into the
                dialog it is in, and the edit path had to open the section by
                hand precisely because correcting those two is most of what an
                edit is FOR. Four labelled fields say what they are, and the
                two with sensible defaults say so in their placeholders. */}
            <div>
              <Label>{t("Based on")}</Label>
              {/* ALL the built-ins, in the same groups the list below uses, so
                  the thing you pick here is a model you can see there. It used
                  to be one option per inherited PROFILE, which collapsed
                  releases that differ (FLUX.2's 4B and 9B) into one line and
                  made the choice unanswerable from the page. */}
              <select
                value={base}
                onChange={(e) => setBase(e.target.value)}
                title={t("Which model these weights are a version of — it decides the engine, the hyperparameters and the memory profile")}
                style={{ ...field, cursor: "pointer" }}
              >
                {byArchitectureLabel(groupByArchitecture(builtin))
                  .map(([engine, group]) => (
                    <optgroup key={engine}
                              label={architectureLabel(engine, group)}>
                      {group.filter((m) => !m.user).map((m) => (
                        <option key={m.key} value={m.key}>{m.label}</option>
                      ))}
                    </optgroup>
                  ))}
              </select>
            </div>
            <div>
              <Label>{t("Weights")}</Label>
              <input
                value={repo}
                placeholder={t("owner/repo, or a path on this machine")}
                title={t("A Hugging Face repository, or a diffusers folder or .safetensors file on this machine — which one it is is read off what you type.")}
                onChange={(e) => setRepo(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && repo.trim()) submit(); }}
                style={field}
              />
              {/* WHICH OF THE TWO IT READ, said back rather than asked. The
                  dropdown that used to ask was a question whose answer was
                  already on screen — and getting it wrong was silent. */}
              {repo.trim() && (
                <div style={{ display: "flex", alignItems: "center", gap: 5,
                              marginTop: 6,
                              fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
                  <Icon name={local ? "folder" : "cloud"} size={13} />
                  {local ? t("Read as a path on this machine")
                         : t("Read as a Hugging Face repository")}
                </div>
              )}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
              gap: 10 }}>
              <div>
                <Label>{t("Name")}</Label>
                <input
                  value={label}
                  placeholder={t("optional")}
                  onChange={(e) => setLabel(e.target.value)}
                  title={t("Left unnamed, the model is listed under its repository or path")}
                  style={field}
                />
              </div>
              <div>
                <Label>{t("Resolution")}</Label>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <input
                    value={area}
                    inputMode="numeric"
                    placeholder={String(baseArea)}
                    title={t("Native training resolution of these weights. Leave empty for the architecture's own.")}
                    onChange={(e) => setArea(e.target.value.replace(/[^0-9]/g, ""))}
                    style={{ ...field, minWidth: 0 }}
                  />
                  <span style={{ flex: "0 0 auto", fontSize: "var(--fs-2)",
                    color: "var(--muted-2)" }}>{t("px")}</span>
                </div>
              </div>
            </div>
            {error && (
              <div style={{ fontSize: "var(--fs-2)", color: "var(--red-text)" }}>{error}</div>
            )}
          </div>
          </Overlay>
        )}

        {/* Grouped by ARCHITECTURE, not by who added it. What decides whether
            two entries are interchangeable — a LoRA trained on one applies to
            the other, they share an engine and the same memory constants — is
            the architecture; "built-in vs yours" is provenance, and it split
            Chroma's two releases from each other while putting SDXL beside
            FLUX.2. */}
        {/* ALPHABETICAL here, unlike the job editor's dropdown: this page is
            a list you come to with a name in mind, and the registry's own
            order is about which model to recommend rather than where to find
            one. */}
        {byArchitectureLabel(groupByArchitecture(models)).map(([engine, group]) => (
          <Section
            key={engine}
            label={architectureLabel(engine, group)}
            hint={architectureHint(group, tn)}
          >
            {nestUserModels(group).map(({ model, child }) => row(model, child))}
          </Section>
        ))}
    </>
  );
}

function architectureHint(group: TrainModelSpec[], tn: TnFn): string {
  const n = group.filter((m) => m.user).length;
  if (!n) return "";
  // One whole sentence per count — the old fragment concatenation
  // (`Includes` + n + `models you added.`) froze English word order into
  // every translation.
  return tn({ one: "Includes 1 model you added.",
              other: "Includes {n} models you added." }, n);
}

/** One row's weights state and the actions on it: download / resume / cancel,
 *  and removing what's on disk. A local model has no download story — its
 *  weights are wherever the user put them. */
function DownloadCell({ m, onChanged, offline, tokenAvailable }: {
  m: TrainModelSpec; onChanged: () => void; offline: string;
  tokenAvailable: boolean;
}) {
  const t = useT();
  const lang = useLang();
  const [error, setError] = useState("");

  const act = async (fn: () => Promise<unknown>) => {
    setError("");
    try { await fn(); } catch (e) { setError(String(e).replace(/^Error:\s*/, "")); }
    onChanged();
  };

  // A local model has no download story — its weights are wherever the user
  // put them — so it keeps a plain status instead of a download button.
  if (m.local) {
    return (
      <span style={{
        fontSize: "var(--fs-1)", fontWeight: 600, flex: "0 0 auto",
        color: m.cached ? "var(--green-text)" : "var(--red-text)",
        display: "flex", alignItems: "center", gap: 3,
      }}>
        <Icon name={m.cached ? "check_circle" : "error"} size={13} />
        {m.cached ? t("On disk") : t("Path missing")}
      </span>
    );
  }

  // Two things stop a download, and the row says WHICH: the environment
  // forcing offline mode, and a GATED repo with no access token — the same
  // pair the Settings models page blocks on, in the same words. The
  // page-level warnings say it once at the top; a gated row says it where the
  // button is, which is where somebody is about to press one and get an
  // authorization error instead.
  const gatedBlocked = !!m.gated && !tokenAvailable;
  const blocked = (!!offline || gatedBlocked) && !m.cached;
  // Same states, same tones as the Settings models page; "partial" is the one
  // this page adds (a download that stopped part-way and can be resumed).
  const tone: SplitTone = m.downloading ? { bg: "transparent", color: "var(--accent)" }
    : m.cached ? { bg: "transparent", color: "var(--green-text)" }
    : blocked ? { bg: "transparent", color: "var(--muted-2)" }
    : { bg: "var(--accent)", color: "var(--on-accent)" };

  const main = () => {
    if (m.downloading)
      return <span style={{ ...splitMainStyle, cursor: "default", color: "var(--accent)" }}>
        <Icon name="progress_activity" size={15} spin />
        {m.queued ? t("Waiting…")
          : (m.progress ?? -1) >= 0 ? `${m.progress}%` : t("Downloading…")}
      </span>;
    if (m.cached)
      return <span style={{ ...splitMainStyle, cursor: "default", color: "var(--green-text)" }}>
        <Icon name="check_circle" size={15} /> {t("Downloaded")}
      </span>;
    if (blocked)
      return <span
        style={{ ...splitMainStyle, cursor: "default", color: "var(--muted-2)" }}
        title={offline ? `${t("Downloads are switched off")} (${offline})`
          : t("This model's repository is gated: accept its license on the model page and set a Hugging Face access token, or the download will fail.")}
      >
        <Icon name="download" size={15} /> {m.partial ? t("Resume") : t("Download")}
      </span>;
    return <button
      onClick={() => act(() => api.trainDownloadModel(m.key))}
      title={m.partial
        ? t("Continue this download where it stopped")
        : t("Download this model")}
      style={{ ...splitMainStyle, cursor: "pointer", color: "var(--on-accent)", background: "var(--accent)" }}
    >
      <Icon name="download" size={15} /> {m.partial ? t("Resume") : t("Download")}
    </button>;
  };

  // Shown left of the button, like the Settings page's blocked subtitle: the
  // byte figures while it runs, WHAT IT TOOK once it is there, otherwise why
  // it can't run. The size is in `downloadSize`'s units rather than the
  // library's `formatBytes`, so a finished download reads in the same terms
  // the progress beside it just did.
  const msg = error || (m.queued ? t("Another download is running")
    : m.downloading ? downloadDetail(m.done_bytes, m.total_bytes, t, lang)
    : m.cached && (m.size ?? 0) > 0
      ? t("{size} on disk", { size: downloadSize(m.size ?? 0, lang) })
    : blocked ? (offline ? t("Enable downloads first") : t("Access token required"))
    : m.partial ? t("Partly downloaded") : "");

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 8, flex: "0 0 auto" }}>
      {msg && (
        <span style={{
          fontSize: "var(--fs-2)", color: error ? "var(--red-text)" : "var(--muted)",
          maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }} title={msg}>
          {msg}
        </span>
      )}
      <SplitDownloadButton
        tone={tone}
        main={main()}
        items={[
          m.downloading && {
            label: t("Cancel download"), icon: "close",
            onClick: () => act(() => api.trainCancelModelDownload(m.key)),
          },
          blocked && {
            label: t("Enable downloads"), icon: "cloud_off",
            onClick: () => act(() => api.clearOffline()),
          },
          !m.downloading && (m.cached || m.partial) && {
            label: m.cached ? t("Delete download") : t("Discard partial download"),
            icon: "delete", danger: true,
            onClick: () => act(() => api.trainDeleteModelCache(m.key)),
          },
        ]}
      />
    </span>
  );
}

/** The LoRAs sub-tab: files the user registered, and every checkpoint the
 *  training jobs produced. */
function LoraLists({ adding, onCloseAdd }: {
  adding: boolean;
  onCloseAdd: () => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ["train-status"], queryFn: api.trainStatus,
  });
  const { data: mine } = useQuery({
    queryKey: ["user-loras"], queryFn: api.trainUserLoras,
  });
  const { data: sources } = useQuery({
    queryKey: ["train-lora-sources"], queryFn: api.trainLoraSources,
  });
  const models = status?.models ?? [];
  const [label, setLabel] = useState("");
  const [base, setBase] = useState("sd15");
  const [path, setPath] = useState("");
  const [error, setError] = useState("");
  // The add form doubles as the edit form, as the model list's does — see
  // there for why there is not a second one.
  const [editing, setEditing] = useState<string | null>(null);
  const open = adding || editing != null;

  const invalidate = () => qc.invalidateQueries({ queryKey: ["user-loras"] });
  const stopEdit = () => {
    setEditing(null); onCloseAdd();
    setLabel(""); setBase("sd15"); setPath(""); setError("");
  };
  const add = useMutation({
    mutationFn: () => api.trainAddUserLora({ label, base, repo: path, local: true }),
    onSuccess: () => { stopEdit(); invalidate(); },
    onError: (e: unknown) => setError(String(e).replace(/^Error:\s*/, "")),
  });
  const save = useMutation({
    mutationFn: () => api.trainEditUserLora(editing as string, {
      label, base, repo: path, local: true,
    }),
    onSuccess: () => { stopEdit(); invalidate(); },
    onError: (e: unknown) => setError(String(e).replace(/^Error:\s*/, "")),
  });
  const submit = () => (editing ? save.mutate() : add.mutate());
  const startEdit = (lo: UserLoraOut) => {
    setEditing(lo.key);
    setLabel(lo.label || "");
    setBase(lo.model || "sd15");
    setPath(lo.path || "");
    setError("");
  };
  const remove = useMutation({
    mutationFn: (key: string) => api.trainDeleteUserLora(key),
    onSuccess: invalidate,
  });
  const delCkpt = useMutation({
    mutationFn: (v: { uid: string; step: number }) =>
      api.trainDeleteCheckpoint(v.uid, v.step),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["train-lora-sources"] }),
  });
  const lockCkpt = useMutation({
    // `step` null is the job's finished output, which locks too — see the
    // row's own comment for what a lock buys there.
    mutationFn: (a: { uid: string; step: number | null; locked: boolean }) =>
      a.step == null
        ? api.trainLockOutput(a.uid, a.locked)
        : api.trainLockCheckpoint(a.uid, a.step, a.locked),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["train-lora-sources"] });
    },
  });

  const modelLabel = (key: string) =>
    models.find((m) => m.key === key)?.label ?? key;

  // EVERY LoRA on this machine, grouped by ARCHITECTURE rather than by where
  // it came from. The two lists were "yours" and "from training jobs", which
  // is provenance — and the question this page is read to answer is which of
  // these will work on the model I am about to generate with.
  //
  // THE HEADING IS THE COARSE ANSWER, NOT THE RULE. What actually fits is
  // `adapterFamily`, which is narrower: two releases of one architecture can
  // be two different transformers (FLUX.2 Klein 4B and 9B, Chroma1 HD and
  // Base), and an adapter for one loads into the other with every key
  // rejected. So the heading gathers them and each row names the SPECIFIC
  // model it was trained for, which is the finer answer the heading cannot
  // give; the pickers that have to be right filter on `fitsModel`.
  const groups = useMemo(() => {
    const engineOf = (key: string) => {
      const m = models.find((x) => x.key === key);
      return m?.engine || m?.base || key;
    };
    type Entry = { engine: string; user?: UserLoraOut; job?: TrainLoraSource };
    const all: Entry[] = [
      ...(mine?.models ?? []).map((lo) => ({ engine: engineOf(lo.model), user: lo })),
      ...(sources?.loras ?? []).map((lo) => ({ engine: engineOf(lo.model), job: lo })),
    ];
    const by = new Map<string, Entry[]>();
    for (const e of all) {
      if (!by.has(e.engine)) by.set(e.engine, []);
      by.get(e.engine)!.push(e);
    }
    // Named and ordered by the same helpers the base-model list uses, so the
    // two halves of this page group and sort alike.
    return [...by.entries()]
      .map(([engine, list]) => {
        const group = models.filter(
          (m) => !m.user && (m.engine || m.base || m.key) === engine);
        return { engine, list, label: architectureLabel(engine, group) };
      })
      .sort((a, b) => a.label.localeCompare(b.label, undefined,
                                           { numeric: true, sensitivity: "base" }));
  }, [mine, sources, models]);

  return (
    <>
      {/* One dialog for adding and editing, opened from the page's button or
          a row's pencil — see the base-model list for why it is not a section
          standing open above the list. */}
      {open && (
        <Overlay
          icon="layers"
          title={editing ? t("Edit LoRA") : t("Add LoRA")}
          width={560}
          onClose={stopEdit}
          unsaved={{ dirty: !!path.trim() || !!label.trim(),
                     onSave: submit, t }}
          footer={
            <>
              <Button variant="ghost" onClick={stopEdit}>{t("Cancel")}</Button>
              <Button variant="primary"
                icon={editing ? "check" : "add"}
                onClick={submit}
                disabled={!path.trim() || add.isPending || save.isPending}
              >
                {editing ? t("Save") : t("Add LoRA")}
              </Button>
            </>
          }
        >
        <div style={{ padding: 18, display: "flex", flexDirection: "column",
          gap: 16 }}>
          {/* Labelled fields, the sibling dialog's shape and the app's — three
              bare inputs saying what they are only in their placeholders read
              as a form whose questions vanish as they are answered. */}
          <div>
            <Label>{t("File")}</Label>
            <input
              value={path}
              placeholder={t("/path/to/lora.safetensors")}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && path.trim()) submit(); }}
              style={field}
            />
          </div>
          <div>
            <Label>{t("Trained for")}</Label>
            <select
              value={base}
              onChange={(e) => setBase(e.target.value)}
              title={t("The base model this LoRA was trained for")}
              style={{ ...field, cursor: "pointer" }}
            >
              {models.map((m) => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
          </div>
          <div>
            <Label>{t("Name")}</Label>
            <input
              value={label}
              placeholder={t("defaults to the file name")}
              onChange={(e) => setLabel(e.target.value)}
              style={field}
            />
          </div>
          {error && <div style={{ fontSize: "var(--fs-2)", color: "var(--red-text)" }}>{error}</div>}
        </div>
        </Overlay>
      )}

      {groups.length === 0 && (
        <Section label={t("LoRAs")}>
          <div style={{ padding: "12px 16px", fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
            {t("No LoRAs yet — add a file above, or finish a training job.")}
          </div>
        </Section>
      )}
      {groups.map((g) => (
        <Section key={g.engine} label={g.label}
                 hint={t("These work on any model of this architecture. Each row says which one it was trained for.")}>
          {g.list.map((e) => (
            e.user
              ? <UserLoraRow key={`u-${e.user.key}`} lo={e.user} t={t}
                             modelLabel={modelLabel}
                             editing={editing === e.user.key}
                             onEdit={startEdit}
                             onRemove={(k) => remove.mutate(k)} />
              : <JobLoraRow key={`j-${e.job!.job_uid}-${e.job!.step ?? "final"}`}
                            lo={e.job!} t={t} modelLabel={modelLabel}
                            onDelete={(v) => delCkpt.mutate(v)}
                            onLock={(v) => lockCkpt.mutate(v)} />
          ))}
        </Section>
      ))}
    </>
  );
}

/** One LoRA the user registered by path. */
function UserLoraRow({ lo, t, modelLabel, editing, onEdit, onRemove }: {
  lo: UserLoraOut;
  t: TFn;
  modelLabel: (key: string) => string;
  /** This row is the one the form above is editing. */
  editing?: boolean;
  onEdit: (lo: UserLoraOut) => void;
  onRemove: (key: string) => void;
}) {
  return (
          <div key={lo.key} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "10px 16px",
            borderBottom: "1px solid var(--border-soft)",
          }}>
            <Icon name="layers" size={17} color="var(--muted)" />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)" }}>{lo.label}</div>
              <div style={{
                fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 2,
                fontFamily: "var(--mono)", overflow: "hidden",
                textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {lo.path}
              </div>
            </div>
            <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)", flex: "0 0 auto" }}>
              {t("for")} {modelLabel(lo.model)}
            </span>
            {!lo.exists && (
              <span title={t("This path no longer exists")}
                    style={{ display: "flex", color: "var(--red-text)", flex: "0 0 auto" }}>
                <Icon name="error" size={15} />
              </span>
            )}
            <IconButton icon="edit" size={26} glyph={15} color={editing ? "var(--accent)" : "var(--muted)"}
              title={t("Edit this LoRA")}
              onClick={() => onEdit(lo)} style={{ flex: "0 0 auto" }} />
            <IconButton icon="close" size={26} glyph={15} tone="muted"
              title={t("Remove from the list (the file is left alone)")}
              onClick={() => onRemove(lo.key)} style={{ flex: "0 0 auto" }} />
          </div>
  );
}

/** The padlock both LoRA rows carry. One component, because a lock means the
 *  same thing on either and the two titles are the only difference. */
function LockButton({ locked, on, off, onClick, t }: {
  locked: boolean;
  /** Titles: `on` while locked (what pressing it gives up), `off` while not. */
  on: string;
  off: string;
  onClick: () => void;
  t: TFn;
}) {
  return (
    <IconButton icon={locked ? "lock" : "lock_open"} size={26} glyph={15} color={locked ? "var(--accent)" : "var(--muted)"}
      title={locked ? on : off}
      aria-label={locked ? t("Unlock") : t("Lock")}
      onClick={onClick} style={{ flex: "0 0 auto" }} />
  );
}


/** One weight set a training job produced: its final output, or a checkpoint. */
function JobLoraRow({ lo, t, modelLabel, onDelete, onLock }: {
  lo: TrainLoraSource;
  t: TFn;
  modelLabel: (key: string) => string;
  onDelete: (v: { uid: string; step: number }) => void;
  onLock: (v: { uid: string; step: number | null; locked: boolean }) => void;
}) {
  return (
          <div key={`${lo.job_uid}-${lo.step ?? "final"}`} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "10px 16px",
            borderBottom: "1px solid var(--border-soft)",
          }}>
            <Icon name={lo.step == null ? "check_circle" : "radio_button_unchecked"}
                  size={15} color="var(--muted)" />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {lo.name}
              </div>
              <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 2, fontFamily: "var(--mono)" }}>
                {/* A job's finished result is not a checkpoint, and calling it
                    "step 7190" made it look like one that had lost its
                    buttons. It is the run's output — named as such, with the
                    step it ended on as context. */}
                {lo.step != null
                  ? `${t("step")} ${lo.step}`
                  : `${t("final")}${lo.final_step ? ` · ${lo.final_step} ${t("steps")}` : ""}`}
                {" · "}{modelLabel(lo.model)}
              </div>
            </div>
            {/* A step checkpoint is a file this tab can hand over or clear
                out; a job's finished result belongs to the job, so it is
                downloadable but has no delete of its own — deleting the job
                is what takes it away, and that is exactly what its LOCK is
                for. */}
            {lo.step == null && (
              <a
                href={api.trainOutputUrl(lo.job_uid)}
                title={t("Download this LoRA")}
                className="hoverable"
                style={{
                  flex: "0 0 auto", width: 26, height: 26, borderRadius: "var(--r-3)",
                  color: "var(--muted)", display: "flex", alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Icon name="download" size={15} />
              </a>
            )}
            {lo.step == null && (
              <LockButton locked={!!lo.locked} t={t}
                on={t("Unlock — deleting the job will take this LoRA with it")}
                off={t("Lock — keeps this LoRA when the job is deleted")}
                onClick={() => onLock({ uid: lo.job_uid, step: null,
                                        locked: !lo.locked })} />
            )}
            {lo.step != null && (
              <>
                <a
                  href={api.trainCheckpointUrl(lo.job_uid, lo.step)}
                  title={t("Download this checkpoint")}
                  className="hoverable"
                  style={{
                    flex: "0 0 auto", width: 26, height: 26, borderRadius: "var(--r-3)",
                    color: "var(--muted)", display: "flex", alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Icon name="download" size={15} />
                </a>
                {/* Locked = protected: no delete button, the trainer's
                    keep-last-N pruning skips it, and deleting the job keeps
                    it (as an entry in the list above). */}
                <LockButton locked={!!lo.locked} t={t}
                  on={t("Unlock — allows deleting again (and the keep-last rule may prune it)")}
                  off={t("Lock — protects this checkpoint from deletion, from the keep-last rule, and from the job being deleted")}
                  onClick={() => onLock({
                    uid: lo.job_uid, step: lo.step as number,
                    locked: !lo.locked,
                  })} />
                {!lo.locked && (
                  <IconButton icon="delete" size={26} glyph={15} tone="muted"
                    title={t("Delete this checkpoint from disk")}
                    onClick={() => onDelete({ uid: lo.job_uid, step: lo.step as number })} style={{ flex: "0 0 auto" }} />
                )}
              </>
            )}
          </div>
  );
}

