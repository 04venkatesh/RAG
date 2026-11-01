import json
import logging
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from .models import ChatSession, ChatMessage
from .services import rag
from .services.llm import LLMServiceError
from documents.models import Document

logger = logging.getLogger(__name__)

@login_required
def chat_view(request, session_id=None):
    """
    Renders the main ChatGPT-like chat interface.
    Loads user's active session, full conversation history, and document library.
    """
    user_sessions = ChatSession.objects.filter(user=request.user).order_by('-updated_at')

    if session_id:
        active_session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    else:
        active_session = user_sessions.first()
        if not active_session:
            active_session = ChatSession.objects.create(
                user=request.user,
                title="New Conversation"
            )
            return redirect('chat:session_detail', session_id=active_session.id)

    chat_messages = active_session.messages.all().order_by('created_at')
    user_documents = Document.objects.filter(user=request.user).order_by('-created_at')

    context = {
        'active_session': active_session,
        'sessions': user_sessions,
        'chat_messages': chat_messages,
        'documents': user_documents,
    }
    return render(request, 'chat/chat.html', context)


@login_required
def new_chat_view(request):
    """Creates a new chat session and redirects to it."""
    session = ChatSession.objects.create(
        user=request.user,
        title="New Conversation"
    )
    return redirect('chat:session_detail', session_id=session.id)


@login_required
@require_POST
def chat_message_api(request, session_id):
    """
    AJAX endpoint handling user questions.
    Enforces strict ownership, executes the RAG pipeline, saves messages, and returns JSON.
    """
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)

    try:
        data = json.loads(request.body)
        question = data.get('question', '').strip()
    except Exception:
        question = request.POST.get('question', '').strip()

    if not question:
        return JsonResponse({
            "success": False,
            "error": "Question cannot be empty."
        }, status=400)

    max_length = getattr(settings, "MAX_CHAT_QUESTION_LENGTH", 4000)
    if len(question) > max_length:
        return JsonResponse({
            "success": False,
            "error": f"Question must be {max_length} characters or fewer."
        }, status=400)

    # 1. Save User message
    user_msg = ChatMessage.objects.create(
        session=session,
        role=ChatMessage.ROLE_USER,
        content=question
    )

    # Auto-title session from first user question if currently default
    if session.title == "New Conversation":
        cleaned_title = question[:45].strip()
        if len(question) > 45:
            cleaned_title += "..."
        session.title = cleaned_title
        session.save(update_fields=['title'])

    # 2. Execute RAG Pipeline
    try:
        rag_result = rag.answer_question(
            user=request.user,
            question=question,
            session=session
        )
        answer = rag_result.get("answer", "")
        sources = rag_result.get("sources", [])

        # 3. Save Assistant response with verified sources
        ChatMessage.objects.create(
            session=session,
            role=ChatMessage.ROLE_ASSISTANT,
            content=answer,
            sources=sources
        )

        session.updated_at = timezone.now()
        session.save(update_fields=['updated_at'])

        return JsonResponse({
            "success": True,
            "answer": answer,
            "sources": sources
        })

    except LLMServiceError as e:
        logger.error(f"LLM Service Error during chat: {e}")
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=503)
    except Exception as e:
        logger.exception(f"Unexpected error processing chat message: {e}")
        return JsonResponse({
            "success": False,
            "error": "An unexpected error occurred while processing your question. Please try again."
        }, status=500)


@login_required
@require_POST
def delete_chat_view(request, session_id):
    """Deletes a chat session and all contained messages."""
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    session.delete()
    messages.success(request, "Conversation deleted.")
    return redirect('chat:chat')
