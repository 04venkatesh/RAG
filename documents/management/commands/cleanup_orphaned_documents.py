"""
Cleans up Document rows (and their DocumentChunk rows + ChromaDB vectors) whose
underlying physical file no longer exists -- e.g. because it was deleted directly
from the media/ folder on disk instead of through the app's Delete button.

Deleting a file manually only removes the file. It does NOT touch the Document
row in PostgreSQL, the DocumentChunk rows, or the ChromaDB vectors -- so old
content keeps being retrieved and answered from indefinitely, even though the
file itself is long gone. This command finds those orphaned rows and removes
them properly (which also triggers the post_delete signal that purges the
matching ChromaDB vectors).

Usage:
    python manage.py cleanup_orphaned_documents            # preview only
    python manage.py cleanup_orphaned_documents --delete    # actually delete
    python manage.py cleanup_orphaned_documents --user alice --delete
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from documents.models import Document


class Command(BaseCommand):
    help = "Find (and optionally delete) Document rows whose physical file is missing on disk."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Actually delete the orphaned rows (and purge their ChromaDB vectors). "
                 "Without this flag, the command only reports what it found.",
        )
        parser.add_argument(
            "--user",
            default=None,
            help="Limit to a single username. Omit to check every user's documents.",
        )

    def handle(self, *args, **options):
        do_delete = options["delete"]
        username = options["user"]

        qs = Document.objects.all()
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"No user found with username '{username}'"))
                return
            qs = qs.filter(user=user)

        orphaned = []
        for doc in qs:
            try:
                exists = bool(doc.file) and doc.file.storage.exists(doc.file.name)
            except Exception:
                exists = False
            if not exists:
                orphaned.append(doc)

        if not orphaned:
            self.stdout.write(self.style.SUCCESS("No orphaned documents found. Everything on disk matches the database."))
            return

        self.stdout.write(f"Found {len(orphaned)} document(s) with a missing file:\n")
        for doc in orphaned:
            self.stdout.write(
                f"  - #{doc.id} '{doc.original_filename}' "
                f"(user: {doc.user.username}, status: {doc.status}, "
                f"{doc.chunks.count()} chunk(s) in Postgres)"
            )

        if not do_delete:
            self.stdout.write(
                self.style.WARNING(
                    "\nThis was a preview only -- nothing was deleted. "
                    "Re-run with --delete to remove these rows and purge their "
                    "ChromaDB vectors."
                )
            )
            return

        self.stdout.write("")
        deleted_count = 0
        for doc in orphaned:
            doc_id = doc.id
            name = doc.original_filename
            doc.delete()  # cascades DocumentChunk rows, triggers ChromaDB purge via signal
            deleted_count += 1
            self.stdout.write(self.style.SUCCESS(f"Deleted #{doc_id} '{name}' and purged its vectors."))

        self.stdout.write(self.style.SUCCESS(f"\nDone. Cleaned up {deleted_count} orphaned document(s)."))
