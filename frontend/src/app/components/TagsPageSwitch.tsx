/** THE TAGS TAB'S TWO PAGES, switched at the right end of the tag-set row:
 *  the list of names, and Faces (owner 2026-09 — Faces was a top-level tab
 *  until then). Drawn on BOTH pages in the same place, so the control that
 *  took you somewhere is where you look to go back.
 *
 *  Absent, not disabled, where the deployment hides Faces (Settings →
 *  Faces): the rule the top bar kept for the tab, and a switch with one
 *  position is not a switch. `?? false` shows it while the setting loads. */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { SegmentedControl } from "../../shared/SegmentedControl";
import { api } from "../api";
import { useT } from "../i18n";
import { useUI, type TagsPage } from "../store";

/** Whether this deployment offers Faces at all. */
export function useFacesHidden(): boolean {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  return data?.hide_faces_tab ?? false;
}

export function TagsPageSwitch() {
  const t = useT();
  const page = useUI((s) => s.tagsPage);
  const setPage = useUI((s) => s.setTagsPage);
  if (useFacesHidden()) return null;
  return (
    <SegmentedControl<TagsPage>
      value={page} onChange={setPage}
      options={[
        { value: "tags", icon: "sell", label: t("Tags") },
        { value: "faces", icon: "face", label: t("Faces") },
      ]} />
  );
}
