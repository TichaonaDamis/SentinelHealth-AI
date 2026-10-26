"use client";

import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { BookOpen, FileText, Send, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import type { CopilotAnswer } from "@/lib/types";
import { DISEASE_LABEL, DISEASE_ORDER } from "@/lib/viz";

type Turn = { q: string; a?: CopilotAnswer; error?: string };

const SUGGESTIONS = [
  "Which regions show unusual influenza activity and why?",
  "Summarize the current measles risk and recommended response steps.",
  "Explain the top alert in plain language for a health officer briefing.",
  "How should we interpret rising wastewater signals with flat case counts?",
];

/** Lightweight renderer for the copilot's markdown (bold, bullets, citation chips). */
function Markdown({ text }: { text: string }) {
  return (
    <div className="space-y-1.5 text-sm leading-relaxed">
      {text.split("\n").map((line, i) => {
        if (!line.trim()) return <div key={i} className="h-1" />;
        const bullet = /^\s*[-*] /.test(line);
        const heading = /^#+ /.test(line);
        const body = line.replace(/^\s*[-*] /, "").replace(/^#+ /, "");
        // Italic only for _phrases_ delimited by non-word characters, so identifiers like otc_ratio_7_28 stay intact.
        const parts = body.split(/(\*\*[^*]+\*\*|\[[SF]\d+\]|(?<!\w)_[^_\n]+_(?!\w))/g).map((p, j) => {
          if (/^\*\*.+\*\*$/.test(p)) return <strong key={j}>{p.slice(2, -2)}</strong>;
          if (/^\[[SF]\d+\]$/.test(p))
            return <span key={j} className="mx-0.5 rounded bg-accent px-1 text-[10px] font-medium text-accent-foreground">{p.slice(1, -1)}</span>;
          if (/^_.+_$/.test(p)) return <em key={j} className="text-muted-foreground">{p.slice(1, -1)}</em>;
          return p;
        });
        if (heading) return <h4 key={i} className="pt-1 font-semibold">{parts}</h4>;
        return bullet ? <div key={i} className="flex gap-2 pl-1"><span className="text-muted-foreground">•</span><span>{parts}</span></div> : <p key={i}>{parts}</p>;
      })}
    </div>
  );
}

export default function CopilotPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [disease, setDisease] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  async function run(question: string, sitrep = false) {
    if (!question.trim() && !sitrep) return;
    const label = sitrep ? `Generate situation report${disease ? ` — ${DISEASE_LABEL[disease]}` : ""}` : question;
    setTurns((t) => [...t, { q: label }]);
    setQ("");
    setBusy(true);
    try {
      const a = sitrep
        ? await api<CopilotAnswer>("copilot/sitrep", { method: "POST", body: JSON.stringify({ disease_code: disease || null, period_days: 14 }) })
        : await api<CopilotAnswer>("copilot/ask", { method: "POST", body: JSON.stringify({ question, disease_code: disease || null }) });
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
    } catch (e) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: e instanceof Error ? e.message : String(e) } : x)));
    } finally {
      setBusy(false);
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }

  return (
    <>
      <PageHeader title="Epidemiology copilot" description="Answers are grounded in live surveillance data and your agency's guidance (RAG, hybrid search) with citations.">
        <Select value={disease} onChange={(e) => setDisease(e.target.value)} aria-label="Disease focus" className="w-52">
          <option value="">All diseases</option>
          {DISEASE_ORDER.map((d) => <option key={d} value={d}>{DISEASE_LABEL[d]}</option>)}
        </Select>
        <Button variant="outline" disabled={busy} onClick={() => run("", true)}><FileText /> Situation report</Button>
      </PageHeader>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="flex min-h-[560px] flex-col lg:col-span-2">
          <div className="flex-1 space-y-5 overflow-y-auto p-5">
            {turns.length === 0 && (
              <div className="grid h-full place-items-center text-center">
                <div>
                  <Sparkles className="mx-auto size-6 text-primary" />
                  <p className="mt-2 text-sm text-muted-foreground">Ask about trends, alerts, or response guidance.</p>
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((s) => (
                      <Button key={s} variant="outline" size="sm" className="h-auto whitespace-normal py-1.5 text-left" onClick={() => run(s)}>{s}</Button>
                    ))}
                  </div>
                </div>
              </div>
            )}
            {turns.map((t, i) => (
              <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-3">
                <div className="ml-auto max-w-[85%] rounded-lg bg-primary px-4 py-2.5 text-sm text-primary-foreground">{t.q}</div>
                <div className="max-w-[95%] rounded-lg border bg-card px-4 py-3">
                  {t.a ? (
                    <>
                      <Markdown text={t.a.answer} />
                      <div className="mt-3 text-[11px] text-muted-foreground">{t.a.provider}{t.a.model ? ` · ${t.a.model}` : ""} · {t.a.citations.length} sources</div>
                    </>
                  ) : t.error ? (
                    <p className="text-sm text-[color:var(--status-critical)]">{t.error}</p>
                  ) : (
                    <div className="flex gap-1 py-2">{[0, 1, 2].map((k) => <span key={k} className="size-2 animate-bounce rounded-full bg-muted-foreground" style={{ animationDelay: `${k * 120}ms` }} />)}</div>
                  )}
                </div>
              </motion.div>
            ))}
            <div ref={endRef} />
          </div>
          <form className="flex gap-2 border-t p-4" onSubmit={(e) => { e.preventDefault(); run(q); }}>
            <Textarea value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a surveillance question… (no patient identifiers)" className="min-h-[44px] resize-none"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(q); } }} />
            <Button type="submit" disabled={busy || !q.trim()} aria-label="Send"><Send /></Button>
          </form>
        </Card>

        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><BookOpen className="size-4" /> Sources &amp; context</CardTitle></CardHeader>
          <CardContent className="space-y-4 text-sm">
            {(() => {
              const last = [...turns].reverse().find((t) => t.a)?.a;
              if (!last) return <p className="text-muted-foreground">Citations and the live facts used to ground the answer appear here.</p>;
              return (
                <>
                  <div className="space-y-2">
                    {last.citations.map((c) => (
                      <div key={c.ref} className="rounded-md border p-2.5">
                        <div className="text-xs font-semibold"><span className="mr-1 rounded bg-accent px-1 text-accent-foreground">{c.ref}</span>{c.title}</div>
                        <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">{c.snippet}</p>
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="mb-1 text-xs font-semibold">Live surveillance facts</div>
                    <ul className="space-y-1 text-xs text-muted-foreground">
                      {last.context_facts.map((f, i) => <li key={i}><span className="font-medium text-foreground">F{i + 1}</span> {f}</li>)}
                    </ul>
                  </div>
                </>
              );
            })()}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
