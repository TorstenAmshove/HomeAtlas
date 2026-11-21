import { createHmac } from "node:crypto";

// Shared by smoke.spec.ts and gates-calm.spec.ts.

export const USERNAME = process.env.SMOKE_ADMIN_USERNAME || "admin";
export const PASSWORD = process.env.SMOKE_ADMIN_PASSWORD || "";

// Second admin, created by smoke.spec.ts at its end for gates-calm.spec.ts: every walk through the
// gates enrolls its user, and the first admin is already enrolled by then. The suffix keeps the
// password policy satisfied (upper case, symbol) whatever SMOKE_ADMIN_PASSWORD is.
export const CALM_USERNAME = "calm-admin";
export const CALM_PASSWORD = `${PASSWORD}-Calm9`;

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
// backend verifies. Inline so the test needs no extra dependency.
export function totp(secret: string, now = Date.now()): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 1000 / 30)));
  const hmac = createHmac("sha1", base32Decode(secret)).update(counter).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return code.toString().padStart(6, "0");
}

/**
 * A code from a 30 s window after the one containing `usedAtMs`. TOTP codes are single-use, so a
 * second login with the same secret needs a window that has not been used; waiting for it (at most
 * ~30 s) is sturdier than relying on the server's +-1 step tolerance for the *next* window.
 */
export async function freshTotp(secret: string, usedAtMs: number): Promise<string> {
  const step = (ms: number) => Math.floor(ms / 30_000);
  const deadline = Date.now() + 32_000;
  while (step(Date.now()) <= step(usedAtMs)) {
    if (Date.now() > deadline) throw new Error("No new TOTP window began in time");
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return totp(secret);
}
