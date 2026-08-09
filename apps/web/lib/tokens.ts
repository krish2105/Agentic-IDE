"use client";

/**
 * Read a design token's computed value.
 *
 * WebGL and xterm need real colour values, not CSS variable references, so
 * anything outside the DOM has to resolve tokens itself. Going through this
 * helper (rather than hardcoding hexes in a scene) is what keeps 3D surfaces
 * theme-aware for free.
 */
export function readToken(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Resolve several at once. */
export function readTokens<K extends string>(
  spec: Record<K, string>,
): Record<K, string> {
  const out = {} as Record<K, string>;
  for (const key of Object.keys(spec) as K[]) {
    out[key] = readToken(key, spec[key]);
  }
  return out;
}
