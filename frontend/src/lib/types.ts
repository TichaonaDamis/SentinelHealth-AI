export type RiskLevel = "green" | "yellow" | "orange" | "red";

export interface Alert {
  id: string;
  outbreak_event_id: string | null;
  disease_code: string;
  region_id: string;
  risk_level: RiskLevel;
  title: string;
  message: string;
  status: "open" | "acknowledged" | "resolved" | "dismissed";
  audiences: string[] | null;
  deliveries: { channel: string; status: string }[] | null;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolution_note: string | null;
  created_at: string;
}

export interface RegionRisk {
  region_id: string;
  name: string;
  state: string;
  lat: number;
  lon: number;
  incidence_7d_per_100k: number;
  risk_level: RiskLevel;
  top_disease: string | null;
}

export interface DashboardSummary {
  as_of: string;
  kpis: {
    active_cases: number;
    active_cases_change_pct: number;
    outbreaks_detected: number;
    forecasted_cases_14d: number;
    open_alerts: number;
    alerts_by_level: Record<string, number>;
    hotspots: number;
  };
  trend: { date: string; values: Record<string, number> }[];
  regions: RegionRisk[];
  recent_alerts: Alert[];
}

export interface RiskAssessment {
  disease_code: string;
  region_id: string;
  region_name: string;
  state: string;
  as_of: string;
  risk_level: RiskLevel;
  risk_score: number;
  outbreak_probability: number;
  outbreak_tier: "High" | "Medium" | "Low";
  anomaly_score: number;
  anomaly_flag: boolean;
  ears_c2: number;
  incidence_7d_per_100k: number;
  growth_7d: number;
  drivers: { feature: string; value: number }[];
  reasons: string[];
}

export interface ForecastPoint {
  date: string;
  mean: number;
  lower: number;
  upper: number;
}

export interface HorizonRisk {
  horizon_days: number;
  forecast_cases: number;
  forecast_cases_lower: number;
  forecast_cases_upper: number;
  expected_admissions: number;
  expected_deaths: number;
  admissions_per_100k: number;
  deaths_per_100k: number;
  hospitalization_risk: string;
  mortality_risk: string;
  trend: string;
}

export interface Forecast {
  disease_code: string;
  region_id: string;
  origin_date: string;
  model: string;
  outbreak_probability: number;
  outbreak_tier: "High" | "Medium" | "Low";
  horizons: HorizonRisk[];
  history: ForecastPoint[];
  path: ForecastPoint[];
}

export interface Disease {
  code: string;
  name: string;
  category: string;
  icd10: string | null;
  severity_weight: number;
}

export interface Region {
  id: string;
  name: string;
  state: string;
  lat: number;
  lon: number;
  population: number;
}

export interface CopilotAnswer {
  answer: string;
  provider: string;
  model: string | null;
  citations: { ref: string; title: string; source: string | null; snippet: string; score: number }[];
  context_facts: string[];
}

export interface Me {
  email: string;
  full_name: string;
  role: string;
  jurisdiction: string | null;
}
