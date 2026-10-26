"use client";

import "mapbox-gl/dist/mapbox-gl.css";
import { useMemo, useState } from "react";
import Map, { Layer, Popup, Source } from "react-map-gl/mapbox";
import type { RegionRisk } from "@/lib/types";
import { RISK_META } from "@/lib/viz";
import { MapLegend, STATES, stateRisk } from "@/components/risk-map";

// Mapbox expressions cannot read CSS variables, so the status palette is restated here.
const HEX = { green: "#0ca30c", yellow: "#fab219", orange: "#ec835a", red: "#d03b3b" } as const;

export default function MapboxRiskMap({ regions }: { regions: RegionRisk[] }) {
  const [popup, setPopup] = useState<RegionRisk | null>(null);
  const byState = useMemo(() => stateRisk(regions), [regions]);
  const states = useMemo(
    () => ({
      ...STATES,
      features: STATES.features.map((f) => ({ ...f, properties: { ...f.properties, risk: byState[String(f.id)] ?? "none" } })),
    }),
    [byState],
  );
  const points = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: regions.map((r) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [r.lon, r.lat] },
        properties: { id: r.region_id, risk: r.risk_level, incidence: r.incidence_7d_per_100k },
      })),
    }),
    [regions],
  );
  const maxInc = Math.max(1, ...regions.map((r) => r.incidence_7d_per_100k));
  const colorExpr = ["match", ["get", "risk"], "green", HEX.green, "yellow", HEX.yellow, "orange", HEX.orange, "red", HEX.red, "#d4d4d0"];

  return (
    <div>
      <div className="h-[420px] overflow-hidden rounded-md">
        <Map
          mapboxAccessToken={process.env.NEXT_PUBLIC_MAPBOX_TOKEN}
          initialViewState={{ longitude: -96, latitude: 37.5, zoom: 3.1 }}
          mapStyle="mapbox://styles/mapbox/light-v11"
          interactiveLayerIds={["regions"]}
          onClick={(e) => {
            const id = e.features?.[0]?.properties?.id as string | undefined;
            setPopup(regions.find((r) => r.region_id === id) ?? null);
          }}
        >
          <Source id="states" type="geojson" data={states}>
            {/* @ts-expect-error expression typing */}
            <Layer id="state-fill" type="fill" paint={{ "fill-color": colorExpr, "fill-opacity": 0.3 }} />
            <Layer id="state-line" type="line" paint={{ "line-color": "#ffffff", "line-width": 1 }} />
          </Source>
          <Source id="regions" type="geojson" data={points}>
            <Layer
              id="regions"
              type="circle"
              paint={{
                // @ts-expect-error expression typing
                "circle-color": colorExpr,
                "circle-radius": ["+", 5, ["*", 20, ["sqrt", ["/", ["get", "incidence"], maxInc]]]],
                "circle-stroke-color": "#ffffff",
                "circle-stroke-width": 2,
                "circle-opacity": 0.85,
              }}
            />
          </Source>
          {popup && (
            <Popup longitude={popup.lon} latitude={popup.lat} onClose={() => setPopup(null)} closeOnClick={false}>
              <div className="text-xs">
                <div className="font-semibold">{popup.name}, {popup.state}</div>
                <div>{RISK_META[popup.risk_level].label} risk · {popup.incidence_7d_per_100k.toFixed(1)}/100k</div>
              </div>
            </Popup>
          )}
        </Map>
      </div>
      <MapLegend />
    </div>
  );
}
