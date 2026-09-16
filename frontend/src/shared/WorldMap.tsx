/**
 * WHERE ON EARTH — a coordinate pair, drawn.
 *
 * There is no map SERVICE here and there never will be: the app is
 * offline-first, so no tiles are fetched and nothing about a picture's
 * location leaves the machine. What it draws is the outline the app ships
 * (`worldLand.ts`, MIT, Robinson projection) with the point on it. That is
 * enough for the only question a small map answers — is this where I think it
 * is — and reading the numbers answers the rest.
 *
 * THE OUTLINE IS FETCHED LAZILY. It is 100 KB of path data, which has no
 * business in the main bundle for a field most libraries never fill in; a
 * dynamic import puts it in a chunk of its own, and until it lands the
 * graticule and the marker are already drawn. The module is cached by the
 * browser after the first map on the page.
 */
import React from "react";

import { project } from "./robinson";

/** The shipped outline's own coordinate space. Kept here as well as in the
 *  generated module so the first paint — before the chunk lands — is the same
 *  size as the one after it. */
const VB = { w: 2000, h: 857 };

let landPromise: Promise<string> | null = null;
function loadLand(): Promise<string> {
  if (!landPromise) {
    landPromise = import("./worldLand").then((m) => m.WORLD_LAND);
  }
  return landPromise;
}

/** Already loaded once? Then the first render can draw it, rather than
 *  flashing an empty ocean while a resolved promise settles. */
let landCache: string | null = null;

export interface MapPoint {
  lat: number;
  lon: number;
  /** Drawn dimmer and smaller — the places AROUND the one being looked at. */
  faint?: boolean;
  title?: string;
}

/**
 * @param height  The drawn height in px; the width follows the map's aspect.
 * @param zoom    1 shows the whole world. Above that the view is cropped to
 *                that factor around the first point — a country-sized look at
 *                a place, without a second projection or any new data.
 */
export function WorldMap({ points, height = 96, zoom = 1, onClick, title }: {
  points: MapPoint[];
  height?: number;
  zoom?: number;
  onClick?: () => void;
  title?: string;
}) {
  const [land, setLand] = React.useState<string | null>(landCache);
  React.useEffect(() => {
    if (land) return;
    let alive = true;
    void loadLand().then((d) => {
      landCache = d;
      if (alive) setLand(d);
    });
    return () => { alive = false; };
  }, [land]);

  const at = points.map((p) => ({ ...p, ...project(p.lon, p.lat) }));
  // The window: the whole map, or a crop around the first point. Clamped to
  // the map's own edges so a coastal point does not open onto blank space.
  const z = Math.max(1, zoom);
  const vw = VB.w / z;
  const vh = VB.h / z;
  const focus = at[0];
  const cx = focus ? focus.x : VB.w / 2;
  const cy = focus ? focus.y : VB.h / 2;
  const vx = Math.min(Math.max(cx - vw / 2, 0), VB.w - vw);
  const vy = Math.min(Math.max(cy - vh / 2, 0), VB.h - vh);
  const width = Math.round(height * (VB.w / VB.h));

  // The graticule, in map units: meridians and parallels every 30°, with the
  // equator and the prime meridian a shade stronger — they are what makes a
  // silhouette readable as a globe rather than as a shape.
  const lines: React.ReactNode[] = [];
  for (let lon = -180; lon <= 180; lon += 30) {
    lines.push(
      <path key={`m${lon}`} d={meridian(lon)}
            fill="none" stroke="var(--border)"
            strokeWidth={lon === 0 ? 2.5 : 1.5}
            opacity={lon === 0 ? 0.9 : 0.55}
            vectorEffect="non-scaling-stroke" />);
  }
  for (let lat = -60; lat <= 80; lat += 30) {
    const a = project(-180, lat);
    const b = project(180, lat);
    lines.push(
      <line key={`p${lat}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
            stroke="var(--border)" strokeWidth={lat === 0 ? 2.5 : 1.5}
            opacity={lat === 0 ? 0.9 : 0.55} vectorEffect="non-scaling-stroke" />);
  }

  return (
    <svg
      viewBox={`${vx} ${vy} ${vw} ${vh}`}
      width={width} height={height}
      onClick={onClick}
      role="img"
      style={{
        display: "block", borderRadius: 8, background: "var(--bg-deep)",
        border: "1px solid var(--border)", maxWidth: "100%",
        cursor: onClick ? "zoom-in" : "default",
      }}
    >
      {title && <title>{title}</title>}
      {land && (
        <path d={land} fill="var(--panel-3)" stroke="var(--border-strong)"
              strokeWidth={0.5} vectorEffect="non-scaling-stroke" />
      )}
      {lines}
      {at.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r={(p.faint ? 5 : 9) / z}
                  fill={p.faint ? "var(--muted-2)" : "var(--accent)"}
                  fillOpacity={p.faint ? 0.65 : 1}
                  stroke="var(--bg-deep)" strokeWidth={2 / z} />
          {p.title && <title>{p.title}</title>}
        </g>
      ))}
    </svg>
  );
}

/** A meridian is a CURVE in this projection — straight only at the equator —
 *  so it is drawn as a polyline through every 5° of latitude. */
function meridian(lon: number): string {
  const pts: string[] = [];
  for (let lat = -85; lat <= 85; lat += 5) {
    const p = project(lon, lat);
    pts.push(`${pts.length ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`);
  }
  return pts.join("");
}
