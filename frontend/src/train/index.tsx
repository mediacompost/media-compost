/** The train package's one door.
 *
 * `app/training.tsx` is the only file allowed to import from this directory
 * (`boundaries.test.ts` holds it to that), and it does so through
 * `React.lazy` — so everything reachable from here is a chunk of its own,
 * fetched the first time a deployment that trains shows a training surface.
 */

export { TrainPages as default } from "./Pages";
export { TrainTabs } from "./Tabs";
