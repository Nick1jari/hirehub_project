import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.models import Document, DocumentStatus
from app.schemas.schemas import DocumentListResponse, DocumentResponse
from app.services.vector_store import delete_index
from app.tasks.tasks import process_document

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document for processing",
    description=(
        "Accepts PDF, DOCX, DOC, or TXT files up to 50 MB. "
        "Processing happens asynchronously — poll GET /documents/{id} to check status."
    ),
)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"'{ext}' is not supported. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024

    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.MAX_FILE_SIZE_MB} MB limit.",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    doc_id = uuid.uuid4()
    saved_filename = f"{doc_id}{ext}"
    file_path = upload_dir / saved_filename

    with open(file_path, "wb") as f:
        f.write(content)

    doc = Document(
        id=doc_id,
        filename=saved_filename,
        original_filename=file.filename,
        file_path=str(file_path),
        file_size=len(content),
        mime_type=file.content_type,
        status=DocumentStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    process_document.delay(str(doc.id))

    return doc


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document status and metadata",
)
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List all documents",
)
def list_documents(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    total = db.query(Document).count()
    docs = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .offset(skip)
        .limit(min(limit, 100))
        .all()
    )
    return {"documents": docs, "total": total, "skip": skip, "limit": limit}


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and all associated data",
)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    try:
        Path(doc.file_path).unlink(missing_ok=True)
    except Exception:
        pass

    delete_index(document_id)

    db.delete(doc)
    db.commit()
