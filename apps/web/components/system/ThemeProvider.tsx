"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  DEFAULT_THEME,
  THEME_STORAGE_KEY,
  isThemeId,
  type ThemeId,
} from "@/lib/themes";
import {
  QUALITY_STORAGE_KEY,
  detectQualityTier,
  isQualityTier,
  readEnvironment,
  type QualityTier,
} from "@/lib/quality";

interface AppearanceValue {
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
  quality: QualityTier;
  setQuality: (tier: QualityTier) => void;
  /** True until the client has read storage and probed the GPU. Consumers that
   *  mount WebGL must wait for this so SSR and the first paint agree. */
  resolving: boolean;
}

const AppearanceContext = createContext<AppearanceValue | null>(null);

/**
 * Runs before paint to stamp the stored theme on <html>.
 *
 * Without this the first frame renders in the default theme and then snaps,
 * which is the classic flash-of-wrong-theme. It is inline and synchronous on
 * purpose -- a React effect is already too late.
 */
export const THEME_BOOTSTRAP_SCRIPT = `
(function(){
  try {
    var t = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
    var valid = ["void","nebula","aurora","solar","mono","daylight"];
    document.documentElement.dataset.theme =
      valid.indexOf(t) >= 0 ? t : ${JSON.stringify(DEFAULT_THEME)};
    var q = localStorage.getItem(${JSON.stringify(QUALITY_STORAGE_KEY)});
    if (q) document.documentElement.dataset.quality = q;
  } catch (e) {}
})();
`;

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeId>(DEFAULT_THEME);
  // Start at "off": no WebGL mounts until we have actually probed. Guessing high
  // and correcting down would spike a weak machine on first paint.
  const [quality, setQualityState] = useState<QualityTier>("off");
  const [resolving, setResolving] = useState(true);

  useEffect(() => {
    let storedTheme: string | null = null;
    let storedQuality: string | null = null;
    try {
      storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
      storedQuality = localStorage.getItem(QUALITY_STORAGE_KEY);
    } catch {
      /* private browsing: fall through to defaults */
    }

    setThemeState(isThemeId(storedTheme) ? storedTheme : DEFAULT_THEME);
    setQualityState(
      isQualityTier(storedQuality) ? storedQuality : detectQualityTier(readEnvironment()),
    );
    setResolving(false);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    if (resolving) return;
    document.documentElement.dataset.quality = quality;
  }, [quality, resolving]);

  const setTheme = useCallback((next: ThemeId) => {
    setThemeState(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* storage unavailable; in-memory state still updates */
    }
  }, []);

  const setQuality = useCallback((next: QualityTier) => {
    setQualityState(next);
    try {
      localStorage.setItem(QUALITY_STORAGE_KEY, next);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const value = useMemo(
    () => ({ theme, setTheme, quality, setQuality, resolving }),
    [theme, setTheme, quality, setQuality, resolving],
  );

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

export function useAppearance(): AppearanceValue {
  const value = useContext(AppearanceContext);
  if (!value) throw new Error("useAppearance must be used inside <ThemeProvider>");
  return value;
}
