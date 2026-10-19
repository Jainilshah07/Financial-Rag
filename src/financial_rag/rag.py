
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

from financial_rag.config import settings


prompt = ChatPromptTemplate.from_template("""
You are a financial document assistant.

Answer the question using only the context provided.
If the answer is not present, say you could not find it.
Cite the source page number for your answer.

Context:
{context}

Question:
{question}
""")


llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=settings.groq_api_key,
)


def ask_question(vector_store, question: str) -> str:
    documents = vector_store.similarity_search(question, k=4)

    context = "\n\n".join(
        f"Page {doc.metadata.get('page', 0) + 1}:\n{doc.page_content}"
        for doc in documents
    )

    chain = prompt | llm

    response = chain.invoke({
        "context": context,
        "question": question,
    })

    return response.content


def stream_answer(chunks: list[dict], question: str):
    """Yield the answer text piece by piece from already-retrieved chunks."""
    context = "\n\n".join(
        f"{c['filename']}, Page {c['page']}:\n{c['text']}" for c in chunks
    )

    for part in (prompt | llm).stream({"context": context, "question": question}):
        if part.content:
            yield part.content
