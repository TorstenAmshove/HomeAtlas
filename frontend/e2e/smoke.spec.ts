import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";
import { CALM_PASSWORD, CALM_USERNAME, PASSWORD, USERNAME, totp } from "./helpers";

// Browser smoke test for the built images (issue #32). It exists so that a dependency update that
// still type-checks and builds, but breaks rendering at runtime (white page), fails CI before
// Renovate auto-merges it. Walks a fresh backend through the same gating sequence a real first
// run takes (login -> MFA enrollment -> setup wizard -> app) and then renders a few routes,
// including a Markdown doc page (react-markdown + remark-gfm).
//
// Any console error or uncaught page error fails the test. The single expected one is the 401
// from /api/auth/me before anyone is logged in -- App.tsx treats that as "show the login page".

function isExpected401(msg: ConsoleMessage): boolean {
  return /status of 401/.test(msg.text()) && /\/api\/auth\/me$/.test(msg.location().url);
}

// Module-level so the afterEach hook can report them: a render crash usually surfaces first as a
// locator timeout ("element not found"), and the actual exception is what someone needs to see.
const errors: string[] = [];

function collectErrors(page: Page): void {
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isExpected401(msg)) {
      errors.push(`console: ${msg.text()} (${msg.location().url})`);
    }
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
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

  await test.step("login page", async () => {
    await page.goto("/");
    await page.getByLabel("Benutzername").fill(USERNAME);
    await page.getByLabel("Passwort").fill(PASSWORD);
    await page.getByRole("button", { name: "Anmelden" }).click();
  });

  await test.step("MFA enrollment", async () => {
    await page.getByRole("button", { name: "Einrichtung starten" }).click();
    const secret = (await page.locator("code.mono").first().innerText()).trim();
    expect(secret).toMatch(/^[A-Z2-7]+=*$/);
    await page.getByPlaceholder("6-stellig").fill(totp(secret));
    await page.getByRole("button", { name: "Aktivieren" }).click();
  });

  await test.step("setup wizard", async () => {
    await expect(page.getByRole("heading", { name: /Willkommen bei HomeAtlas/ })).toBeVisible();
    await page.getByLabel("Wie soll dein Zuhause heißen?").fill("Smoke-Test-Zuhause");
    await page.getByRole("button", { name: "Weiter", exact: true }).click();
    await page.getByRole("button", { name: "Weiter", exact: true }).click();
    await page.getByRole("button", { name: /Fertig/ }).click();
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
      await expect(page.locator("main h1, main h2").first()).toBeVisible();
    }
    await page.locator(".app-shell").getByRole("link", { name: "Geräte", exact: true }).first().click();
    await expect(page).toHaveURL(/\/geraete$/);
  });

  await test.step("new UI: Hilfe opens the assistant first", async () => {
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

  await test.step("new UI: assistant creates no empty conversation and deletes with confirmation", async () => {
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

  await test.step("new UI: device search survives opening a device and Back", async () => {
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

  await test.step("new UI: the device selection follows the visible list", async () => {
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

  await test.step("new UI: chat text typed while the conversations load is kept", async () => {
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

  await test.step("new UI: a doc draft survives switching chapters", async () => {
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

  await test.step("new UI: device tab and edit draft survive reload and Back", async () => {
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

  await test.step("?ui=classic after login still shows the new shell", async () => {
    await page.goto("/?ui=classic");
    await expect(page.locator(".app-shell")).toBeVisible();
  });

  await test.step("hand-over to gates-calm.spec.ts", async () => {
    // The calm gates test runs after this one (playwright.config.ts, project dependency) against the
    // same backend. It needs an admin that has not enrolled MFA yet and an open setup, so both are
    // prepared here through the regular admin API.
    const created = await page.request.post("/api/users", {
      data: { username: CALM_USERNAME, password: CALM_PASSWORD, role: "ADMIN", displayName: "Calm-Test" },
    });
    expect(created.ok(), await created.text()).toBe(true);
    const reopened = await page.request.patch("/api/settings", { data: { setupCompleted: false } });
    expect(reopened.ok()).toBe(true);
  });

  expect(errors).toEqual([]);
});
