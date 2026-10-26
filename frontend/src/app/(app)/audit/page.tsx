"use client";

import { useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface AuditRow {
  id: number;
  occurred_at: string;
  user_email: string | null;
  role: string | null;
  action: string;
  resource: string | null;
  method: string | null;
  path: string | null;
  status_code: number | null;
  ip_address: string | null;
}

export default function AuditPage() {
  const [user, setUser] = useState("");
  const [action, setAction] = useState("");
  const params = new URLSearchParams({ limit: "300", ...(user && { user_email: user }), ...(action && { action }) });
  const { data, error } = useApi<AuditRow[]>(`admin/audit-logs?${params}`);

  return (
    <>
      <PageHeader title="Audit log" description="Append-only record of every API access (HIPAA §164.312(b)). Also archived to an Object Lock bucket.">
        <Input placeholder="Filter by user email" value={user} onChange={(e) => setUser(e.target.value)} className="w-56" />
        <Input placeholder="Action prefix (e.g. denied)" value={action} onChange={(e) => setAction(e.target.value)} className="w-56" />
      </PageHeader>
      <Card>
        {error && <p className="p-4 text-sm">{error}</p>}
        {!data && !error ? <div className="p-4"><Skeleton className="h-96" /></div> : (
          <Table>
            <THead><TR><TH>Time</TH><TH>User</TH><TH>Action</TH><TH>Request</TH><TH className="text-right">Status</TH><TH>IP</TH></TR></THead>
            <TBody>
              {(data ?? []).map((r) => (
                <TR key={r.id}>
                  <TD className="whitespace-nowrap text-muted-foreground">{fmtDateTime(r.occurred_at)}</TD>
                  <TD>{r.user_email ?? "anonymous"}{r.role && <span className="block text-xs text-muted-foreground">{r.role}</span>}</TD>
                  <TD className="font-mono text-xs">{r.action}{r.resource && <span className="block text-muted-foreground">{r.resource}</span>}</TD>
                  <TD className="max-w-xs truncate font-mono text-xs">{r.method} {r.path}</TD>
                  <TD className="text-right tabular-nums">{r.status_code}</TD>
                  <TD className="font-mono text-xs text-muted-foreground">{r.ip_address}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
