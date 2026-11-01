document.addEventListener("DOMContentLoaded", function () {
    const chatApp = document.querySelector(".chat-app-wrapper");
    if (!chatApp) return;

    const sessionId = chatApp.dataset.sessionId;
    const form = document.getElementById("chat-form");
    const textarea = document.getElementById("message-input");
    const sendButton = document.getElementById("send-button");
    const messagesContainer = document.getElementById("chat-messages-container");
    const messagesList = document.getElementById("chat-messages");
    const welcomeCard = document.getElementById("chat-welcome");
    const chatTitleHeader = document.getElementById("chat-title");

    // Retrieve CSRF token from meta tag
    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    // Scroll chat viewport to the very bottom
    function scrollToBottom(smooth = true) {
        if (messagesContainer) {
            messagesContainer.scrollTo({
                top: messagesContainer.scrollHeight,
                behavior: smooth ? "smooth" : "auto"
            });
        }
    }

    // Initial scroll on page load
    scrollToBottom(false);

    // Auto-grow textarea height
    function adjustTextareaHeight() {
        textarea.style.height = "auto";
        textarea.style.height = Math.min(textarea.scrollHeight, 180) + "px";
    }

    textarea.addEventListener("input", adjustTextareaHeight);

    // Enter to submit, Shift+Enter for newline
    textarea.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!sendButton.disabled) {
                form.dispatchEvent(new Event("submit", { cancelable: true }));
            }
        }
    });

    // Make welcome hint items clickable
    document.querySelectorAll(".hint-item").forEach(hint => {
        hint.addEventListener("click", function () {
            textarea.value = this.textContent.replace(/["']/g, "").trim();
            adjustTextareaHeight();
            form.dispatchEvent(new Event("submit", { cancelable: true }));
        });
    });

    // Escape HTML to prevent XSS
    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    // Format text replacing newlines with <br>
    function formatMessageText(text) {
        return escapeHtml(text).replace(/\n/g, "<br>");
    }

    // Append a message bubble to the list
    function appendMessage(role, content, sources = [], isPending = false) {
        if (welcomeCard) {
            welcomeCard.style.display = "none";
        }

        const row = document.createElement("div");
        row.className = `message-row message-${role}`;

        const avatarDiv = document.createElement("div");
        avatarDiv.className = "message-avatar";

        const senderName = role === "user" ? "You" : "RAG Assistant (Mistral)";
        const avatarIcon = role === "user" 
            ? `<div class="avatar-icon user-icon">U</div>`
            : `<div class="avatar-icon ai-icon">🦙</div>`;

        avatarDiv.innerHTML = avatarIcon;

        const contentWrapper = document.createElement("div");
        contentWrapper.className = "message-content-wrapper";

        let bubbleContent = "";
        if (isPending) {
            bubbleContent = `
                <div class="message-text">
                    <span class="text-muted">Searching ChromaDB & querying Mistral...</span>
                    <div class="typing-indicator ml-2">
                        <span class="typing-dot"></span>
                        <span class="typing-dot"></span>
                        <span class="typing-dot"></span>
                    </div>
                </div>
            `;
        } else {
            bubbleContent = `<div class="message-text">${formatMessageText(content)}</div>`;

            // Append sources if available
            if (role === "assistant" && sources && sources.length > 0) {
                let sourcesHtml = `
                    <div class="sources-container">
                        <details class="sources-details" open>
                            <summary class="sources-summary">
                                <span>📚 Verified Sources (${sources.length})</span>
                            </summary>
                            <div class="sources-list">
                `;

                sources.forEach(src => {
                    const pageTag = src.page ? `<span class="source-tag">Page ${escapeHtml(String(src.page))}</span>` : "";
                    const scoreTag = src.score !== undefined ? `<span class="source-tag score-tag">Similarity: ${src.score}</span>` : "";
                    const snippetHtml = src.snippet ? `<p class="source-snippet">"${escapeHtml(src.snippet)}"</p>` : "";

                    sourcesHtml += `
                        <div class="source-card">
                            <div class="source-card-header">
                                <strong class="source-doc-name">${escapeHtml(src.document_name || "Document")}</strong>
                                <div class="source-tags">${pageTag} ${scoreTag}</div>
                            </div>
                            ${snippetHtml}
                        </div>
                    `;
                });

                sourcesHtml += `
                            </div>
                        </details>
                    </div>
                `;
                bubbleContent += sourcesHtml;
            }
        }

        const now = new Date();
        const timeStr = now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0');

        contentWrapper.innerHTML = `
            <div class="message-sender">${senderName}</div>
            <div class="message-bubble">${bubbleContent}</div>
            <div class="message-timestamp">${timeStr}</div>
        `;

        row.appendChild(avatarDiv);
        row.appendChild(contentWrapper);
        messagesList.appendChild(row);

        scrollToBottom();
        return row;
    }

    // Form submission handler
    form.addEventListener("submit", async function (e) {
        e.preventDefault();

        const question = textarea.value.trim();
        if (!question) return;

        // 1. Immediately render user question
        appendMessage("user", question);

        // 2. Clear and reset textarea
        textarea.value = "";
        adjustTextareaHeight();

        // 3. Disable send controls
        textarea.disabled = true;
        sendButton.disabled = true;

        // 4. Render pending indicator
        const pendingRow = appendMessage("assistant", "", [], true);

        try {
            const response = await fetch(`/chat/${sessionId}/message/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken()
                },
                body: JSON.stringify({ question: question })
            });

            const data = await response.json();

            // Remove pending row
            pendingRow.remove();

            if (response.ok && data.success) {
                // Render assistant response
                appendMessage("assistant", data.answer, data.sources || []);

                // Update session title if first message
                if (chatTitleHeader && (chatTitleHeader.textContent === "New Conversation" || chatTitleHeader.textContent.trim() === "")) {
                    const newTitle = question.length > 45 ? question.substring(0, 45) + "..." : question;
                    chatTitleHeader.textContent = newTitle;

                    const activeConvTitle = document.querySelector(".conversation-item.active .conv-title");
                    if (activeConvTitle) {
                        activeConvTitle.textContent = newTitle;
                    }
                }
            } else {
                const errorMsg = data.error || "An error occurred while generating the answer.";
                const errorRow = appendMessage("assistant", `⚠️ Error: ${errorMsg}`);
                const bubble = errorRow.querySelector(".message-bubble");
                if (bubble) {
                    bubble.style.borderColor = "var(--danger-hover)";
                }
            }
        } catch (err) {
            console.error("Chat API error:", err);
            pendingRow.remove();
            appendMessage("assistant", "⚠️ Network Error: Unable to reach the local server. Please ensure the Django server and Ollama are running.");
        } finally {
            // Re-enable inputs
            textarea.disabled = false;
            sendButton.disabled = false;
            textarea.focus();
            scrollToBottom();
        }
    });
});
