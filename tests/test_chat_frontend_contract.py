from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src/static/index.html").read_text(encoding="utf-8")
CHAT_JS = (ROOT / "src/static/js/chat.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/static/css/main.css").read_text(encoding="utf-8")
API_JS = (ROOT / "src/static/js/api.js").read_text(encoding="utf-8")


def test_chat_events_are_bound_once():
    assert "_bound: false" in CHAT_JS
    assert "if (!this._bound)" in CHAT_JS
    assert "this._bound = true;" in CHAT_JS


def test_chat_uses_open_source_markdown_renderer_with_sanitizer():
    assert "/vendor/purify.min.js" in HTML
    assert "/vendor/marked.min.js" in HTML
    assert "/vendor/mermaid.min.js" in HTML
    assert "window.marked.parse(text)" in CHAT_JS
    assert "window.DOMPurify.sanitize" in CHAT_JS


def test_chat_markdown_renders_mermaid_fences_as_chart_containers():
    assert "_renderMarkdownWithLibraries" in CHAT_JS
    assert "const renderer = new window.marked.Renderer();" in CHAT_JS
    assert "if (lang === 'mermaid')" in CHAT_JS
    assert "mermaid-container" in CHAT_JS
    assert "mermaid-chart" in CHAT_JS
    assert "mermaid-source" in CHAT_JS
    assert ".msg-text .mermaid-container" in CSS
    assert ".msg-text .mermaid-chart svg" in CSS


def test_chat_message_rendering_defers_mermaid_until_stream_end():
    send_message_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
    append_block = CHAT_JS.split("_appendMessage(role, content)", 1)[1].split("_renderMarkdown(text)", 1)[0]
    assert "this._schedulePostStreamMermaid(contentEl);" in send_message_block
    assert "_renderMermaidOnStreamEnd" in CHAT_JS
    assert "async _renderMermaidCharts(scope = document)" in CHAT_JS


def test_chat_markdown_has_readable_styles():
    assert ".msg-text h1" in CSS
    assert ".msg-text ul" in CSS
    assert ".msg-text table" in CSS
    assert ".msg-text blockquote" in CSS


def test_conversation_history_deduplicates_adjacent_same_assistant_message():
    assert "_normalizeHistoryMessages(messages)" in CHAT_JS
    assert "const messages = this._normalizeHistoryMessages(data.messages || []);" in CHAT_JS
    assert "last.role === 'assistant'" in CHAT_JS
    assert "m.role === 'assistant'" in CHAT_JS
    assert "last.content === m.content" in CHAT_JS


def test_conversation_delete_button_is_top_right_hover_action():
    assert "String(c.id) === String(this._currentConvId)" in CHAT_JS
    assert 'class="conv-title"' in CHAT_JS
    assert 'class="conv-del"' in CHAT_JS
    assert ".conv-item {" in CSS
    assert "position: relative;" in CSS
    assert ".conv-del {" in CSS
    assert "position: absolute;" in CSS
    assert "top: 6px;" in CSS
    assert "right: 6px;" in CSS
    assert "opacity: 0;" in CSS
    assert ".conv-item:hover .conv-del" in CSS
    assert ".conv-item.active .conv-del" in CSS
    assert ".conv-del:focus-visible" in CSS


def test_chat_sse_error_is_not_overwritten_by_empty_reply_fallback():
    send_message_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
    assert "let hadError = false;" in send_message_block
    assert "if (data.error) {" in send_message_block
    assert "hadError = true;" in send_message_block
    assert "if (!fullText && !reasoningText && !hadError)" in send_message_block
    assert "contentEl.innerHTML = '<span class=\"msg-error\">未收到回复</span>';" in send_message_block
    assert "if (!fullText && reasoningText)" in send_message_block


def test_chat_sse_parser_buffers_partial_lines():
    """SSE JSON 跨网络 chunk 分片时不能丢弃半行。"""
    send_message_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
    assert "let sseBuffer = '';" in send_message_block
    assert "sseBuffer += decoder.decode(value, { stream: true });" in send_message_block
    assert "const lines = sseBuffer.split('\\n');" in send_message_block
    assert "sseBuffer = lines.pop() || '';" in send_message_block
    assert "for (const rawLine of lines)" in send_message_block


def test_chat_css_class_names_match_rendered_message_dom():
    append_block = CHAT_JS.split("_appendMessage(role, content)", 1)[1].split("_renderMarkdown(text)", 1)[0]
    assert "div.className = `msg msg-${role}`;" in append_block
    assert "<div class=\"msg-avatar\">${avatar}</div>" in append_block
    assert "<div class=\"msg-bubble\">" in append_block
    assert ".msg-user {" in CSS
    assert ".msg-assistant {" in CSS
    assert ".msg-user .msg-avatar" in CSS
    assert ".msg-assistant .msg-avatar" in CSS
    assert ".msg-user .msg-bubble" in CSS
    assert ".msg-assistant .msg-bubble" in CSS


def test_send_message_sets_sending_lock_before_dom_work():
    send_message_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
    lock_idx = send_message_block.index("this._sending = true;")
    update_btn_idx = send_message_block.index("this._updateSendBtn();")
    welcome_idx = send_message_block.index("const welcome = document.querySelector('.welcome');")
    append_user_idx = send_message_block.index("this._appendMessage('user', text);")
    assert lock_idx < update_btn_idx < welcome_idx < append_user_idx


def test_conversation_list_has_alternating_item_background():
    assert ".conv-item:nth-child(odd)" in CSS
    odd_rule = CSS.split(".conv-item:nth-child(odd)", 1)[1].split("}", 1)[0]
    assert "background:" in odd_rule
    assert "var(--gray-1)" in odd_rule


def test_selecting_current_conversation_returns_early_and_blocks_switch_while_streaming():
    select_block = CHAT_JS.split("async selectConversation(convId)", 1)[1].split("newConversation()", 1)[0]
    assert "if (String(this._currentConvId) === String(convId)) return;" in select_block
    assert "if (this._sending) return;" in select_block


def test_new_conversation_clears_unsent_attachments_and_urls():
    new_block = CHAT_JS.split("newConversation()", 1)[1].split("async sendMessage()", 1)[0]
    clear_idx = new_block.index("this._clearAttachments();")
    reset_idx = new_block.index("this._currentConvId = null;")
    assert clear_idx < reset_idx


def test_conversation_list_active_state_compares_ids_as_strings():
    load_block = CHAT_JS.split("async loadConversations()", 1)[1].split("async selectConversation", 1)[0]
    assert "String(c.id) === String(this._currentConvId)" in load_block
    assert "c.id === this._currentConvId" not in load_block


def test_new_conversation_context_is_synced_after_first_sse_conversation_id():
    send_message_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
    assert "const pendingContextItems = this._contextItems" in send_message_block
    assert "if (data.conversation_id && !this._currentConvId) {" in send_message_block
    assert "await this._persistPendingContextItems(data.conversation_id, pendingContextItems);" in send_message_block


def test_pending_context_persistence_only_creates_missing_items():
    assert "async _persistPendingContextItems(conversationId, items)" in CHAT_JS
    persist_block = CHAT_JS.split("async _persistPendingContextItems(conversationId, items)", 1)[1].split("_bindContextEvents()", 1)[0]
    assert "items.filter(item => !item.id || String(item.id).startsWith('ctx_'))" in persist_block
    assert "API.createContextItem(conversationId" in persist_block
    assert "this._contextItems = this._contextItems.map(existing =>" in persist_block


def test_send_message_waits_for_context_sync_before_streaming():
    send_message_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
    wait_idx = send_message_block.index("await this._flushContextSync();")
    stream_idx = send_message_block.index("const reader = await API.chatStream({")
    assert wait_idx < stream_idx


def test_persisted_context_mutations_are_queued_instead_of_fire_and_forget():
    toggle_block = CHAT_JS.split("_toggleContextItem(id)", 1)[1].split("_removeContextItem(id)", 1)[0]
    assert "this._queueContextSync(" in toggle_block
    assert "API.updateContextItem" in toggle_block

    remove_block = CHAT_JS.split("_removeContextItem(id)", 1)[1].split("_clearContext()", 1)[0]
    assert "this._queueContextSync(" in remove_block
    assert "API.deleteContextItem" in remove_block

    clear_block = CHAT_JS.split("_clearContext()", 1)[1].split("async _addContextFile", 1)[0]
    assert "this._queueContextSync(" in clear_block


def test_select_conversation_ignores_stale_async_results():
    assert "_isConversationCurrent(conversationId)" in CHAT_JS
    select_block = CHAT_JS.split("async selectConversation(convId)", 1)[1].split("newConversation()", 1)[0]
    assert "const requestConvId = String(convId);" in select_block
    assert select_block.count("if (!this._isConversationCurrent(requestConvId)) return;") >= 2


def test_context_sync_captures_conversation_id_at_enqueue_time():
    toggle_block = CHAT_JS.split("_toggleContextItem(id)", 1)[1].split("_removeContextItem(id)", 1)[0]
    assert "const conversationId = this._currentConvId;" in toggle_block
    assert "API.updateContextItem(conversationId, id, { enabled })" in toggle_block

    remove_block = CHAT_JS.split("_removeContextItem(id)", 1)[1].split("_clearContext()", 1)[0]
    assert "const conversationId = this._currentConvId;" in remove_block
    assert "API.deleteContextItem(conversationId, id)" in remove_block

    clear_block = CHAT_JS.split("_clearContext()", 1)[1].split("async _addContextFile", 1)[0]
    assert "const conversationId = this._currentConvId;" in clear_block
    assert "API.deleteContextItem(conversationId, id)" in clear_block


def test_async_context_creation_only_updates_matching_conversation_panel():
    add_file_block = CHAT_JS.split("async _addContextFile(files, contextType)", 1)[1].split("_addManualRule()", 1)[0]
    assert "const conversationId = this._currentConvId;" in add_file_block
    assert "if (!this._isConversationCurrent(conversationId)) continue;" in add_file_block

    submit_rule_block = CHAT_JS.split("async _submitManualRule()", 1)[1].split("async _persistPendingContextItems", 1)[0]
    assert "const conversationId = this._currentConvId;" in submit_rule_block
    assert "if (!this._isConversationCurrent(conversationId)) return;" in submit_rule_block


def test_chat_input_supports_at_mention_candidates_for_context_docs():
    assert 'id="mention-suggest" class="mention-suggest"' in HTML
    assert "_getMentionTrigger(text, caretPos)" in CHAT_JS
    assert "_getMentionCandidates()" in CHAT_JS
    assert "_updateMentionSuggestions()" in CHAT_JS
    assert ".mention-suggest" in CSS
    assert ".mention-suggest-item" in CSS


def test_send_message_passes_mention_selected_context_doc_ids():
    send_message_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
    assert "const mentionedContextItems = this._collectMentionedContextItems(rawText);" in send_message_block
    assert "mention_context_item_ids: mentionContextItemIds.length ? mentionContextItemIds : undefined" in send_message_block
    assert "file_ids: [...fileIds, ...contextFileIds].length ? [...fileIds, ...contextFileIds] : undefined" in send_message_block


# ── P2.C.1/P2.C.3/P2.C.4: 知识库引用前端契约测试 ──


def test_knowledge_btn_in_html():
    """P2.C.1: 对话页存在引用资料 toggle 按钮"""
    assert 'id="knowledge-btn"' in HTML
    assert 'data-active="false"' in HTML


def test_knowledge_btn_toggle_logic_in_chat_js():
    """P2.C.1: Chat 对象有 _toggleKnowledge 方法"""
    assert "_toggleKnowledge()" in CHAT_JS
    assert "_knowledgeEnabled" in CHAT_JS
    assert "_knowledgeWorkspaceId" in CHAT_JS
    assert "knowledge-btn" in CHAT_JS


def test_chat_stream_payload_includes_knowledge_fields():
    """P2.C.1: sendMessage 的 chatStream payload 包含 enable_knowledge 和 knowledge_workspace_id"""
    send_block = CHAT_JS.split("async sendMessage()", 1)[1].split("_normalizeHistoryMessages(messages)", 1)[0]
    assert "enable_knowledge: this._knowledgeEnabled" in send_block
    assert "knowledge_workspace_id: this._knowledgeEnabled ? this._knowledgeWorkspaceId" in send_block


def test_retrieve_api_method_in_api_js():
    """P2.C.1: API 有 retrieveKnowledge 方法"""
    assert "retrieveKnowledge(wsId, query" in API_JS


def test_citation_card_class_in_css():
    """P2.C.3: CSS 包含对话引用卡片样式"""
    assert ".chat-citation-card" in CSS
    assert ".chat-citation-header" in CSS
    assert ".chat-citation-item" in CSS
    assert ".chat-citation-source" in CSS
    assert ".chat-citation-link" in CSS


def test_citation_confidence_styles_in_css():
    """P2.C.3: CSS 包含引用置信度样式"""
    assert ".chat-citation-confidence-high" in CSS
    assert ".chat-citation-confidence-medium" in CSS
    assert ".chat-citation-confidence-low" in CSS


def test_knowledge_based_class_in_css():
    """P2.C.4: CSS 包含引用资料/模型推断区分样式"""
    assert ".chat-knowledge-based" in CSS
    assert ".chat-model-inference" in CSS
    assert ".chat-citation-inline" in CSS
    assert ".msg-knowledge-tag" in CSS


def test_knowledge_paragraph_annotation_in_chat_js():
    """P2.C.4: Chat 有 _annotateKnowledgeParagraphs 方法，能匹配 [来源ID:x]"""
    assert "_annotateKnowledgeParagraphs(text)" in CHAT_JS
    assert "[来源ID:" in CHAT_JS
    assert "chat-knowledge-based" in CHAT_JS
    assert "chat-model-inference" in CHAT_JS


def test_citation_card_methods_in_chat_js():
    """P2.C.3: Chat 有 _appendCitationCard 和 _fillCitationTitles 方法"""
    assert "_appendCitationCard(contentEl, citations)" in CHAT_JS
    assert "_fillCitationTitles(cardEl, citations)" in CHAT_JS


def test_knowledge_status_style_in_css():
    """P2.C.1: tool-btn active 状态有统一样式（虚线框→实线框+蓝色）"""
    assert ".tool-btn[data-active=\"true\"]" in CSS
    assert ".tool-btn" in CSS
    assert "dashed" in CSS


# ─── P4.Pre.5: Message anchor ────────────────────────────────


def test_message_model_has_anchor_fields():
    """P4.Pre.5: Message 模型有 anchor_type 和 anchor_id 字段"""
    from app.models.user import Message
    columns = {c.name for c in Message.__table__.columns}
    assert "anchor_type" in columns
    assert "anchor_id" in columns


def test_conversation_repo_append_message_accepts_anchor():
    """P4.Pre.5: ConversationRepository.append_message 接受 anchor_type/anchor_id 参数"""
    import inspect
    from app.repositories.conversation_repository import ConversationRepository
    sig = inspect.signature(ConversationRepository.append_message)
    assert "anchor_type" in sig.parameters
    assert "anchor_id" in sig.parameters


# ─── P4.Pre.2: Conversation mode/project_id ──────────────────


def test_conversation_model_has_mode_and_project_id():
    """P4.Pre.2: Conversation 模型有 mode 和 project_id 字段"""
    from app.models.user import Conversation
    columns = {c.name for c in Conversation.__table__.columns}
    assert "mode" in columns
    assert "project_id" in columns


def test_chat_request_schema_has_mode_and_project_id():
    """P4.Pre.2: ChatRequest schema 有 mode 和 project_id 可选参数"""
    from app.schemas.chat import ChatRequest
    fields = ChatRequest.model_fields
    assert "mode" in fields
    assert "project_id" in fields


def test_conversation_repo_create_accepts_mode_project_id():
    """P4.Pre.2: ConversationRepository.create_conversation 接受 mode/project_id 参数"""
    import inspect
    from app.repositories.conversation_repository import ConversationRepository
    sig = inspect.signature(ConversationRepository.create_conversation)
    assert "mode" in sig.parameters
    assert "project_id" in sig.parameters
