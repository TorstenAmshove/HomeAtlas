/**
 * Display-prefix check for the version shown under Settings -> Über, run by `npm run build`.
 * Plain Node with built-in type stripping (Node >= 22.18), no test framework needed.
 */
import { formatVersion } from "../src/lib/version.ts";

const cases: [string, string][] = [
  ["1.2.3", "v1.2.3"],
  ["10.20.30", "v10.20.30"],
  ["dev", "dev"],
  ["", ""],
  ["v1.2.3", "v1.2.3"],
  ["1.2.3-rc1", "1.2.3-rc1"],
  ["1.2.3+b", "1.2.3+b"],
];
const errors = cases
  .filter(([input, want]) => formatVersion(input) !== want)
  .map(([input, want]) => `formatVersion(${JSON.stringify(input)}) = ${JSON.stringify(formatVersion(input))}, expected ${JSON.stringify(want)}`);

if (errors.length > 0) {
  console.error(`check-version: ${errors.length} problem(s)\n  - ${errors.join("\n  - ")}`);
  process.exit(1);
}
console.log(`check-version: ${cases.length} cases ok`);
