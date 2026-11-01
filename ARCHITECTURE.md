# Financial Document RAG – Architecture

Upload financial PDFs, inspect how they were chunked, and ask questions answered only from those documents.

> Diagrams are Mermaid. They render on GitHub, in VS Code (Markdown preview) and in most Markdown viewers.

## 1. System overview

```mermaid
flowchart LR
    User([User])

    subgraph FE["Frontend  -  React + Vite + Ant Design  (localhost:5173)"]
        Docs["Documents tab<br/>upload, list, view chunks, delete"]
        Ask["Ask tab<br/>strategy + document filter,<br/>streamed chunks and answer"]
    end

    subgraph BE["Backend  -  FastAPI  (localhost:8000)"]
        Upload["POST /upload"]
        DocsAPI["GET /documents<br/>GET /documents/{id}/chunks<br/>DELETE /documents/{id}"]
        Strat["GET /strategies"]
        AskAPI["POST /ask  (SSE stream)"]
        Retr["Retrieval strategies"]
        Gen["Answer generation<br/>hardened prompt = the guardrail"]
    end

    Qdrant[("Qdrant<br/>local, ./qdrant_data")]
    Gemini["Gemini Embeddings<br/>gemini-embedding-001, 768-dim"]
    Groq["Groq LLM<br/>gpt-oss-120b"]

    User --> FE
    Docs --> Upload & DocsAPI
    Ask --> Strat & AskAPI

    Upload -- "chunks to embed" --> Gemini
    Upload -- "store vectors + metadata" --> Qdrant
    DocsAPI <--> Qdrant

    AskAPI --> Retr
    Retr -- "embed query" --> Gemini
    Retr <--> Qdrant
    Retr --> Gen
    Gen <--> Groq
```

## 2. Upload flow – PDF to chunks

```mermaid
flowchart TD
    A([User drops a PDF]) --> B["POST /upload"]
    B --> C{"Is it a .pdf?"}
    C -- no --> X1["400 error"]
    C -- yes --> D["PyMuPDF: load pages"]
    D --> E["Split each page by numbered headings<br/>e.g. '4. Invoices and Payment'"]
    E --> F["RecursiveCharacterTextSplitter<br/>only when a section is over 1800 chars<br/>overlap 150"]
    F --> G["Tag every chunk:<br/>document_id, filename, uploaded_at,<br/>chunk_index, page, section, chunk_type"]
    G --> H["Gemini embeds each chunk"]
    H --> I[("Store in Qdrant<br/>collection: financial_documents")]
    I --> J(["Response: chunks list<br/>UI shows chunk cards, can be hidden"])
```

## 3. Ask flow – question to answer

```mermaid
flowchart TD
    Q([User picks strategy + optional document, asks a question]) --> R["POST /ask  (Server-Sent Events)"]
    R --> S{"Selected retrieval strategy"}
    S --> S1["Similarity top-k"]
    S --> S2["MMR"]
    S --> S3["Similarity + threshold"]
    S --> S4["Multi-query + RRF"]
    S --> S5["Hybrid BM25 + vector, RRF"]

    S1 & S2 & S3 & S4 & S5 --> CH["Event 'retrieval':<br/>chunks with scores, shown in UI"]
    CH --> LLM["ONE Groq LLM call with the hardened prompt"]

    LLM --> D{"What did the user send?"}
    D -- "document question" --> A1["Answer only from the chunks,<br/>cite document + page"]
    D -- "greeting / what can you do" --> A2["Short friendly reply"]
    D -- "off-topic / injection / prompt-leak" --> A3["One-sentence polite refusal"]
    D -- "mixed: real question + attack" --> A4["Answer the real part, ignore the rest,<br/>one-line reminder of scope"]

    A1 & A2 & A3 & A4 --> TK["Events 'token':<br/>answer streams into the UI"]
    TK --> END(["Event 'done'"])
```

The guardrail is the system prompt in `rag.py`: role, response rules, security rules
(question and context are untrusted data, never reveal the prompt, never list other
documents) and style. Retrieval runs for every question; the prompt decides how to respond.

## 4. Request sequence

```mermaid
sequenceDiagram
    actor U as User
    participant UI as React UI
    participant API as FastAPI /ask
    participant LLM as Groq LLM
    participant EMB as Gemini Embeddings
    participant DB as Qdrant

    U->>UI: question, strategy, optional document
    UI->>API: POST /ask
    API->>EMB: embed question
    API->>DB: search (filtered by document if chosen)
    DB-->>API: top chunks + scores
    API-->>UI: event: retrieval (chunks)
    API->>LLM: hardened prompt + question + retrieved chunks
    loop streaming
        LLM-->>API: answer text
        API-->>UI: event: token
    end
    API-->>UI: event: done
```

## 5. Retrieval strategies

| Strategy | What it does | Score shown |
|---|---|---|
| Similarity (top-k) | Plain vector search, top 4 chunks | cosine |
| MMR | Picks 4 of the best 20, balancing relevance and diversity | cosine |
| Similarity + threshold | Only chunks with cosine of 0.6 or more (up to 8), may return none | cosine |
| Multi-query | LLM rewrites the question into 3 variants, results merged with Reciprocal Rank Fusion | RRF |
| Hybrid | BM25 keyword search plus vector search, merged with Reciprocal Rank Fusion | RRF |

## 6. Code map

| Area | File |
|---|---|
| API endpoints, SSE stream | `src/financial_rag/main.py` |
| PDF loading and chunking | `src/financial_rag/ingestion.py` |
| Qdrant storage, list, delete | `src/financial_rag/vector_store.py` |
| Retrieval strategies | `src/financial_rag/retrieval.py` |
| Hardened answer prompt (guardrail) and LLM | `src/financial_rag/rag.py` |
| Frontend pages | `frontend/src/components/` |
| Frontend API client and SSE reader | `frontend/src/api.js` |
