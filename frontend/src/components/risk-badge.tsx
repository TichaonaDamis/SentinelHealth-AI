import { AlertTriangle, CheckCircle2, CircleAlert, OctagonAlert } from "lucide-react";
import type { RiskLevel } from "@/lib/types";
import { RISK_META } from "@/lib/viz";
import { cn } from "@/lib/utils";

const ICONS = { green: CheckCircle2, yellow: CircleAlert, orange: AlertTriangle, red: OctagonAlert } as const;

/** Status colour is never used alone: every level carries an icon and a text label. */
export function RiskBadge({ level, className, compact }: { level: RiskLevel; className?: string; compact?: boolean }) {
  const Icon = ICONS[level];
  const meta = RISK_META[level];
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full border bg-card px-2 py-0.5 text-xs font-medium text-foreground", className)}
      title={`${meta.label} risk`}
    >
      <Icon className="size-3.5" style={{ color: meta.color }} aria-hidden />
      {!compact && meta.label}
    </span>
  );
}
