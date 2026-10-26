"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { geoAlbersUsa, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import statesTopo from "us-atlas/states-10m.json";
import type { RegionRisk, RiskLevel } from "@/lib/types";
import { DISEASE_LABEL, RISK_META } from "@/lib/viz";
import { RiskBadge } from "@/components/risk-badge";

const MapboxRiskMap = dynamic(() => import("./risk-map-mapbox"), { ssr: false });

const topo = statesTopo as unknown as Topology<{ states: GeometryCollection<{ name: string }> }>;
export const STATES = feature(topo, topo.objects.states) as FeatureCollection<Geometry, { name: string }>;

const LEVELS: RiskLevel[] = ["green", "yellow", "orange", "red"];

/** State fill = highest risk level among monitored regions in that state. */
export function stateRisk(regions: RegionRisk[]) {
  const out: Record<string, RiskLevel> = {};
  for (const r of regions) {
    const fips = r.region_id.slice(0, 2);
    if (!out[fips] || RISK_META[r.risk_level].rank > RISK_META[out[fips]].rank) out[fips] = r.risk_level;
  }
  return out;
}

export function RiskMap({ regions }: { regions: RegionRisk[] }) {
  if (process.env.NEXT_PUBLIC_MAPBOX_TOKEN) return <MapboxRiskMap regions={regions} />;
  return <SvgRiskMap regions={regions} />;
}

/** Offline choropleth (no map tiles required): state fill by risk, region bubbles sized by 7-day incidence. */
function SvgRiskMap({ regions }: { regions: RegionRisk[] }) {
  const [hover, setHover] = useState<RegionRisk | null>(null);
  const width = 960;
  const height = 560;
  const { path, project } = useMemo(() => {
    const projection = geoAlbersUsa().fitSize([width, height], STATES);
    return { path: geoPath(projection), project: (lon: number, lat: number) => projection([lon, lat]) };
  }, []);
  const byState = useMemo(() => stateRisk(regions), [regions]);
  const maxInc = Math.max(1, ...regions.map((r) => r.incidence_7d_per_100k));
  const offMap = regions.filter((r) => !project(r.lon, r.lat));

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label="Map of risk levels by state and region">
        <g>
          {STATES.features.map((f) => {
            const level = byState[String(f.id)];
            return (
              <path key={String(f.id)} d={path(f) ?? ""} stroke="var(--viz-surface)" strokeWidth={1}
                fill={level ? RISK_META[level].color : "hsl(var(--muted))"} fillOpacity={level ? 0.35 : 1}>
                <title>{`${f.properties.name}${level ? ` — ${RISK_META[level].label} risk` : " — not monitored"}`}</title>
              </path>
            );
          })}
        </g>
        <g>
          {[...regions].sort((a, b) => b.incidence_7d_per_100k - a.incidence_7d_per_100k).map((r) => {
            const xy = project(r.lon, r.lat);
            if (!xy) return null;
            const rad = 5 + 20 * Math.sqrt(r.incidence_7d_per_100k / maxInc);
            return (
              <circle key={r.region_id} cx={xy[0]} cy={xy[1]} r={rad} fill={RISK_META[r.risk_level].color} fillOpacity={0.85}
                stroke="var(--viz-surface)" strokeWidth={2} className="cursor-pointer"
                onMouseEnter={() => setHover(r)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(r)} tabIndex={0}>
                <title>{`${r.name}, ${r.state}`}</title>
              </circle>
            );
          })}
        </g>
      </svg>
      {hover && (
        <div className="pointer-events-none absolute left-3 top-3 rounded-md border bg-card p-3 text-xs shadow-md">
          <div className="font-semibold">{hover.name}, {hover.state}</div>
          <div className="mt-1 flex items-center gap-2"><RiskBadge level={hover.risk_level} />
            {hover.top_disease && <span className="text-muted-foreground">driven by {DISEASE_LABEL[hover.top_disease]}</span>}</div>
          <div className="mt-1 text-muted-foreground">{hover.incidence_7d_per_100k.toFixed(1)} cases / 100k (7 days, all diseases)</div>
        </div>
      )}
      <MapLegend />
      {offMap.length > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          Not shown on the map: {offMap.map((r) => `${r.name} (${RISK_META[r.risk_level].label})`).join(", ")}
        </p>
      )}
    </div>
  );
}

export function MapLegend() {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
      {LEVELS.map((l) => <RiskBadge key={l} level={l} />)}
      <span>· Bubble size = 7-day incidence per 100k</span>
    </div>
  );
}
