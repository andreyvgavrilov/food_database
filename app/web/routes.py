from __future__ import annotations

import sqlite3
import threading
from typing import Any, Iterator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from html import escape
from fastapi.responses import HTMLResponse

from app.agent.engine import NutritionAgent
from app.agent.ollama import IngredientNormalizer
from app.chat.history import (
    add_chat_message,
    create_chat_thread,
    get_chat_thread,
    list_chat_messages,
    list_chat_threads,
)
from app.config import Settings
from app.db import (
    connect,
    has_successful_import,
    initialize_database,
    latest_import_status,
    record_import_started,
    update_import_status,
)
from app.nutrition.calculator import NutritionCalculator
from app.schemas import ChatRequest, ChatResponse, IngredientLookupRequest, NutritionCalculationRequest
from app.usda.downloader import download_usda_json_dump
from app.usda.importer import SOURCE_NAME, import_usda_dump
from app.usda.lookup import IngredientLookup


import_lock = threading.Lock()
CHAT_UNAVAILABLE_DETAIL = "Nutrition data has not been imported yet. Open Settings and update the nutrition database."


def create_router(settings: Settings, connection: sqlite3.Connection) -> APIRouter:
    router = APIRouter()

    def get_connection() -> Iterator[sqlite3.Connection]:
        request_connection = connect(settings.database_path)
        try:
            yield request_connection
        finally:
            request_connection.close()

    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        status_connection = connect(settings.database_path)
        try:
            chat_available = has_successful_import(status_connection)
            status = latest_import_status(status_connection)
        finally:
            status_connection.close()

        disabled_attr = "" if chat_available else " disabled"
        setup_warning = ""
        if not chat_available:
            status_text = status["status"] if status else "not imported"
            setup_warning = f"""
              <p class="setup-warning">
                Nutrition database setup is required before chat can answer questions.
                Current status: <strong>{escape(str(status_text))}</strong>.
                <a href="/settings">Open Settings</a> and update the nutrition database.
              </p>
            """

        return """
        <!doctype html>
        <html>
          <head>
            <title>AI Nutrition Agent</title>
            <style>
              :root {
                color-scheme: light;
                --border: #d8dee9;
                --muted: #5f6b7a;
                --panel: #f7f9fc;
                --primary: #1769aa;
                --primary-dark: #0f4f82;
                --assistant: #ffffff;
                --user: #e9f4ff;
              }

              * { box-sizing: border-box; }

              body {
                font-family: Arial, sans-serif;
                margin: 0;
                color: #18202a;
                background: #f2f5f8;
              }

              .page {
                width: min(960px, calc(100vw - 2rem));
                min-height: 100vh;
                margin: 0 auto;
                padding: 1.5rem 0;
                display: flex;
                flex-direction: column;
                gap: 1rem;
              }

              nav a { margin-right: 1rem; color: var(--primary-dark); }
              h1 { margin: 0; font-size: 1.7rem; }

              .setup-warning {
                margin: 0;
                padding: 0.8rem 1rem;
                border: 1px solid #d6b656;
                background: #fff7df;
                color: #533f04;
              }

              .chat {
                display: grid;
                grid-template-columns: 220px minmax(0, 1fr);
                min-height: calc(100vh - 7rem);
                border: 1px solid var(--border);
                background: #ffffff;
              }

              .chat-sidebar {
                border-right: 1px solid var(--border);
                background: var(--panel);
                padding: 0.75rem;
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                min-width: 0;
              }

              .chat-panel {
                min-width: 0;
                display: flex;
                flex-direction: column;
              }

              .chat-list {
                display: flex;
                flex-direction: column;
                gap: 0.4rem;
                overflow-y: auto;
              }

              .chat-item {
                width: 100%;
                border: 1px solid transparent;
                background: transparent;
                color: #18202a;
                padding: 0.55rem 0.6rem;
                text-align: left;
                cursor: pointer;
              }

              .chat-item.active,
              .chat-item:hover {
                border-color: var(--border);
                background: #ffffff;
              }

              .chat-title {
                display: block;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
              }

              .chat-count {
                display: block;
                color: var(--muted);
                font-size: 0.8rem;
                margin-top: 0.2rem;
              }

              .history {
                flex: 1;
                min-height: 20rem;
                overflow-y: auto;
                padding: 1rem;
                display: flex;
                flex-direction: column;
                gap: 0.85rem;
              }

              .empty {
                color: var(--muted);
                margin: auto;
                text-align: center;
              }

              .message {
                width: min(82%, 720px);
                border: 1px solid var(--border);
                padding: 0.85rem 1rem;
                line-height: 1.45;
              }

              .message.user {
                align-self: flex-end;
                background: var(--user);
              }

              .message.assistant {
                align-self: flex-start;
                background: var(--assistant);
              }

              .message.loading {
                width: auto;
                color: var(--muted);
              }

              .message p { margin: 0 0 0.7rem; }
              .message p:last-child,
              .message ul:last-child,
              .message ol:last-child,
              .message pre:last-child { margin-bottom: 0; }
              .message h1, .message h2, .message h3 {
                margin: 0.2rem 0 0.55rem;
                font-size: 1rem;
              }
              .message ul, .message ol { margin: 0 0 0.7rem 1.25rem; padding: 0; }
              .message code {
                background: #eef2f7;
                padding: 0.05rem 0.25rem;
                border-radius: 4px;
              }
              .message pre {
                background: #101828;
                color: #f8fafc;
                padding: 0.85rem;
                overflow: auto;
              }
              .message pre code { background: transparent; padding: 0; }
              .message a { color: var(--primary-dark); }
              .table-wrap {
                width: 100%;
                margin: 0 0 0.85rem;
                overflow-x: auto;
                border: 1px solid var(--border);
              }
              table {
                width: 100%;
                border-collapse: collapse;
                min-width: 620px;
                font-size: 0.95rem;
              }
              th, td {
                padding: 0.55rem 0.65rem;
                border-bottom: 1px solid var(--border);
                text-align: left;
                vertical-align: top;
              }
              th {
                background: #eef2f7;
                font-weight: 700;
              }
              tr:last-child td { border-bottom: 0; }
              .math {
                white-space: nowrap;
                font-variant-numeric: tabular-nums;
              }

              .tool-activity {
                margin-top: 0.8rem;
                padding-top: 0.8rem;
                border-top: 1px solid var(--border);
                color: #2f3b48;
              }

              .tool-activity-title {
                margin-bottom: 0.45rem;
                font-weight: 700;
                font-size: 0.9rem;
              }

              details.raw {
                margin-top: 0.8rem;
                color: var(--muted);
              }

              details.raw pre {
                margin-top: 0.5rem;
                white-space: pre-wrap;
              }

              .composer {
                border-top: 1px solid var(--border);
                padding: 0.85rem;
                background: var(--panel);
              }

              .composer form {
                display: flex;
                gap: 0.75rem;
                align-items: flex-end;
              }

              textarea {
                flex: 1;
                width: 100%;
                min-height: 5rem;
                max-height: 12rem;
                resize: vertical;
                border: 1px solid var(--border);
                padding: 0.75rem;
                font: inherit;
                background: #ffffff;
              }

              textarea:disabled {
                color: #6b7280;
                background: #eef2f7;
              }

              button {
                min-width: 6rem;
                padding: 0.72rem 0.9rem;
                border: 0;
                color: #ffffff;
                background: var(--primary);
                font-weight: 700;
                cursor: pointer;
              }

              button:disabled {
                background: #8aa8c3;
                cursor: wait;
              }

              .loader {
                display: inline-flex;
                align-items: center;
                gap: 0.55rem;
              }

              .spinner {
                width: 1rem;
                height: 1rem;
                border: 2px solid #c8d3df;
                border-top-color: var(--primary);
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
              }

              @keyframes spin {
                to { transform: rotate(360deg); }
              }

              @media (max-width: 680px) {
                .chat { grid-template-columns: 1fr; }
                .chat-sidebar { border-right: 0; border-bottom: 1px solid var(--border); }
                .chat-list { max-height: 9rem; }
                .message { width: 100%; }
                .composer form { flex-direction: column; align-items: stretch; }
                button { width: 100%; }
              }
            </style>
          </head>
          <body>
            <div class="page">
              <nav><a href="/">Chat</a><a href="/settings">Settings</a></nav>
              <h1>AI Nutrition Agent</h1>
              __SETUP_WARNING__
              <section class="chat" aria-label="Chat">
                <aside class="chat-sidebar" aria-label="Saved chats">
                  <button id="newChatButton" type="button">New chat</button>
                  <div id="chatList" class="chat-list"></div>
                </aside>
                <div class="chat-panel">
                  <div id="history" class="history">
                    <p id="emptyState" class="empty">Paste a recipe or ask about ingredients.</p>
                  </div>
                  <div class="composer">
                    <form id="chatForm">
                      <textarea id="message" placeholder="Paste a recipe or ask about ingredients"__DISABLED_ATTR__></textarea>
                      <button id="sendButton" type="submit"__DISABLED_ATTR__>Send</button>
                    </form>
                  </div>
                </div>
              </section>
            </div>
            <script src="https://cdn.jsdelivr.net/npm/marked/lib/marked.umd.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
            <script>
              window.MathJax = {
                tex: {
                  inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                  processEscapes: true
                },
                options: {
                  skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
                }
              };
            </script>
            <script src="https://cdn.jsdelivr.net/npm/mathjax@4/tex-mml-chtml.js"></script>
            <script>
              const form = document.getElementById('chatForm');
              const textarea = document.getElementById('message');
              const button = document.getElementById('sendButton');
              const history = document.getElementById('history');
              const chatList = document.getElementById('chatList');
              const newChatButton = document.getElementById('newChatButton');
              const chatAvailable = __CHAT_AVAILABLE__;
              let emptyState = document.getElementById('emptyState');
              let loadingNode = null;
              let currentChatId = null;
              let knownChats = [];

              form.addEventListener('submit', (event) => {
                event.preventDefault();
                sendChat();
              });

              textarea.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault();
                  sendChat();
                }
              });

              newChatButton.addEventListener('click', () => {
                currentChatId = null;
                clearHistory();
                renderChatList(knownChats);
                if (chatAvailable) {
                  textarea.focus();
                }
              });

              loadChats({selectFirst: true});

              async function sendChat() {
                const message = textarea.value.trim();
                if (!chatAvailable || !message || textarea.disabled) {
                  return;
                }

                appendMessage('user', escapeHtml(message));
                textarea.value = '';
                setLoading(true);

                try {
                  const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({chat_id: currentChatId, message})
                  });
                  const payload = await res.json();
                  if (!res.ok) {
                    throw new Error(payload.detail || 'Request failed');
                  }
                  currentChatId = payload.chat_id;
                  appendAssistantMessage(payload);
                  await loadChats();
                } catch (error) {
                  appendMessage('assistant', escapeHtml(error.message || 'Something went wrong.'));
                } finally {
                  setLoading(false);
                }
              }

              function setLoading(isLoading) {
                textarea.disabled = !chatAvailable || isLoading;
                button.disabled = !chatAvailable || isLoading;
                button.textContent = isLoading ? 'Sending' : 'Send';

                if (isLoading) {
                  loadingNode = appendMessage(
                    'assistant loading',
                    '<span class="loader"><span class="spinner" aria-hidden="true"></span><span>Thinking...</span></span>'
                  );
                  return;
                }

                if (loadingNode) {
                  loadingNode.remove();
                  loadingNode = null;
                }
                if (chatAvailable) {
                  textarea.focus();
                }
              }

              async function loadChats(options) {
                const res = await fetch('/api/chats');
                if (!res.ok) {
                  return;
                }
                const payload = await res.json();
                knownChats = payload.chats || [];
                renderChatList(knownChats);
                if (options && options.selectFirst && !currentChatId && knownChats.length) {
                  await loadChat(knownChats[0].id);
                }
              }

              async function loadChat(chatId) {
                const res = await fetch('/api/chats/' + encodeURIComponent(chatId) + '/messages');
                if (!res.ok) {
                  return;
                }
                const payload = await res.json();
                currentChatId = chatId;
                clearHistory();
                for (const message of payload.messages || []) {
                  if (message.role === 'assistant') {
                    appendAssistantMessage({response: message.content, raw: message.raw});
                  } else {
                    appendMessage('user', escapeHtml(message.content || ''));
                  }
                }
                renderChatList(knownChats);
              }

              function renderChatList(chats) {
                chatList.innerHTML = '';
                if (!chats.length) {
                  const empty = document.createElement('p');
                  empty.className = 'empty';
                  empty.textContent = 'No saved chats yet.';
                  chatList.appendChild(empty);
                  return;
                }
                for (const chat of chats) {
                  const item = document.createElement('button');
                  item.type = 'button';
                  item.className = 'chat-item' + (chat.id === currentChatId ? ' active' : '');
                  item.innerHTML = '<span class="chat-title"></span><span class="chat-count"></span>';
                  item.querySelector('.chat-title').textContent = chat.title || 'New chat';
                  item.querySelector('.chat-count').textContent = (chat.message_count || 0) + ' messages';
                  item.addEventListener('click', () => loadChat(chat.id));
                  chatList.appendChild(item);
                }
              }

              function clearHistory() {
                history.innerHTML = '<p id="emptyState" class="empty">Paste a recipe or ask about ingredients.</p>';
                emptyState = document.getElementById('emptyState');
              }

              function appendAssistantMessage(payload) {
                const article = appendMessage('assistant', renderMarkdown(payload.response || ''));
                wrapRenderedTables(article);
                renderMathIn(article);
                if (payload.raw) {
                  const details = document.createElement('details');
                  details.className = 'raw';
                  details.innerHTML = '<summary>Raw response</summary><pre><code></code></pre>';
                  details.querySelector('code').textContent = JSON.stringify(payload.raw, null, 2);
                  article.appendChild(details);
                }
              }

              function appendMessage(role, html) {
                if (emptyState) {
                  emptyState.remove();
                }
                const article = document.createElement('article');
                article.className = 'message ' + role;
                article.innerHTML = html;
                history.appendChild(article);
                history.scrollTop = history.scrollHeight;
                return article;
              }

              function renderMarkdown(markdown) {
                const source = String(markdown || '');
                if (!window.marked || !window.DOMPurify) {
                  return '<p>' + escapeHtml(source).replace(/\\n/g, '<br>') + '</p>';
                }
                const dirty = marked.parse(source, {gfm: true, breaks: true});
                return DOMPurify.sanitize(dirty);
              }

              function wrapRenderedTables(root) {
                root.querySelectorAll('table').forEach((table) => {
                  if (table.parentElement && table.parentElement.classList.contains('table-wrap')) {
                    return;
                  }
                  const wrapper = document.createElement('div');
                  wrapper.className = 'table-wrap';
                  table.parentNode.insertBefore(wrapper, table);
                  wrapper.appendChild(table);
                });
              }

              function renderMathIn(root) {
                if (window.MathJax && MathJax.typesetPromise) {
                  MathJax.typesetPromise([root]).catch(() => {});
                }
              }

              function escapeHtml(value) {
                return String(value)
                  .replace(/&/g, '&amp;')
                  .replace(/</g, '&lt;')
                  .replace(/>/g, '&gt;')
                  .replace(/"/g, '&quot;')
                  .replace(/'/g, '&#039;');
              }
            </script>
          </body>
        </html>
        """.replace("__SETUP_WARNING__", setup_warning).replace("__DISABLED_ATTR__", disabled_attr).replace(
            "__CHAT_AVAILABLE__",
            str(chat_available).lower(),
        )

    @router.get("/settings", response_class=HTMLResponse)
    def settings_page() -> str:
        status_connection = connect(settings.database_path)
        try:
            status = latest_import_status(status_connection)
        finally:
            status_connection.close()
        status_text = status["status"] if status else "no import yet"
        error_text = status.get("error_message") if status else None
        return f"""
        <!doctype html>
        <html>
          <head>
            <title>Nutrition Agent Settings</title>
            <style>
              body {{ font-family: Arial, sans-serif; margin: 2rem; max-width: 960px; }}
              button {{ padding: 0.5rem 0.8rem; }}
              pre {{ background: #f4f4f4; padding: 1rem; overflow: auto; }}
              nav a {{ margin-right: 1rem; }}
            </style>
          </head>
          <body>
            <nav><a href="/">Chat</a><a href="/settings">Settings</a></nav>
            <h1>Settings</h1>
            <p>USDA import status: <strong id="statusText">{escape(str(status_text))}</strong></p>
            <p id="errorText">{escape(str(error_text)) if error_text else ""}</p>
            <p>Ollama endpoint: <code>{escape(settings.ollama_base_url)}</code></p>
            <p>Ollama model: <code>{escape(settings.ollama_model)}</code></p>
            <button onclick="updateDb()">Update nutrition database</button>
            <pre id="status"></pre>
            <script>
              let pollTimer = null;

              function renderStatus(payload) {{
                const status = payload.status || null;
                document.getElementById('status').textContent = JSON.stringify(payload, null, 2);
                document.getElementById('statusText').textContent = status ? status.status : 'no import yet';
                document.getElementById('errorText').textContent = status && status.error_message ? status.error_message : '';
                if (status && (status.status === 'running' || status.status === 'downloading')) {{
                  if (!pollTimer) {{
                    pollTimer = setInterval(fetchStatus, 3000);
                  }}
                }} else if (pollTimer) {{
                  clearInterval(pollTimer);
                  pollTimer = null;
                }}
              }}

              async function fetchStatus() {{
                const res = await fetch('/api/usda/import/status');
                renderStatus(await res.json());
              }}

              async function updateDb() {{
                const res = await fetch('/api/usda/import', {{ method: 'POST' }});
                renderStatus(await res.json());
              }}

              fetchStatus();
            </script>
          </body>
        </html>
        """

    @router.get("/api/chats")
    def chats(db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        return {"chats": list_chat_threads(db)}

    @router.post("/api/chats")
    def create_chat(db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        chat_id = create_chat_thread(db)
        return {"chat": get_chat_thread(db, chat_id)}

    @router.get("/api/chats/{chat_id}/messages")
    def chat_messages(chat_id: int, db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        if not get_chat_thread(db, chat_id):
            raise HTTPException(status_code=404, detail="Chat not found")
        return {"messages": list_chat_messages(db, chat_id)}

    @router.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest, db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        if not has_successful_import(db):
            raise HTTPException(status_code=503, detail=CHAT_UNAVAILABLE_DETAIL)

        if request.chat_id is None:
            chat_id = create_chat_thread(db, title=_chat_title(request.message))
            previous_messages: list[dict[str, Any]] = []
        else:
            chat_id = request.chat_id
            if not get_chat_thread(db, chat_id):
                raise HTTPException(status_code=404, detail="Chat not found")
            previous_messages = list_chat_messages(db, chat_id)

        history = _agent_history(previous_messages)
        add_chat_message(db, chat_id, "user", request.message)
        result = NutritionAgent(settings, db).invoke(request.message, history=history)
        add_chat_message(
            db,
            chat_id,
            "assistant",
            str(result.get("response") or ""),
            tool_activity=result.get("tool_activity") if isinstance(result.get("tool_activity"), list) else [],
            raw=result.get("raw"),
        )
        return {"chat_id": chat_id, **result}

    @router.post("/api/nutrition/lookup")
    def lookup(request: IngredientLookupRequest, db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        return IngredientLookup(db).get_ingredient_nutrition(
            request.ingredient_name,
            request.preferred_food_category,
            request.max_results,
        )

    @router.post("/api/nutrition/calculate")
    def calculate(request: NutritionCalculationRequest, db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        ingredients = [ingredient.model_dump() for ingredient in request.ingredients]
        normalization_warning = None
        try:
            ingredients = IngredientNormalizer(settings).normalize(ingredients)
        except Exception as exc:
            normalization_warning = f"Ingredient normalization unavailable, using submitted names: {exc}"

        result = NutritionCalculator(db).calculate_total_nutrition(ingredients, request.servings)
        if normalization_warning:
            result["warnings"].insert(0, normalization_warning)
        return result

    @router.get("/api/usda/import/status")
    def import_status(db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        return {"status": latest_import_status(db)}

    @router.post("/api/usda/import")
    def start_import(background_tasks: BackgroundTasks) -> dict[str, Any]:
        if not import_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="USDA import is already running")

        starter_connection = connect(settings.database_path)
        try:
            import_id = record_import_started(
                starter_connection,
                SOURCE_NAME,
                settings.usda_download_page_url,
                f"downloading: {', '.join(settings.usda_download_data_types)}",
                "downloading",
            )
            response_status = latest_import_status(starter_connection)
        finally:
            starter_connection.close()

        def run_import() -> None:
            task_connection = connect(settings.database_path)
            try:
                initialize_database(task_connection)
                download = download_usda_json_dump(
                    settings.usda_download_page_url,
                    settings.usda_download_data_types,
                    settings.usda_json_dump_path,
                )
                import_usda_dump(task_connection, download.extracted_path, import_id=import_id)
            except Exception as exc:
                update_import_status(
                    task_connection,
                    import_id,
                    "failed",
                    error_message=str(exc),
                    completed=True,
                )
            finally:
                task_connection.close()
                import_lock.release()

        background_tasks.add_task(run_import)
        return {"status": response_status}

    return router


def _chat_title(message: str) -> str:
    title = " ".join(message.strip().split())
    if len(title) <= 48:
        return title or "New chat"
    return title[:45].rstrip() + "..."


def _agent_history(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            history.append({"role": role, "content": content})
    return history
