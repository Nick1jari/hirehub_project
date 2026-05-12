from openai import OpenAI, RateLimitError, APIConnectionError, APITimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

client = OpenAI(api_key=settings.OPENAI_API_KEY)

SYSTEM_PROMPT = """You are a document assistant. Your job is to answer questions using only the excerpts from the document provided below.

Rules:
- Answer strictly from the provided context. Do not use outside knowledge.
- If the context doesn't contain enough information to answer, say exactly: "I couldn't find information about that in the document."
- If the context is partially relevant, use what's available and note what's missing.
- Be concise. Quote the document when it helps clarity.
- For follow-up questions, consider the conversation history."""


@retry(
    retry=retry_if_exception_type((RateLimitError, APIConnectionError, APITimeoutError)),
    wait=wait_exponential(multiplier=1, min=4, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
def get_answer(
    question: str,
    context_chunks: list[str],
    conversation_history: list[dict],
) -> str:
    if not context_chunks:
        return "I couldn't find information about that in the document."

    context = "\n\n---\n\n".join(
        f"[Excerpt {i + 1}]\n{chunk}" for i, chunk in enumerate(context_chunks)
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Last 3 turns (6 messages) — enough for follow-up context without hitting token limits
    for msg in conversation_history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append(
        {
            "role": "user",
            "content": f"Document excerpts:\n{context}\n\nQuestion: {question}",
        }
    )

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=1024,
    )

    return response.choices[0].message.content
