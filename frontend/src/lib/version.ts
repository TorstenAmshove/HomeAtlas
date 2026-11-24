/**
 * Display form of a version string. Release builds carry the raw `X.Y.Z` (build arg, `GET
 * /api/version`); only the display adds the `v`. Anything else (`dev`, empty, `v1.2.3`,
 * pre-release/build suffixes) is shown unchanged.
 */
export function formatVersion(raw: string): string {
  return /^\d+\.\d+\.\d+$/.test(raw) ? `v${raw}` : raw;
}
