// THE ONE `localStorage`. Thirty-five files each wrapped it in their own
// try/catch — or did not, and a private window threw on the first read —
// and each parsed its own number, its own "1"/"0", its own JSON. The
// try/catch lives here once, and the typed makers below say what a key
// holds and what its bounds are, beside the key.
export const storage = {
  get(key: string): string | null {
    try { return localStorage.getItem(key); } catch { return null; }
  },
  set(key: string, value: string): void {
    try { localStorage.setItem(key, value); } catch { /* a full or disabled store just means no memory */ }
  },
  remove(key: string): void {
    try { localStorage.removeItem(key); } catch { /* ignore */ }
  },
};

export interface Pref<T> {
  readonly key: string;
  read(): T;
  write(v: T): void;
  remove(): void;
}

/** A number, clamped to its bounds; anything unreadable is the default. */
export function numPref(key: string, { def, min = -Infinity, max = Infinity, integer = true }: {
  def: number; min?: number; max?: number; integer?: boolean;
}): Pref<number> {
  const clamp = (v: number) => Math.max(min, Math.min(max, integer ? Math.round(v) : v));
  return {
    key,
    read() {
      const raw = storage.get(key);
      if (raw === null || raw === "") return def;
      const v = Number(raw);
      return Number.isFinite(v) && v >= min && v <= max ? (integer ? Math.round(v) : v) : def;
    },
    write(v) { storage.set(key, String(clamp(v))); },
    remove() { storage.remove(key); },
  };
}

/** A boolean as "1"/"0". `inverted` keeps the keys whose "0" has always
 *  meant ON (the sidebar's open-branch flags), so nobody's setting resets. */
export function boolPref(key: string, def: boolean, { inverted = false } = {}): Pref<boolean> {
  return {
    key,
    read() {
      const raw = storage.get(key);
      if (raw === null) return def;
      return inverted ? raw !== "0" : raw === "1";
    },
    write(v) { storage.set(key, (inverted ? !v : v) ? "1" : "0"); },
    remove() { storage.remove(key); },
  };
}

/** A string, optionally from a closed list — anything else is the default. */
export function strPref<T extends string>(key: string, def: T, oneOf?: readonly T[]): Pref<T> {
  return {
    key,
    read() {
      const raw = storage.get(key);
      if (raw === null) return def;
      if (oneOf && !oneOf.includes(raw as T)) return def;
      return raw as T;
    },
    write(v) { storage.set(key, v); },
    remove() { storage.remove(key); },
  };
}

/** JSON, checked by `guard` — a shape that fails it is the default, never a
 *  half-typed object handed to the caller. */
export function jsonPref<T>(key: string, def: T, guard?: (v: unknown) => v is T): Pref<T> {
  return {
    key,
    read() {
      const raw = storage.get(key);
      if (raw === null) return def;
      try {
        const v = JSON.parse(raw) as unknown;
        return guard ? (guard(v) ? v : def) : (v as T);
      } catch { return def; }
    },
    write(v) { storage.set(key, JSON.stringify(v)); },
    remove() { storage.remove(key); },
  };
}

/** A family of keys under one prefix (`mc.sec.<section>`). */
export function prefixPref<T>(prefix: string, make: (key: string) => Pref<T>): (suffix: string) => Pref<T> {
  return (suffix) => make(prefix + suffix);
}
