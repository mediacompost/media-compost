/**
 * How many device pixels the display packs into one CSS pixel.
 *
 * It is what "100%" has to mean in an image editor: one pixel of the picture
 * on one pixel of the screen. A browser measures in CSS pixels, so on a retina
 * display drawing an image at its pixel size makes it come out twice as large
 * as it is — which is what made 100% look like 200% here.
 *
 * Live, because the number changes under a window that is dragged to another
 * monitor or whose browser zoom is changed. `matchMedia` on the CURRENT ratio
 * is the standard way to hear about it: the query stops matching the moment
 * the ratio moves, and the listener re-arms on the new one.
 */
import { useEffect, useState } from "react";

export function devicePixelRatio(): number {
  const r = typeof window === "undefined" ? 1 : window.devicePixelRatio;
  return r && r > 0 ? r : 1;
}

export function useDevicePixelRatio(): number {
  const [dpr, setDpr] = useState(devicePixelRatio);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    let mq: MediaQueryList | null = null;
    let cancelled = false;
    const arm = () => {
      if (cancelled) return;
      const current = devicePixelRatio();
      setDpr(current);
      mq = window.matchMedia(`(resolution: ${current}dppx)`);
      // `change` fires once, when the ratio leaves the value it was armed on.
      mq.addEventListener("change", arm, { once: true });
    };
    arm();
    return () => { cancelled = true; mq?.removeEventListener("change", arm); };
  }, []);
  return dpr;
}
