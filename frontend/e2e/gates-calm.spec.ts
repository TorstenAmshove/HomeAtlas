import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";
import { CALM_PASSWORD, CALM_USERNAME, PASSWORD, freshTotp, totp } from "./helpers";

// The redesigned gates (login -> MFA enrollment -> setup wizard, docs/redesign PR 7) on the same
// fresh backend as smoke.spec.ts, which runs first (project dependency in playwright.config.ts) and
// leaves behind a second, not yet enrolled admin plus an open setup. This browser opts into the new
// UI the way a person would (`homeatlas.ui=calm` in localStorage); the instance switch stays off.
//
// Besides the happy path it checks the ways out and the error texts: a wrong password and a wrong
// code show an error, "Abmelden" works in MFA and in setup, a reload keeps the wizard's entries --
// and neither a password nor the TOTP secret ever lands in browser storage.

// Expected failures of this walk-through; anything else on the console fails the test.
function isExpected(msg: ConsoleMessage): boolean {
  const url = msg.location().url;
  if (!/status of (400|401)/.test(msg.text())) return false;
  return /\/api\/auth\/me$/.test(url) || /\/api\/auth\/login$/.test(url) || /\/api\/auth\/mfa\/confirm$/.test(url);
}

const errors: string[] = [];

function collectErrors(page: Page): void {
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isExpected(msg)) errors.push(`console: ${msg.text()} (${msg.location().url})`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
}

/** Everything this origin keeps in browser storage, as one string to search in. */
async function storageDump(page: Page): Promise<string> {
  return page.evaluate(() => {
    const dump = (s: Storage) => Array.from({ length: s.length }, (_, i) => `${s.key(i)}=${s.getItem(s.key(i)!)}`).join("\n");
    return `${dump(window.sessionStorage)}\n${dump(window.localStorage)}`;
  });
}

test.afterEach(async ({}, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus && errors.length) {
    console.error(`Browser errors during the calm gates test:\n  ${errors.join("\n  ")}`);
    await testInfo.attach("browser-errors", { body: errors.join("\n"), contentType: "text/plain" });
  }
});

test("calm gates: login, MFA enrollment and setup with their ways out", async ({ page }) => {
  expect(PASSWORD, "SMOKE_ADMIN_PASSWORD must be set").not.toBe("");
  collectErrors(page);
  await page.addInitScript(() => window.localStorage.setItem("homeatlas.ui", "calm"));

  const gate = page.locator(".gate-shell");
  const alert = gate.getByRole("alert");
  const username = gate.getByLabel("Benutzername");
  const password = gate.getByLabel("Passwort", { exact: true });
  let secret = "";
  let enrolledAt = 0; // when the enrollment code was computed: its 30 s window is used up
  let setupPosts = 0;
  page.on("request", (req) => {
    if (req.method() === "POST" && /\/api\/setup$/.test(req.url())) setupPosts += 1;
  });

  async function login() {
    await username.fill(CALM_USERNAME);
    await password.fill(CALM_PASSWORD);
    await password.press("Enter");
  }

  await test.step("login: wrong password, show/hide, Enter submits", async () => {
    await page.goto("/");
    await expect(gate).toBeVisible();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    await expect(username).toHaveAttribute("autocomplete", "username");
    await expect(password).toHaveAttribute("autocomplete", "current-password");

    await username.fill(CALM_USERNAME);
    await password.fill("ganz-falsches-Passwort-1");
    await gate.getByRole("button", { name: "Passwort anzeigen" }).click();
    await expect(password).toHaveAttribute("type", "text");
    await gate.getByRole("button", { name: "Passwort verbergen" }).click();
    await expect(password).toHaveAttribute("type", "password");
    await password.press("Enter");
    await expect(alert).toContainText("stimmt nicht");
    await expect(password).toHaveValue("");

    await password.fill(CALM_PASSWORD);
    await password.press("Enter");
    await expect(page.getByRole("heading", { name: "Zwei-Faktor-Anmeldung einrichten" })).toBeVisible();
  });

  await test.step("MFA: Abmelden is a way out", async () => {
    await gate.getByRole("button", { name: "Abmelden" }).click();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    await login();
    await expect(page.getByRole("heading", { name: "Zwei-Faktor-Anmeldung einrichten" })).toBeVisible();
  });

  await test.step("MFA: wrong code, then enrollment", async () => {
    await gate.getByRole("button", { name: "Einrichtung starten" }).click();
    await expect(gate.locator(".gate-qr svg")).toBeVisible();
    secret = (await gate.locator(".gate-secret").innerText()).replace(/\s/g, "");
    expect(secret).toMatch(/^[A-Z2-7]+=*$/);
    expect(await storageDump(page)).not.toContain(secret);

    const code = gate.getByLabel("Code aus der Authenticator-App");
    await expect(code).toHaveAttribute("inputmode", "numeric");
    await expect(code).toHaveAttribute("autocomplete", "one-time-code");
    const valid = [-30_000, 0, 30_000].map((d) => totp(secret, Date.now() + d));
    const wrong = ["000000", "111111", "222222", "333333"].find((c) => !valid.includes(c))!;
    await code.fill(wrong);
    await code.press("Enter");
    await expect(alert).toContainText("stimmt nicht");

    enrolledAt = Date.now();
    await code.fill(totp(secret, enrolledAt));
    await gate.getByRole("button", { name: "Aktivieren" }).click();
    await expect(page.getByRole("heading", { name: "Willkommen bei HomeAtlas" })).toBeVisible();
  });

  await test.step("setup: Abmelden asks, can be cancelled, and logs out", async () => {
    await gate.getByLabel("Wie soll dein Zuhause heißen?").fill("Calm-Zuhause");
    await gate.getByRole("button", { name: "Abmelden" }).click();
    await expect(page.getByRole("alertdialog", { name: "Abmelden?" })).toBeVisible();
    await page.getByRole("button", { name: "Angemeldet bleiben" }).click();
    await expect(gate.getByLabel("Wie soll dein Zuhause heißen?")).toHaveValue("Calm-Zuhause");

    await gate.getByRole("button", { name: "Abmelden" }).click();
    await page.getByRole("button", { name: "Trotzdem abmelden" }).click();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    expect(await storageDump(page)).not.toContain("Calm-Zuhause");

    // Back in: the factor is active now, so the code field appears. The enrollment code's time step
    // is used up (codes are single-use), so wait for the next window and use its current code.
    await login();
    const code = gate.getByLabel("Code aus der Authenticator-App");
    await code.fill(await freshTotp(secret, enrolledAt));
    await code.press("Enter");
    await expect(page.getByRole("heading", { name: "Willkommen bei HomeAtlas" })).toBeVisible();
    await expect(gate.getByLabel("Wie soll dein Zuhause heißen?")).toHaveValue("Mein Zuhause");
  });

  await test.step("setup: entries survive a reload, passwords are never stored", async () => {
    await expect(gate.locator('.gate-steps [aria-current="step"]')).toContainText("Zuhause");
    await gate.getByLabel("Wie soll dein Zuhause heißen?").fill("Calm-Zuhause");
    await gate.getByLabel("Wie soll dein Zuhause heißen?").press("Enter");
    await expect(page.getByRole("heading", { name: "Die wichtigsten Geräte" })).toBeVisible();
    await gate.getByLabel("Name", { exact: true }).fill("Calm-Router");
    await gate.getByLabel("Passwort (optional)").fill("Router-Geheim-42");

    await page.reload();
    await expect(page.getByRole("heading", { name: "Die wichtigsten Geräte" })).toBeVisible();
    await expect(gate.getByLabel("Name", { exact: true })).toHaveValue("Calm-Router");
    await expect(gate.getByLabel("Passwort (optional)")).toHaveValue("");
    await expect(gate.getByText("Passwörter und Notizen werden aus Sicherheitsgründen nicht zwischengespeichert")).toBeVisible();
    const stored = await storageDump(page);
    expect(stored).toContain("Calm-Router");
    expect(stored).not.toContain("Router-Geheim-42");
    expect(stored).not.toContain(secret);
    expect(stored).not.toContain(CALM_PASSWORD);

    await gate.getByRole("button", { name: "Zurück" }).click();
    await expect(gate.getByLabel("Wie soll dein Zuhause heißen?")).toHaveValue("Calm-Zuhause");
    await gate.getByRole("button", { name: "Weiter", exact: true }).click();
    await gate.getByRole("button", { name: "Weiter", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Wichtige Konten" })).toBeVisible();
    await gate.getByLabel("Passwort", { exact: true }).fill("Konto-Geheim-7");
    await gate.getByLabel("Benutzername / Kundennummer").fill("Kunde-4711");
    await gate.getByLabel("Notiz (optional)").fill("Hotline 0800 123");
    const typed = await storageDump(page);
    expect(typed).not.toContain("Konto-Geheim-7");
    expect(typed).not.toContain("Hotline 0800 123");

    // Notes are dropped on reload like passwords (people put access hints there); the user name stays.
    await page.reload();
    await expect(page.getByRole("heading", { name: "Wichtige Konten" })).toBeVisible();
    await expect(gate.getByLabel("Notiz (optional)")).toHaveValue("");
    await expect(gate.getByLabel("Passwort", { exact: true })).toHaveValue("");
    await expect(gate.getByLabel("Benutzername / Kundennummer")).toHaveValue("Kunde-4711");
    await expect(gate.getByText("Passwörter und Notizen werden aus Sicherheitsgründen nicht zwischengespeichert")).toBeVisible();
    expect(await storageDump(page)).not.toContain("Hotline 0800 123");
  });

  await test.step("setup: a double click on Weiter does not finish the setup", async () => {
    await gate.getByRole("button", { name: "Zurück" }).click();
    await expect(page.getByRole("heading", { name: "Die wichtigsten Geräte" })).toBeVisible();
    await gate.getByRole("button", { name: "Weiter", exact: true }).dblclick();
    await expect(page.getByRole("heading", { name: "Wichtige Konten" })).toBeVisible();
    await expect(gate.getByRole("button", { name: /Fertig/ })).toBeVisible();
    expect(setupPosts).toBe(0);
  });

  await test.step("setup done: the calm Start page", async () => {
    // A double click on "Fertig" sends POST /api/setup once (busy/disabled guard).
    await gate.getByRole("button", { name: /Fertig/ }).dblclick();
    await expect(page.locator(".app-shell")).toBeVisible();
    expect(setupPosts).toBe(1);
    await expect(page.locator("#start-hero-title")).toBeVisible();
    expect(await storageDump(page)).not.toContain("Calm-Router");
  });

  expect(errors).toEqual([]);
});
