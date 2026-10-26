"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await fetch("/bff/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    setBusy(false);
    if (!res.ok) {
      setError("Incorrect email or password.");
      return;
    }
    const next = params.get("next");
    router.push(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <label htmlFor="email" className="text-sm font-medium">Work email</label>
        <Input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="password" className="text-sm font-medium">Password</label>
        <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </div>
      {error && <p className="text-sm text-[color:var(--status-critical)]" role="alert">{error}</p>}
      <Button type="submit" className="w-full" disabled={busy}>
        <Lock /> {busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="grid min-h-screen place-items-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-7">
        <div className="mb-6 flex items-center gap-2">
          <div className="grid size-9 place-items-center rounded-md bg-primary text-primary-foreground"><Activity className="size-5" /></div>
          <div>
            <div className="font-semibold">SentinelHealth AI</div>
            <div className="text-xs text-muted-foreground">Disease surveillance &amp; forecasting</div>
          </div>
        </div>
        <Suspense>
          <LoginForm />
        </Suspense>
        <p className="mt-6 text-[11px] leading-relaxed text-muted-foreground">
          Authorized public-health use only. Activity is logged and audited. Do not enter patient identifiers in free-text fields.
        </p>
      </Card>
    </div>
  );
}
