export const homeRefreshChoices = [1, 5, 10, 15, 30] as const;
export type HomeRefreshMinutes = (typeof homeRefreshChoices)[number];
export const homeRefreshKey = "epm.home-refresh-minutes";

export function preferredHomeRefresh(): HomeRefreshMinutes {
  try {
    const value = Number(localStorage.getItem(homeRefreshKey));
    return homeRefreshChoices.find((minutes) => minutes === value) ?? 5;
  } catch {
    return 5;
  }
}

export function saveHomeRefresh(minutes: HomeRefreshMinutes): boolean {
  try {
    localStorage.setItem(homeRefreshKey, String(minutes));
    return true;
  } catch {
    return false;
  }
}
