import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { ApiError, api, type User } from "./lib/api";
import { clearAllDrafts, hasDrafts } from "./lib/drafts";
import ConfirmDialog from "./components/ConfirmDialog";
import Login from "./gates/Login";
import MfaEnroll from "./gates/MfaEnroll";
import Setup from "./gates/Setup";
import StartPage from "./pages/start/StartPage";
import InventoryPage from "./pages/geraete/InventoryPage";
import PlanPage from "./pages/geraete/PlanPage";
import NetworksPage from "./pages/geraete/NetworksPage";
import AccountsPage from "./pages/zugaenge/AccountsPage";
import AccountFormPage from "./pages/zugaenge/AccountFormPage";
import ScanPage from "./pages/mehr/ScanPage";
import UsersPage from "./pages/mehr/UsersPage";
import AccessLogPage from "./pages/mehr/AccessLogPage";
import DevicePage from "./pages/device/DevicePage";
import DocsPage from "./pages/DocsPage";
import ChatPage from "./pages/ChatPage";
import SettingsPage from "./pages/SettingsPage";
import AppShell, { ShellSkeleton } from "./shell/AppShell";
import { UiContext, type UiState } from "./shell/ui";
import { getThemeMode, removeLegacyUiKeys, setThemeModePref, type ThemeMode } from "./shell/prefs";

// Once per page load, not per render. Drops the keys of the removed old-UI switch.
removeLegacyUiKeys();

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

/** The new device page, remounted per device: switching from one device to another (a link, ⌘K)
 *  starts from a clean state, so revealed passwords and form state never carry over. */
function DeviceKeyed() {
  const { id } = useParams();
  return <DevicePage key={id} />;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [setupCompleted, setSetupCompleted] = useState(true);

  const [themeMode, setThemeModeState] = useState<ThemeMode>(getThemeMode);
  const ui: UiState = {
    themeMode,
    setThemeMode: (value) => { setThemeModePref(value); setThemeModeState(value); },
  };

  const refresh = useCallback(async () => {
    // Both requests are awaited before `loading` ends, so the gates below decide on complete
    // information (setupCompleted) and never re-render under the user's fingers.
    const [me, health] = await Promise.allSettled([api.me(), api.health()]);
    if (health.status === "fulfilled") {
      setSetupCompleted(health.value.setupCompleted);
    } else {
      console.error(health.reason);
    }
    if (me.status === "fulfilled" && health.status === "fulfilled") {
      setUser(me.value.user);
    } else {
      // A 401 is the normal "not logged in yet" case, not something to surface.
      const error = me.status === "rejected" ? me.reason : null;
      if (error && !(error instanceof ApiError && error.status === 401)) console.error(error);
      setUser(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Drafts are cleared only once the server has ended the session: a logout that fails (network,
  // backend down) must not throw away unsaved text. Callers show the error (it is rethrown).
  const logout = useCallback(async () => {
    await api.logout();
    clearAllDrafts();
    setUser(null);
  }, []);

  // The logout buttons ask first when this tab still holds unsaved drafts (doc text,
  // notes, chat input): logout clears them (see clearAllDrafts), so leaving must be a choice.
  const [logoutAsk, setLogoutAsk] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const requestLogout = useCallback(async () => {
    if (hasDrafts()) {
      setLogoutAsk(true);
      return;
    }
    try {
      await logout();
    } catch (e) {
      // Shown in the same dialog, which then offers to try again.
      setLogoutError(e instanceof Error ? e.message : String(e));
      setLogoutAsk(true);
    }
  }, [logout]);
  const logoutDialog = (
    <ConfirmDialog
      open={logoutAsk}
      title="Abmelden?"
      consequences={hasDrafts() ? [
        <>Ungespeicherte Entwürfe gehen verloren (Doku-Text, Notizen oder Chat-Eingabe, die noch nicht gespeichert bzw. gesendet sind).</>,
      ] : []}
      confirmLabel={logoutError ? "Erneut versuchen" : "Trotzdem abmelden"}
      cancelLabel="Angemeldet bleiben"
      danger
      busy={loggingOut}
      onConfirm={async () => {
        setLoggingOut(true);
        setLogoutError("");
        try {
          await logout();
          setLogoutAsk(false);
        } catch (e) {
          setLogoutError(e instanceof Error ? e.message : String(e));
        } finally {
          setLoggingOut(false);
        }
      }}
      onCancel={() => { setLogoutAsk(false); setLogoutError(""); }}
    >
      {logoutError && (
        <p className="notice error" role="alert">
          Abmelden hat nicht geklappt ({logoutError}). Du bist noch angemeldet; deine Entwürfe sind erhalten.
        </p>
      )}
    </ConfirmDialog>
  );

  if (loading) {
    return (
      <UiContext.Provider value={ui}>
        <ShellSkeleton />
      </UiContext.Provider>
    );
  }

  // The gates (login -> MFA -> setup) render before the app. The backend enforces the same order
  // independently (deps.current_user, POST /api/setup).
  if (!user) {
    return (
      <UiContext.Provider value={ui}>
        <Login onLoggedIn={() => void refresh()} />
      </UiContext.Provider>
    );
  }

  const isAdmin = user.role === "ADMIN";

  // The second factor is mandatory (the backend enforces this on every other route -- see
  // main.py's `current_user`); this is just the matching UI. Comes before the setup wizard below:
  // the account gets secured first, then the household gets configured.
  if (!user.totpEnabled) {
    return (
      <AuthContext.Provider value={{ user, isAdmin, setUser, logout }}>
        <UiContext.Provider value={ui}>
          <MfaEnroll onDone={() => void refresh()} />
        </UiContext.Provider>
      </AuthContext.Provider>
    );
  }

  // First run: an admin lands in the wizard until the household basics are recorded. Members are
  // let through -- they can't complete it anyway, and locking them out of a working app is worse.
  if (!setupCompleted && isAdmin) {
    return (
      <AuthContext.Provider value={{ user, isAdmin, setUser, logout }}>
        <UiContext.Provider value={ui}>
          <Setup onDone={() => void refresh()} />
        </UiContext.Provider>
      </AuthContext.Provider>
    );
  }

  // Every <Route> appears exactly once (scripts/check-nav.ts), and the admin gating (`isAdmin &&`)
  // is the same on the backend routes behind these pages.
  return (
    <AuthContext.Provider value={{ user, isAdmin, setUser, logout }}>
      <UiContext.Provider value={ui}>
        <AppShell user={user} isAdmin={isAdmin} onLogout={requestLogout}>
          <Routes>
            <Route path="/" element={<StartPage />} />
            <Route path="/geraete" element={<InventoryPage />} />
            <Route path="/geraete/:id" element={<DeviceKeyed />} />
            {isAdmin && <Route path="/zugaenge" element={<AccountsPage />} />}
            {isAdmin && <Route path="/zugaenge/neu" element={<AccountFormPage mode="new" />} />}
            {isAdmin && <Route path="/zugaenge/:id" element={<AccountFormPage mode="edit" />} />}
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
        </AppShell>
        {logoutDialog}
      </UiContext.Provider>
    </AuthContext.Provider>
  );
}
