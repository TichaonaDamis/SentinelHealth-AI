"use client";

import { Fragment } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PageHeader } from "@/components/app-shell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { fmtInt, fmtPct } from "@/lib/utils";
import { seqColor, seqInk } from "@/lib/viz";

interface Metrics {
  data: { rows: number; series: number; test_start: string; source: string; outbreak_prevalence_test: number };
  classifier: {
    accuracy: number; precision: number; recall: number; f1: number; roc_auc: number; pr_auc: number; threshold: number;
    confusion_matrix: number[][]; roc_curve: { fpr: number[]; tpr: number[] };
    risk_tiers: Record<string, { n: number; outbreak_rate: number | null }>;
    feature_importance: [string, number][];
  };
  classifier_by_disease: Record<string, { roc_auc: number; f1: number }>;
  anomaly: Record<string, { roc_auc: number; precision: number; recall: number }>;
  early_detection: Record<string, {
    episodes: number; detected: number; detection_rate: number; median_delay_days: number | null;
    false_alerts_per_series_year: number; median_lead_days_vs_flag_traditional_ears?: number | null; share_detected_earlier?: number | null;
  }>;
  forecast: { model: string; horizon: number; mae: number; smape: number; coverage_80: number; skill_vs_naive: number }[];
}

const NAMES: Record<string, string> = {
  flag_traditional_ears: "Traditional (EARS C2, lagged case reports)",
  flag_ensemble: "Anomaly ensemble",
  flag_classifier: "Outbreak classifier",
  flag_sentinel: "SentinelHealth combined",
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

export default function ModelsPage() {
  const { data: m, error } = useApi<Metrics>("admin/model-evaluation");
  const versions = useApi<Record<string, string>>("admin/models");
  if (error) return <Card className="p-4 text-sm">{error}</Card>;
  if (!m) return <Skeleton className="h-[600px]" />;
  const c = m.classifier;
  const roc = c.roc_curve.fpr.map((x, i) => ({ fpr: x, model: c.roc_curve.tpr[i] }));
  const cm = c.confusion_matrix;
  const cmMax = Math.max(...cm.flat());
  const ed = m.early_detection;

  return (
    <>
      <PageHeader title="Model performance" description={`Evaluation on a held-out period from ${m.data.test_start} · ${fmtInt(m.data.rows)} rows · source: ${m.data.source}`} />
      {m.data.source === "synthetic" && (
        <Card className="mb-4 border-[color:var(--status-warning)] p-4 text-sm">
          These metrics come from the synthetic validation dataset and confirm the pipeline works. Re-validate on your own surveillance history before you rely on them operationally.
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Accuracy" value={c.accuracy.toFixed(3)} />
        <Stat label="Precision" value={c.precision.toFixed(3)} />
        <Stat label="Recall" value={c.recall.toFixed(3)} />
        <Stat label="F1 score" value={c.f1.toFixed(3)} />
        <Stat label="ROC AUC" value={c.roc_auc.toFixed(3)} />
        <Stat label="PR AUC" value={c.pr_auc.toFixed(3)} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>ROC curve</CardTitle><CardDescription>Outbreak classifier (LightGBM, calibrated)</CardDescription></CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={roc} margin={{ top: 4, right: 8, bottom: 12, left: 0 }}>
                <CartesianGrid stroke="var(--viz-grid)" />
                <XAxis dataKey="fpr" type="number" domain={[0, 1]} tickCount={6} tick={{ fill: "var(--viz-axis)", fontSize: 11 }}
                  label={{ value: "False positive rate", position: "insideBottom", offset: -6, fill: "var(--viz-axis)", fontSize: 11 }} />
                <YAxis type="number" domain={[0, 1]} tickCount={6} tick={{ fill: "var(--viz-axis)", fontSize: 11 }} width={36} />
                <Tooltip formatter={(v) => Number(v).toFixed(3)} labelFormatter={(l) => `FPR ${Number(l).toFixed(3)}`}
                  contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                itemStyle={{ color: "hsl(var(--foreground))" }} />
                <Legend verticalAlign="top" height={28} formatter={(v) => <span className="text-xs text-foreground">{v === "model" ? `LightGBM (AUC ${c.roc_auc.toFixed(3)})` : v}</span>} />
                <Line dataKey="model" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line data={[{ fpr: 0, chance: 0 }, { fpr: 1, chance: 1 }]} dataKey="chance" name="Chance" stroke="var(--viz-axis)" strokeDasharray="4 4" strokeWidth={1} dot={false} isAnimationActive={false} legendType="none" />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Confusion matrix</CardTitle><CardDescription>Decision threshold {c.threshold.toFixed(2)} · prevalence {fmtPct(m.data.outbreak_prevalence_test, 1)}</CardDescription></CardHeader>
          <CardContent>
            <div className="grid grid-cols-[auto_1fr_1fr] gap-1 text-sm">
              <div />
              <div className="pb-1 text-center text-xs text-muted-foreground">Predicted: no outbreak</div>
              <div className="pb-1 text-center text-xs text-muted-foreground">Predicted: outbreak</div>
              {["Actual: no outbreak", "Actual: outbreak"].map((label, i) => (
                <Fragment key={label}>
                  <div className="flex items-center pr-2 text-xs text-muted-foreground">{label}</div>
                  {cm[i].map((v, j) => {
                    const t = Math.sqrt(v / cmMax);
                    return (
                      <div key={`${i}${j}`} className="grid h-24 place-items-center rounded-md" style={{ background: seqColor(t), color: seqInk(t) }}>
                        <div className="text-center"><div className="text-lg font-semibold tabular-nums">{fmtInt(v)}</div>
                          <div className="text-[11px] opacity-80">{[["TN", "FP"], ["FN", "TP"]][i][j]}</div></div>
                      </div>
                    );
                  })}
                </Fragment>
              ))}
            </div>
            <div className="mt-4 text-xs text-muted-foreground">Risk-tier calibration (share of days that were truly outbreak days):</div>
            <div className="mt-1 grid grid-cols-3 gap-2 text-xs">
              {Object.entries(c.risk_tiers).map(([tier, v]) => (
                <div key={tier} className="rounded-md border p-2"><div className="font-medium">{tier}</div><div className="text-muted-foreground">{v.outbreak_rate == null ? "—" : fmtPct(v.outbreak_rate, 1)} of {fmtInt(v.n)}</div></div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Explainability</CardTitle><CardDescription>Global feature importance (gain share)</CardDescription></CardHeader>
          <CardContent className="space-y-1.5">
            {c.feature_importance.map(([f, v]) => (
              <div key={f} className="grid grid-cols-[1fr_auto] items-center gap-2 text-xs">
                <div>
                  <div className="font-mono">{f}</div>
                  <div className="mt-0.5 h-1.5 rounded-full bg-muted"><div className="h-1.5 rounded-full" style={{ width: `${(v / c.feature_importance[0][1]) * 100}%`, background: "var(--series-1)" }} /></div>
                </div>
                <span className="tabular-nums text-muted-foreground">{v.toFixed(2)}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader><CardTitle>Early detection vs traditional reporting</CardTitle>
          <CardDescription>Event-level evaluation across outbreak episodes in the test period</CardDescription></CardHeader>
        <CardContent>
          <Table>
            <THead><TR><TH>Detector</TH><TH className="text-right">Detected</TH><TH className="text-right">Median delay from onset</TH>
              <TH className="text-right">Median lead vs traditional</TH><TH className="text-right">Detected earlier</TH><TH className="text-right">False alerts / series-year</TH></TR></THead>
            <TBody>
              {Object.entries(ed).map(([k, v]) => (
                <TR key={k}>
                  <TD className="font-medium">{NAMES[k] ?? k}</TD>
                  <TD className="text-right tabular-nums">{v.detected}/{v.episodes} ({fmtPct(v.detection_rate)})</TD>
                  <TD className="text-right tabular-nums">{v.median_delay_days == null ? "—" : `${v.median_delay_days} d`}</TD>
                  <TD className="text-right tabular-nums">{v.median_lead_days_vs_flag_traditional_ears == null ? "—" : `${v.median_lead_days_vs_flag_traditional_ears} d`}</TD>
                  <TD className="text-right tabular-nums">{v.share_detected_earlier == null ? "—" : fmtPct(v.share_detected_earlier)}</TD>
                  <TD className="text-right tabular-nums">{v.false_alerts_per_series_year.toFixed(2)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Forecast backtest</CardTitle><CardDescription>Rolling-origin evaluation; skill relative to the persistence baseline</CardDescription></CardHeader>
          <CardContent>
            <Table>
              <THead><TR><TH>Model</TH><TH className="text-right">Horizon</TH><TH className="text-right">MAE</TH><TH className="text-right">sMAPE</TH>
                <TH className="text-right">80% coverage</TH><TH className="text-right">Skill</TH></TR></THead>
              <TBody>
                {m.forecast.map((r) => (
                  <TR key={r.model + r.horizon}>
                    <TD>{r.model}</TD><TD className="text-right">{r.horizon}d</TD><TD className="text-right tabular-nums">{r.mae.toFixed(1)}</TD>
                    <TD className="text-right tabular-nums">{r.smape.toFixed(3)}</TD><TD className="text-right tabular-nums">{fmtPct(r.coverage_80)}</TD>
                    <TD className="text-right tabular-nums">{r.skill_vs_naive >= 0 ? "+" : ""}{r.skill_vs_naive.toFixed(2)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Anomaly detectors &amp; per-disease accuracy</CardTitle><CardDescription>Unsupervised detectors scored against outbreak labels</CardDescription></CardHeader>
          <CardContent>
            <Table>
              <THead><TR><TH>Detector</TH><TH className="text-right">ROC AUC</TH><TH className="text-right">Precision</TH><TH className="text-right">Recall</TH></TR></THead>
              <TBody>
                {Object.entries(m.anomaly).map(([k, v]) => (
                  <TR key={k}><TD>{k.replaceAll("_", " ")}</TD><TD className="text-right tabular-nums">{v.roc_auc.toFixed(3)}</TD>
                    <TD className="text-right tabular-nums">{v.precision.toFixed(3)}</TD><TD className="text-right tabular-nums">{v.recall.toFixed(3)}</TD></TR>
                ))}
              </TBody>
            </Table>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              {Object.entries(m.classifier_by_disease).map(([d, v]) => (
                <span key={d} className="rounded-md border px-2 py-1">{d}: AUC {v.roc_auc.toFixed(3)} · F1 {v.f1.toFixed(2)}</span>
              ))}
            </div>
            {versions.data && (
              <div className="mt-3 text-[11px] text-muted-foreground">Loaded artifacts: {Object.entries(versions.data).map(([k, v]) => `${k}@${v}`).join(" · ")}</div>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
