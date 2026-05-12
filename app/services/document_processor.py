import re
from pathlib import Path

import PyPDF2
from docx import Document


def extract_text(file_path: str) -> str:
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(file_path)
    elif ext in (".docx", ".doc"):
        return _extract_docx(file_path)
    elif ext == ".txt":
        return _extract_txt(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _extract_pdf(file_path: str) -> str:
    pages = []
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported.")
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
    if not pages:
        raise ValueError("Could not extract any text from the PDF. It may be a scanned image.")
    return "\n\n".join(pages)


def _extract_docx(file_path: str) -> str:
    doc = Document(file_path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if not paragraphs:
        raise ValueError("No text found in the document.")
    return "\n\n".join(paragraphs)


def _extract_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 60) -> list[dict]:
    """
    Split text into overlapping chunks by sentence boundary.

    chunk_size is a soft word-count limit per chunk. We don't cut mid-sentence,
    so actual sizes vary. overlap keeps a tail of the previous chunk at the start
    of the next one — this helps retrieval when the answer spans a chunk boundary.
    """
    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Split on sentence-ending punctuation followed by whitespace + capital letter.
    # Not perfect, but handles the majority of real document text.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\'])", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current_words: list[str] = []
    chunk_index = 0

    for sentence in sentences:
        words = sentence.split()

        if len(current_words) + len(words) > chunk_size and current_words:
            chunk_content = " ".join(current_words)
            chunks.append(
                {
                    "content": chunk_content,
                    "chunk_index": chunk_index,
                    "word_count": len(current_words),
                }
            )
            chunk_index += 1
            # Seed next chunk with overlapping tail to preserve context
            current_words = current_words[-overlap:] + words
        else:
            current_words.extend(words)

    if current_words:
        chunks.append(
            {
                "content": " ".join(current_words),
                "chunk_index": chunk_index,
                "word_count": len(current_words),
            }
        )

    return chunks
