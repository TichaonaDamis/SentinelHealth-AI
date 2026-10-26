import type { RiskLevel } from "./types";

/** Fixed disease -> categorical slot mapping (colour follows the entity, never its rank). */
export const DISEASE_ORDER = ["INFLUENZA", "CLI", "RSV", "DENGUE", "MEASLES", "FOODBORNE"] as const;
export const DISEASE_LABEL: Record<string, string> = {
  INFLUENZA: "Influenza",
  CLI: "COVID-like illness",
  RSV: "RSV",
  DENGUE: "Dengue",
  MEASLES: "Measles",
  FOODBORNE: "Foodborne",
};
export const DISEASE_SHORT: Record<string, string> = {
  INFLUENZA: "Flu",
  CLI: "CLI",
  RSV: "RSV",
  DENGUE: "Dengue",
  MEASLES: "Measles",
  FOODBORNE: "Food",
};
export const diseaseColor = (code: string) => {
  const i = DISEASE_ORDER.indexOf(code as (typeof DISEASE_ORDER)[number]);
  return `var(--series-${i >= 0 ? i + 1 : 1})`;
};

export const RISK_META: Record<RiskLevel, { label: string; color: string; rank: number }> = {
  green: { label: "Green", color: "var(--status-good)", rank: 0 },
  yellow: { label: "Yellow", color: "var(--status-warning)", rank: 1 },
  orange: { label: "Orange", color: "var(--status-serious)", rank: 2 },
  red: { label: "Red", color: "var(--status-critical)", rank: 3 },
};

/** Sequential blue ramp for magnitudes (heatmap cells). t in [0, 1]. */
const SEQ = ["#f0efec", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
export const seqColor = (t: number) => SEQ[Math.max(0, Math.min(SEQ.length - 1, Math.round(t * (SEQ.length - 1))))];
export const seqInk = (t: number) => (t > 0.55 ? "#ffffff" : "#0b0b0b");
