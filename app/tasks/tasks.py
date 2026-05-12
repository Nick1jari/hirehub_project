import logging
from datetime import datetime

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.models import Chunk, Document, DocumentStatus
from app.services import document_processor, embeddings, vector_store

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="process_document")
def process_document(self, document_id: str) -> dict:
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            logger.error(f"Document {document_id} not found in DB")
            return {"status": "error", "reason": "document not found"}

        doc.status = DocumentStatus.PROCESSING
        doc.updated_at = datetime.utcnow()
        db.commit()

        # --- Step 1: Extract text ---
        try:
            text = document_processor.extract_text(doc.file_path)
        except Exception as e:
            logger.exception(f"Text extraction failed for {document_id}")
            _mark_failed(db, doc, f"Text extraction failed: {str(e)}")
            return {"status": "error", "reason": str(e)}

        if not text or not text.strip():
            _mark_failed(db, doc, "No text could be extracted from the document.")
            return {"status": "error", "reason": "empty document"}

        # --- Step 2: Chunk ---
        raw_chunks = document_processor.chunk_text(text)
        if not raw_chunks:
            _mark_failed(db, doc, "Document produced no chunks after processing.")
            return {"status": "error", "reason": "no chunks"}

        # --- Step 3: Save chunks to DB ---
        db.query(Chunk).filter(Chunk.document_id == document_id).delete()

        chunk_objects = []
        for c in raw_chunks:
            chunk_obj = Chunk(
                document_id=doc.id,
                content=c["content"],
                chunk_index=c["chunk_index"],
                word_count=c["word_count"],
            )
            db.add(chunk_obj)
            chunk_objects.append(chunk_obj)

        db.flush()  # get IDs assigned before building index

        # --- Step 4: Embed ---
        texts = [c.content for c in chunk_objects]
        try:
            vecs = embeddings.embed_texts(texts)
        except Exception as e:
            logger.exception(f"Embedding failed for {document_id}")
            _mark_failed(db, doc, f"Embedding failed: {str(e)}")
            return {"status": "error", "reason": str(e)}

        # --- Step 5: Build FAISS index ---
        chunk_ids = [c.id for c in chunk_objects]
        try:
            vector_store.build_index(document_id, vecs, chunk_ids)
        except Exception as e:
            logger.exception(f"Index build failed for {document_id}")
            _mark_failed(db, doc, f"Index build failed: {str(e)}")
            return {"status": "error", "reason": str(e)}

        # --- Done ---
        total_words = sum(c["word_count"] for c in raw_chunks)
        doc.status = DocumentStatus.READY
        doc.chunk_count = len(chunk_objects)
        doc.word_count = total_words
        doc.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"Document {document_id} processed: {len(chunk_objects)} chunks, {total_words} words")
        return {"status": "ready", "chunks": len(chunk_objects), "words": total_words}

    except Exception as e:
        logger.exception(f"Unexpected error processing document {document_id}")
        try:
            _mark_failed(db, doc, f"Unexpected error: {str(e)}")
        except Exception:
            pass
        return {"status": "error", "reason": str(e)}
    finally:
        db.close()


def _mark_failed(db, doc, message: str) -> None:
    doc.status = DocumentStatus.FAILED
    doc.error_message = message
    doc.updated_at = datetime.utcnow()
    db.commit()
