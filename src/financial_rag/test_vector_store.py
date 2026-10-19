from financial_rag.ingestion import load_and_split_pdf
from financial_rag.vector_store import create_vector_store

chunks = load_and_split_pdf("data/sample.pdf")
vector_store = create_vector_store(chunks)

results = vector_store.similarity_search(
    "What are the payment terms?",
    k=3,
)

for result in results:
    print("\n--- Result ---")
    print(result.page_content[:500])
    print(result.metadata)

vector_store.client.close()