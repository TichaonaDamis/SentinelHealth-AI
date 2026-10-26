"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, Bell, Flame, LineChart as LineIcon, Radar, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { AlertTimeline } from "@/components/alert-timeline";
import { ForecastChart } from "@/components/forecast-chart";
import { KpiCard } from "@/components/kpi-card";
import { RiskBadge } from "@/components/risk-badge";
import { RiskHeatmap } from "@/components/risk-heatmap";
import { RiskMap } from "@/components/risk-map";
import { TrendChart } from "@/components/trend-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi } from "@/lib/api";
import type { DashboardSummary, Forecast, RiskAssessment, RiskLevel } from "@/lib/types";
import { DISEASE_LABEL } from "@/lib/viz";
import { fmtCompact, fmtDate, fmtInt, fmtPct } from "@/lib/utils";

export default function DashboardPage() {
  const [state, setState] = useState("");
  const q = state ? `?state=${state}` : "";
  const summary = useApi<DashboardSummary>(`dashboard/summary${q}`);
  const risk = useApi<RiskAssessment[]>(`analytics/risk${q}`);
  const d = summary.data;

  const top = useMemo(() => (risk.data ?? []).filter((a) => a.risk_level !== "green").slice(0, 6), [risk.data]);
  const [focus, setFocus] = useState<{ disease: string; region: string } | null>(null);
  useEffect(() => {
    if (!focus && top[0]) setFocus({ disease: top[0].disease_code, region: top[0].region_id });
  }, [top, focus]);
  const forecast = useApi<Forecast>(focus ? `forecasts/${focus.disease}/${focus.region}?persist=false` : null);
  const focusRow = (risk.data ?? []).find((a) => a.disease_code === focus?.disease && a.region_id === focus?.region);
  const states = useMemo(() => [...new Set((d?.regions ?? []).map((r) => r.state))].sort(), [d?.regions]);

  return (
    <>
      <PageHeader
        title="Executive dashboard"
        description={d ? `National surveillance picture · data through ${fmtDate(d.as_of)}` : "Loading surveillance picture…"}
      >
        <Select value={state} onChange={(e) => setState(e.target.value)} aria-label="Jurisdiction" className="w-40">
          <option value="">All jurisdictions</option>
          {states.map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <Button variant="outline" onClick={() => { summary.reload(); risk.reload(); }}>
          <RefreshCw /> Refresh
        </Button>
      </PageHeader>

      {summary.error && <Card className="mb-4 p-4 text-sm">Could not load dashboard: {summary.error}</Card>}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {d ? (
          <>
            <KpiCard index={0} label="Active cases (14 days)" value={fmtCompact(d.kpis.active_cases)} icon={Activity}
              delta={{ value: d.kpis.active_cases_change_pct, goodWhenDown: true }} sub="vs prior 14 days" />
            <KpiCard index={1} label="Outbreaks detected" value={fmtInt(d.kpis.outbreaks_detected)} icon={Radar}
              sub="orange/red signals, last 14 days" />
            <KpiCard index={2} label="Forecasted cases (next 14 days)" value={fmtCompact(d.kpis.forecasted_cases_14d)} icon={LineIcon}
              sub="ensemble forecast" />
            <KpiCard index={3} label="Open alerts" value={fmtInt(d.kpis.open_alerts)} icon={Bell}>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(["red", "orange", "yellow"] as RiskLevel[]).map((l) => (
                  <span key={l} className="inline-flex items-center gap-1 text-xs">
                    <RiskBadge level={l} compact /> {d.kpis.alerts_by_level[l] ?? 0}
                  </span>
                ))}
              </div>
            </KpiCard>
            <KpiCard index={4} label="Hotspot regions" value={fmtInt(d.kpis.hotspots)} icon={Flame} sub="regions at orange or red" />
          </>
        ) : (
          Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-32" />)
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Disease activity trend</CardTitle>
            <CardDescription>Reported cases per day across monitored regions</CardDescription>
          </CardHeader>
          <CardContent>{d ? <TrendChart data={d.trend} /> : <Skeleton className="h-72" />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Alert timeline</CardTitle>
            <CardDescription>Most recent public-health alerts</CardDescription>
          </CardHeader>
          <CardContent className="max-h-[360px] overflow-y-auto">
            {d ? <AlertTimeline alerts={d.recent_alerts} /> : <Skeleton className="h-60" />}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>Geographic risk</CardTitle>
            <CardDescription>State shading = highest regional risk level; bubbles = monitored regions</CardDescription>
          </CardHeader>
          <CardContent>{d ? <RiskMap regions={d.regions} /> : <Skeleton className="h-96" />}</CardContent>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Risk heatmap</CardTitle>
            <CardDescription>Composite risk score by region and disease (highest-risk regions first)</CardDescription>
          </CardHeader>
          <CardContent>{risk.data ? <RiskHeatmap data={risk.data} /> : <Skeleton className="h-96" />}</CardContent>
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader className="flex-row flex-wrap items-start justify-between gap-2">
            <div>
              <CardTitle>Forecast — {focusRow ? `${DISEASE_LABEL[focusRow.disease_code]}, ${focusRow.region_name}` : "select a signal"}</CardTitle>
              <CardDescription>Observed 7-day average, 30-day forecast and 80% prediction interval</CardDescription>
            </div>
            {forecast.data && (
              <span className="text-xs text-muted-foreground">model: {forecast.data.model} · outbreak likelihood {fmtPct(forecast.data.outbreak_probability)} ({forecast.data.outbreak_tier})</span>
            )}
          </CardHeader>
          <CardContent>
            {forecast.data ? <ForecastChart forecast={forecast.data} /> : <Skeleton className="h-[280px]" />}
            {forecast.data && (
              <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
                {forecast.data.horizons.map((h) => (
                  <div key={h.horizon_days} className="rounded-md border p-2.5">
                    <div className="text-muted-foreground">{h.horizon_days}-day outlook</div>
                    <div className="text-base font-semibold">{fmtInt(h.forecast_cases)} cases</div>
                    <div className="text-muted-foreground">hospitalization {h.hospitalization_risk.replace("_", " ")} · trend {h.trend}</div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Top signals</CardTitle>
            <CardDescription>Explainable drivers for the highest-risk series</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {!risk.data && <Skeleton className="h-60" />}
            {risk.data && top.length === 0 && <p className="text-sm text-muted-foreground">All series within expected range.</p>}
            {top.map((a) => (
              <button key={a.disease_code + a.region_id} onClick={() => setFocus({ disease: a.disease_code, region: a.region_id })}
                className="w-full rounded-md border p-3 text-left transition-colors hover:bg-muted data-[on=true]:border-primary"
                data-on={focus?.disease === a.disease_code && focus?.region === a.region_id}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{DISEASE_LABEL[a.disease_code]} · {a.region_name}, {a.state}</span>
                  <RiskBadge level={a.risk_level} />
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Likelihood {fmtPct(a.outbreak_probability)} · {a.incidence_7d_per_100k.toFixed(1)}/100k · growth ×{a.growth_7d.toFixed(2)}
                </div>
                <div className="mt-1 text-xs">{a.reasons[0]}</div>
              </button>
            ))}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
