from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel


# --- Document schemas ---

class DocumentResponse(BaseModel):
    id: UUID
    original_filename: str
    file_size: Optional[int]
    status: str
    error_message: Optional[str]
    chunk_count: int
    word_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int
    skip: int
    limit: int


# --- Conversation schemas ---

class ConversationCreate(BaseModel):
    document_id: UUID
    title: Optional[str] = None


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    sources: Optional[List[int]]
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: UUID
    document_id: UUID
    title: Optional[str]
    created_at: datetime
    messages: List[MessageResponse] = []

    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    conversations: List[ConversationResponse]


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: List[int]
    conversation_id: UUID
