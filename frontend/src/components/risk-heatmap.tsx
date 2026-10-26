"use client";

import type { RiskAssessment } from "@/lib/types";
import { DISEASE_LABEL, DISEASE_ORDER, DISEASE_SHORT, seqColor, seqInk } from "@/lib/viz";

/** Region x disease matrix of risk score (0–100), sequential blue ramp. Top regions by max score. */
export function RiskHeatmap({ data, maxRows = 14 }: { data: RiskAssessment[]; maxRows?: number }) {
  const diseases = DISEASE_ORDER.filter((d) => data.some((a) => a.disease_code === d));
  const byRegion = new Map<string, { name: string; state: string; cells: Record<string, RiskAssessment> }>();
  for (const a of data) {
    const row = byRegion.get(a.region_id) ?? { name: a.region_name, state: a.state, cells: {} };
    row.cells[a.disease_code] = a;
    byRegion.set(a.region_id, row);
  }
  const rows = [...byRegion.entries()]
    .map(([id, r]) => ({ id, ...r, max: Math.max(...Object.values(r.cells).map((c) => c.risk_score)) }))
    .sort((a, b) => b.max - a.max)
    .slice(0, maxRows);

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate" style={{ borderSpacing: 2 }}>
        <thead>
          <tr>
            <th className="text-left text-xs font-medium text-muted-foreground">Region</th>
            {diseases.map((d) => (
              <th key={d} className="px-1 text-center text-xs font-medium text-muted-foreground" title={DISEASE_LABEL[d]}>{DISEASE_SHORT[d]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="whitespace-nowrap pr-2 text-xs">{r.name}, {r.state}</td>
              {diseases.map((d) => {
                const c = r.cells[d];
                const t = c ? c.risk_score / 100 : 0;
                return (
                  <td key={d} className="h-7 min-w-9 rounded text-center text-xs tabular-nums"
                    style={{ background: seqColor(t), color: seqInk(t) }}
                    title={c ? `${DISEASE_LABEL[d]} · ${r.name}: score ${c.risk_score}, outbreak likelihood ${(c.outbreak_probability * 100).toFixed(0)}%\n${c.reasons.join("; ")}` : "no data"}>
                    {c ? Math.round(c.risk_score) : "–"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
        <span>Risk score 0</span>
        <div className="h-2 w-32 rounded" style={{ background: `linear-gradient(90deg, ${[0, 0.25, 0.5, 0.75, 1].map(seqColor).join(",")})` }} />
        <span>100</span>
      </div>
    </div>
  );
}
