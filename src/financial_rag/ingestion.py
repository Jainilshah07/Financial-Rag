
import re

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# uv run uvicorn financial_rag.main:app --reload --app-dir src

def load_and_split_pdf(file_path: str) -> list[Document]:
    pages = PyMuPDFLoader(file_path).load() # Load the PDF and extract pages as List of Document objects
    chunks = []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1800,
        chunk_overlap=150,
    )

    for page in pages:
        text = page.page_content.strip()

        if not text:
            continue

        # Find numbered section headings, e.g. "4. Invoices and Payment:"
        pattern = r"(?m)^\s*(\d{1,2})\.\s+([A-Z][^\n]{2,80})\s*$"
        matches = list(re.finditer(pattern, text))

        sections = []

        if matches:
            # Keep introductory content before section 1
            if matches[0].start() > 0:
                sections.append(("Page introduction", text[:matches[0].start()]))

            # Keep each numbered section together
            for i, match in enumerate(matches):
                end = (
                    matches[i + 1].start()
                    if i + 1 < len(matches)
                    else len(text)
                )

                heading = match.group(0).strip()
                content = text[match.start():end].strip()
                sections.append((heading, content))
        else:
            # Pages without numbered sections stay together initially
            sections.append(("Page content", text))

        for heading, content in sections:
            # Split only when a section exceeds the target size
            parts = splitter.split_text(content)

            for part in parts:
                chunks.append(
                    Document(
                        page_content=part,
                        metadata={
                            **page.metadata,
                            "section": heading,
                            "chunk_type": (
                                "numbered_section"
                                if heading[0].isdigit()
                                else "page_content"
                            ),
                        },
                    )
                )

    return chunks
