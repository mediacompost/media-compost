// What each generated-artifact kind is CALLED, in one table.
//
// Two places name these: the item sidebar's nested rows under a source file
// (one artifact at a time, so the singular) and Settings → Storage (a whole
// type at once, so a count and the plural). They were about to be two tables
// of the same six words, which is how a "Depth map" in one view becomes a
// "Depth" in the other.
//
// A PURE module, and deliberately: the names reach `t()` as data rather than
// as literals, so the extractor in `i18nCoverage.test.ts` cannot see them —
// the table itself is the harvest, exactly as the grid's colour bands and the
// History verbs are.
import type { PluralSource } from "../shared/i18nCore";

export interface ArtifactKind {
  icon: string;
  name: PluralSource;
}

export const ARTIFACT_KINDS: Record<string, ArtifactKind> = {
  depth: { icon: "lens_blur",
           name: { one: "Depth map", other: "Depth maps" } },
  pose: { icon: "accessibility_new",
          name: { one: "Pose (OpenPose)", other: "Pose overlays (OpenPose)" } },
  canny: { icon: "line_style",
           name: { one: "Edge map (Canny)", other: "Edge maps (Canny)" } },
  lineart: { icon: "draw",
             name: { one: "Line art", other: "Line art" } },
  // Not an image: a VAE-encoded tensor a training run cached beside the file.
  // Listed because it lives in the item's folder and takes up its disk.
  latent: { icon: "dataset",
            name: { one: "Training latent", other: "Training latents" } },
  // A deliberately spoiled copy of the picture, cached by a training run that
  // trains on it alongside the original. Its own latents nest under it.
  degraded: { icon: "compress",
              name: { one: "Degraded copy", other: "Degraded copies" } },
};

/** The entry for `kind`, or one built from the kind itself.
 *
 *  A kind this build has never heard of is a real possibility — the table is
 *  the UI's, while the rows come from the library, which may have been
 *  written by a newer build — and showing its bare name beats showing
 *  nothing at all on a page about where the disk went. */
export function artifactKind(kind: string): ArtifactKind {
  return ARTIFACT_KINDS[kind]
    ?? { icon: "draft", name: { one: kind, other: kind } };
}
