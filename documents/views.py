import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import Document, DocumentChunk
from .forms import DocumentUploadForm
from .services import loaders, ingestion

logger = logging.getLogger(__name__)

@login_required
def document_list_view(request):
    """Lists all documents uploaded by the authenticated user."""
    docs = Document.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'documents/document_list.html', {'documents': docs})

@login_required
def document_upload_view(request):
    """
    Handles single and multiple document uploads.
    Immediately processes each document through the local RAG ingestion pipeline.
    """
    if request.method == 'POST':
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_files = request.FILES.getlist('files')
            success_count = 0
            fail_count = 0

            for uploaded_file in uploaded_files:
                orig_name = loaders.sanitize_filename(uploaded_file.name)
                ext = orig_name.rsplit('.', 1)[-1].lower() if '.' in orig_name else ''

                # Create PostgreSQL Document record
                doc = Document.objects.create(
                    user=request.user,
                    file=uploaded_file,
                    original_filename=orig_name,
                    file_type=ext,
                    file_size=uploaded_file.size,
                    status=Document.STATUS_PENDING
                )

                # Ingest document into ChromaDB and PostgreSQL
                logger.info(f"Processing uploaded document {doc.id} ({orig_name})...")
                ok = ingestion.process_document(doc.id)
                if ok:
                    success_count += 1
                else:
                    fail_count += 1

            if success_count > 0:
                messages.success(request, f"Successfully processed {success_count} document(s).")
            if fail_count > 0:
                messages.error(request, f"{fail_count} document(s) failed ingestion. Check document details for error logs.")

            return redirect('documents:list')
        else:
            messages.error(request, "Please fix the upload errors below.")
    else:
        form = DocumentUploadForm()

    return render(request, 'documents/upload.html', {'form': form})

@login_required
def document_detail_view(request, pk):
    """
    Displays metadata and extracted chunks for a specific document.
    Enforces user ownership.
    """
    doc = get_object_or_404(Document, pk=pk, user=request.user)
    chunks = doc.chunks.order_by('chunk_index')
    return render(request, 'documents/document_detail.html', {
        'document': doc,
        'chunks': chunks
    })

@login_required
@require_POST
def document_delete_view(request, pk):
    """
    Securely deletes a document. Enforces user ownership.

    ChromaDB vector cleanup and physical file removal are handled centrally by
    the post_delete signal in documents/signals.py -- this guarantees cleanup
    happens no matter how the Document row gets deleted (this view, Django
    admin, a bulk action, or a cascade from user deletion), instead of only
    working when this specific view is used.
    """
    doc = get_object_or_404(Document, pk=pk, user=request.user)
    doc_id = doc.id
    filename = doc.original_filename

    logger.info(f"User {request.user.id} requested deletion of document {doc_id} ('{filename}').")

    doc.delete()  # triggers post_delete signal: purges ChromaDB vectors + physical file

    messages.success(request, f"Document '{filename}' and all associated vector embeddings have been deleted.")
    return redirect('documents:list')
