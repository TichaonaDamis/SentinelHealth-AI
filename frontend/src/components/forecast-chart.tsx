"use client";

import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Forecast } from "@/lib/types";
import { fmtCompact, fmtDate, fmtInt } from "@/lib/utils";

/** Observed 7-day average, then the forecast mean (dashed) with its 80% conformal interval band. */
export function ForecastChart({ forecast, height = 280 }: { forecast: Forecast; height?: number }) {
  type Row = { date: string; observed?: number; forecast?: number; band?: [number, number] };
  const rows: Row[] = [
    ...forecast.history.map((p) => ({ date: p.date, observed: p.mean })),
    ...forecast.path.map((p) => ({ date: p.date, forecast: p.mean, band: [p.lower, p.upper] as [number, number] })),
  ];
  // Connect the forecast line to the last observation.
  const last = forecast.history.at(-1);
  if (last) Object.assign(rows[forecast.history.length - 1], { forecast: last.mean, band: [last.mean, last.mean] });

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--viz-grid)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: "var(--viz-axis)", fontSize: 11 }} tickLine={false}
            axisLine={{ stroke: "var(--viz-grid)" }} minTickGap={36} />
          <YAxis tickFormatter={fmtCompact} tick={{ fill: "var(--viz-axis)", fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
          <Tooltip
            contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                itemStyle={{ color: "hsl(var(--foreground))" }}
            labelFormatter={(l) => fmtDate(String(l))}
            formatter={(v, name) =>
              Array.isArray(v)
                ? [`${fmtInt(Number(v[0]))} – ${fmtInt(Number(v[1]))}`, "80% interval"]
                : [fmtInt(Number(v)), name === "observed" ? "Observed (7-day avg)" : "Forecast"]
            }
          />
          <ReferenceLine x={forecast.origin_date} stroke="var(--viz-axis)" strokeDasharray="2 4"
            label={{ value: "today", position: "insideTopLeft", fill: "var(--viz-axis)", fontSize: 11 }} />
          <Area dataKey="band" stroke="none" fill="var(--series-1)" fillOpacity={0.15} isAnimationActive={false} />
          <Line dataKey="observed" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="forecast" stroke="var(--series-1)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
