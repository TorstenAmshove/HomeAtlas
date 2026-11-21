import type { ReactNode } from "react";
import { useDocumentChrome, useResolvedTheme } from "../shell/AppShell";
import { useUi } from "../shell/ui";
import "./gates.css";

/**
 * Frame of the gates (login, MFA enrollment, setup wizard; PR 7 of
 * docs/redesign/5-information-architecture.md). They run before the app, so they are not inside
 * `.app-shell`: their tokens live in gates.css under `body:has(.gate-shell)`, with the same values
 * as the shell.
 *
 * Light/dark follows the same per-browser preference as the shell (`shell/prefs.ts`, "System"
 * unless chosen otherwise). Only the logo and "HomeAtlas" are shown: the household name is not
 * public (the gates may only use `/api/health`), so it appears only once the wizard knows it.
 */
export default function GateShell({ wide = false, children }: { wide?: boolean; children: ReactNode }) {
  const theme = useResolvedTheme(useUi().themeMode);
  useDocumentChrome(theme);
  return (
    <div className="gate-shell" data-theme={theme}>
      <main className={`gate-card${wide ? " gate-card-wide" : ""}`}>{children}</main>
    </div>
  );
}

/** Logo, product name and an optional line below it (e.g. "Angemeldet als …"). */
export function GateBrand({ title = "HomeAtlas", sub, aside }: { title?: string; sub?: ReactNode; aside?: ReactNode }) {
  return (
    <div className="gate-brand">
      <img src="/icon.svg" alt="" width={36} height={36} />
      <div className="gate-brand-text">
        <div className="gate-brand-name">{title}</div>
        {sub && <div className="gate-brand-sub">{sub}</div>}
      </div>
      {aside}
    </div>
  );
}
