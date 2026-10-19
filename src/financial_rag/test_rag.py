from financial_rag.vector_store import open_vector_store
from financial_rag.rag import ask_question

# Create the vector store
vector_store = open_vector_store()

# Ask a question
answer = ask_question(
    vector_store,
    "What are the payment terms for purchase order 3600031165?",
)

print("\nAnswer:")
print(answer)

vector_store.client.close()