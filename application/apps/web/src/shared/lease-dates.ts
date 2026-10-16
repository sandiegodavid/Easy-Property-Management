/** Lease boundaries are exclusive; this is the inclusive date shown to operators. */
export function leaseLastCoveredOn(exclusiveEnd: string | null): string | null {
  if (exclusiveEnd === null) return null;
  const date = new Date(`${exclusiveEnd}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}
