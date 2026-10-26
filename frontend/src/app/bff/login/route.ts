import { NextResponse } from "next/server";
import { API_URL, TOKEN_COOKIE } from "@/lib/server-config";

/**
 * Exchanges credentials for an API token and stores it in an httpOnly, Secure, SameSite=Strict
 * cookie. The token is never exposed to browser JavaScript (mitigates XSS token theft).
 */
export async function POST(req: Request) {
  const { email, password } = (await req.json()) as { email?: string; password?: string };
  if (!email || !password) return NextResponse.json({ detail: "email and password required" }, { status: 400 });
  const res = await fetch(`${API_URL}/api/v1/auth/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", "x-forwarded-for": req.headers.get("x-forwarded-for") ?? "" },
    body: new URLSearchParams({ username: email, password }),
    cache: "no-store",
  });
  if (!res.ok) return NextResponse.json({ detail: "Incorrect email or password" }, { status: 401 });
  const { access_token, expires_in } = (await res.json()) as { access_token: string; expires_in: number };
  const out = NextResponse.json({ ok: true });
  out.cookies.set(TOKEN_COOKIE, access_token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: expires_in,
  });
  return out;
}
