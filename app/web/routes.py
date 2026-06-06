from __future__ import annotations

import sqlite3
import threading
from typing import Any, Iterator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from html import escape
from fastapi.responses import HTMLResponse

from app.agent.engine import NutritionAgent
from app.agent.ollama import IngredientNormalizer
from app.config import Settings
from app.db import connect, initialize_database, latest_import_status, record_import_started, update_import_status
from app.nutrition.calculator import NutritionCalculator
from app.schemas import ChatRequest, ChatResponse, IngredientLookupRequest, NutritionCalculationRequest
from app.usda.downloader import download_usda_json_dump
from app.usda.importer import SOURCE_NAME, import_usda_dump
from app.usda.lookup import IngredientLookup


import_lock = threading.Lock()


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

              .chat {
                display: flex;
                flex-direction: column;
                min-height: calc(100vh - 7rem);
                border: 1px solid var(--border);
                background: #ffffff;
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
              <section class="chat" aria-label="Chat">
                <div id="history" class="history">
                  <p id="emptyState" class="empty">Paste a recipe or ask about ingredients.</p>
                </div>
                <div class="composer">
                  <form id="chatForm">
                    <textarea id="message" placeholder="Paste a recipe or ask about ingredients"></textarea>
                    <button id="sendButton" type="submit">Send</button>
                  </form>
                </div>
              </section>
            </div>
            <script>
              const form = document.getElementById('chatForm');
              const textarea = document.getElementById('message');
              const button = document.getElementById('sendButton');
              const history = document.getElementById('history');
              const emptyState = document.getElementById('emptyState');
              let loadingNode = null;

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

              async function sendChat() {
                const message = textarea.value.trim();
                if (!message || textarea.disabled) {
                  return;
                }

                appendMessage('user', escapeHtml(message));
                textarea.value = '';
                setLoading(true);

                try {
                  const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message})
                  });
                  const payload = await res.json();
                  if (!res.ok) {
                    throw new Error(payload.detail || 'Request failed');
                  }
                  appendAssistantMessage(payload);
                } catch (error) {
                  appendMessage('assistant', escapeHtml(error.message || 'Something went wrong.'));
                } finally {
                  setLoading(false);
                }
              }

              function setLoading(isLoading) {
                textarea.disabled = isLoading;
                button.disabled = isLoading;
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
                textarea.focus();
              }

              function appendAssistantMessage(payload) {
                const article = appendMessage('assistant', renderMarkdown(payload.response || ''));
                if (Array.isArray(payload.tool_activity) && payload.tool_activity.length) {
                  const activity = document.createElement('div');
                  activity.className = 'tool-activity';
                  activity.innerHTML = '<div class="tool-activity-title">Tool activity</div>' +
                    '<ul>' + payload.tool_activity.map((item) => '<li>' + renderInlineMarkdown(item) + '</li>').join('') + '</ul>';
                  article.appendChild(activity);
                }

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
                const lines = String(markdown || '').replace(/\\r\\n/g, '\\n').split('\\n');
                const html = [];
                let paragraph = [];
                let listType = null;
                let inCode = false;
                let codeLines = [];

                function flushParagraph() {
                  if (paragraph.length) {
                    html.push('<p>' + renderInlineMarkdown(paragraph.join(' ')) + '</p>');
                    paragraph = [];
                  }
                }

                function closeList() {
                  if (listType) {
                    html.push('</' + listType + '>');
                    listType = null;
                  }
                }

                for (let index = 0; index < lines.length; index += 1) {
                  const line = lines[index];
                  const trimmed = line.trim();

                  if (trimmed.startsWith('```')) {
                    if (inCode) {
                      html.push('<pre><code>' + escapeHtml(codeLines.join('\\n')) + '</code></pre>');
                      codeLines = [];
                      inCode = false;
                    } else {
                      flushParagraph();
                      closeList();
                      inCode = true;
                    }
                    continue;
                  }

                  if (inCode) {
                    codeLines.push(line);
                    continue;
                  }

                  if (!trimmed) {
                    flushParagraph();
                    closeList();
                    continue;
                  }

                  if (isTableHeader(lines, index)) {
                    flushParagraph();
                    closeList();
                    const table = collectTable(lines, index);
                    html.push(renderTable(table.lines));
                    index = table.endIndex;
                    continue;
                  }

                  const heading = trimmed.match(/^(#{1,3})\\s+(.+)$/);
                  if (heading) {
                    flushParagraph();
                    closeList();
                    const level = heading[1].length;
                    html.push('<h' + level + '>' + renderInlineMarkdown(heading[2]) + '</h' + level + '>');
                    continue;
                  }

                  const unordered = trimmed.match(/^[-*]\\s+(.+)$/);
                  const ordered = trimmed.match(/^\\d+\\.\\s+(.+)$/);
                  if (unordered || ordered) {
                    flushParagraph();
                    const nextListType = unordered ? 'ul' : 'ol';
                    if (listType !== nextListType) {
                      closeList();
                      html.push('<' + nextListType + '>');
                      listType = nextListType;
                    }
                    html.push('<li>' + renderInlineMarkdown((unordered || ordered)[1]) + '</li>');
                    continue;
                  }

                  paragraph.push(trimmed);
                }

                if (inCode) {
                  html.push('<pre><code>' + escapeHtml(codeLines.join('\\n')) + '</code></pre>');
                }
                flushParagraph();
                closeList();
                return html.join('');
              }

              function renderInlineMarkdown(text) {
                let html = escapeHtml(text);
                html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
                html = html.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\s)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
                html = html.replace(/\\$([^$]+)\\$/g, (_match, expression) => '<span class="math">' + formatInlineMath(expression) + '</span>');
                html = html.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
                html = html.replace(/\\*([^*]+)\\*/g, '<em>$1</em>');
                return html;
              }

              function isTableHeader(lines, index) {
                const current = lines[index] ? lines[index].trim() : '';
                const next = lines[index + 1] ? lines[index + 1].trim() : '';
                return isTableRow(current) && isTableSeparator(next);
              }

              function collectTable(lines, startIndex) {
                const tableLines = [lines[startIndex].trim(), lines[startIndex + 1].trim()];
                let endIndex = startIndex + 1;
                for (let index = startIndex + 2; index < lines.length; index += 1) {
                  const trimmed = lines[index].trim();
                  if (!isTableRow(trimmed) || isTableSeparator(trimmed)) {
                    break;
                  }
                  tableLines.push(trimmed);
                  endIndex = index;
                }
                return { lines: tableLines, endIndex };
              }

              function renderTable(tableLines) {
                const headers = parseTableRow(tableLines[0]);
                const alignments = parseTableRow(tableLines[1]).map((cell) => {
                  const trimmed = cell.trim();
                  if (trimmed.startsWith(':') && trimmed.endsWith(':')) {
                    return 'center';
                  }
                  if (trimmed.endsWith(':')) {
                    return 'right';
                  }
                  return 'left';
                });
                const rows = tableLines.slice(2).map(parseTableRow);
                const headerHtml = headers.map((header, index) => (
                  '<th style="text-align: ' + (alignments[index] || 'left') + '">' + renderInlineMarkdown(header) + '</th>'
                )).join('');
                const rowHtml = rows.map((row) => (
                  '<tr>' + row.map((cell, index) => (
                    '<td style="text-align: ' + (alignments[index] || 'left') + '">' + renderInlineMarkdown(cell) + '</td>'
                  )).join('') + '</tr>'
                )).join('');
                return '<div class="table-wrap"><table><thead><tr>' + headerHtml + '</tr></thead><tbody>' + rowHtml + '</tbody></table></div>';
              }

              function parseTableRow(line) {
                return line
                  .replace(/^\\|/, '')
                  .replace(/\\|$/, '')
                  .split('|')
                  .map((cell) => cell.trim());
              }

              function isTableRow(line) {
                return /^\\|.*\\|$/.test(line) && line.split('|').length > 2;
              }

              function isTableSeparator(line) {
                return /^\\|?\\s*:?-{3,}:?\\s*(\\|\\s*:?-{3,}:?\\s*)+\\|?$/.test(line);
              }

              function formatInlineMath(expression) {
                return expression
                  .replace(/\\\\approx/g, '&asymp;')
                  .replace(/\\\\times/g, '&times;')
                  .replace(/\\\\pm/g, '&plusmn;')
                  .replace(/\\\\cdot/g, '&middot;')
                  .replace(/[{}]/g, '')
                  .replace(/\\\\/g, '')
                  .trim();
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
        """

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

    @router.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest, db: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
        return NutritionAgent(settings, db).invoke(request.message)

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
