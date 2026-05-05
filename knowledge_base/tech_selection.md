# Technology Selection Rationale

This document records the technology decisions for the Dental Customer Success Agent and the reasoning behind each choice. It serves as a reference for team members and a technical brief for client demonstrations.

## 1. Core Component Stack

| Component | Selection | Alternatives | Rationale |
| :--- | :--- | :--- | :--- |
| **LLM** | **Claude 3.5 Sonnet** | GPT-4o, Gemini 1.5 Pro | Superior multilingual nuance and professional tone. High performance-to-cost ratio for complex dental terminology. |
| **Embedding Model** | **text-embedding-3-large** | Cohere, HuggingFace | High-dimensional accuracy. Excellent multilingual support (cross-lingual retrieval) which is critical for our 6 target languages. |
| **Vector Store** | **ChromaDB** | Pinecone, Weaviate | Runs locally with zero infrastructure cost for the current knowledge base scale (30–200 chunks). Low latency and easy setup for Phase 1/2. |
| **Orchestration** | **LangChain** | LlamaIndex, Haystack | Industry standard with robust community integrations for document loaders, RAG chains, and future scalability. |
| **UI Framework** | **Streamlit** | Flask, React | Rapid prototyping. Turns Python logic into a professional demo dashboard in hours rather than days, which fits the Phase 2 timeline. |
| **Language Detection** | **langdetect** | Google Translate API | Lightweight, open-source, and runs locally. Sufficiently accurate for identifying the specific 6 target languages (EN, FR, DE, NL, ES, BE). |
| **Version Control** | **GitHub** | GitLab, Bitbucket | Standard for collaborative development and seamless integration with deployment platforms like Render or Railway. |

---

## 2. Platform Comparison: Coze vs. Python

In the demo Q&A, a client might ask why we didn't use a "No-Code" platform like **Coze**. Below is our rationale for choosing a custom **Python** build:

### If we used Coze:
* **Workflow:** We would have used their drag-and-drop builder for API connections.
* **Limitations:** High dependency on their internal ecosystem, less control over specific interaction logging (Module M7), and harder to implement custom stub logic for M5/M6 during Phase 2.

### Why Python was chosen:
1.  **Transparency & Ownership:** We own the entire codebase and logic. There are no "black boxes" in how the RAG retrieval or intent classification works.
2.  **Scalability:** A custom build allows us to transition from a local ChromaDB to a cloud vector store (like Pinecone) with a single line of code update.
3.  **Complex Logic:** Handling custom "Escalation Gates" and dental-specific file parsing (STLs/PDFs) is more reliable and customizable in a native Python environment.
4.  **Integration:** Python offers superior libraries (`imaplib`, `smtplib`) for the Phase 3 live email connection requirement.

---

## 3. Implementation Strategy

We have prioritized a **"Stub" architecture** for Modules M5 (File Parsing) and M6 (System Integration) during the demo phase. 

* **Rationale:** The demo's primary goal is to validate the core RAG pipeline: intent classification, multilingual retrieval, and professional reply generation. 
* **Outcome:** Using stubs allows the architecture to be theoretically correct and "plumbed in" while deferring the engineering complexity of real ERP/API access until Phase 3 and 4.