"""
Diagnostic command for the RAG query pipeline.

Run this from your project root (where manage.py lives):

    python manage.py diagnose_rag --user <username> --question "What is in my resume?"

It walks through every stage of the real pipeline (embedding, ChromaDB query,
prompt building, Ollama generation) and reports exactly which stage fails and why,
instead of the generic 500 you see in the browser.
"""
import time
import traceback

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.conf import settings


class Command(BaseCommand):
    help = "Diagnose the RAG query pipeline stage-by-stage."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username to run the query as")
        parser.add_argument(
            "--question",
            default="What is this document about?",
            help="Question to test with",
        )

    def handle(self, *args, **options):
        username = options["user"]
        question = options["question"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"No user found with username '{username}'")

        self.stdout.write(self.style.NOTICE(f"Running diagnosis for user '{username}'...\n"))

        # --- Stage 0: Config sanity check ---
        self.stdout.write("[0/5] Checking configuration...")
        self.stdout.write(f"      CHROMA_PERSIST_DIRECTORY = {settings.CHROMA_PERSIST_DIRECTORY}")
        self.stdout.write(f"      CHROMA_COLLECTION_NAME   = {settings.CHROMA_COLLECTION_NAME}")
        self.stdout.write(f"      EMBEDDING_MODEL          = {settings.EMBEDDING_MODEL}")
        self.stdout.write(f"      OLLAMA_BASE_URL          = {settings.OLLAMA_BASE_URL}")
        self.stdout.write(f"      OLLAMA_MODEL             = {settings.OLLAMA_MODEL}")
        self.stdout.write(f"      SIMILARITY_THRESHOLD     = {settings.SIMILARITY_THRESHOLD}")
        self.stdout.write(f"      TOP_K                    = {settings.TOP_K}\n")

        # --- Stage 1: Does this user actually have processed documents? ---
        self.stdout.write("[1/5] Checking Document records...")
        try:
            from documents.models import Document

            docs = Document.objects.filter(user=user)
            if not docs.exists():
                self.stdout.write(self.style.WARNING("      No Document rows for this user at all."))
            for d in docs:
                self.stdout.write(f"      - #{d.id} '{d.original_filename}' status={d.status}")
            processed = docs.filter(status=Document.STATUS_PROCESSED).count()
            if processed == 0:
                self.stdout.write(
                    self.style.ERROR(
                        "      No documents with status=processed. Uploads may be failing "
                        "ingestion silently -- check document_detail page for error_message."
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS(f"      {processed} processed document(s) found.\n"))
        except Exception:
            self.stdout.write(self.style.ERROR("      FAILED at Document lookup:"))
            self.stdout.write(traceback.format_exc())
            return

        # --- Stage 2: Embedding model load + query embedding ---
        self.stdout.write("[2/5] Loading embedding model & embedding the query...")
        try:
            from documents.services import embedder

            t0 = time.time()
            query_embedding = embedder.embed_text(question)
            self.stdout.write(
                self.style.SUCCESS(
                    f"      OK -- {len(query_embedding)}-dim vector in {time.time() - t0:.2f}s\n"
                )
            )
        except Exception:
            self.stdout.write(self.style.ERROR("      FAILED at embedding stage:"))
            self.stdout.write(traceback.format_exc())
            self.stdout.write(
                self.style.WARNING(
                    "\n      This usually means the SentenceTransformer model could not be "
                    "loaded (no internet on first run / model not cached, or an incompatible "
                    "version of sentence-transformers/torch)."
                )
            )
            return

        # --- Stage 3: ChromaDB query ---
        self.stdout.write("[3/5] Querying ChromaDB...")
        try:
            from chat.services import retriever

            chunks = retriever.retrieve_relevant_chunks(user=user, query=question)
            self.stdout.write(f"      Retrieved {len(chunks)} chunk(s) above threshold.")
            for c in chunks[:3]:
                self.stdout.write(f"      - '{c['document_name']}' score={c['score']}")
            if not chunks:
                self.stdout.write(
                    self.style.WARNING(
                        "      Zero chunks passed SIMILARITY_THRESHOLD "
                        f"({settings.SIMILARITY_THRESHOLD}). This is not an error -- it just "
                        "means the app will return the 'not enough information' fallback "
                        "message instead of calling the LLM. Try lowering SIMILARITY_THRESHOLD "
                        "in .env if this happens for questions that clearly relate to the "
                        "uploaded documents."
                    )
                )
            self.stdout.write("")
        except Exception:
            self.stdout.write(self.style.ERROR("      FAILED at ChromaDB query stage:"))
            self.stdout.write(traceback.format_exc())
            return

        # --- Stage 4: Ollama connectivity + generation ---
        self.stdout.write("[4/5] Calling Ollama...")
        try:
            from chat.services import llm

            t0 = time.time()
            answer = llm.generate("Reply with the single word: OK", timeout=30)
            self.stdout.write(
                self.style.SUCCESS(f"      OK -- Ollama responded in {time.time() - t0:.2f}s: '{answer[:80]}'\n")
            )
        except llm.LLMServiceError as e:
            self.stdout.write(self.style.ERROR(f"      FAILED -- Ollama error: {e}"))
            self.stdout.write(
                self.style.WARNING(
                    "\n      Fix: run `ollama serve` in a terminal, and make sure the model "
                    f"is pulled with `ollama pull {settings.OLLAMA_MODEL}`."
                )
            )
            return
        except Exception:
            self.stdout.write(self.style.ERROR("      FAILED at Ollama stage (unexpected):"))
            self.stdout.write(traceback.format_exc())
            return

        # --- Stage 5: Full pipeline, exactly as the view calls it ---
        self.stdout.write("[5/5] Running the full answer_question() pipeline...")
        try:
            from chat.services import rag

            result = rag.answer_question(user=user, question=question)
            self.stdout.write(self.style.SUCCESS("      SUCCESS. Full result:"))
            self.stdout.write(f"      Answer : {result['answer'][:200]}")
            self.stdout.write(f"      Sources: {len(result['sources'])}")
        except Exception:
            self.stdout.write(self.style.ERROR("      FAILED at full pipeline stage:"))
            self.stdout.write(traceback.format_exc())
            return

        self.stdout.write(self.style.SUCCESS("\nAll stages passed. The pipeline works end-to-end."))
