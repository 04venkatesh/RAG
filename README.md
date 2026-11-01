# Local RAG Document Assistant

A multi-user Retrieval-Augmented Generation (RAG) web application built with Django, PostgreSQL, ChromaDB, Sentence Transformers, and Ollama. Users can upload documents, ask questions in natural language, and receive answers grounded in retrieved document passages with source references.

## Features

- User registration, login, and isolated chat histories.
- Upload PDF, DOCX, TXT, CSV, and XLSX documents.
- Extract text with page, sheet, and row metadata.
- Chunk documents and generate embeddings with `all-MiniLM-L6-v2`.
- Persist vectors in ChromaDB using cosine distance.
- Enforce user-level vector filtering during retrieval.
- Generate grounded answers locally through Ollama (Mistral by default).
- Display source document references and snippets.
- Delete documents and associated chunks/vectors.
- Diagnostic management command and automated tests.

## Architecture

```text
Browser
  |
  v
Django Views / Templates
  |------------------------------|
  v                              v
PostgreSQL                   Document Storage
(users, chats,               (uploaded files)
documents, chunks)
  |
  v
Document Ingestion
  |-- Extract (PyMuPDF / python-docx / openpyxl)
  |-- Chunk
  |-- Embed (Sentence Transformers)
  v
ChromaDB (persistent vectors + user/document metadata)

Question -> Query Embedding -> User-scoped Chroma Search
         -> Relevant Context + Chat History
         -> Ollama / Mistral
         -> Answer + Source References
```

PostgreSQL stores application records and chunk-to-vector mappings. ChromaDB stores embeddings and searchable chunk text. Uploaded files and ChromaDB data are runtime data and must be backed up separately.

## Requirements

- Python 3.10 or newer (Python 3.11 is recommended).
- PostgreSQL 14+ for a shared/production deployment; SQLite is used automatically for simple local development when `DATABASE_URL` is not set.
- Ollama installed and running.
- Sufficient RAM/disk for PyTorch and the embedding model. First model load may download `all-MiniLM-L6-v2`.

## Local setup (Windows PowerShell)

1. Extract the project and open a terminal in the folder containing `manage.py`.

2. Create and activate a virtual environment:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Create your local environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

   Set a private `SECRET_KEY`. For local development, leave `DATABASE_URL` unset to use SQLite. To use PostgreSQL, uncomment and configure the `DATABASE_URL` value in `.env`.

5. Install/start Ollama and download the model:

   ```powershell
   ollama serve
   ollama pull mistral
   ```

6. Run database migrations and start Django:

   ```powershell
   python manage.py migrate
   python manage.py check
   python manage.py runserver
   ```

7. Open `http://127.0.0.1:8000/`, register an account, upload a document, and ask a question.

The embedding model is loaded on first ingestion/query. The first run can take longer while model files are downloaded and cached.

## Docker setup

1. Copy `.env.example` to `.env` and set a strong `SECRET_KEY`, `POSTGRES_PASSWORD`, and `ALLOWED_HOSTS`. Set `DEBUG=False`.
2. Start the services:

   ```bash
   docker compose up --build -d
   ```
3. Pull the LLM inside the Ollama container:

   ```bash
   docker compose exec ollama ollama pull mistral
   ```
4. Open `http://localhost:8000`.

The Compose stack persists PostgreSQL, Ollama model files, ChromaDB vectors, and uploaded media in named volumes. For a public deployment, configure HTTPS, a real domain, secure secrets, backups, and an Ollama endpoint reachable from the web container. Do not expose PostgreSQL or the Ollama API publicly without appropriate network controls.

## Useful commands

```bash
python manage.py check
python manage.py makemigrations
python manage.py migrate
python manage.py test
python manage.py diagnose_rag --user <username> --question "Summarize my document"
python manage.py cleanup_orphaned_documents
```

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DEBUG` | Django debug mode | `True` |
| `SECRET_KEY` | Django signing key | Local-only fallback |
| `ALLOWED_HOSTS` | Comma-separated hostnames | localhost |
| `DATABASE_URL` | PostgreSQL connection URL | SQLite |
| `CHROMA_PERSIST_DIRECTORY` | ChromaDB persistence path | `./chroma_db` |
| `CHROMA_COLLECTION_NAME` | Vector collection | `document_chunks` |
| `OLLAMA_BASE_URL` | Ollama API base URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Generation model | `mistral` |
| `OLLAMA_TIMEOUT` | LLM request timeout in seconds | `300` |
| `EMBEDDING_MODEL` | Sentence Transformer model | `all-MiniLM-L6-v2` |
| `CHUNK_SIZE` | Chunk target size | `800` |
| `CHUNK_OVERLAP` | Chunk overlap | `100` |
| `TOP_K` | Retrieved chunk count | `5` |
| `SIMILARITY_THRESHOLD` | Minimum cosine similarity | `0.35` |
| `MAX_UPLOAD_SIZE_MB` | Upload size limit | `20` |

See `.env.example` for the complete configuration list.

## Security and operational notes

- ChromaDB queries must always include the authenticated `user_id` metadata filter. Preserve and extend the cross-user isolation tests when changing retrieval.
- Document and chat detail views must scope database queries to `request.user`.
- Keep `.env`, uploaded files, ChromaDB persistence, database files, and model weights out of Git.
- Configure production `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, HTTPS, and trusted CSRF origins before deployment.
- The current ingestion flow runs synchronously in the web request. For larger files or production traffic, move ingestion and LLM generation to a background worker (Celery/RQ) with job status updates.
- ChromaDB and PostgreSQL are separate stores; backup and restore both consistently.
- Similarity thresholds are model- and dataset-dependent. Evaluate retrieval quality with representative questions instead of assuming one threshold is universally correct.
- Prompt instructions reduce prompt-injection risk but do not replace access control, input validation, or output review.

## Project layout

```text
RAG/
├── accounts/              # Registration, login, logout
├── chat/                  # Chat sessions, messages, RAG pipeline
│   ├── management/         # Diagnostic commands
│   └── services/           # Retrieval, prompt building, Ollama
├── config/                 # Django settings and URL configuration
├── documents/              # Uploads, extraction, chunking, embeddings
│   ├── management/         # Cleanup commands
│   └── services/
├── media/                  # Runtime uploads (not committed)
├── static/                 # CSS and JavaScript
├── templates/              # Django templates
├── tests/                  # Automated tests
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── manage.py
└── requirements.txt
```

## Current limitations / recommended next upgrades

1. Background jobs for ingestion and long-running LLM requests.
2. Hybrid retrieval (keyword + vector) and a reranker for better recall/precision.
3. OCR support for scanned PDFs and image-based documents.
4. Streaming responses and cancellation.
5. Rate limiting, per-user storage quotas, and observability.
6. Evaluation dataset with retrieval recall, answer faithfulness, and citation correctness metrics.
7. Object storage for uploaded files and a managed/remote vector database for multi-instance deployment.

## License

Add a license before distributing or publishing this project.
