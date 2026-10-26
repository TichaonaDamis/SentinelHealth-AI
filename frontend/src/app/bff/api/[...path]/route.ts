import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { API_URL, TOKEN_COOKIE } from "@/lib/server-config";

/** Authenticated proxy: browser -> /bff/api/<path> -> API /api/v1/<path> with the session token attached. */
async function proxy(req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "not authenticated" }, { status: 401 });
  const { path } = await params;
  if (path.some((p) => p === ".." || p.includes("/"))) return NextResponse.json({ detail: "bad path" }, { status: 400 });
  const url = new URL(req.url);
  const target = `${API_URL}/api/v1/${path.map(encodeURIComponent).join("/")}${url.search}`;
  const init: RequestInit = {
    method: req.method,
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": req.headers.get("content-type") ?? "application/json",
      "x-forwarded-for": req.headers.get("x-forwarded-for") ?? "",
      "user-agent": req.headers.get("user-agent") ?? "sentinel-web",
    },
    cache: "no-store",
  };
  if (!["GET", "HEAD"].includes(req.method)) init.body = await req.text();
  const res = await fetch(target, init);
  const body = await res.text();
  const out = new NextResponse(body, { status: res.status, headers: { "content-type": res.headers.get("content-type") ?? "application/json" } });
  if (res.status === 401) out.cookies.set(TOKEN_COOKIE, "", { path: "/", maxAge: 0 });
  return out;
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
