import { useEffect, useState } from "react";
import { api, type Account, type RemoteContainer } from "../../lib/api";
import { proxmoxConsoleUrl } from "../../lib/device";
import Terminal from "../../components/Terminal";
import { LogBox, NoticeLine, Section, StateChip, type Notice } from "./common";
import type { PendingAction } from "./SteuernTab";

/**
 * Docker containers on a host reached over SSH, or VMs/LXC guests on a Proxmox host -- the plain
 * version of SystemDetailPage's RemoteContainersCard, with the same calls (list, start/stop/restart,
 * logs, journal, task log, `docker exec` console, noVNC link). Differences: stop and restart go
 * through the page's review step instead of window.confirm, and on a phone each container is a
 * stacked row instead of a wide table. Loads once on mount (the parent keys it by device).
 */
export default function RemoteHostSection({ systemId, sshAccounts, isProxmoxHost, ask }: {
  systemId: string;
  sshAccounts: Account[];
  isProxmoxHost: boolean;
  ask: (action: PendingAction) => void;
}) {
  const [accountId, setAccountId] = useState(sshAccounts[0]?.id ?? "");
  const [containers, setContainers] = useState<RemoteContainer[] | null>(null);
  const [proxmoxUrl, setProxmoxUrl] = useState("");
  const [busyId, setBusyId] = useState("");
  const [consoleContainerId, setConsoleContainerId] = useState<string | null>(null);
  const [logsFor, setLogsFor] = useState<{ id: string; mode: "" | "journal" } | null>(null);
  const [logsText, setLogsText] = useState("");
  const [logsLoading, setLogsLoading] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(false);
  const what = isProxmoxHost ? "Gast" : "Container";

  useEffect(() => {
    if (isProxmoxHost || accountId) void load();
    // Mount-time only: switching the SSH account must not re-fetch mid-choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function load() {
    setLoading(true);
    setNotice(null);
    try {
      const r = await api.listRemoteContainers(systemId, accountId);
      setContainers(r.containers);
      setProxmoxUrl(r.proxmoxUrl);
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
      setContainers(null);
    } finally {
      setLoading(false);
    }
  }

  async function runAction(c: RemoteContainer, action: "start" | "stop" | "restart") {
    setBusyId(c.id + action);
    setNotice(null);
    try {
      await api.remoteContainerAction(systemId, c.id, action, accountId);
      await load();
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusyId("");
    }
  }

  function askAction(c: RemoteContainer, action: "stop" | "restart") {
    ask(action === "stop" ? {
      title: `${what} „${c.name}“ stoppen?`,
      consequences: [
        <>{what} „{c.name}“ wird gestoppt.</>,
        <>Was darin läuft, ist danach nicht erreichbar, bis ihn jemand wieder startet.</>,
      ],
      confirmLabel: `${what} stoppen`,
      run: () => runAction(c, "stop"),
    } : {
      title: `${what} „${c.name}“ neu starten?`,
      consequences: [<>{what} „{c.name}“ startet neu; was darin läuft, ist dabei kurz nicht erreichbar.</>],
      confirmLabel: "Neu starten",
      run: () => runAction(c, "restart"),
    });
  }

  async function toggleLogs(c: RemoteContainer, mode: "" | "journal" = "") {
    if (logsFor?.id === c.id && logsFor.mode === mode) {
      setLogsFor(null);
      return;
    }
    setLogsFor({ id: c.id, mode });
    setLogsText("");
    setLogsLoading(true);
    setNotice(null);
    try {
      const r = await api.remoteContainerLogs(systemId, c.id, accountId, mode);
      setLogsText(r.text);
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
      setLogsFor(null);
    } finally {
      setLogsLoading(false);
    }
  }

  return (
    <Section title={isProxmoxHost ? "VMs & LXC-Container auf diesem Proxmox-Host" : "Container auf diesem Host"} id="dv-remote"
             aside={(
               <span className="dv-control-buttons">
                 {sshAccounts.length > 1 && (
                   <select aria-label="SSH-Zugang" className="dv-select" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                     {sshAccounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                   </select>
                 )}
                 <button type="button" className="secondary dv-btn-small" onClick={() => void load()}
                         disabled={loading || (!isProxmoxHost && !accountId)}>
                   {loading ? "Lade …" : containers === null ? "Laden" : "Neu laden"}
                 </button>
               </span>
             )}>
      <p className="dv-hint">
        {isProxmoxHost
          ? "Über die Proxmox-API abgefragt und gesteuert (mit „pct“/„qm“ per SSH als Ausweichmöglichkeit). Web-Konsole und Aufgabenprotokoll gibt es nur für Gäste, die über die API gefunden wurden."
          : "Über SSH mit einem der hinterlegten Zugänge abgefragt und gesteuert — für Docker-Hosts, die nicht selbst als Container in HomeAtlas geführt werden."}
      </p>
      <NoticeLine notice={notice} />

      {containers !== null && (
        containers.length === 0 ? (
          <p className="dv-empty">
            {isProxmoxHost ? "Keine VMs/LXC-Container auf diesem Host gefunden." : "Keine Container auf diesem Host gefunden."}
          </p>
        ) : (
          <ul className="dv-rows">
            {containers.map((c) => (
              <li key={c.id} className="dv-row dv-row-stack">
                <span className="dv-row-main">
                  <span className="dv-row-name">{c.name}</span>
                  <StateChip tone={c.state === "running" ? "ok" : ""}>{c.status}</StateChip>
                </span>
                <span className="dv-row-sub mono">
                  {c.image}{isProxmoxHost && c.ip ? ` · ${c.ip}` : ""}
                </span>
                <span className="dv-row-actions">
                  <button type="button" className="secondary dv-btn-small" disabled={busyId !== ""}
                          onClick={() => void runAction(c, "start")}>Starten</button>
                  <button type="button" className="secondary dv-btn-small" disabled={busyId !== ""}
                          onClick={() => askAction(c, "stop")}>Stoppen …</button>
                  <button type="button" className="secondary dv-btn-small" disabled={busyId !== ""}
                          onClick={() => askAction(c, "restart")}>Neu starten …</button>
                  {isProxmoxHost ? (
                    <>
                      {c.node && proxmoxUrl && (
                        <a className="dv-link dv-btn-small" target="_blank" rel="noreferrer noopener"
                           href={proxmoxConsoleUrl(proxmoxUrl, c.node, c.kind, c.vmid ?? "", c.name)}>
                          Web-Konsole ↗
                        </a>
                      )}
                      {c.node && (
                        <button type="button" className="secondary dv-btn-small" onClick={() => void toggleLogs(c, "")}>
                          {logsFor?.id === c.id && logsFor.mode === "" ? "Protokoll schließen" : "Aufgabenprotokoll"}
                        </button>
                      )}
                      {c.kind === "container" && accountId && (
                        <button type="button" className="secondary dv-btn-small" onClick={() => void toggleLogs(c, "journal")}>
                          {logsFor?.id === c.id && logsFor.mode === "journal" ? "Logs schließen" : "System-Logs"}
                        </button>
                      )}
                    </>
                  ) : (
                    <>
                      <button type="button" className="secondary dv-btn-small" onClick={() => void toggleLogs(c)}>
                        {logsFor?.id === c.id ? "Logs schließen" : "Logs"}
                      </button>
                      <button type="button" className="secondary dv-btn-small"
                              onClick={() => setConsoleContainerId(consoleContainerId === c.id ? null : c.id)}>
                        {consoleContainerId === c.id ? "Konsole schließen" : "Konsole"}
                      </button>
                    </>
                  )}
                </span>
                {logsFor?.id === c.id && <LogBox label={`Logs ${c.name}`}>{logsLoading ? "Lade …" : logsText}</LogBox>}
                {!isProxmoxHost && consoleContainerId === c.id && (
                  <div className="dv-terminal">
                    <Terminal wsUrl={api.remoteDockerConsoleWsUrl(systemId, accountId, c.id)}
                              onClose={() => setConsoleContainerId(null)} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )
      )}
    </Section>
  );
}
