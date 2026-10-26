from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import DB, Principal, require
from app.core.rbac import Perm
from app.models import KnowledgeDocument
from app.schemas import CopilotAnswer, CopilotQuestion, KnowledgeDocIn, KnowledgeDocOut, SitrepRequest
from app.services.copilot import service

router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.post("/ask", response_model=CopilotAnswer, summary="Ask a surveillance question (RAG, cited)")
async def ask(body: CopilotQuestion, db: DB, principal: Annotated[Principal, Depends(require(Perm.USE_COPILOT))]):
    return await service.answer(db, body.question, body.disease_code, body.region_id, principal.scope_state)


@router.post("/sitrep", response_model=CopilotAnswer, summary="Generate a situation report / risk assessment")
async def sitrep(body: SitrepRequest, db: DB, principal: Annotated[Principal, Depends(require(Perm.USE_COPILOT))]):
    return await service.situation_report(db, body.disease_code, principal.effective_state(body.state),
                                          body.period_days)


@router.post("/documents", response_model=KnowledgeDocOut, status_code=201,
             summary="Add a guideline / case definition / bulletin to the knowledge base")
async def add_document(body: KnowledgeDocIn, db: DB,
                       _: Annotated[Principal, Depends(require(Perm.MANAGE_KNOWLEDGE))]):
    return await service.index_document(db, body)


@router.get("/documents", response_model=list[KnowledgeDocOut])
async def list_documents(db: DB, _: Annotated[Principal, Depends(require(Perm.USE_COPILOT))]):
    return (await db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()))).all()
