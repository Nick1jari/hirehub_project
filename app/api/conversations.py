import logging

from fastapi import APIRouter, Depends, HTTPException, status
from openai import OpenAIError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Chunk, Conversation, Document, DocumentStatus, Message
from app.schemas.schemas import (
    AskRequest,
    AskResponse,
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
)
from app.services import embeddings, llm_service, vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new conversation about a document",
)
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == body.document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if doc.status != DocumentStatus.READY:
        raise HTTPException(
            status_code=409,
            detail=f"Document is not ready yet (current status: {doc.status}). Wait for processing to complete.",
        )

    conv = Conversation(
        document_id=doc.id,
        title=body.title,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get a conversation and its full message history",
)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conv


@router.post(
    "/{conversation_id}/ask",
    response_model=AskResponse,
    summary="Ask a question and get an answer grounded in the document",
)
def ask_question(
    conversation_id: str,
    body: AskRequest,
    db: Session = Depends(get_db),
):
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    doc = db.query(Document).filter(Document.id == conv.document_id).first()
    if not doc or doc.status != DocumentStatus.READY:
        raise HTTPException(status_code=409, detail="Document is not ready for querying.")

    # Retrieve relevant chunks
    try:
        query_vec = embeddings.embed_query(body.question)
        hits = vector_store.search_index(str(conv.document_id), query_vec, top_k=5)
    except FileNotFoundError:
        raise HTTPException(status_code=409, detail="Document index not found. It may need reprocessing.")
    except Exception as e:
        logger.exception("Vector search failed")
        raise HTTPException(status_code=500, detail="Search failed. Please try again.")

    # Fetch chunk text from DB (source of truth; index only holds IDs)
    chunk_ids = [chunk_id for chunk_id, _ in hits]
    chunks = (
        db.query(Chunk)
        .filter(Chunk.id.in_(chunk_ids))
        .order_by(Chunk.chunk_index)
        .all()
    ) if chunk_ids else []

    context_texts = [c.content for c in chunks]

    # Build conversation history for the LLM
    history_messages = [
        {"role": m.role, "content": m.content}
        for m in conv.messages
    ]

    # Call OpenAI
    try:
        answer = llm_service.get_answer(
            question=body.question,
            context_chunks=context_texts,
            conversation_history=history_messages,
        )
    except OpenAIError as e:
        logger.error(f"OpenAI error: {e}")
        raise HTTPException(
            status_code=503,
            detail="The AI service is temporarily unavailable. Please try again in a moment.",
        )

    # Persist the exchange
    db.add(Message(conversation_id=conv.id, role="user", content=body.question, sources=None))
    db.add(
        Message(
            conversation_id=conv.id,
            role="assistant",
            content=answer,
            sources=chunk_ids or None,
        )
    )
    db.commit()

    return AskResponse(
        answer=answer,
        sources=chunk_ids,
        conversation_id=conv.id,
    )


@router.get(
    "/by-document/{document_id}",
    response_model=ConversationListResponse,
    summary="List all conversations for a document",
)
def list_conversations_for_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    convs = (
        db.query(Conversation)
        .filter(Conversation.document_id == document_id)
        .order_by(Conversation.created_at.desc())
        .all()
    )
    return {"conversations": convs}
