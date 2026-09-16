/** What a session overlay's BODY shows — one rule for the tag batch and the
 *  tag grid, which were each deciding it inline and both got it wrong the
 *  same way.
 *
 *  Both used to read "nothing queued and a pool of 0" as EXHAUSTED and put
 *  the summary up — and that is exactly the state a session is in from the
 *  moment Start is pressed until the first reply lands, since the pool's
 *  figure is what that reply carries. On a scope of a few thousand pictures
 *  the reply is back before the frame is painted; on sixty thousand it is
 *  not, and the session opened on "Nothing decided yet · 0 left in the
 *  pool" for as long as the server took — or forever, when the fetch failed,
 *  because nothing caught it. Neither state is "exhausted": one is a
 *  question still being asked and the other is a question that got no
 *  answer.
 *
 *  So a fetch in flight or a failed one is named before anything else is
 *  inferred, a picture on screen is a picture on screen whatever else is
 *  going on, and "exhausted" is what is LEFT: nothing queued, nothing in
 *  flight, nothing failed. The pool's figure says nothing here — it is
 *  `null` until the first reply and the header simply omits it then.
 */

export type SessionBody = "loading" | "error" | "card" | "exhausted";

export interface SessionState {
  /** A fetch is in flight. */
  loading: boolean;
  /** The last fetch failed and nothing has succeeded since. */
  failed: boolean;
  /** How many pictures the session holds, the one on screen included. */
  queued: number;
}

export function sessionBody(s: SessionState): SessionBody {
  if (s.queued > 0) return "card";
  if (s.failed) return "error";
  if (s.loading) return "loading";
  return "exhausted";
}
