/**
 * Device-page helpers shared by the device page and its tabs
 * (pages/device/DevicePage.tsx). Pure functions over what `GET /api/systems/{id}` already returns.
 */

export const KINDS = [
  "router", "network", "server", "nas", "container", "vm", "pc", "mobile", "printer",
  "camera", "smarthome", "climate", "heating", "energy", "media", "iot", "other",
];
