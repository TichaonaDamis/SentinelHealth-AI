"""RAG copilot orchestration: live surveillance facts + retrieved guidance -> grounded LLM answer."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Alert, DailySignal, Disease, KnowledgeChunk, KnowledgeDocument, Region
from app.schemas import Citation, CopilotAnswer, KnowledgeDocIn
from app.services.analytics import assess
from app.services.copilot.embeddings import get_embedder
from app.services.copilot.llm import SYSTEM_PROMPT, get_llm, scrub_phi
from app.services.copilot.retriever import OpenSearchHybridRetriever, SQLHybridRetriever, chunk_text
from app.services.data_access import latest_signal_date

SITREP_INSTRUCTIONS = """Write a public-health SITUATION REPORT with these sections:
1. Key points (3-5 bullets)
2. Epidemiological situation (by disease and geography, with numbers from the facts)
3. Signals and alerts (risk level, why it was raised, confidence)
4. Outlook (forecast trend; hospitalization/mortality risk where available)
5. Recommended actions (proportionate; investigation, lab confirmation, communication)
6. Data limitations"""


def _retriever(db: AsyncSession):
    s = get_settings()
    if s.opensearch_url:
        return OpenSearchHybridRetriever(s.opensearch_url, get_embedder())
    return SQLHybridRetriever(db, get_embedder())


async def surveillance_facts(
    db: AsyncSession, disease: str | None, state: str | None, region_id: str | None, period_days: int = 14
) -> list[str]:
    as_of = await latest_signal_date(db)
    if as_of is None:
        return ["No surveillance data has been loaded yet."]
    facts: list[str] = [f"Data current through {as_of:%Y-%m-%d}."]
    names = {d.code: d.name for d in (await db.scalars(select(Disease))).all()}
    start = as_of - timedelta(days=period_days - 1)
    prev_start = start - timedelta(days=period_days)

    stmt = (select(DailySignal.disease_code,
                   func.sum(DailySignal.cases).filter(DailySignal.observed_on >= start),
                   func.sum(DailySignal.cases).filter(DailySignal.observed_on < start))
            .join(Region, Region.id == DailySignal.region_id)
            .where(DailySignal.observed_on >= prev_start).group_by(DailySignal.disease_code))
    if disease:
        stmt = stmt.where(DailySignal.disease_code == disease)
    if state:
        stmt = stmt.where(Region.state == state)
    if region_id:
        stmt = stmt.where(DailySignal.region_id == region_id)
    for code, cur, prev in (await db.execute(stmt)).all():
        cur, prev = float(cur or 0), float(prev or 0)
        change = (cur - prev) / prev * 100 if prev else 0.0
        facts.append(f"{names.get(code, code)}: {cur:,.0f} cases in the last {period_days} days "
                     f"({change:+.0f}% vs prior {period_days} days).")

    assessments = await assess(db, as_of, [disease] if disease else None, state)
    if region_id:
        assessments = [a for a in assessments if a.region_id == region_id]
    elevated = [a for a in assessments if a.risk_level != "green"][:8]
    for a in elevated:
        facts.append(
            f"{a.risk_level.upper()} signal — {names.get(a.disease_code, a.disease_code)} in {a.region_name}, {a.state}: "
            f"outbreak likelihood {a.outbreak_probability:.0%} ({a.outbreak_tier}), incidence "
            f"{a.incidence_7d_per_100k:.1f}/100k/7d, growth ×{a.growth_7d:.2f}. Drivers: "
            + ", ".join(d.feature for d in a.drivers[:3]) + "."
        )
    if not elevated:
        facts.append("No region/disease combination is currently above GREEN risk in this scope.")

    alert_stmt = select(Alert).where(Alert.status.in_(["open", "acknowledged"])).order_by(Alert.created_at.desc()).limit(5)
    if disease:
        alert_stmt = alert_stmt.where(Alert.disease_code == disease)
    if state:
        alert_stmt = alert_stmt.join(Region, Region.id == Alert.region_id).where(Region.state == state)
    for al in (await db.scalars(alert_stmt)).all():
        facts.append(f"Open alert ({al.risk_level}, {al.status}) raised {al.created_at:%Y-%m-%d}: {al.title}.")
    return facts


def _prompt(question: str, facts: list[str], chunks) -> str:
    parts = ["SURVEILLANCE FACTS:"]
    parts += [f"[F{i}] {f}" for i, f in enumerate(facts, 1)]
    parts.append("\nSOURCES:")
    for i, c in enumerate(chunks, 1):
        parts.append(f"[S{i}] {c.document_title}\n{c.text}")
    parts.append(f"\nQUESTION:\n{question}")
    return "\n".join(parts)


async def answer(
    db: AsyncSession, question: str, disease: str | None = None, region_id: str | None = None,
    state: str | None = None, instructions: str | None = None, period_days: int = 14,
) -> CopilotAnswer:
    facts = await surveillance_facts(db, disease, state, region_id, period_days)
    chunks = await _retriever(db).search(question, top_k=6, disease=disease)
    prompt = _prompt(question if not instructions else f"{instructions}\n\n{question}", facts, chunks)
    result = await get_llm().complete(SYSTEM_PROMPT, prompt)
    return CopilotAnswer(
        answer=scrub_phi(result.text), provider=result.provider, model=result.model,
        citations=[Citation(ref=f"S{i}", title=c.document_title, source=c.document_source,
                            snippet=c.text[:280], score=c.score) for i, c in enumerate(chunks, 1)],
        context_facts=facts,
    )


async def situation_report(db: AsyncSession, disease: str | None, state: str | None, period_days: int) -> CopilotAnswer:
    scope = " ".join(filter(None, [disease, f"in {state}" if state else "nationally"]))
    q = f"Generate a situation report and risk assessment for {scope or 'all monitored diseases'} " \
        f"covering the last {period_days} days."
    return await answer(db, q, disease=disease, state=state, instructions=SITREP_INSTRUCTIONS, period_days=period_days)


async def index_document(db: AsyncSession, doc: KnowledgeDocIn) -> KnowledgeDocument:
    record = KnowledgeDocument(title=doc.title, doc_type=doc.doc_type, source=doc.source,
                               disease_code=doc.disease_code, published_on=doc.published_on or date.today())
    pieces = chunk_text(doc.content)
    vectors = await get_embedder().embed([f"{doc.title}. {p}" for p in pieces])
    record.chunks = [KnowledgeChunk(chunk_index=i, text=p, embedding=v.tolist())
                     for i, (p, v) in enumerate(zip(pieces, vectors))]
    db.add(record)
    await db.commit()
    return record
