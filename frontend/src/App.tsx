import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ApiError, api, type User } from "./lib/api";
import { clearAllDrafts, hasDrafts } from "./lib/drafts";
import ConfirmDialog from "./components/ConfirmDialog";
import LoginPage from "./pages/LoginPage";
import MfaEnrollPage from "./pages/MfaEnrollPage";
import SetupPage from "./pages/SetupPage";
import DashboardPage from "./pages/DashboardPage";
import StartCalm from "./pages/start/StartCalm";
import InventoryPage from "./pages/InventoryPage";
import SystemDetailPage from "./pages/SystemDetailPage";
import DeviceCalm from "./pages/device/DeviceCalm";
import AccessLogPage from "./pages/AccessLogPage";
import AccountsPage from "./pages/AccountsPage";
import DocsPage from "./pages/DocsPage";
import PlanPage from "./pages/PlanPage";
import ChatPage from "./pages/ChatPage";
import ScanPage from "./pages/ScanPage";
import SettingsPage from "./pages/SettingsPage";
import UsersPage from "./pages/UsersPage";
import NetworksPage from "./pages/NetworksPage";
import AppShell, { ShellSkeleton } from "./shell/AppShell";
import { UiContext, type UiState } from "./shell/ui";
import {
  consumeUiQueryParam, getLastServerCalm, getThemeMode, getUiOverride, resolveCalm, setLastServerCalm,
  setThemeModePref, setUiOverride, type ThemeMode, type UiOverride,
} from "./shell/prefs";

interface AuthState {
  user: User | null;
  isAdmin: boolean;
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  isAdmin: false,
  setUser: () => {},
  logout: async () => {},
});

export const useAuth = () => useContext(AuthContext);

const NAV = [
  { to: "/", label: "Übersicht", icon: "🏠", end: true },
  { to: "/geraete", label: "Geräte", icon: "🖧" },
  { to: "/plan", label: "Netzplan", icon: "🗺️" },
  { to: "/netze", label: "Netze & WLAN", icon: "📡" },
  { to: "/zugaenge", label: "Zugänge", icon: "🔑", adminOnly: true },
  { to: "/dokumentation", label: "Dokumentation", icon: "📘" },
  { to: "/assistent", label: "KI-Assistent", icon: "💬" },
  { to: "/scan", label: "Netzwerk-Scan", icon: "🔍", adminOnly: true },
  { to: "/benutzer", label: "Benutzer", icon: "👥", adminOnly: true },
  { to: "/protokoll", label: "Protokoll", icon: "📋", adminOnly: true },
  { to: "/einstellungen", label: "Einstellungen", icon: "⚙️" },
];

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [setupCompleted, setSetupCompleted] = useState(true);
  const location = useLocation();

  // Which shell to render (docs/redesign/5-information-architecture.md, "Schalter"). With the flag
  // off and no ?ui=calm override, everything below renders exactly the pre-redesign UI.
  const [override, setOverrideState] = useState<UiOverride>(() => {
    consumeUiQueryParam();
    return getUiOverride();
  });
  const [serverCalm, setServerCalm] = useState(getLastServerCalm);
  const [themeMode, setThemeModeState] = useState<ThemeMode>(getThemeMode);
  const calm = resolveCalm(serverCalm, override);
  const ui: UiState = {
    calm,
    serverCalm,
    setServerCalm: (value) => { setServerCalm(value); setLastServerCalm(value); },
    override,
    setOverride: (value) => { setUiOverride(value); setOverrideState(value); },
    themeMode,
    setThemeMode: (value) => { setThemeModePref(value); setThemeModeState(value); },
  };

  const refresh = useCallback(async () => {
    try {
      const [me, health] = await Promise.all([api.me(), api.health()]);
      setUser(me.user);
      setSetupCompleted(health.setupCompleted);
      setServerCalm(Boolean(health.uiCalm));
      setLastServerCalm(Boolean(health.uiCalm));
    } catch (error) {
      // A 401 is the normal "not logged in yet" case, not something to surface.
      if (!(error instanceof ApiError && error.status === 401)) console.error(error);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    clearAllDrafts();
    await api.logout();
    setUser(null);
  }, []);

  // The logout buttons of both shells ask first when this tab still holds unsaved drafts (doc text,
  // notes, chat input): logout clears them (see clearAllDrafts), so leaving must be a choice.
  const [logoutAsk, setLogoutAsk] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const requestLogout = useCallback(async () => {
    if (hasDrafts()) setLogoutAsk(true);
    else await logout();
  }, [logout]);
  const logoutDialog = (
    <ConfirmDialog
      open={logoutAsk}
      title="Abmelden?"
      consequences={[
        <>Ungespeicherte Entwürfe gehen verloren (Doku-Text, Notizen oder Chat-Eingabe, die noch nicht gespeichert bzw. gesendet sind).</>,
      ]}
      confirmLabel="Trotzdem abmelden"
      cancelLabel="Angemeldet bleiben"
      danger
      busy={loggingOut}
      onConfirm={async () => {
        setLoggingOut(true);
        try {
          await logout();
        } finally {
          setLoggingOut(false);
          setLogoutAsk(false);
        }
      }}
      onCancel={() => setLogoutAsk(false)}
    />
  );

  if (loading) {
    if (calm) {
      return (
        <UiContext.Provider value={ui}>
          <ShellSkeleton />
        </UiContext.Provider>
      );
    }
    return (
      <div className="centered">
        <span className="spinner" />
      </div>
    );
  }

  if (!user) return <LoginPage onLoggedIn={() => void refresh()} />;

  const isAdmin = user.role === "ADMIN";

  // The second factor is mandatory (the backend enforces this on every other route -- see
  // main.py's `current_user`); this is just the matching UI. Comes before the setup wizard below:
  // the account gets secured first, then the household gets configured.
  if (!user.totpEnabled) {
    return (
      <AuthContext.Provider value={{ user, isAdmin, setUser, logout }}>
        <MfaEnrollPage onDone={() => void refresh()} />
      </AuthContext.Provider>
    );
  }

  // First run: an admin lands in the wizard until the household basics are recorded. Members are
  // let through -- they can't complete it anyway, and locking them out of a working app is worse.
  if (!setupCompleted && isAdmin) {
    return (
      <AuthContext.Provider value={{ user, isAdmin, setUser, logout }}>
        <SetupPage onDone={() => void refresh()} />
      </AuthContext.Provider>
    );
  }

  // One route list for both shells, so scripts/check-nav.ts sees every <Route> exactly once and the
  // admin gating (`isAdmin &&`) is the same whichever frame is around it.
  const routes = (
    <Routes>
      <Route path="/" element={calm ? <StartCalm /> : <DashboardPage />} />
      <Route path="/geraete" element={<InventoryPage />} />
      <Route path="/geraete/:id" element={calm ? <DeviceCalm /> : <SystemDetailPage />} />
      {isAdmin && <Route path="/zugaenge" element={<AccountsPage />} />}
      <Route path="/dokumentation" element={<DocsPage />} />
      <Route path="/dokumentation/:slug" element={<DocsPage />} />
      <Route path="/assistent" element={<ChatPage />} />
      <Route path="/assistent/:chatId" element={<ChatPage />} />
      {isAdmin && <Route path="/scan" element={<ScanPage />} />}
      <Route path="/plan" element={<PlanPage />} />
      <Route path="/netze" element={<NetworksPage />} />
      {isAdmin && <Route path="/benutzer" element={<UsersPage />} />}
      {isAdmin && <Route path="/protokoll" element={<AccessLogPage />} />}
      <Route path="/einstellungen" element={<SettingsPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );

  if (calm) {
    return (
      <AuthContext.Provider value={{ user, isAdmin, setUser, logout }}>
        <UiContext.Provider value={ui}>
          <AppShell user={user} isAdmin={isAdmin} onLogout={requestLogout}>
            {routes}
          </AppShell>
          {logoutDialog}
        </UiContext.Provider>
      </AuthContext.Provider>
    );
  }

  return (
    <AuthContext.Provider value={{ user, isAdmin, setUser, logout }}>
      <UiContext.Provider value={ui}>
      <div className="app">
        <nav className="sidebar">
          <div className="brand">
            <span className="brand-mark">🧭</span>
            <div>
              <div className="brand-name">HomeAtlas</div>
              <div className="brand-sub">Dein Zuhause, dokumentiert</div>
            </div>
          </div>
          {NAV.filter((item) => !item.adminOnly || isAdmin).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className="nav-link">
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
          <div className="sidebar-footer">
            <div>
              Angemeldet als <strong>{user.displayName || user.username}</strong>
            </div>
            <div className="muted">{isAdmin ? "Administrator" : "Mitglied (nur lesen)"}</div>
            <button className="secondary small" style={{ marginTop: 10 }} onClick={() => void requestLogout()}>
              Abmelden
            </button>
          </div>
        </nav>

        <main className={`content${location.pathname === "/assistent" || location.pathname.startsWith("/assistent/") ? " content-chat" : ""}`}>
          {routes}
        </main>
      </div>
      {logoutDialog}
      </UiContext.Provider>
    </AuthContext.Provider>
  );
}
