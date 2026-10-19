from financial_rag.ingestion import load_and_split_pdf

pdf_path = "data/sample.pdf"
chunks = load_and_split_pdf(pdf_path)

for i, chunk in enumerate(chunks):
    print(f"\n--- Chunk {i + 1} ---")
    print("Page:", chunk.metadata.get("page"))
    print("Section:", chunk.metadata["section"])
    print(chunk.page_content[:500])