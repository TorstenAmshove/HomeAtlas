import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { ApiError, api, type User } from "./lib/api";
import { clearAllDrafts, hasDrafts } from "./lib/drafts";
import ConfirmDialog from "./components/ConfirmDialog";
import LoginPage from "./pages/LoginPage";
import MfaEnrollPage from "./pages/MfaEnrollPage";
import SetupPage from "./pages/SetupPage";
import LoginCalm from "./gates/LoginCalm";
import MfaEnrollCalm from "./gates/MfaEnrollCalm";
import SetupCalm from "./gates/SetupCalm";
import StartCalm from "./pages/start/StartCalm";
import InventoryCalm from "./pages/geraete/InventoryCalm";
import PlanCalm from "./pages/geraete/PlanCalm";
import NetworksCalm from "./pages/geraete/NetworksCalm";
import AccountsCalm from "./pages/zugaenge/AccountsCalm";
import AccountFormCalm from "./pages/zugaenge/AccountFormCalm";
import ScanCalm from "./pages/mehr/ScanCalm";
import UsersCalm from "./pages/mehr/UsersCalm";
import AccessLogCalm from "./pages/mehr/AccessLogCalm";
import DeviceCalm from "./pages/device/DeviceCalm";
import DocsPage from "./pages/DocsPage";
import ChatPage from "./pages/ChatPage";
import SettingsPage from "./pages/SettingsPage";
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

/** The new device page, remounted per device: switching from one device to another (a link, ⌘K)
 *  starts from a clean state, so revealed passwords and form state never carry over. */
function DeviceCalmKeyed() {
  const { id } = useParams();
  return <DeviceCalm key={id} />;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [setupCompleted, setSetupCompleted] = useState(true);

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
    // /api/health is public: its answer (uiCalm included) is applied even when /me says "not logged
    // in", so the login gate already follows the instance-wide switch, not only the last known value.
    // Both requests are awaited before `loading` ends: if the login form rendered on the 401 from /me
    // while health was still open, a late health answer could swap classic and calm login under the
    // user's fingers (remount, typed input gone).
    const [me, health] = await Promise.allSettled([api.me(), api.health()]);
    if (health.status === "fulfilled") {
      setSetupCompleted(health.value.setupCompleted);
      setServerCalm(Boolean(health.value.uiCalm));
      setLastServerCalm(Boolean(health.value.uiCalm));
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

  // The logout buttons of both shells ask first when this tab still holds unsaved drafts (doc text,
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

  // The gates (login -> MFA -> setup) render before the app. With the switch on they use the
  // redesigned versions in gates/; the order and the conditions are the same for both, and the
  // backend enforces them independently (deps.current_user, POST /api/setup).
  if (!user) {
    if (calm) {
      return (
        <UiContext.Provider value={ui}>
          <LoginCalm onLoggedIn={() => void refresh()} />
        </UiContext.Provider>
      );
    }
    return <LoginPage onLoggedIn={() => void refresh()} />;
  }

  const isAdmin = user.role === "ADMIN";

  // The second factor is mandatory (the backend enforces this on every other route -- see
  // main.py's `current_user`); this is just the matching UI. Comes before the setup wizard below:
  // the account gets secured first, then the household gets configured.
  if (!user.totpEnabled) {
    return (
      <AuthContext.Provider value={{ user, isAdmin, setUser, logout }}>
        <UiContext.Provider value={ui}>
          {calm ? <MfaEnrollCalm onDone={() => void refresh()} /> : <MfaEnrollPage onDone={() => void refresh()} />}
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
          {calm ? <SetupCalm onDone={() => void refresh()} /> : <SetupPage onDone={() => void refresh()} />}
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
            <Route path="/" element={<StartCalm />} />
            <Route path="/geraete" element={<InventoryCalm />} />
            <Route path="/geraete/:id" element={<DeviceCalmKeyed />} />
            {isAdmin && <Route path="/zugaenge" element={<AccountsCalm />} />}
            {isAdmin && <Route path="/zugaenge/neu" element={<AccountFormCalm mode="new" />} />}
            {isAdmin && <Route path="/zugaenge/:id" element={<AccountFormCalm mode="edit" />} />}
            <Route path="/dokumentation" element={<DocsPage />} />
            <Route path="/dokumentation/:slug" element={<DocsPage />} />
            <Route path="/assistent" element={<ChatPage />} />
            <Route path="/assistent/:chatId" element={<ChatPage />} />
            {isAdmin && <Route path="/scan" element={<ScanCalm />} />}
            <Route path="/plan" element={<PlanCalm />} />
            <Route path="/netze" element={<NetworksCalm />} />
            {isAdmin && <Route path="/benutzer" element={<UsersCalm />} />}
            {isAdmin && <Route path="/protokoll" element={<AccessLogCalm />} />}
            <Route path="/einstellungen" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
        {logoutDialog}
      </UiContext.Provider>
    </AuthContext.Provider>
  );
}
