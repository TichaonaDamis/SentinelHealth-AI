"use client";

import { Fragment, useState } from "react";
import { Check, CheckCheck, X } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { RiskBadge } from "@/components/risk-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, useApi } from "@/lib/api";
import type { Alert } from "@/lib/types";
import { DISEASE_LABEL } from "@/lib/viz";
import { fmtDateTime } from "@/lib/utils";

export default function AlertsPage() {
  const [status, setStatus] = useState("open");
  const [level, setLevel] = useState("");
  const params = new URLSearchParams({ limit: "200", ...(status && { status }), ...(level && { level }) });
  const { data, loading, error, reload } = useApi<Alert[]>(`alerts?${params}`);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function update(id: string, next: "acknowledged" | "resolved" | "dismissed") {
    const note = next === "acknowledged" ? undefined : window.prompt(`Note for ${next} (optional)`) ?? undefined;
    setBusy(id);
    try {
      await api(`alerts/${id}`, { method: "PATCH", body: JSON.stringify({ status: next, note }) });
      await reload();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader title="Alerts" description="Triage queue for outbreak signals. Every action is recorded in the audit log.">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status" className="w-40">
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
          <option value="dismissed">Dismissed</option>
        </Select>
        <Select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Level" className="w-36">
          <option value="">All levels</option>
          <option value="red">Red</option>
          <option value="orange">Orange</option>
          <option value="yellow">Yellow</option>
        </Select>
      </PageHeader>
      <Card>
        {error && <p className="p-4 text-sm">{error}</p>}
        {loading && !data ? (
          <div className="p-4"><Skeleton className="h-64" /></div>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Level</TH>
                <TH>Alert</TH>
                <TH>Disease</TH>
                <TH>Raised</TH>
                <TH>Status</TH>
                <TH>Notified</TH>
                <TH className="text-right">Actions</TH>
              </TR>
            </THead>
            <TBody>
              {(data ?? []).map((a) => (
                <Fragment key={a.id}>
                  <TR className="cursor-pointer" onClick={() => setExpanded(expanded === a.id ? null : a.id)}>
                    <TD><RiskBadge level={a.risk_level} /></TD>
                    <TD className="max-w-md font-medium">{a.title.replace(/^\w+ alert: /, "")}</TD>
                    <TD>{DISEASE_LABEL[a.disease_code] ?? a.disease_code}</TD>
                    <TD className="whitespace-nowrap text-muted-foreground">{fmtDateTime(a.created_at)}</TD>
                    <TD className="capitalize">{a.status}{a.acknowledged_by ? <span className="block text-xs text-muted-foreground">{a.acknowledged_by}</span> : null}</TD>
                    <TD className="text-xs text-muted-foreground">{(a.audiences ?? []).map((x) => x.replaceAll("_", " ")).join(", ")}</TD>
                    <TD className="text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="inline-flex gap-1">
                        {a.status === "open" && (
                          <Button size="sm" variant="outline" disabled={busy === a.id} onClick={() => update(a.id, "acknowledged")}><Check /> Ack</Button>
                        )}
                        {a.status !== "resolved" && a.status !== "dismissed" && (
                          <>
                            <Button size="sm" variant="outline" disabled={busy === a.id} onClick={() => update(a.id, "resolved")}><CheckCheck /> Resolve</Button>
                            <Button size="sm" variant="ghost" disabled={busy === a.id} onClick={() => update(a.id, "dismissed")} aria-label="Dismiss"><X /></Button>
                          </>
                        )}
                      </div>
                    </TD>
                  </TR>
                  {expanded === a.id && (
                    <TR className="bg-muted/30 hover:bg-muted/30">
                      <TD colSpan={7}>
                        <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{a.message}</pre>
                        {a.resolution_note && <p className="mt-2 text-xs text-muted-foreground">Note: {a.resolution_note}</p>}
                      </TD>
                    </TR>
                  )}
                </Fragment>
              ))}
              {data && data.length === 0 && (
                <TR><TD colSpan={7} className="py-10 text-center text-muted-foreground">No alerts match these filters.</TD></TR>
              )}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
