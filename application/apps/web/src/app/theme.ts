type Appearance = "light" | "dark";
const appearanceKey = "epm.appearance";

export function preferredAppearance(fallback: Appearance): Appearance {
  try {
    const stored = localStorage.getItem(appearanceKey);
    return stored === "light" || stored === "dark" ? stored : fallback;
  } catch {
    return fallback;
  }
}

export function applyAppearance(appearance: Appearance) {
  document.documentElement.dataset.theme = appearance;
  try {
    localStorage.setItem(appearanceKey, appearance);
  } catch {
    // Appearance still applies when the browser does not allow persistent storage.
  }
}
