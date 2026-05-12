# Document Q&A API

Upload PDFs, DOCX, or text files and ask natural language questions about them. Processing happens in the background so uploads never block. Answers are grounded in the document — if the information isn't there, the system says so.

---

## Quick Start

```bash
cp .env.example .env
# Add your OpenAI API key to .env

docker-compose up --build
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

To test with the included sample documents:

```bash
# Upload a document
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@sample_docs/climate_change_report_2024.txt"

# Returns a document ID. Check processing status:
curl http://localhost:8000/api/v1/documents/{document_id}

# Once status is "ready", start a conversation:
curl -X POST http://localhost:8000/api/v1/conversations \
  -H "Content-Type: application/json" \
  -d '{"document_id": "{document_id}"}'

# Ask a question:
curl -X POST http://localhost:8000/api/v1/conversations/{conversation_id}/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the current level of CO2 in the atmosphere?"}'
```

---

## API Reference

### Documents

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/documents/upload` | Upload a document (PDF, DOCX, TXT) |
| `GET` | `/api/v1/documents/{id}` | Get document status and metadata |
| `GET` | `/api/v1/documents` | List all documents |
| `DELETE` | `/api/v1/documents/{id}` | Delete document and all associated data |

### Conversations

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/conversations` | Create a conversation tied to a document |
| `GET` | `/api/v1/conversations/{id}` | Get conversation with full message history |
| `POST` | `/api/v1/conversations/{id}/ask` | Ask a follow-up question |
| `GET` | `/api/v1/conversations/by-document/{doc_id}` | List conversations for a document |

Document status flows: `pending` → `processing` → `ready` (or `failed` with an error message).

---

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌──────────┐
│   FastAPI   │───▶│    Redis    │───▶│  Celery  │
│   (port     │    │   (queue)   │    │  Worker  │
│    8000)    │    └─────────────┘    └──────────┘
└──────┬──────┘                            │
       │                                   │
       ▼                                   ▼
┌─────────────┐    ┌─────────────────────────────┐
│  PostgreSQL │    │  data/                      │
│  (metadata, │    │  ├── uploads/  (raw files)   │
│   chunks,   │    │  └── indexes/  (FAISS index) │
│   history)  │    └─────────────────────────────┘
└─────────────┘
```

Upload returns immediately with a `202 Accepted`. The Celery worker picks up the processing task, extracts text, chunks it, embeds the chunks, and builds a FAISS index — all without blocking the API. Both the API and worker share the `data/` volume so the index is accessible to the API when it's time to answer questions.

---

## Design Decisions

**Why Celery instead of FastAPI background tasks?**

FastAPI's `BackgroundTasks` run in the same process as the API. Embedding with sentence-transformers is CPU-intensive and can take 10–30 seconds for a large document. Blocking a FastAPI worker for that long under any load is a problem. Celery workers run in separate processes, can be scaled independently, and survive API restarts without losing queued work.

**Why FAISS instead of a hosted vector database?**

For this kind of system at moderate scale (thousands of documents), FAISS is fast, requires no external service, and runs entirely on disk. A hosted vector database like Pinecone or Qdrant adds operational complexity and cost that isn't justified until you're running at a scale where FAISS's single-machine limits actually bite you. The indexes are stored per-document so we're not dealing with one massive index that needs careful management.

**Chunking strategy**

The chunker splits on sentence boundaries rather than a fixed character count. This keeps sentences intact, which matters for embedding quality — embedding half a sentence gives a worse vector than embedding a complete thought. Chunks are approximately 400 words with 60-word overlap between adjacent chunks. The overlap helps when an answer spans a chunk boundary (e.g., the first half of an explanation is at the end of chunk 3 and the second half is at the start of chunk 4). After retrieval, chunks are re-sorted by their original position in the document before being sent to the LLM — reading context in document order produces cleaner answers than reading it in similarity-score order.

**Why all-MiniLM-L6-v2 for embeddings?**

It's 80 MB, runs on CPU in reasonable time, and performs well on semantic similarity tasks. For a production system handling high query volume, you'd want to look at larger models or GPU inference. But for this use case, MiniLM is a good tradeoff between speed and quality. It's also the most common starting point in the community, which means there's a lot of known behavior around it.

**What happens when OpenAI is down?**

The LLM service uses `tenacity` to retry on rate limit errors, connection errors, and timeouts — up to 3 attempts with exponential backoff. If all retries fail, the API returns a `503 Service Unavailable` with a message asking the user to try again. The question is not persisted in this case, so there's no phantom "user asked this" entry in the conversation history.

**What happens if the document has no answer?**

The system prompt explicitly instructs the model to respond with "I couldn't find information about that in the document." if the context doesn't contain the answer. We also apply a similarity threshold (0.25 cosine similarity) when retrieving chunks — if no chunk meets the threshold, we skip the LLM call entirely and return the fallback message directly. This avoids sending the model an empty context and hoping it handles it gracefully.

**What happens with a corrupt or scanned PDF?**

Text extraction will fail (PyPDF2 can't read images). The Celery task catches this, marks the document as `failed`, and saves a descriptive error message that's returned by the status endpoint. The file is still stored so you could retry with a different extraction method if you added one.

**Why PostgreSQL over MySQL?**

Mainly the `JSONB` column type, which we use to store the list of chunk IDs that sourced each answer. MySQL's JSON support is functional but less ergonomic. PostgreSQL also handles UUIDs as a native type rather than storing them as strings.

---

## Sample Documents

Three sample documents are included in `sample_docs/`:

| File | Content | Good test questions |
|------|---------|-------------------|
| `climate_change_report_2024.txt` | Environmental report covering emissions, sea level rise, policy | "What is the current CO2 level?" / "What percentage of global emissions does China produce?" |
| `python_engineering_guide.txt` | Internal engineering reference covering Python best practices | "What does the guide say about N+1 queries?" / "How should I handle retries?" |
| `acme_employee_handbook.txt` | Fictional company handbook covering benefits, compensation, policies | "How much parental leave do employees get?" / "What is the 401k match?" |

---

## Local Development (without Docker)

```bash
# Start dependencies
docker-compose up db redis -d

# Install deps
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env to point DATABASE_URL and REDIS_URL at localhost

# Run migrations
alembic upgrade head

# Start API
uvicorn app.main:app --reload

# Start worker (separate terminal)
celery -A app.celery_app worker --loglevel=info
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | — | Your OpenAI API key |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `REDIS_URL` | Yes | — | Redis connection string |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | OpenAI model to use for answers |
| `UPLOAD_DIR` | No | `data/uploads` | Where to store uploaded files |
| `INDEX_DIR` | No | `data/indexes` | Where to store FAISS indexes |
| `MAX_FILE_SIZE_MB` | No | `50` | Maximum upload size in megabytes |
