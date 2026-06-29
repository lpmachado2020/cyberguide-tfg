import { useCallback, useEffect, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "cg-theme";
const THEME_EVENT = "cg-theme-change";

function getSystemTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readStored(): ThemePreference {
  if (typeof window === "undefined") return "dark";
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (raw === "light" || raw === "dark" || raw === "system") return raw;
  return "dark";
}

function resolveTheme(pref: ThemePreference): "light" | "dark" {
  return pref === "system" ? getSystemTheme() : pref;
}

function applyTheme(pref: ThemePreference) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const resolved = resolveTheme(pref);
  root.classList.remove("light", "dark");
  root.classList.add(resolved);
  root.style.colorScheme = resolved;
  root.dataset.themePreference = pref;
}

export function useTheme() {
  const [theme, setThemeState] = useState<ThemePreference>(() => readStored());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const syncSystemTheme = () => {
      if (readStored() === "system") {
        setThemeState("system");
        applyTheme("system");
      }
    };

    if (media.addEventListener) media.addEventListener("change", syncSystemTheme);
    else media.addListener(syncSystemTheme);

    return () => {
      if (media.removeEventListener) media.removeEventListener("change", syncSystemTheme);
      else media.removeListener(syncSystemTheme);
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const syncTheme = () => setThemeState(readStored());
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) syncTheme();
    };

    window.addEventListener("storage", onStorage);
    window.addEventListener(THEME_EVENT, syncTheme);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(THEME_EVENT, syncTheme);
    };
  }, []);

  const setTheme = useCallback((next: ThemePreference) => {
    window.localStorage.setItem(STORAGE_KEY, next);
    setThemeState(next);
    applyTheme(next);
    window.dispatchEvent(new Event(THEME_EVENT));
  }, []);

  return { theme, setTheme } as const;
}
