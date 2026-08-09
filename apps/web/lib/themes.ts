/**
 * The six themes.
 *
 * Values live in globals.css under [data-theme]; this module is the registry
 * the UI enumerates and the type the rest of the app narrows against.
 */

export type ThemeId = "void" | "nebula" | "aurora" | "solar" | "mono" | "daylight";

export const THEMES: ThemeId[] = ["void", "nebula", "aurora", "solar", "mono", "daylight"];

export const DEFAULT_THEME: ThemeId = "void";

export const THEME_STORAGE_KEY = "sani.theme";

export interface ThemeMeta {
  label: string;
  hint: string;
  /** Two swatch colours for the picker: base and chrome. */
  swatch: [string, string];
  dark: boolean;
}

export const THEME_META: Record<ThemeId, ThemeMeta> = {
  void: {
    label: "Void",
    hint: "Near-black. The default.",
    swatch: ["#08090d", "#6b7280"],
    dark: true,
  },
  nebula: {
    label: "Nebula",
    hint: "Deep indigo, higher drama.",
    swatch: ["#09071a", "#7d74b0"],
    dark: true,
  },
  aurora: {
    label: "Aurora",
    hint: "Teal-black. Agent violet pops hardest here.",
    swatch: ["#03100f", "#5f9ea3"],
    dark: true,
  },
  solar: {
    label: "Solar",
    hint: "Warm and low-blue, for late sessions.",
    swatch: ["#100b07", "#9a7d5c"],
    dark: true,
  },
  mono: {
    label: "Mono",
    hint: "Neutral chrome. Only agent, attention and risk carry hue.",
    swatch: ["#0a0a0a", "#6e6e6e"],
    dark: true,
  },
  daylight: {
    label: "Daylight",
    hint: "Light, and actually designed as one.",
    swatch: ["#fbfaf7", "#8b8578"],
    dark: false,
  },
};

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === "string" && (THEMES as string[]).includes(value);
}
