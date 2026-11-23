// Thin typed wrapper around the backend. Every call goes through `request`, so the session-expiry
// and error-message handling exists in exactly one place.

export class ApiError extends Error {
  constructor(public status: number, message: string, public mfaRequired = false) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    // Session lives in an httpOnly cookie; without this it is never sent.
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      // FastAPI puts validation errors in `detail` as an array; flatten so the UI never renders
      // "[object Object]" at the user.
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: any) => d.msg).join(", ");
    } catch {
      /* keep the status line */
    }
    const mfaHeader = response.headers.get("X-HomeAtlas-MFA");
    if (mfaHeader === "enrollment-required") {
      // The account's second factor was reset (by an admin) while this session was open
      // elsewhere. A reload re-fetches /me and lets App.tsx route into the enrollment screen,
      // instead of every subsequent action in this tab just failing with a confusing 403.
      window.location.reload();
    }
    throw new ApiError(response.status, detail, mfaHeader === "required");
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const patch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const put = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

// ---------------------------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------------------------

export type Role = "ADMIN" | "MEMBER";

export interface User {
  id: string;
  username: string;
  role: Role;
  displayName: string;
  totpEnabled: number;
  createdAt: string;
}

export interface AccessLogEntry {
  id: string;
  at: string;
  userId: string | null;
  username: string;
  action: string;
  detail: string;
  ip: string;
  userAgent: string;
  ok: number;
}

export interface MonitorEvent {
  id: string;
  systemId: string;
  systemName: string | null;
  at: string;
  status: string;
  detail: string;
}

export interface MonitorSystem {
  id: string;
  name: string;
  ip: string;
  kind: string;
  status: string;
  importance: string;
  lastSeen: string;
  ports: number[];
  /** Container without ports: the ping only proves the host is up. */
  hostOnly?: boolean;
}

export interface MonitorState {
  enabled: boolean;
  intervalSeconds: number;
  status: { running: boolean; lastRun: number; lastError: string };
  systems: MonitorSystem[];
  events: MonitorEvent[];
}

export interface DnsResult {
  servers: string[];
  results: { name: string; resolved: boolean; addresses: string[]; elapsedMs: number; explanation: string }[];
  resolvedCount: number;
  totalCount: number;
  explanation: string;
  serversExplanation: string;
}

export interface SpeedtestResult {
  ok: boolean;
  error: string;
  downloadMbps: number | null;
  uploadMbps: number | null;
  pingMs: number | null;
  explanation: string;
}

export interface PasswordPolicy {
  minLength: number;
  passphraseLength: number;
  rules: string[];
}

export interface ServiceInfo {
  port: number;
  service: string;
  explanation: string;
}

export interface System {
  id: string;
  kind: string;
  name: string;
  hostname: string;
  ip: string;
  mac: string;
  vendor: string;
  model: string;
  os: string;
  location: string;
  purpose: string;
  descriptionMd: string;
  url: string;
  docUrl: string;
  docLink: string;
  notes: string;
  importance: "critical" | "normal" | "low";
  parentId: string | null;
  status: "online" | "offline" | "unknown";
  discovered: number;
  confirmed: number;
  discoverySource: string;
  monitored: number;
  monitorPorts: number[] | null;
  openPorts: number[] | null;
  services: ServiceInfo[] | null;
  tags: string[] | null;
  extra: Record<string, any> | null;
  firstSeen: string;
  lastSeen: string;
  updatedAt: string;
  accountCount?: number;
  /** Number of logged scan-time failures for this device (SSH timeout, Proxmox auth error, a
   * monitored device going down, ...) -- see GET /api/systems/{id}/errors for the full list. */
  errorCount?: number;
  /** Server-derived "what is this for" sentence; falls back to the kind when nothing is stored. */
  description?: string;
}

export interface DeviceErrorEvent {
  id: string;
  systemId: string;
  level: "error" | "warning" | "info";
  message: string;
  createdAt: string;
  /** null = open; only open events count toward the inventory badge. */
  acknowledgedAt: string | null;
}

export interface Account {
  id: string;
  systemId: string | null;
  label: string;
  category: string;
  username: string;
  url: string;
  notes: string;
  allowProbe: number;
  port: number;
  updatedAt: string;
  hasSecret: boolean;
  hasPassphrase: boolean;
  /** Number of group/multi-device targets (see AccountAssignment) beyond the single system
   *  `systemId` points at. Only populated by GET /accounts (the accounts list); absent from
   *  responses scoped to one system's own accounts, which don't need it. */
  assignmentCount?: number;
  /** True when this account reaches the device only through an AccountAssignment rule
   *  (kind/subnet/extra system), not through its own `systemId`. Only populated by
   *  GET /systems/{id} (the device page's own account list); absent everywhere else. */
  viaAssignment?: boolean;
}

export interface NetworkResource {
  id: string;
  kind: "network" | "wifi" | "wan";
  source: string;
  sourceAccountId: string;
  ownerSystemId: string | null;
  siteExternalId: string;
  siteName: string;
  externalId: string;
  name: string;
  enabled: number;
  active: number;
  facts: Record<string, any>;
  manualMd: string;
  firstSeen: string;
  lastSeen: string;
  updatedAt: string;
}

/** One group/multi-device target a credential profile additionally applies to, beyond its own
 *  `systemId` -- e.g. every device of a given kind ("router"), a subnet, or a further specific
 *  system. Resolved automatically at scan time (see the backend's db.list_probe_accounts) -- a
 *  device never needs the credential directly attached to be probed with it. */
export interface AccountAssignment {
  id: string;
  accountId: string;
  targetType: "system" | "kind" | "subnet";
  targetValue: string;
  createdAt: string;
}

export interface DocVersion {
  id: string;
  slug: string;
  title: string;
  generated: number;
  reason: string;
  createdAt: string;
  size: number;
  bodyMd?: string;
  manualMd?: string;
}

export interface ApiToken {
  id: string;
  label: string;
  createdAt: string;
  lastUsedAt: string | null;
  /** Only present in the response right after creation — never returned by the list endpoint. */
  token?: string;
}

export interface ConfigVersion {
  id: string;
  systemId: string;
  label: string;
  source: string;
  createdAt: string;
  size: number;
  /** Only present when fetched via getConfigVersion — the list endpoint omits it. */
  content?: string;
}

export interface ProbeFact {
  label: string;
  value: string;
}

export interface ProbeResult {
  ok: boolean;
  error: string;
  /** Failure next to a working credential of the same kind (ssh/snmp/ha/http). */
  superseded?: boolean;
  facts: Record<string, ProbeFact>;
}

export interface ProbeOutcome {
  ran: boolean;
  results: Record<string, ProbeResult>;
  purpose?: string;
  reason: string;
}

export interface DocPage {
  id: string;
  slug: string;
  topic: string;
  title: string;
  bodyMd: string;
  /** Own notes — never touched by generation. */
  manualMd: string;
  intro: string;
  generated: number;
  sortOrder: number;
  updatedAt: string;
}

export interface Scan {
  id: string;
  startedAt: string;
  finishedAt: string | null;
  status: "running" | "completed" | "failed";
  subnets: string;
  progress: number;
  phase: string;
  summary: Record<string, any> | null;
  log?: string;
}

export interface ChatMessage {
  id: string;
  chatId: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  /** How long the whole turn (every tool round-trip included) took to produce this message.
   *  Only ever set on the final assistant answer of a turn -- null for user messages and for the
   *  optimistic local echo, which never round-trips through the backend. */
  durationMs: number | null;
}

export interface Chat {
  id: string;
  title: string;
  /** Owner; null for conversations from before ownership existed (ADMIN-only). */
  userId?: string | null;
  createdAt: string;
  updatedAt: string;
}

/** Slim on purpose: MEMBER never gets the scan log/summary. */
export interface LastScan {
  startedAt: string;
  finishedAt: string | null;
  status: "running" | "completed" | "failed";
}

export interface Dashboard {
  homeName: string;
  counts: {
    total: number;
    online: number;
    critical: number;
    accounts: number;
  };
  byKind: Record<string, number>;
  kindLabels: Record<string, string>;
  criticalSystems: (System & { monitorPortsEffective?: number[] })[];
  lastScan: LastScan | null;
  llmConfigured: boolean;
  monitorEnabled: boolean;
  monitorIntervalSeconds: number;
}

export interface ModelOption {
  id: string;
  label: string;
  price_tier: string;
}

export interface SettingsResponse {
  settings: Record<string, any>;
  providers: Record<string, string>;
  catalog: Record<string, ModelOption[]>;
  ouiLoaded: boolean;
  ouiEntries: number;
  dockerAvailable: boolean;
}

export interface DiagnosticResult {
  explanation: string;
  [key: string]: any;
}

// ---------------------------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------------------------

export type DuplicateReason = "hostname" | "selfName";
export interface DuplicateCandidate {
  aId: string; bId: string; aName: string; bName: string; reasons: DuplicateReason[];
}
export interface SystemAlias { aliasKey: string; ip: string; mac: string; createdAt: string }

export interface ExposureEntry {
  host: string;
  scope: "extern" | "intern" | "portforward";
  via: string;
  status: string;
  mtls: boolean;
}

export const DUPLICATE_REASON_LABEL: Record<DuplicateReason, string> = {
  hostname: "gleicher Hostname",
  selfName: "gleicher selbstgemeldeter Name",
};

export const api = {
  version: () => get<{ version: string }>("/version"),
  health: () => get<{ status: string; setupCompleted: boolean }>("/health"),

  login: (username: string, password: string, totpCode = "") =>
    post<{ user: User }>("/auth/login", { username, password, totpCode }),
  passwordPolicy: () => get<PasswordPolicy>("/auth/password-policy"),
  mfaSetup: () => post<{ secret: string; uri: string; qrSvg: string }>("/auth/mfa/setup"),
  mfaConfirm: (code: string) => post<{ ok: boolean }>("/auth/mfa/confirm", { code }),
  logout: () => post<{ ok: boolean }>("/auth/logout"),
  me: () => get<{ user: User }>("/auth/me"),
  changePassword: (currentPassword: string, newPassword: string) =>
    post<{ ok: boolean }>("/auth/password", { currentPassword, newPassword }),

  listUsers: () => get<{ users: User[] }>("/users"),
  createUser: (body: { username: string; password: string; role: Role; displayName: string }) =>
    post<{ user: User }>("/users", body),
  updateUser: (id: string, body: { displayName?: string; role?: Role; newPassword?: string }) =>
    patch<{ user: User; changes: string[] }>(`/users/${id}`, body),
  deleteUser: (id: string) => del<{ ok: boolean }>(`/users/${id}`),
  resetUserMfa: (id: string) => post<{ user: User }>(`/users/${id}/mfa/reset`),

  accessLog: (params: { limit?: number; action?: string; onlyFailures?: boolean } = {}) => {
    const query = new URLSearchParams();
    if (params.limit) query.set("limit", String(params.limit));
    if (params.action) query.set("action", params.action);
    if (params.onlyFailures) query.set("onlyFailures", "true");
    return get<{ entries: AccessLogEntry[]; actions: string[] }>(`/access-log?${query}`);
  },

  monitor: () => get<MonitorState>("/monitor"),
  monitorRunNow: () => post<{ changes: { systemId: string; name: string; status: string }[] }>("/monitor/run"),
  dnsCheck: (names?: string[]) => post<{ result: DnsResult }>("/diagnostics/dns", names ? { names } : {}),
  speedtest: () => post<{ result: SpeedtestResult }>("/diagnostics/speedtest", {}),

  getSettings: () => get<SettingsResponse>("/settings"),
  /** Secrets are never cleared by an empty value; name them in `clearSecrets` to remove them. */
  updateSettings: (patchBody: Record<string, any> & { clearSecrets?: string[] }) =>
    patch<{ settings: Record<string, any> }>("/settings", patchBody),
  testLlm: (provider: string, settings: Record<string, any>) =>
    post<{ ok: boolean; message: string; model: string }>("/settings/llm/test", { provider, settings }),
  refreshModels: (provider: string, settings: Record<string, any>) =>
    post<{ ok: boolean; message: string; models: ModelOption[]; persisted: boolean }>("/settings/llm/models", { provider, settings }),
  refreshOui: () => post<{ ok: boolean; message: string; entries: number }>("/settings/oui/refresh"),

  listSystems: (kind?: string) =>
    get<{ systems: System[]; kindLabels: Record<string, string> }>(`/systems${kind ? `?kind=${kind}` : ""}`),
  getSystem: (id: string) =>
    get<{ system: System; accounts: Account[]; description: string; monitorPortsEffective: number[] }>(
      `/systems/${id}`,
    ),
  createSystem: (body: Partial<System>) => post<{ system: System }>("/systems", body),
  updateSystem: (id: string, body: Partial<System>) => patch<{ system: System }>(`/systems/${id}`, body),
  // The API refuses to delete a device that still has accounts unless `withAccounts` is set;
  // the UI passes it only after its confirm dialog has named that consequence.
  deleteSystem: (id: string, withAccounts = false) =>
    del<{ ok: boolean }>(`/systems/${id}${withAccounts ? "?withAccounts=true" : ""}`),
  mergeSystems: (keepId: string, removeId: string) =>
    post<{ system: System }>(`/systems/${keepId}/merge`, { removeId }),
  getDuplicateCandidates: () => get<{ candidates: DuplicateCandidate[] }>("/systems/duplicates"),
  getSystemExposure: (id: string) => get<{ entries: ExposureEntry[] }>(`/systems/${id}/exposure`),
  getSystemAliases: (id: string) => get<{ aliases: SystemAlias[] }>(`/systems/${id}/aliases`),
  markNotDuplicate: (id: string, otherId: string) =>
    post<{ ok: boolean }>(`/systems/${id}/not-duplicate`, { otherId }),
  classifySystem: (id: string) =>
    post<{ system: System; changed: boolean; warnings: string[] }>(`/systems/${id}/classify`),
  probeSystem: (id: string) => post<{ outcome: ProbeOutcome; system: System }>(`/systems/${id}/probe`),
  systemAdminLinks: (systemId: string) =>
    get<{ links: { label: string; url: string }[] }>(`/systems/${systemId}/admin-links`),
  listConfigVersions: (systemId: string) =>
    get<{ versions: ConfigVersion[] }>(`/systems/${systemId}/config-versions`),
  getConfigVersion: (systemId: string, id: string) =>
    get<{ version: ConfigVersion }>(`/systems/${systemId}/config-versions/${id}`),
  listSystemErrors: (systemId: string) =>
    get<{ events: DeviceErrorEvent[] }>(`/systems/${systemId}/errors`),
  acknowledgeSystemError: (systemId: string, eventId: string) =>
    post<{ ok: boolean }>(`/systems/${systemId}/errors/${eventId}/acknowledge`),
  acknowledgeAllSystemErrors: (systemId: string) =>
    post<{ acknowledged: number }>(`/systems/${systemId}/errors/acknowledge`),

  listMcpTokens: () => get<{ tokens: ApiToken[] }>("/settings/mcp-tokens"),
  createMcpToken: (label: string) => post<{ token: ApiToken }>("/settings/mcp-tokens", { label }),
  deleteMcpToken: (id: string) => del<{ ok: boolean }>(`/settings/mcp-tokens/${id}`),

  listAccounts: () => get<{ accounts: Account[] }>("/accounts"),
  listNetworkResources: (kind?: NetworkResource["kind"], activeOnly = true) =>
    get<{ resources: NetworkResource[] }>(`/network-resources?${new URLSearchParams({
      ...(kind ? { kind } : {}), ...(activeOnly ? { activeOnly: "true" } : {}),
    })}`),
  updateNetworkResource: (id: string, manualMd: string) =>
    patch<{ resource: NetworkResource }>(`/network-resources/${id}`, { manualMd }),
  createAccount: (body: Record<string, any>) => post<{ account: Account }>("/accounts", body),
  updateAccount: (id: string, body: Record<string, any>) => patch<{ account: Account }>(`/accounts/${id}`, body),
  revealSecret: (id: string) => get<{ secret: string }>(`/accounts/${id}/secret`),
  deleteAccount: (id: string) => del<{ ok: boolean }>(`/accounts/${id}`),
  listAccountAssignments: (id: string) => get<{ assignments: AccountAssignment[] }>(`/accounts/${id}/assignments`),
  setAccountAssignments: (id: string, assignments: { targetType: string; targetValue: string }[]) =>
    put<{ assignments: AccountAssignment[] }>(`/accounts/${id}/assignments`, assignments),
  listDocs: () => get<{ pages: Omit<DocPage, "bodyMd">[] }>("/docs"),
  getDoc: (slug: string) => get<{ page: DocPage }>(`/docs/${slug}`),
  saveDoc: (slug: string, bodyMd: string) => put<{ page: DocPage }>(`/docs/${slug}`, { bodyMd }),
  saveDocManual: (slug: string, manualMd: string) =>
    put<{ page: DocPage }>(`/docs/${slug}/manual`, { manualMd }),
  resetDoc: (slug: string) => post<{ page: DocPage }>(`/docs/${slug}/reset`),
  generateDocs: (useLlm: boolean) => post<{ generated: string[] }>("/docs/generate", { useLlm }),
  listDocVersions: (slug: string) => get<{ versions: DocVersion[] }>(`/docs/${slug}/versions`),
  getDocVersion: (slug: string, id: string) => get<{ version: DocVersion }>(`/docs/${slug}/versions/${id}`),
  restoreDocVersion: (slug: string, id: string) =>
    post<{ page: DocPage }>(`/docs/${slug}/versions/${id}/restore`),

  startScan: () => post<{ scanId: string }>("/scans"),
  listScans: () => get<{ scans: Scan[]; running: Scan | null }>("/scans"),
  getScan: (id: string) => get<{ scan: Scan }>(`/scans/${id}`),

  runDiagnostic: (tool: string, args: Record<string, any> = {}) =>
    post<{ result: DiagnosticResult }>("/diagnostics", { tool, args }),

  listChats: () => get<{ chats: Chat[] }>("/chats"),
  createChat: () => post<{ chat: Chat }>("/chats"),
  listMessages: (chatId: string) => get<{ messages: ChatMessage[] }>(`/chats/${chatId}/messages`),
  sendMessage: (chatId: string, message: string) =>
    post<{ message: ChatMessage; model: string; toolsUsed: string[] }>(`/chats/${chatId}/messages`, { message }),
  deleteChat: (chatId: string) => del<{ ok: boolean }>(`/chats/${chatId}`),

  dashboard: () => get<Dashboard>("/dashboard"),
  setup: (body: Record<string, any>) => post<{ ok: boolean; systems: number; merged: number; accounts: number }>("/setup", body),
};
