import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";
import { PASSWORD, USERNAME, freshTotp, totp } from "./helpers";

// Browser smoke test for the built images (issue #32). It exists so that a dependency update that
// still type-checks and builds, but breaks rendering at runtime (white page), fails CI before
// Renovate auto-merges it. Walks a fresh backend through the gating sequence a real first run takes
// (login -> MFA enrollment -> setup wizard -> app), then renders a few routes, including a Markdown
// doc page (react-markdown + remark-gfm), and logs out.
//
// Besides the happy path it checks the ways out and the error texts of the gates: a wrong password
// and a wrong code show an error, "Abmelden" works in MFA and in setup, a reload keeps the wizard's
// entries -- and neither a password nor the TOTP secret ever lands in browser storage.
//
// Any console error or uncaught page error fails the test, except the expected 400/401 answers of
// this walk-through (/api/auth/me before login, a wrong password or code).

function isExpected(msg: ConsoleMessage): boolean {
  const url = msg.location().url;
  if (!/status of (400|401)/.test(msg.text())) return false;
  return /\/api\/auth\/me$/.test(url) || /\/api\/auth\/login$/.test(url) || /\/api\/auth\/mfa\/confirm$/.test(url);
}

// Module-level so the afterEach hook can report them: a render crash usually surfaces first as a
// locator timeout ("element not found"), and the actual exception is what someone needs to see.
const errors: string[] = [];

function collectErrors(page: Page): void {
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isExpected(msg)) {
      errors.push(`console: ${msg.text()} (${msg.location().url})`);
    }
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
    console.error(`Browser errors during the smoke test:\n  ${errors.join("\n  ")}`);
    await testInfo.attach("browser-errors", { body: errors.join("\n"), contentType: "text/plain" });
  }
});

test("login, MFA enrollment, setup and main routes render without errors", async ({ page }) => {
  expect(PASSWORD, "SMOKE_ADMIN_PASSWORD must be set").not.toBe("");
  collectErrors(page);

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
    await username.fill(USERNAME);
    await password.fill(PASSWORD);
    await password.press("Enter");
  }

  await test.step("login: wrong password, show/hide, Enter submits", async () => {
    await page.goto("/");
    await expect(gate).toBeVisible();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    await expect(username).toHaveAttribute("autocomplete", "username");
    await expect(password).toHaveAttribute("autocomplete", "current-password");

    await username.fill(USERNAME);
    await password.fill("ganz-falsches-Passwort-1");
    await gate.getByRole("button", { name: "Passwort anzeigen" }).click();
    await expect(password).toHaveAttribute("type", "text");
    await gate.getByRole("button", { name: "Passwort verbergen" }).click();
    await expect(password).toHaveAttribute("type", "password");
    await password.press("Enter");
    await expect(alert).toContainText("stimmt nicht");
    await expect(password).toHaveValue("");

    await password.fill(PASSWORD);
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
    await gate.getByLabel("Wie soll dein Zuhause heißen?").fill("Smoke-Test-Zuhause");
    await gate.getByRole("button", { name: "Abmelden" }).click();
    await expect(page.getByRole("alertdialog", { name: "Abmelden?" })).toBeVisible();
    await page.getByRole("button", { name: "Angemeldet bleiben" }).click();
    await expect(gate.getByLabel("Wie soll dein Zuhause heißen?")).toHaveValue("Smoke-Test-Zuhause");

    await gate.getByRole("button", { name: "Abmelden" }).click();
    await page.getByRole("button", { name: "Trotzdem abmelden" }).click();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    expect(await storageDump(page)).not.toContain("Smoke-Test-Zuhause");

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
    await gate.getByLabel("Wie soll dein Zuhause heißen?").fill("Smoke-Test-Zuhause");
    await gate.getByLabel("Wie soll dein Zuhause heißen?").press("Enter");
    await expect(page.getByRole("heading", { name: "Die wichtigsten Geräte" })).toBeVisible();
    await gate.getByLabel("Name", { exact: true }).fill("Setup-Router");
    await gate.getByLabel("Passwort (optional)").fill("Router-Geheim-42");

    await page.reload();
    await expect(page.getByRole("heading", { name: "Die wichtigsten Geräte" })).toBeVisible();
    await expect(gate.getByLabel("Name", { exact: true })).toHaveValue("Setup-Router");
    await expect(gate.getByLabel("Passwort (optional)")).toHaveValue("");
    await expect(gate.getByText("Passwörter und Notizen werden aus Sicherheitsgründen nicht zwischengespeichert")).toBeVisible();
    const stored = await storageDump(page);
    expect(stored).toContain("Setup-Router");
    expect(stored).not.toContain("Router-Geheim-42");
    expect(stored).not.toContain(secret);
    expect(stored).not.toContain(PASSWORD);

    await gate.getByRole("button", { name: "Zurück" }).click();
    await expect(gate.getByLabel("Wie soll dein Zuhause heißen?")).toHaveValue("Smoke-Test-Zuhause");
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

  await test.step("setup done: the Start page", async () => {
    // A double click on "Fertig" sends POST /api/setup once (busy/disabled guard).
    await gate.getByRole("button", { name: /Fertig/ }).dblclick();
    await expect(page.locator(".app-shell")).toBeVisible();
    expect(setupPosts).toBe(1);
    await expect(page.locator("#start-hero-title")).toBeVisible();
    expect(await storageDump(page)).not.toContain("Setup-Router");
  });

  await test.step("dashboard", async () => {
    await expect(page.locator(".app-shell")).toBeVisible();
    await expect(page.locator("#start-hero-title")).toBeVisible();
  });

  await test.step("documentation (Markdown)", async () => {
    // Without a scan there are no chapters yet; generate them without an LLM (none is configured).
    const response = await page.request.post("/api/docs/generate", { data: { useLlm: false } });
    expect(response.ok()).toBe(true);
    await page.goto("/dokumentation");
    const chapter = page.locator("a.docs-toc-link").first();
    await expect(chapter).toBeVisible();
    await chapter.click();
    await expect(page.locator(".markdown").first()).toBeVisible();
    await expect(page.locator(".markdown :is(h1, h2, h3, p, li)").first()).toBeVisible();
  });

  await test.step("further routes", async () => {
    for (const path of ["/geraete", "/plan", "/netze", "/einstellungen"]) {
      await page.goto(path);
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.locator(".app-shell")).toBeVisible();
      await expect(page.locator("main h1, main h2, main .inv-list").first()).toBeVisible();
    }
    await page.locator(".app-shell").getByRole("link", { name: "Geräte", exact: true }).first().click();
    await expect(page).toHaveURL(/\/geraete$/);
  });

  await test.step("Hilfe opens the assistant first", async () => {
    await page.goto("/");
    await page.locator(".shell-side").getByRole("link", { name: "Hilfe", exact: true }).click();
    await expect(page).toHaveURL(/\/assistent$/);
    const tabs = page.getByRole("navigation", { name: "Hilfe: Bereiche" });
    await expect(tabs.getByRole("link").nth(0)).toHaveText("Assistent");
    await expect(tabs.getByRole("link").nth(0)).toHaveAttribute("aria-current", "page");
    await expect(tabs.getByRole("link").nth(1)).toHaveText("Dokumentation");
    await tabs.getByRole("link", { name: "Dokumentation" }).click();
    await expect(page).toHaveURL(/\/dokumentation/);
    await expect(page.locator(".shell-side").getByRole("link", { name: "Hilfe", exact: true })).toHaveAttribute("aria-current", "page");

    // Bottom bar (phone layout) takes the same entry.
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto("/");
    await page.locator(".shell-bottom").getByRole("link", { name: "Hilfe", exact: true }).click();
    await expect(page).toHaveURL(/\/assistent$/);
    await page.setViewportSize({ width: 1280, height: 720 });
  });

  await test.step("assistant creates no empty conversation and deletes with confirmation", async () => {
    const count = async () => ((await (await page.request.get("/api/chats")).json()) as { chats: unknown[] }).chats.length;
    const before = await count();
    const created = await page.request.post("/api/chats", { data: {} });
    expect(created.ok()).toBe(true);
    const chatId = ((await created.json()) as { chat: { id: string } }).chat.id;

    await page.goto("/assistent");
    await expect(page).toHaveURL(new RegExp(`/assistent/${chatId}$`));
    await page.getByRole("button", { name: "Neue Unterhaltung" }).click();
    await expect(page).toHaveURL(/\/assistent\/neu$/);
    await expect(page.getByRole("heading", { name: "Womit kann ich helfen?" })).toBeVisible();
    expect(await count()).toBe(before + 1);

    await page.goto(`/assistent/${chatId}`);
    await page.getByRole("button", { name: "Weitere Aktionen" }).click();
    await page.getByRole("menuitem", { name: "Unterhaltung löschen …" }).click();
    await page.getByRole("button", { name: "Abbrechen" }).click();
    expect(await count()).toBe(before + 1);

    await page.getByRole("button", { name: "Weitere Aktionen" }).click();
    await page.getByRole("menuitem", { name: "Unterhaltung löschen …" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Unterhaltung löschen" }).click();
    await expect(page.getByText("Unterhaltung gelöscht")).toBeVisible();
    expect(await count()).toBe(before);

    // Reload on the deleted id falls back without an error.
    await page.goto(`/assistent/${chatId}`);
    await expect(page.locator(".notice.error")).toHaveCount(0);
    await expect(page).not.toHaveURL(new RegExp(chatId));
  });

  await test.step("device search survives opening a device and Back", async () => {
    // A fresh backend has no devices; one created through the API is enough for the list.
    const created = await page.request.post("/api/systems", { data: { name: "Smoke-NAS", kind: "nas", ip: "192.0.2.10" } });
    expect(created.ok()).toBe(true);
    await page.goto("/geraete");
    const search = page.getByLabel("Geräte durchsuchen");
    await search.fill("Smoke");
    await expect(page).toHaveURL(/[?&]q=Smoke/);
    await page.locator(".inv-list").getByRole("link", { name: /Smoke-NAS/ }).click();
    await expect(page).toHaveURL(/\/geraete\/[^/?]+$/);
    await page.goBack();
    await expect(page).toHaveURL(/[?&]q=Smoke/);
    await expect(page.getByLabel("Geräte durchsuchen")).toHaveValue("Smoke");
    await expect(page.locator(".inv-list").getByRole("link", { name: /Smoke-NAS/ })).toBeVisible();

    // Filters and sort live in the URL too, including descending sorts the classic list produces.
    await page.goto("/geraete?importance=normal&sort=-ip");
    await expect(page.getByLabel("Sortieren")).toHaveValue("-ip");
    await page.locator(".inv-list").getByRole("link", { name: /Smoke-NAS/ }).click();
    await page.goBack();
    await expect(page).toHaveURL(/[?&]importance=normal/);
    await expect(page).toHaveURL(/[?&]sort=-ip/);
    await expect(page.getByLabel("Sortieren")).toHaveValue("-ip");

    // Column headers sort too: asc -> desc -> unsorted, in sync with `?sort=` and the sort menu.
    await page.goto("/geraete");
    for (const [label, key] of [["Gerät", "name"], ["Adresse", "ip"], ["Art", "kind"], ["Standort", "location"], ["Zustand", "status"]]) {
      const head = page.getByRole("columnheader", { name: label, exact: true });
      await head.getByRole("button").click();
      await expect(page).toHaveURL(new RegExp(`[?&]sort=${key}$`));
      await expect(head).toHaveAttribute("aria-sort", "ascending");
      await head.getByRole("button").click();
      await expect(page).toHaveURL(new RegExp(`[?&]sort=-${key}$`));
      await expect(head).toHaveAttribute("aria-sort", "descending");
      await expect(page.getByLabel("Sortieren")).toHaveValue(`-${key}`);
      await head.getByRole("button").click();
      await expect(page).not.toHaveURL(/[?&]sort=/);
      await expect(head).toHaveAttribute("aria-sort", "none");
    }

    // Subnet filter (no UniFi in the smoke run -> /24 groups); survives reload and Back.
    await page.goto("/geraete?subnet=192.0.2.0%2F24");
    await expect(page.locator(".inv-list").getByRole("link", { name: /Smoke-NAS/ })).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("Nach Netz filtern")).toHaveValue("192.0.2.0/24");
    await page.locator(".inv-list").getByRole("link", { name: /Smoke-NAS/ }).click();
    await page.goBack();
    await expect(page).toHaveURL(/[?&]subnet=192\.0\.2\.0%2F24/);
    await page.goto("/geraete?subnet=192.0.2.0%2F24&kind=router");
    await expect(page.locator(".inv-list").getByRole("link", { name: /Smoke-NAS/ })).toHaveCount(0);
    await page.goto("/geraete?subnet=198.51.100.0%2F24");
    await expect(page.getByText("Kein Gerät passt zu diesem Filter.")).toBeVisible();
    await page.getByRole("button", { name: "Filter zurücksetzen" }).click();
    await expect(page).not.toHaveURL(/subnet=/);
  });

  await test.step("the device selection follows the visible list", async () => {
    // Two selected, search hides one: the count drops to 1 and "Löschen …" names only the visible one.
    const created = await page.request.post("/api/systems", { data: { name: "Smoke-Drucker", kind: "printer", ip: "192.0.2.11" } });
    expect(created.ok()).toBe(true);
    const printerId = ((await created.json()) as { system: { id: string } }).system.id;
    try {
      await page.goto("/geraete");
      await page.getByRole("button", { name: "Auswählen", exact: true }).click();
      await page.getByLabel("Smoke-NAS auswählen").check();
      await page.getByLabel("Smoke-Drucker auswählen").check();
      const bar = page.getByRole("region", { name: "Auswahl" });
      await expect(bar.locator(".inv-selectbar-count")).toHaveText("2 ausgewählt");
      await page.getByLabel("Geräte durchsuchen").fill("Smoke-NAS");
      await expect(bar.locator(".inv-selectbar-count")).toHaveText("1 ausgewählt");
      await bar.getByRole("button", { name: "Löschen …" }).click();
      const dialog = page.getByRole("alertdialog");
      await expect(dialog).toContainText("Smoke-NAS");
      await expect(dialog).not.toContainText("Smoke-Drucker");
      await dialog.getByRole("button", { name: "Abbrechen" }).click();
    } finally {
      await page.request.delete(`/api/systems/${printerId}`);
    }
  });

  await test.step("chat text typed while the conversations load is kept", async () => {
    const created = await page.request.post("/api/chats", { data: {} });
    expect(created.ok()).toBe(true);
    const chatId = ((await created.json()) as { chat: { id: string } }).chat.id;
    try {
      let open!: () => void;
      const gate = new Promise<void>((resolve) => { open = resolve; });
      await page.route("**/api/chats", async (route) => {
        if (route.request().method() === "GET") await gate;
        await route.continue();
      });
      await page.goto("/assistent");
      const question = page.getByLabel("Frage an den Assistenten");
      await question.fill("Ladesekunden-Frage");
      open();
      await expect(page).toHaveURL(new RegExp(`/assistent/[^/]+$`));
      await expect(page).not.toHaveURL(/\/assistent\/neu$/);
      await expect(question).toHaveValue("Ladesekunden-Frage");
      await page.unroute("**/api/chats");

      // Text typed on /assistent/neu stays out of an existing conversation.
      await page.goto("/assistent/neu");
      await page.getByLabel("Frage an den Assistenten").fill("nur-neu");
      await page.goto(`/assistent/${chatId}`);
      await expect(page.getByLabel("Frage an den Assistenten")).not.toHaveValue("nur-neu");
    } finally {
      await page.unroute("**/api/chats").catch(() => {});
      await page.request.delete(`/api/chats/${chatId}`);
    }
  });

  await test.step("a doc draft survives switching chapters", async () => {
    await page.goto("/dokumentation");
    const chapters = page.locator("a.docs-toc-link");
    await expect(chapters.nth(1)).toBeVisible();
    const firstHref = await chapters.nth(0).getAttribute("href");
    const secondHref = await chapters.nth(1).getAttribute("href");
    await chapters.nth(0).click();
    await expect(page).toHaveURL(new RegExp(`${firstHref}$`));
    await page.locator(".docs-actions").getByRole("button", { name: "Bearbeiten" }).click();
    const editor = page.locator("textarea.docs-textarea");
    await editor.fill("Smoke-Entwurf: bitte nicht verlieren");
    await page.locator(`a.docs-toc-link[href="${secondHref}"]`).click();
    await page.getByRole("button", { name: "Trotzdem wechseln" }).click();
    await expect(page).toHaveURL(new RegExp(`${secondHref}$`));
    await page.locator(`a.docs-toc-link[href="${firstHref}"]`).click();
    await expect(page.locator("textarea.docs-textarea")).toHaveValue("Smoke-Entwurf: bitte nicht verlieren");
    // Logging out would throw the draft away, so it asks first; staying keeps the session.
    await page.locator(".shell-side").getByRole("button", { name: "Abmelden" }).click();
    await expect(page.getByRole("alertdialog", { name: "Abmelden?" })).toBeVisible();
    await page.getByRole("button", { name: "Angemeldet bleiben" }).click();
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    // Discard the draft, so the next navigation is not held up by the "leave page?" prompt.
    await page.locator(".docs-actions").getByRole("button", { name: "Abbrechen" }).click();
  });

  await test.step("device tab and edit draft survive reload and Back", async () => {
    const list = await page.request.get("/api/systems");
    const device = ((await list.json()).systems as { id: string; name: string }[]).find((s) => s.name === "Smoke-NAS");
    expect(device, "Smoke-NAS from the device-search step").toBeTruthy();
    await page.goto(`/geraete/${device!.id}?tab=technik`);
    const technik = page.locator(".dv-tabs").getByRole("link", { name: "Technik" });
    await expect(technik).toHaveAttribute("aria-current", "page");
    await page.reload();
    await expect(technik).toHaveAttribute("aria-current", "page");

    await page.goto(`/geraete/${device!.id}?edit=1`);
    const name = page.locator("#device-name");
    await name.fill("Smoke-NAS-Entwurf");
    await page.goBack();
    // Back is not intercepted (no data router); if a leave prompt shows anyway, stay with the draft.
    const leave = page.getByRole("button", { name: "Trotzdem wechseln" });
    if (await leave.isVisible().catch(() => false)) await leave.click();
    await page.goForward();
    await expect(page.locator("#device-name")).toHaveValue("Smoke-NAS-Entwurf");
    // Discard, so later steps are not held up by the draft.
    await page.locator(".dv-edit").getByRole("button", { name: "Abbrechen" }).click();
    await expect(page.locator("#device-name")).toHaveCount(0);
  });

  await test.step("keys of the removed UI switch are cleaned up and ?ui=classic changes nothing", async () => {
    await page.evaluate(() => {
      window.localStorage.setItem("homeatlas.ui", "classic");
      window.localStorage.setItem("homeatlas.uiServer", "0");
    });
    await page.goto("/?ui=classic");
    await expect(page.locator(".app-shell")).toBeVisible();
    const stored = await storageDump(page);
    expect(stored).not.toContain("homeatlas.ui=");
    expect(stored).not.toContain("homeatlas.uiServer");
  });

  await test.step("settings: Darstellung is there without the UI switch", async () => {
    await page.goto("/einstellungen?tab=display");
    await expect(page.getByText("Farbmodus")).toBeVisible();
    await expect(page.getByText("Immer die bisherige Oberfläche")).toHaveCount(0);
    await page.goto("/einstellungen?tab=general");
    await expect(page.getByText("Neue Oberfläche")).toHaveCount(0);
  });

  await test.step("logout", async () => {
    await page.goto("/");
    await page.locator(".shell-side").getByRole("button", { name: "Abmelden" }).click();
    // Logout asks first while this tab still holds drafts (e.g. the wizard's); confirm if it does.
    const confirm = page.getByRole("button", { name: "Trotzdem abmelden" });
    if (await confirm.isVisible().catch(() => false)) await confirm.click();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    expect(await storageDump(page)).not.toContain(PASSWORD);
  });

  expect(errors).toEqual([]);
});
