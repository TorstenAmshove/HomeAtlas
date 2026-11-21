import type { System } from "../lib/api";
import { KINDS } from "../lib/device";

/** The "Gerät bearbeiten" form, shared by the device page (same fields,
 *  same parsing of tags and ports). The parent owns the draft and where it is kept (lib/deviceDraft.ts). */
export default function DeviceEditForm({ draft, onChange, onSave, onCancel, saving = false, title = "Gerät bearbeiten" }: {
  draft: Partial<System>;
  onChange: (next: Partial<System>) => void;
  onSave: () => void;
  onCancel: () => void;
  saving?: boolean;
  /** Pass null to leave the heading out (the new UI names the device in the top bar). */
  title?: string | null;
}) {
  const setDraft = onChange;
  return (
    <>
      {title && <h2>{title}</h2>}
      <div className="grid cols-2">
        {([
          ["name", "Name"], ["ip", "Adresse im Netzwerk"], ["hostname", "Hostname"],
          ["vendor", "Hersteller"], ["model", "Modell"], ["location", "Standort"],
          ["url", "Weboberfläche (URL)"], ["docUrl", "Hersteller-Dokumentation (URL)"],
          ["docLink", "Eigene Dokumentation (URL)"], ["purpose", "Zweck in einem Satz"],
        ] as const).map(([field, label]) => (
          <div className="field" key={field}>
            <label htmlFor={`device-${field}`}>{label}</label>
            <input id={`device-${field}`} value={(draft[field] as string) ?? ""}
                   onChange={(e) => setDraft({ ...draft, [field]: e.target.value })} />
          </div>
        ))}
        <div className="field">
          <label htmlFor="device-kind">Art des Geräts</label>
          <select id="device-kind" value={draft.kind ?? "other"} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
            {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="device-importance">Bedeutung</label>
          <select id="device-importance" value={draft.importance ?? "normal"}
                  onChange={(e) => setDraft({ ...draft, importance: e.target.value as System["importance"] })}>
            <option value="critical">kritisch — Ausfall fällt im Haus auf</option>
            <option value="normal">normal</option>
            <option value="low">gering</option>
          </select>
        </div>
      </div>
      <div className="field">
        <label htmlFor="device-description">Beschreibung für Laien (Markdown)</label>
        <textarea id="device-description" value={draft.descriptionMd ?? ""}
                  onChange={(e) => setDraft({ ...draft, descriptionMd: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="device-notes">Interne Notiz</label>
        <input id="device-notes" value={draft.notes ?? ""} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="device-tags">Schlagworte</label>
        <input
          id="device-tags"
          placeholder="z. B. PoE, Dachboden"
          value={(draft.tags ?? []).join(", ")}
          onChange={(e) => setDraft({ ...draft, tags: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
        />
        <div className="field-hint">
          Frei wählbar. Ein Schlagwort mit „PoE" markiert das Gerät als PoE-abhängig — es
          funktioniert dann nur an einem PoE-fähigen Switch oder mit einem Injector, was als
          Hinweis oben und im Geräte-Überblick angezeigt wird.
        </div>
      </div>

      <label className="row" style={{ cursor: "pointer", fontWeight: 400, color: "var(--text)", marginBottom: 8 }}>
        <input type="checkbox" style={{ width: "auto" }} checked={Boolean(draft.monitored)}
               onChange={(e) => setDraft({ ...draft, monitored: e.target.checked ? 1 : 0 })} />
        Dauerhaft überwachen (alle paar Sekunden prüfen)
      </label>
      {Boolean(draft.monitored) && (
        <div className="field">
          <label htmlFor="device-ports">Zu prüfende Ports (optional, max. 3)</label>
          <input
            id="device-ports"
            placeholder="z. B. 443, 445 — leer = automatisch bzw. Ping"
            value={(draft.monitorPorts ?? []).join(", ")}
            onChange={(e) =>
              setDraft({
                ...draft,
                monitorPorts: e.target.value
                  .split(",")
                  .map((s) => Number(s.trim()))
                  .filter((n) => Number.isInteger(n) && n > 0 && n < 65536)
                  .slice(0, 3),
              })
            }
          />
          <div className="field-hint">
            Ein geprüfter Port sagt mehr als ein Ping: ein NAS, das auf Ping antwortet, während
            die Dateifreigabe tot ist, gilt sonst als „erreichbar".
          </div>
        </div>
      )}
      <div className="row">
        <button onClick={onSave} disabled={saving}>{saving ? "Speichere …" : "Speichern"}</button>
        <button className="secondary" onClick={onCancel} disabled={saving}>Abbrechen</button>
      </div>
    </>
  );
}
