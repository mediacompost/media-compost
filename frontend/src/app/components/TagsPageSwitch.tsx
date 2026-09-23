/** THE TAGS TAB'S TWO PAGES, switched at the right end of the tag-set row:
 *  the list of names, and Faces (owner 2026-09 — Faces was a top-level tab
 *  until then). Drawn on BOTH pages in the same place, so the control that
 *  took you somewhere is where you look to go back. */
import React from "react";
import { SegmentedControl } from "../../shared/SegmentedControl";
import { useT } from "../i18n";
import { useUI, type TagsPage } from "../store";

export function TagsPageSwitch() {
  const t = useT();
  const page = useUI((s) => s.tagsPage);
  const setPage = useUI((s) => s.setTagsPage);
  return (
    <SegmentedControl<TagsPage>
      value={page} onChange={setPage}
      options={[
        { value: "tags", icon: "sell", label: t("Tags") },
        { value: "faces", icon: "face", label: t("Faces") },
      ]} />
  );
}
