"use client";

import { motion } from "framer-motion";
import type { Alert } from "@/lib/types";
import { RISK_META } from "@/lib/viz";
import { RiskBadge } from "@/components/risk-badge";
import { fmtDateTime } from "@/lib/utils";

export function AlertTimeline({ alerts, max = 8 }: { alerts: Alert[]; max?: number }) {
  if (!alerts.length) return <p className="text-sm text-muted-foreground">No alerts in this scope.</p>;
  return (
    <ol className="relative ml-2 border-l">
      {alerts.slice(0, max).map((a, i) => (
        <motion.li key={a.id} className="mb-4 ml-4" initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}>
          <span className="absolute -left-[5px] mt-1.5 size-2.5 rounded-full ring-2 ring-card" style={{ background: RISK_META[a.risk_level].color }} aria-hidden />
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge level={a.risk_level} />
            <time className="text-xs text-muted-foreground">{fmtDateTime(a.created_at)}</time>
            {a.status !== "open" && <span className="text-xs capitalize text-muted-foreground">· {a.status}</span>}
          </div>
          <p className="mt-1 text-sm font-medium leading-snug">{a.title.replace(/^\w+ alert: /, "")}</p>
        </motion.li>
      ))}
    </ol>
  );
}
