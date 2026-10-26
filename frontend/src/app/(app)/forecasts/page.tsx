"use client";

import { useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { ForecastChart } from "@/components/forecast-chart";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi } from "@/lib/api";
import type { Disease, Forecast, Region } from "@/lib/types";
import { fmtInt, fmtPct } from "@/lib/utils";

const RISK_WORD: Record<string, string> = { low: "Low", moderate: "Moderate", high: "High", very_high: "Very high" };

export default function ForecastsPage() {
  const diseases = useApi<Disease[]>("diseases");
  const regions = useApi<Region[]>("regions");
  const [disease, setDisease] = useState("INFLUENZA");
  const [region, setRegion] = useState("");
  const regionId = region || regions.data?.[0]?.id;
  const fc = useApi<Forecast>(regionId ? `forecasts/${disease}/${regionId}?persist=false` : null);
  const f = fc.data;

  return (
    <>
      <PageHeader title="Forecasts" description="7, 14 and 30-day projections with hospitalization and mortality risk. Intervals are 80% split-conformal.">
        <Select value={disease} onChange={(e) => setDisease(e.target.value)} aria-label="Disease" className="w-52">
          {(diseases.data ?? []).map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
        </Select>
        <Select value={regionId ?? ""} onChange={(e) => setRegion(e.target.value)} aria-label="Region" className="w-52">
          {(regions.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}, {r.state}</option>)}
        </Select>
      </PageHeader>
      {fc.error && <Card className="mb-4 p-4 text-sm">{fc.error}</Card>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card className="p-5">
          <div className="text-xs text-muted-foreground">Outbreak likelihood (now → 7 days)</div>
          <div className="mt-2 text-3xl font-semibold">{f ? fmtPct(f.outbreak_probability) : "—"}</div>
          <div className="mt-1 text-xs text-muted-foreground">{f ? `${f.outbreak_tier} · model ${f.model}` : ""}</div>
        </Card>
        {(f?.horizons ?? [null, null, null]).map((h, i) => (
          <Card key={i} className="p-5">
            {h ? (
              <>
                <div className="text-xs text-muted-foreground">{h.horizon_days}-day forecast</div>
                <div className="mt-2 text-3xl font-semibold">{fmtInt(h.forecast_cases)}</div>
                <div className="text-xs text-muted-foreground">80% PI {fmtInt(h.forecast_cases_lower)}–{fmtInt(h.forecast_cases_upper)} · {h.trend}</div>
                <dl className="mt-3 grid grid-cols-2 gap-1 text-xs">
                  <dt className="text-muted-foreground">Hospitalization</dt><dd className="text-right font-medium">{RISK_WORD[h.hospitalization_risk]} ({fmtInt(h.expected_admissions)})</dd>
                  <dt className="text-muted-foreground">Mortality</dt><dd className="text-right font-medium">{RISK_WORD[h.mortality_risk]} ({h.expected_deaths.toFixed(1)})</dd>
                </dl>
              </>
            ) : <Skeleton className="h-28" />}
          </Card>
        ))}
      </div>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Projected daily cases</CardTitle>
          <CardDescription>Observed 7-day average (solid) and forecast mean (dashed) with prediction interval</CardDescription>
        </CardHeader>
        <CardContent>{f ? <ForecastChart forecast={f} height={360} /> : <Skeleton className="h-[360px]" />}</CardContent>
      </Card>
    </>
  );
}
