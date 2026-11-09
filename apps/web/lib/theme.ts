/** Theme preference: "system" follows prefers-color-scheme; "light"/"dark" pin it via <html data-theme>. */
export type ThemePref = "light" | "dark" | "system";

export const THEME_KEY = "signal-theme";
export const THEME_COLORS = { light: "#eeeff2", dark: "#07080a" } as const;

export function isThemePref(v: unknown): v is ThemePref {
  return v === "light" || v === "dark" || v === "system";
}

export function readThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return isThemePref(v) ? v : "system";
  } catch {
    return "system";
  }
}

/** Applies a preference to the document: data-theme attribute and the browser chrome colour. */
export function applyTheme(pref: ThemePref) {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((m) => {
    const media = m.getAttribute("data-media") ?? m.media;
    if (!m.hasAttribute("data-media")) m.setAttribute("data-media", media);
    if (pref === "system") {
      m.media = media;
      m.content = media.includes("dark") ? THEME_COLORS.dark : THEME_COLORS.light;
    } else {
      m.media = "all";
      m.content = THEME_COLORS[pref];
    }
  });
}

export function saveThemePref(pref: ThemePref) {
  try {
    if (pref === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, pref);
  } catch {
    /* storage blocked: the choice lasts for this page only */
  }
  applyTheme(pref);
}

/** Runs in <head> before first paint so a pinned theme never flashes the OS one. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(THEME_KEY)});if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})();`;
