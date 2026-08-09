/**
 * Runtime quality tiers for the 3D and motion layers.
 *
 * The product must be fully usable with zero WebGL and zero animation, so the
 * tier is a budget rather than a feature flag: every 3D surface has a defined
 * behaviour at each tier, down to a static fallback. `off` is a first-class
 * design target, not a degraded accident.
 *
 * Detection is a pure function over an environment snapshot so it can be tested
 * without a browser -- the same reason `sani_core` owns its own seams.
 */

export type QualityTier = "ultra" | "balanced" | "minimal" | "off";

export const QUALITY_TIERS: QualityTier[] = ["ultra", "balanced", "minimal", "off"];

export const QUALITY_STORAGE_KEY = "sani.quality";

export interface QualityEnvironment {
  /** `prefers-reduced-motion: reduce`. Forces `minimal` -- never `off`, because
   *  the user asked for less motion, not less product. */
  reducedMotion: boolean;
  /** `navigator.deviceMemory` in GB. `undefined` on browsers that hide it. */
  deviceMemory?: number;
  /** `navigator.hardwareConcurrency`. */
  hardwareConcurrency?: number;
  /** Coarse WebGL capability: 2 = WebGL2, 1 = WebGL1, 0 = none. */
  webglTier: 0 | 1 | 2;
  /** `navigator.connection.saveData`. Someone on a metered link does not want
   *  a shader field. */
  saveData?: boolean;
}

export const QUALITY_META: Record<QualityTier, { label: string; hint: string }> = {
  ultra: { label: "Ultra", hint: "Full 3D, post-processing, every effect" },
  balanced: { label: "Balanced", hint: "3D without post-processing" },
  minimal: { label: "Minimal", hint: "2D only, motion reduced" },
  off: { label: "Off", hint: "No 3D, no ambient motion" },
};

/**
 * Pick a tier from an environment snapshot.
 *
 * Ordering matters: explicit user signals (reduced motion, save-data) outrank
 * raw capability, because a fast machine whose owner asked for calm should get
 * calm.
 */
export function detectQualityTier(env: QualityEnvironment): QualityTier {
  if (env.webglTier === 0) return "off";
  if (env.reducedMotion || env.saveData) return "minimal";

  const memory = env.deviceMemory ?? 8;
  const cores = env.hardwareConcurrency ?? 8;

  if (memory <= 2 || cores <= 2) return "minimal";
  if (env.webglTier === 1 || memory <= 4 || cores <= 4) return "balanced";
  return "ultra";
}

/** Does this tier render any WebGL at all? */
export function allows3D(tier: QualityTier): boolean {
  return tier === "ultra" || tier === "balanced";
}

/** Does this tier run the ambient shader field behind the shell? */
export function allowsAmbient(tier: QualityTier): boolean {
  return tier === "ultra" || tier === "balanced";
}

/** Post-processing (bloom, depth of field) is Ultra only -- it is the single
 *  most expensive thing in the scene graph. */
export function allowsPostProcessing(tier: QualityTier): boolean {
  return tier === "ultra";
}

/** Read the live browser environment. Safe to call during SSR: returns the
 *  conservative `off`-producing snapshot rather than throwing. */
export function readEnvironment(): QualityEnvironment {
  if (typeof window === "undefined") {
    return { reducedMotion: false, webglTier: 0 };
  }

  const nav = navigator as Navigator & {
    deviceMemory?: number;
    connection?: { saveData?: boolean };
  };

  return {
    reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    deviceMemory: nav.deviceMemory,
    hardwareConcurrency: nav.hardwareConcurrency,
    webglTier: probeWebgl(),
    saveData: nav.connection?.saveData,
  };
}

/** One throwaway canvas, discarded immediately. Creating a context is the only
 *  honest way to know; feature-sniffing the UA string is not. */
function probeWebgl(): 0 | 1 | 2 {
  try {
    const canvas = document.createElement("canvas");
    if (canvas.getContext("webgl2")) return 2;
    if (canvas.getContext("webgl")) return 1;
    return 0;
  } catch {
    return 0;
  }
}

export function isQualityTier(value: unknown): value is QualityTier {
  return typeof value === "string" && (QUALITY_TIERS as string[]).includes(value);
}
