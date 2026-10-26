"use client";

import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  delta,
  index = 0,
  children,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: LucideIcon;
  delta?: { value: number; goodWhenDown?: boolean };
  index?: number;
  children?: React.ReactNode;
}) {
  const up = (delta?.value ?? 0) > 0;
  const bad = delta ? (delta.goodWhenDown ? up : !up) : false;
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05, duration: 0.3 }}>
      <Card className="h-full p-5">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
          <Icon className="size-4 text-muted-foreground" aria-hidden />
        </div>
        <div className="mt-2 text-3xl font-semibold tracking-tight">{value}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {delta && (
            <span className={cn("font-medium", bad ? "text-[color:var(--status-critical)]" : "text-[color:var(--status-good)]")}>
              {up ? "▲" : "▼"} {Math.abs(delta.value).toFixed(1)}%
            </span>
          )}
          {sub && <span>{sub}</span>}
        </div>
        {children}
      </Card>
    </motion.div>
  );
}
