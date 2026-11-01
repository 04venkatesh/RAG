import logging
import os

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Document
from .services import chroma

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Document)
def cleanup_on_document_delete(sender, instance, **kwargs):
    """
    Guarantees ChromaDB vectors AND the physical uploaded file are removed
    whenever a Document row is deleted, no matter which code path triggered it:
    the dedicated delete view, the Django admin (single or bulk delete), a
    management shell, or a CASCADE delete from the owning User being removed.

    This exists because ChromaDB is a separate store from PostgreSQL with no
    foreign-key/CASCADE relationship to Document -- only the dedicated delete
    view cleaned it up, and only on the happy path. Any other deletion path
    (e.g. Django admin) skipped that step entirely, leaving orphaned vectors
    that a later chat query would still retrieve and treat as live document
    data, even though the document was "deleted".
    """
    # 1. Purge ChromaDB vectors for this document/user.
    try:
        deleted_count = chroma.delete_document_chunks(
            document_id=instance.id,
            user_id=instance.user_id,
        )
        logger.info(
            f"[signals] Purged {deleted_count} ChromaDB vector(s) for deleted "
            f"Document {instance.id} ('{instance.original_filename}')."
        )
    except Exception as e:
        # Deliberately do not re-raise: the PostgreSQL row is already gone by the
        # time post_delete fires, so raising here would just turn a cleanup
        # failure into an unrelated 500 error. Log loudly instead so it's visible
        # in the console/log file rather than silently disappearing.
        logger.error(
            f"[signals] FAILED to purge ChromaDB vectors for deleted Document "
            f"{instance.id} (user {instance.user_id}): {e}. Orphaned vectors may "
            f"remain in ChromaDB for this document_id/user_id and could still "
            f"surface in future chat answers."
        )

    # 2. Remove the physical file from media storage, if it still exists.
    try:
        if instance.file and instance.file.name:
            file_path = instance.file.path
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"[signals] Removed physical file: {file_path}")
    except Exception as e:
        logger.warning(
            f"[signals] Could not remove physical file for deleted Document "
            f"{instance.id}: {e}"
        )

