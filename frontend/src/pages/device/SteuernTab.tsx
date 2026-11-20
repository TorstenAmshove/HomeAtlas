import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type Account, type HaEntity, type System } from "../../lib/api";
import { directAccounts, isShelly, rebootAccountFor, sshEligible, streamContainerLogs } from "../../lib/device";
import ConfirmDialog from "../../components/ConfirmDialog";
import Terminal from "../../components/Terminal";
import { LogBox, NoticeLine, Section, StateChip, type Notice } from "./common";
import RemoteHostSection from "./RemoteHostSection";

/** A pending state-changing action waiting for its review step. */
export interface PendingAction {
  title: string;
  consequences: ReactNode[];
  confirmLabel: string;
  run: () => Promise<void>;
}

/** Shared review step for every state-changing click on this tab (forensics "Gerät" 2, Q4). */
export function usePendingAction(): [ReactNode, (action: PendingAction) => void] {
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [busy, setBusy] = useState(false);
  const dialog = (
    <ConfirmDialog
      open={pending !== null}
      title={pending?.title ?? ""}
      consequences={pending?.consequences}
      confirmLabel={pending?.confirmLabel ?? ""}
      danger
      busy={busy}
      onCancel={() => setPending(null)}
      onConfirm={async () => {
        if (!pending) return;
        setBusy(true);
        try {
          await pending.run();
        } finally {
          setBusy(false);
          setPending(null);
        }
      }}
    />
  );
  return [dialog, setPending];
}

const STATUS_WORD: Record<string, string> = { online: "erreichbar", offline: "nicht erreichbar", unknown: "Zustand unbekannt" };

function errorText(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

/**
 * Tab "Steuern" (admin only): every action that changes something on or at the device, each with
 * its current state shown before the click. Stop/off/restart/reboot go through a review step that
 * says in plain words what happens; start and switch-on run directly, as they did before. The calls
 * are the same admin-gated endpoints as on the classic page (routes/remote.py, docker_admin,
 * switch_admin); nothing here is reachable for the LLM tools.
 */
export default function SteuernTab({ system, status, accounts, onSystemChanged }: {
  system: System;
  /** Live status if the monitor watches the device, else the last scan's. */
  status: System["status"];
  accounts: Account[];
  onSystemChanged: () => Promise<void>;
}) {
  const id = system.id;
  const name = system.name;
  const direct = directAccounts(accounts);
  const rebootAccount = rebootAccountFor(system, accounts);
  const shelly = isShelly(system);
  const haAccount = direct.find((a) => a.category === "homeassistant");
  const sshAccounts = direct.filter(sshEligible);
  const isProxmoxHost = direct.some((a) => a.category === "proxmox");
  const docker = system.extra?.docker;

  const [confirmDialog, ask] = usePendingAction();
  const [rebootNotice, setRebootNotice] = useState<Notice>(null);
  const [switchNotice, setSwitchNotice] = useState<Notice>(null);
  const [switchBusy, setSwitchBusy] = useState("");
  const [haEntities, setHaEntities] = useState<HaEntity[] | null>(null);
  const [containerNotice, setContainerNotice] = useState<Notice>(null);
  const [containerBusy, setContainerBusy] = useState("");
  const [showLogs, setShowLogs] = useState(false);
  const [logLines, setLogLines] = useState("");
  const logsAbort = useRef<AbortController | null>(null);
  const [showDockerConsole, setShowDockerConsole] = useState(false);
  const [consoleAccountId, setConsoleAccountId] = useState<string | null>(null);

  useEffect(() => {
    if (!haAccount) return;
    api.listHaSwitchables(id, haAccount.id).then((r) => setHaEntities(r.entities)).catch(() => setHaEntities([]));
  }, [id, haAccount?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => logsAbort.current?.abort(), []);

  function reboot(account: Account) {
    ask({
      title: `„${name}“ neu starten?`,
      consequences: [
        <>„{name}“ startet neu und ist danach einige Minuten nicht erreichbar.</>,
        <>Was darüber läuft (Internet, Freigaben, Dienste), ist in der Zeit ebenfalls weg.</>,
        <>Ausgelöst wird der Neustart über den Zugang „{account.label}“.</>,
      ],
      confirmLabel: "Jetzt neu starten",
      run: async () => {
        setRebootNotice(null);
        try {
          await api.rebootSystem(id, account.id);
          setRebootNotice({ kind: "ok", text: "Neustart ausgelöst." });
        } catch (e) {
          setRebootNotice({ kind: "error", text: errorText(e) });
        }
      },
    });
  }

  async function shellySwitch(action: "on" | "off") {
    setSwitchBusy(`shelly-${action}`);
    setSwitchNotice(null);
    try {
      await api.shellySwitch(id, action);
      setSwitchNotice({ kind: "ok", text: `Geschaltet: ${action === "on" ? "ein" : "aus"}.` });
    } catch (e) {
      setSwitchNotice({ kind: "error", text: errorText(e) });
    } finally {
      setSwitchBusy("");
    }
  }

  async function haSwitch(accountId: string, entity: HaEntity, action: "on" | "off") {
    setSwitchBusy(`${entity.entityId}-${action}`);
    setSwitchNotice(null);
    try {
      await api.haSwitch(id, action, accountId, entity.entityId);
      setSwitchNotice({ kind: "ok", text: `${entity.name}: ${action === "on" ? "eingeschaltet" : "ausgeschaltet"}.` });
      const { entities } = await api.listHaSwitchables(id, accountId);
      setHaEntities(entities);
    } catch (e) {
      setSwitchNotice({ kind: "error", text: errorText(e) });
    } finally {
      setSwitchBusy("");
    }
  }

  async function containerAction(action: "start" | "stop" | "restart") {
    setContainerBusy(action);
    setContainerNotice(null);
    try {
      if (action === "start") await api.startContainer(id);
      else if (action === "stop") await api.stopContainer(id);
      else await api.restartContainer(id);
      const labels = { start: "gestartet", stop: "gestoppt", restart: "neu gestartet" } as const;
      setContainerNotice({ kind: "ok", text: `Container ${labels[action]}.` });
      await onSystemChanged();
    } catch (e) {
      setContainerNotice({ kind: "error", text: errorText(e) });
    } finally {
      setContainerBusy("");
    }
  }

  function askContainer(action: "stop" | "restart") {
    ask(action === "stop" ? {
      title: `Container „${name}“ stoppen?`,
      consequences: [
        <>Der Container „{name}“ wird gestoppt.</>,
        <>Der Dienst darin ist danach nicht erreichbar, bis ihn jemand wieder startet.</>,
      ],
      confirmLabel: "Container stoppen",
      run: () => containerAction("stop"),
    } : {
      title: `Container „${name}“ neu starten?`,
      consequences: [<>Der Container „{name}“ startet neu; der Dienst darin ist dabei kurz nicht erreichbar.</>],
      confirmLabel: "Neu starten",
      run: () => containerAction("restart"),
    });
  }

  function startLogs() {
    setShowLogs(true);
    setLogLines("");
    const controller = new AbortController();
    logsAbort.current = controller;
    void streamContainerLogs(id, controller.signal, setLogLines);
  }

  function stopLogs() {
    logsAbort.current?.abort();
    setShowLogs(false);
  }

  const nothing = !rebootAccount && !shelly && !haAccount && !docker && sshAccounts.length === 0 && !isProxmoxHost;
  const statusTone = status === "online" ? "ok" : status === "offline" ? "bad" : "";

  return (
    <div className="dv-tab-body">
      {confirmDialog}
      {nothing && (
        <p className="dv-empty">
          Für dieses Gerät gibt es nichts zu steuern. Steuern geht nur mit einem passenden Zugang
          (SSH, Router-Login, Home Assistant, Proxmox), der direkt diesem Gerät zugeordnet ist — unter{" "}
          <Link to="/zugaenge">Zugänge</Link> hinterlegen.
        </p>
      )}

      {rebootAccount && (
        <Section title="Neustart" id="dv-reboot">
          <div className="dv-control">
            <span className="dv-control-state">Jetzt: <StateChip tone={statusTone}>{STATUS_WORD[status] ?? status}</StateChip></span>
            <button type="button" className="secondary" onClick={() => reboot(rebootAccount)}>Neu starten …</button>
          </div>
          <NoticeLine notice={rebootNotice} />
        </Section>
      )}

      {(shelly || haAccount) && (
        <Section title="Schalten" id="dv-switch">
          <NoticeLine notice={switchNotice} />
          {shelly && (
            <div className="dv-control">
              <span className="dv-control-state">
                Shelly-Relais · Schaltzustand wird nicht abgefragt · Gerät{" "}
                <StateChip tone={statusTone}>{STATUS_WORD[status] ?? status}</StateChip>
              </span>
              <span className="dv-control-buttons">
                <button type="button" className="secondary" disabled={switchBusy !== ""} onClick={() => void shellySwitch("on")}>
                  {switchBusy === "shelly-on" ? "Schalte ein …" : "Einschalten"}
                </button>
                <button type="button" className="secondary" disabled={switchBusy !== ""} onClick={() => ask({
                  title: `„${name}“ ausschalten?`,
                  consequences: [<>Das Relais von „{name}“ schaltet aus; was daran hängt, bekommt keinen Strom mehr.</>],
                  confirmLabel: "Ausschalten",
                  run: () => shellySwitch("off"),
                })}>
                  {switchBusy === "shelly-off" ? "Schalte aus …" : "Ausschalten …"}
                </button>
              </span>
            </div>
          )}
          {haAccount && (
            haEntities === null ? (
              <p className="dv-empty">Lade schaltbare Entities …</p>
            ) : haEntities.length === 0 ? (
              <p className="dv-empty">Keine schaltbaren switch/light-Entities in Home Assistant gefunden.</p>
            ) : (
              <ul className="dv-rows">
                {haEntities.map((entity) => (
                  <li key={entity.entityId} className="dv-row dv-control">
                    <span className="dv-row-main dv-row-stack-inline">
                      <span className="dv-row-name">{entity.name}</span>
                      <span className="dv-row-sub mono">{entity.entityId}</span>
                    </span>
                    <span className="dv-control-buttons">
                      <StateChip tone={entity.state === "on" ? "ok" : ""}>
                        {entity.state === "on" ? "ein" : entity.state === "off" ? "aus" : entity.state}
                      </StateChip>
                      <button type="button" className="secondary dv-btn-small" disabled={switchBusy !== ""}
                              onClick={() => void haSwitch(haAccount.id, entity, "on")}>
                        {switchBusy === `${entity.entityId}-on` ? "…" : "Ein"}
                      </button>
                      <button type="button" className="secondary dv-btn-small" disabled={switchBusy !== ""}
                              onClick={() => ask({
                                title: `„${entity.name}“ ausschalten?`,
                                consequences: [<>Home Assistant schaltet „{entity.name}“ ({entity.entityId}) aus.</>],
                                confirmLabel: "Ausschalten",
                                run: () => haSwitch(haAccount.id, entity, "off"),
                              })}>
                        {switchBusy === `${entity.entityId}-off` ? "…" : "Aus …"}
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )
          )}
        </Section>
      )}

      {docker && (
        <Section title="Container" id="dv-container">
          {docker.containerId ? (
            <>
              <div className="dv-control">
                <span className="dv-control-state">
                  Jetzt: <StateChip tone={docker.state === "running" ? "ok" : ""}>{docker.status || docker.state || "unbekannt"}</StateChip>
                </span>
                <span className="dv-control-buttons">
                  <button type="button" className="secondary" disabled={containerBusy !== ""} onClick={() => void containerAction("start")}>
                    {containerBusy === "start" ? "Starte …" : "Starten"}
                  </button>
                  <button type="button" className="secondary" disabled={containerBusy !== ""} onClick={() => askContainer("stop")}>
                    {containerBusy === "stop" ? "Stoppe …" : "Stoppen …"}
                  </button>
                  <button type="button" className="secondary" disabled={containerBusy !== ""} onClick={() => askContainer("restart")}>
                    {containerBusy === "restart" ? "Starte neu …" : "Neu starten …"}
                  </button>
                  {!showLogs ? (
                    <button type="button" className="secondary" onClick={startLogs}>Live-Logs</button>
                  ) : (
                    <button type="button" className="secondary" onClick={stopLogs}>Logs schließen</button>
                  )}
                  <button type="button" className="secondary" aria-expanded={showDockerConsole}
                          onClick={() => setShowDockerConsole((v) => !v)}>
                    {showDockerConsole ? "Konsole schließen" : "Konsole öffnen"}
                  </button>
                </span>
              </div>
              <NoticeLine notice={containerNotice} />
              {showLogs && <LogBox label="Live-Logs">{logLines || "Warte auf Ausgabe …"}</LogBox>}
              {showDockerConsole && (
                <div className="dv-terminal">
                  <Terminal wsUrl={api.dockerConsoleWsUrl(id)} onClose={() => setShowDockerConsole(false)} />
                </div>
              )}
            </>
          ) : (
            <p className="dv-empty">Steuerung braucht die Container-ID aus einem neueren Scan — bitte einmal erneut scannen.</p>
          )}
        </Section>
      )}

      {sshAccounts.length > 0 && (
        <Section title="SSH-Konsole" id="dv-ssh">
          <p className="dv-hint">Eine Anmeldung auf dem Gerät mit dem gewählten Zugang. Was du dort eingibst, wird direkt ausgeführt.</p>
          <ul className="dv-rows">
            {sshAccounts.map((a) => (
              <li key={a.id} className="dv-row">
                <span className="dv-row-main">
                  <span className="dv-row-name">{a.label}</span>
                  {a.username && <span className="dv-row-sub mono"> · {a.username}</span>}
                </span>
                <button type="button" className="secondary dv-btn-small" aria-expanded={consoleAccountId === a.id}
                        onClick={() => setConsoleAccountId(consoleAccountId === a.id ? null : a.id)}>
                  {consoleAccountId === a.id ? "Konsole schließen" : "Konsole öffnen"}
                </button>
              </li>
            ))}
          </ul>
          {consoleAccountId && (
            <div className="dv-terminal">
              <Terminal wsUrl={api.sshConsoleWsUrl(id, consoleAccountId)} onClose={() => setConsoleAccountId(null)} />
            </div>
          )}
        </Section>
      )}

      {(sshAccounts.length > 0 || isProxmoxHost) && (
        <RemoteHostSection key={id} systemId={id} sshAccounts={sshAccounts} isProxmoxHost={isProxmoxHost} ask={ask} />
      )}
    </div>
  );
}
