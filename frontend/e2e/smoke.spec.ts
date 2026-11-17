import { createHmac } from "node:crypto";
import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

// Browser smoke test for the built images (issue #32). It exists so that a dependency update that
// still type-checks and builds, but breaks rendering at runtime (white page), fails CI before
// Renovate auto-merges it. Walks a fresh backend through the same gating sequence a real first
// run takes (login -> MFA enrollment -> setup wizard -> app) and then renders a few routes,
// including a Markdown doc page (react-markdown + remark-gfm).
//
// Any console error or uncaught page error fails the test. The single expected one is the 401
// from /api/auth/me before anyone is logged in -- App.tsx treats that as "show the login page".

const USERNAME = process.env.SMOKE_ADMIN_USERNAME || "admin";
const PASSWORD = process.env.SMOKE_ADMIN_PASSWORD || "";

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of input.replace(/[\s=]/g, "").toUpperCase()) {
    const value = alphabet.indexOf(char);
    if (value < 0) throw new Error(`Invalid base32 character: ${char}`);
    bits += value.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

// RFC 6238 TOTP (SHA-1, 30 s, 6 digits) -- what every authenticator app computes, and what the
// backend's pyotp verifies. Inline so the test needs no extra dependency.
function totp(secret: string, now = Date.now()): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 1000 / 30)));
  const hmac = createHmac("sha1", base32Decode(secret)).update(counter).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return code.toString().padStart(6, "0");
}

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
    await expect(page.getByRole("heading", { level: 1, name: "Smoke-Test-Zuhause" })).toBeVisible();
    await expect(page.getByRole("link", { name: /Übersicht/ })).toBeVisible();
  });

  await test.step("documentation (Markdown)", async () => {
    // Without a scan there are no chapters yet; generate them without an LLM (none is configured).
    const response = await page.request.post("/api/docs/generate", { data: { useLlm: false } });
    expect(response.ok()).toBe(true);
    await page.getByRole("link", { name: /Dokumentation/ }).click();
    const chapter = page.locator('a.nav-link[href^="/dokumentation/"]').first();
    await expect(chapter).toBeVisible();
    await chapter.click();
    await expect(page.locator(".markdown").first()).toBeVisible();
    await expect(page.locator(".markdown :is(h1, h2, h3, p, li)").first()).toBeVisible();
  });

  await test.step("further routes", async () => {
    for (const [label, heading] of [
      ["Geräte", "Geräte"],
      ["Netzplan", "Netzplan und Diagnose"],
      ["Netze & WLAN", "Netze & WLAN"],
      ["Einstellungen", "Einstellungen"],
    ]) {
      await page.getByRole("link", { name: label, exact: false }).first().click();
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    }
  });

  expect(errors).toEqual([]);
});
