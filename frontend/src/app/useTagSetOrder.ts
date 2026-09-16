/** The per-user preference behind the `?` popover's switcher, and the sets'
 *  display names — one query each, shared by every mark on screen.
 *
 *  `prefer(key)` writes the new order back with `setQueryData` first (the
 *  `SavedSearches` pattern), so every open popover reorders at once rather
 *  than after the round trip. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import { moveToFront } from "./tagSetOrder";

export function useTagSetOrder(): {
  keys: string[];
  /** Whether `keys` is the stored answer yet (an empty list before the
   *  first reply is "not loaded", not "no preference"). */
  loaded: boolean;
  prefer: (key: string) => void;
} {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["tag-set-order"],
    queryFn: () => api.tagSetOrder(),
    staleTime: 60_000,
  });
  const keys = data?.keys ?? [];
  const mutation = useMutation({
    mutationFn: (next: string[]) => api.putTagSetOrder(next),
    onSuccess: (res) => qc.setQueryData(["tag-set-order"], res),
  });
  return {
    keys,
    loaded: data != null,
    prefer: (key) => {
      const next = moveToFront(keys, key);
      qc.setQueryData(["tag-set-order"], { keys: next });
      mutation.mutate(next);
    },
  };
}

/** key -> display name for every tag set the library has. */
export function useTagSetNames(): Record<string, string> {
  const { data } = useQuery({
    queryKey: ["tag-sets"],
    queryFn: () => api.tagSets(),
    staleTime: 60_000,
  });
  const out: Record<string, string> = {};
  for (const ts of data ?? []) out[ts.key] = ts.name;
  return out;
}

/** key -> id, for the one thing a popover cannot do with a key: say which
 *  set to open in the Sets sub-tab. Reads the same cached list as
 *  `useTagSetNames`, so it costs nothing extra. */
export function useTagSetIds(): Record<string, number> {
  const { data } = useQuery({
    queryKey: ["tag-sets"],
    queryFn: () => api.tagSets(),
    staleTime: 60_000,
  });
  const out: Record<string, number> = {};
  for (const ts of data ?? []) out[ts.key] = ts.id;
  return out;
}
