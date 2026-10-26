"use client";

import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { DISEASE_LABEL, DISEASE_ORDER, diseaseColor } from "@/lib/viz";
import { fmtCompact, fmtDate, fmtInt } from "@/lib/utils";

type Point = { date: string; values: Record<string, number> };

/** Daily cases by disease, smoothed with a trailing 7-day mean. "Indexed" puts diseases of very
 * different size on one common base (100 = disease's own mean over the window) instead of a second axis. */
export function TrendChart({ data }: { data: Point[] }) {
  const [mode, setMode] = useState<"counts" | "indexed">("counts");
  const [view, setView] = useState<"chart" | "table">("chart");
  const diseases = DISEASE_ORDER.filter((d) => data.some((p) => d in p.values));

  const rows = useMemo(() => {
    const smoothed = data.map((p, i) => {
      const win = data.slice(Math.max(0, i - 6), i + 1);
      const row: Record<string, number | string> = { date: p.date };
      for (const d of diseases) row[d] = win.reduce((s, q) => s + (q.values[d] ?? 0), 0) / win.length;
      return row;
    });
    if (mode === "counts") return smoothed;
    const means = Object.fromEntries(
      diseases.map((d) => [d, smoothed.reduce((s, r) => s + (r[d] as number), 0) / Math.max(smoothed.length, 1) || 1]),
    );
    return smoothed.map((r) => ({ ...r, ...Object.fromEntries(diseases.map((d) => [d, ((r[d] as number) / means[d]) * 100])) }));
  }, [data, diseases, mode]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border p-0.5" role="group" aria-label="Scale">
          {(["counts", "indexed"] as const).map((m) => (
            <Button key={m} size="sm" variant={mode === m ? "secondary" : "ghost"} onClick={() => setMode(m)} className="h-7">
              {m === "counts" ? "Cases (7-day avg)" : "Indexed (100 = mean)"}
            </Button>
          ))}
        </div>
        <Button size="sm" variant="ghost" className="ml-auto h-7" onClick={() => setView(view === "chart" ? "table" : "chart")}>
          {view === "chart" ? "Table view" : "Chart view"}
        </Button>
      </div>
      {view === "chart" ? (
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--viz-grid)" vertical={false} />
              <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: "var(--viz-axis)", fontSize: 11 }} tickLine={false}
                axisLine={{ stroke: "var(--viz-grid)" }} minTickGap={40} />
              <YAxis tickFormatter={fmtCompact} tick={{ fill: "var(--viz-axis)", fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
              <Tooltip
                cursor={{ stroke: "var(--viz-axis)", strokeDasharray: "3 3" }}
                contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                itemStyle={{ color: "hsl(var(--foreground))" }}
                labelFormatter={(l) => fmtDate(String(l))}
                formatter={(v, name) => [mode === "counts" ? fmtInt(Number(v)) : Number(v).toFixed(0), DISEASE_LABEL[String(name)] ?? name]}
              />
              <Legend formatter={(v: string) => <span className="text-xs text-foreground">{DISEASE_LABEL[v] ?? v}</span>} iconType="plainline" />
              {diseases.map((d) => (
                <Line key={d} type="monotone" dataKey={d} stroke={diseaseColor(d)} strokeWidth={2} dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--viz-surface)" }} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="max-h-72 overflow-y-auto">
          <Table>
            <THead>
              <TR>
                <TH>Date</TH>
                {diseases.map((d) => <TH key={d} className="text-right">{DISEASE_LABEL[d]}</TH>)}
              </TR>
            </THead>
            <TBody>
              {[...rows].reverse().map((r) => (
                <TR key={r.date as string}>
                  <TD>{fmtDate(r.date as string)}</TD>
                  {diseases.map((d) => <TD key={d} className="text-right tabular-nums">{fmtInt(r[d] as number)}</TD>)}
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      )}
    </div>
  );
}
