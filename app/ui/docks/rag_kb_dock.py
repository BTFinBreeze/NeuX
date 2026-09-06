"""RAG Knowledge Base Dock - Chat interface with local knowledge base."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QPoint, Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.rag_service import RAGService
from app.ui.dialogs.index_file_picker_dialog import IndexFilePickerDialog
from app.ui.models.chat_history_store import (
    load_conversations,
    save_conversations,
)


class ChatMessage:
    """A chat message (user or assistant)."""

    def __init__(self, role: str, content: str) -> None:
        self.role = role  # "user" or "assistant"
        self.content = content


class MessageBubble(QFrame):
    """Styled chat message bubble with asymmetric rounded corners."""

    def __init__(
        self,
        message: ChatMessage,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.message = message

        self.setObjectName("message_bubble")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if message.role == "user":
            layout.addStretch(1)
            layout.addWidget(self.label)
            self.label.setStyleSheet("""
                QLabel {
                    background-color: #2563EB;
                    color: #FFFFFF;
                    border-radius: 8px;
                    border-top-right-radius: 4px;
                    padding: 8px 12px;
                }
            """)
            self.label.setText(message.content)
        else:
            layout.addWidget(self.label)
            layout.addStretch(1)
            self.label.setStyleSheet("""
                QLabel {
                    background-color: #FFFFFF;
                    color: #111827;
                    border: 1px solid #D9E1EC;
                    border-radius: 8px;
                    border-top-left-radius: 4px;
                    padding: 8px 12px;
                }
            """)
            self._set_html_content(message.content)

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QFrame#message_bubble { background: transparent; }")

    def resizeEvent(self, event) -> None:
        """Dynamically constrain label width so bubbles adapt to text size."""
        super().resizeEvent(event)
        max_w = int(self.width() * 0.82)
        if max_w > 0:
            self.label.setMaximumWidth(max_w)

    def _set_html_content(self, text: str) -> None:
        """Render text as Markdown via QTextDocument."""
        try:
            doc = QTextDocument()
            font = QFont(self.label.font())
            if font.pointSize() <= 0:
                font.setPointSize(11)
            doc.setDefaultFont(font)
            doc.setDefaultStyleSheet("""
                code { background-color: #F3F4F6; padding: 1px 4px; border-radius: 3px; }
                pre { background-color: #F3F4F6; padding: 8px; border-radius: 6px; }
            """)
            doc.setMarkdown(text)
            self.label.setText(doc.toHtml())
            self.label.setTextFormat(Qt.TextFormat.RichText)
        except Exception:
            self.label.setText(text)
            self.label.setTextFormat(Qt.TextFormat.PlainText)

    def set_text(self, text: str) -> None:
        """Update the message text."""
        self.message.content = text
        if self.message.role == "assistant":
            self._set_html_content(text)
        else:
            self.label.setText(text)
        self.updateGeometry()

    def set_plain_text(self, text: str) -> None:
        """Update text without Markdown rendering (for fast streaming)."""
        self.message.content = text
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setText(text)
        self.updateGeometry()

    def render_markdown(self) -> None:
        """Render the current content as Markdown (called once when streaming ends)."""
        if self.message.role == "assistant":
            self._set_html_content(self.message.content)


class _KbSignals(QObject):
    """Signals for thread-safe UI updates."""
    chunk_ready = Signal(str)
    generation_done = Signal()
    generation_error = Signal(str)
    rebuild_done = Signal(dict)


class RagKbDock(QDockWidget):
    """RAG Knowledge Base dock - manages local KB and answers questions via RAG."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("本地知识库问答", parent)
        self.workspace_root: Path | None = None
        self.rag_service: RAGService | None = None
        self.chat_history: list[ChatMessage] = []
        self._conversations: list[dict[str, Any]] = []
        self._current_conv_id: str | None = None
        self._generating = False
        self._loading_model = False
        self._current_bubble: MessageBubble | None = None
        self._current_message: ChatMessage | None = None
        self._stream_signals = _KbSignals()
        self._pending_text = ""
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._flush_stream)

        self.setObjectName("rag_kb_dock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._build_ui()
        self._bind_signals()

    def _build_ui(self) -> None:
        surface = QWidget(self)
        surface.setObjectName("dock_surface")
        root_layout = QVBoxLayout(surface)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        title = QLabel("本地知识库问答", surface)
        title.setObjectName("section_label")
        root_layout.addWidget(title)

        self.tabs = QTabWidget(surface)
        self.tabs.addTab(self._build_chat_tab(), "问答")
        self.tabs.addTab(self._build_management_tab(), "知识库管理")
        self.tabs.addTab(self._build_history_tab(), "历史对话")
        root_layout.addWidget(self.tabs, 1)

        self._update_conversation_title_label()
        self._refresh_history_list()
        self.setWidget(surface)

    def _build_chat_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        chat_header = QHBoxLayout()
        chat_header.setSpacing(6)
        self.conversation_title_label = QLabel("新对话", page)
        self.conversation_title_label.setObjectName("muted_label")
        self.conversation_title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.new_chat_button = QPushButton("新对话", page)
        self.new_chat_button.setToolTip("清空当前问答区，开始一段新的对话")
        chat_header.addWidget(self.conversation_title_label, 1)
        chat_header.addWidget(self.new_chat_button)
        layout.addLayout(chat_header)

        self.chat_area = QScrollArea(page)
        self.chat_area.setWidgetResizable(True)
        self.chat_container = QWidget(self.chat_area)
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(12)
        self.chat_container.setLayout(self.chat_layout)
        self.chat_area.setWidget(self.chat_container)
        layout.addWidget(self.chat_area, 1)

        input_layout = QHBoxLayout()
        self.input_field = QLineEdit(page)
        self.input_field.setPlaceholderText("输入问题，按回车发送...")
        self.send_button = QPushButton("发送", page)
        input_layout.addWidget(self.input_field, 1)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)

        self._add_welcome_message()
        return page

    def _build_management_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.stats_label = QLabel("未加载知识库", page)
        self.stats_label.setObjectName("muted_label")
        layout.addWidget(self.stats_label)

        self.doc_list = QListWidget(page)
        self.doc_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.doc_list, 1)

        button_layout = QHBoxLayout()
        self.build_index_btn = QPushButton("重建索引", page)
        self.clear_index_btn = QPushButton("清空索引", page)
        self.refresh_btn = QPushButton("刷新列表", page)
        button_layout.addWidget(self.build_index_btn)
        button_layout.addWidget(self.clear_index_btn)
        button_layout.addWidget(self.refresh_btn)
        layout.addLayout(button_layout)

        return page

    def _build_history_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        hint = QLabel(
            "当前工作区的全部问答对话。点击对话可在“问答”中继续，\n"
            "右键或点击右侧“⋯”可重命名、置顶或删除。",
            page,
        )
        hint.setObjectName("muted_label")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.history_list = QListWidget(page)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_list.setWordWrap(False)
        self.history_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        layout.addWidget(self.history_list, 1)

        return page

    def _bind_signals(self) -> None:
        self.send_button.clicked.connect(self._send_message)
        self.input_field.returnPressed.connect(self._send_message)
        self.new_chat_button.clicked.connect(self._start_new_chat)
        self.history_list.itemClicked.connect(self._on_history_item_clicked)
        self.history_list.customContextMenuRequested.connect(self._show_history_list_context_menu)
        self.doc_list.customContextMenuRequested.connect(self._show_doc_context_menu)
        self.build_index_btn.clicked.connect(self._rebuild_index)
        self.clear_index_btn.clicked.connect(self._clear_index)
        self.refresh_btn.clicked.connect(self._refresh_doc_list)

        self._stream_signals.chunk_ready.connect(self._on_stream_chunk)
        self._stream_signals.generation_done.connect(self._on_generation_done)
        self._stream_signals.generation_error.connect(self._on_generation_error)
        self._stream_signals.rebuild_done.connect(self._on_rebuild_done)

    def set_workspace(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.rag_service = RAGService(self.workspace_root)
        self._load_conversations_from_store()
        self._start_new_chat(reset_list=True)
        self._refresh_doc_list()

    def focus_input(self) -> None:
        self.input_field.setFocus()
        self.tabs.setCurrentIndex(0)

    def focus_default(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.focus_input()

    def _add_welcome_message(self) -> None:
        welcome = ChatMessage(
            "assistant",
            "欢迎使用本地知识库问答！\n\n"
            "在「知识库管理」标签中重建索引后，即可在这里问答。\n"
            "每个工作区绑定一个独立的知识库，RAG会召回相关知识片段回答。",
        )
        self._append_message(welcome)

    def _append_message(self, message: ChatMessage) -> MessageBubble:
        bubble = MessageBubble(message, self.chat_container)
        self.chat_layout.addWidget(bubble)
        self._scroll_to_bottom()
        return bubble

    def _scroll_to_bottom(self) -> None:
        sb = self.chat_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _send_message(self) -> None:
        if self._generating or self._loading_model or self.rag_service is None:
            return

        question = self.input_field.text().strip()
        if not question:
            return

        conversation = self._current_conversation()
        if conversation is None:
            conversation = self._create_conversation(question)
            self._conversations.append(conversation)
            self._current_conv_id = conversation["id"]

        user_msg = ChatMessage("user", question)
        self._append_message(user_msg)
        self.chat_history.append(user_msg)
        self._append_message_to_current("user", question)
        self.input_field.clear()

        self._generating = True
        self.send_button.setEnabled(False)
        self.input_field.setEnabled(False)
        self.new_chat_button.setEnabled(False)

        assistant_msg = ChatMessage("assistant", "")
        self._current_message = assistant_msg
        self._current_bubble = self._append_message(assistant_msg)

        def generation_thread():
            try:
                self._loading_model = True
                self._stream_signals.chunk_ready.emit("正在加载模型，请稍候...")
                full_text = ""
                generator = self.rag_service.query(question, stream=True)
                assert isinstance(generator, Generator)
                for chunk in generator:
                    full_text += chunk
                    self._stream_signals.chunk_ready.emit(full_text)
            except Exception as e:
                self._stream_signals.generation_error.emit(str(e))
            finally:
                self._loading_model = False
                self._stream_signals.generation_done.emit()

        Thread(target=generation_thread, daemon=True).start()

    def _on_stream_chunk(self, full_text: str) -> None:
        # Throttle UI updates: only refresh at most every ~33ms, and use
        # plain text during streaming to avoid O(n^2) Markdown re-parsing.
        self._pending_text = full_text
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(33)

    def _flush_stream(self) -> None:
        if self._current_bubble is None:
            return
        self._current_bubble.set_plain_text(self._pending_text)
        self.chat_container.adjustSize()
        self._scroll_to_bottom()

    def _on_generation_done(self) -> None:
        self._refresh_timer.stop()
        self._flush_stream()
        if self._current_bubble is not None:
            self._current_bubble.render_markdown()
            self.chat_container.adjustSize()
            self._scroll_to_bottom()
        self._finish_generation()

    def _on_generation_error(self, error: str) -> None:
        self._refresh_timer.stop()
        if self._current_bubble is not None:
            if "402" in error or "余额" in error:
                title = "💰 账户余额不足"
            elif "401" in error or "API Key" in error:
                title = "🔑 API Key 无效"
            elif "429" in error or "限流" in error:
                title = "⏱️ 请求过于频繁"
            else:
                title = "⚠️ 生成回答时出错"
            self._current_bubble.set_text(f"{title}\n\n{error}")
            self.chat_container.adjustSize()
            self._scroll_to_bottom()
        self._finish_generation()

    def _finish_generation(self) -> None:
        if self._current_message is not None:
            self.chat_history.append(self._current_message)
            self._append_message_to_current("assistant", self._current_message.content)
            self._current_message = None
        self._generating = False
        self.send_button.setEnabled(True)
        self.input_field.setEnabled(True)
        self.new_chat_button.setEnabled(True)
        self.input_field.setFocus()

    def _current_conversation(self) -> dict[str, Any] | None:
        if self._current_conv_id is None:
            return None
        return self._find_conversation(self._current_conv_id)

    def _find_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        for conversation in self._conversations:
            if str(conversation.get("id") or "") == conversation_id:
                return conversation
        return None

    def _now_iso(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _auto_title(self, question: str) -> str:
        compact = " ".join(str(question).split())
        return compact[:30] or "新对话"

    def _create_conversation(self, first_question: str) -> dict[str, Any]:
        now = self._now_iso()
        return {
            "id": uuid4().hex,
            "title": self._auto_title(first_question),
            "pinned": False,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }

    def _load_conversations_from_store(self) -> None:
        self._conversations = (
            load_conversations(self.workspace_root) if self.workspace_root is not None else []
        )
        self._current_conv_id = None

    def _save_history(self) -> None:
        if self.workspace_root is not None:
            save_conversations(self.workspace_root, self._conversations)

    def _append_message_to_current(self, role: str, content: str) -> None:
        conversation = self._current_conversation()
        if conversation is None:
            return
        conversation.setdefault("messages", []).append({"role": role, "content": content})
        conversation["updated_at"] = self._now_iso()
        self._save_history()
        self._update_conversation_title_label()
        self._refresh_history_list()

    def _start_new_chat(self, *, reset_list: bool = False) -> None:
        if self._generating or self._loading_model:
            return
        self._current_conv_id = None
        self.chat_history = []
        self._clear_chat_widgets()
        self._add_welcome_message()
        self._update_conversation_title_label()
        self._refresh_history_list()
        if not reset_list:
            self.tabs.setCurrentIndex(0)
            self.input_field.setFocus()

    def _clear_chat_widgets(self) -> None:
        while self.chat_layout.count():
            item = self.chat_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _update_conversation_title_label(self) -> None:
        conversation = self._current_conversation()
        title = str(conversation.get("title") or "") if conversation else ""
        if not title.strip():
            title = "新对话"
        self.conversation_title_label.setText(self._elide_text(title, 260))
        self.conversation_title_label.setToolTip(title)

    def _sorted_conversations(self) -> list[dict[str, Any]]:
        pinned = [c for c in self._conversations if c.get("pinned")]
        unpinned = [c for c in self._conversations if not c.get("pinned")]
        pinned.sort(key=lambda c: str(c.get("updated_at") or ""), reverse=True)
        unpinned.sort(key=lambda c: str(c.get("updated_at") or ""), reverse=True)
        return pinned + unpinned

    def _refresh_history_list(self) -> None:
        self.history_list.clear()
        if self.workspace_root is None:
            self._add_disabled_item(self.history_list, "尚未打开工作区")
            return
        if not self._conversations:
            self._add_disabled_item(self.history_list, "暂无历史对话，发送消息后会自动保存")
            return
        for conversation in self._sorted_conversations():
            self._add_history_row(conversation)
        self._mark_active_conversation()

    def _add_history_row(self, conversation: dict[str, Any]) -> None:
        conversation_id = str(conversation.get("id") or "")
        if not conversation_id:
            return

        item = QListWidgetItem(self.history_list)
        item.setData(Qt.ItemDataRole.UserRole, conversation_id)
        item.setText("")

        title = str(conversation.get("title") or "新对话")
        time_text = self._format_conversation_time(conversation)
        if conversation.get("pinned"):
            time_text = f"{time_text} · 已置顶"
        tooltip = title
        if conversation.get("updated_at"):
            tooltip = f"{title}\n最近对话：{conversation.get('updated_at')}"

        row = QWidget()
        outer = QVBoxLayout(row)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(6)
        title_label = QLabel(self._elide_text(title, 220), row)
        title_label.setToolTip(tooltip)
        header.addWidget(title_label, 1)

        more_button = QToolButton(row)
        more_button.setText("⋯")
        more_button.setToolTip("更多操作")
        more_button.setAutoRaise(True)
        more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        more_button.setFixedSize(26, 26)
        more_button.setStyleSheet(
            "QToolButton { background: transparent; border: none; border-radius: 5px;"
            " color: #6B7280; font-size: 16px; font-weight: 600; padding: 0; }"
            " QToolButton:hover { background: #E5E7EB; color: #111827; }"
        )
        header.addWidget(more_button)
        outer.addLayout(header)

        time_label = QLabel(time_text, row)
        time_label.setObjectName("muted_label")
        time_label.setToolTip(tooltip)
        outer.addWidget(time_label)

        more_button.clicked.connect(
            lambda _checked=False, cid=conversation_id, btn=more_button: self._show_conversation_menu(
                cid,
                btn.mapToGlobal(QPoint(0, btn.height())),
            )
        )

        item.setSizeHint(row.sizeHint())
        self.history_list.setItemWidget(item, row)

    def _mark_active_conversation(self) -> None:
        if self._current_conv_id is None:
            return
        for index in range(self.history_list.count()):
            item = self.history_list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == self._current_conv_id:
                self.history_list.setCurrentItem(item)
                self.history_list.scrollToItem(item)
                break

    def _on_history_item_clicked(self, item: QListWidgetItem) -> None:
        conversation_id = item.data(Qt.ItemDataRole.UserRole)
        if conversation_id:
            self._open_conversation(str(conversation_id))

    def _show_history_list_context_menu(self, position: QPoint) -> None:
        item = self.history_list.itemAt(position)
        if item is None:
            return
        conversation_id = item.data(Qt.ItemDataRole.UserRole)
        if not conversation_id:
            return
        self._show_conversation_menu(
            str(conversation_id),
            self.history_list.mapToGlobal(position),
        )

    def _open_conversation(self, conversation_id: str) -> None:
        if self._generating or self._loading_model:
            return
        conversation = self._find_conversation(conversation_id)
        if conversation is None:
            return
        self._current_conv_id = conversation_id
        self.chat_history = []
        self._clear_chat_widgets()
        for message in conversation.get("messages", []):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            chat_message = ChatMessage(role, str(message.get("content") or ""))
            self.chat_history.append(chat_message)
            self._append_message(chat_message)
        self._update_conversation_title_label()
        self._refresh_history_list()
        self.tabs.setCurrentIndex(0)
        self.input_field.setFocus()

    def _show_conversation_menu(self, conversation_id: str, global_pos: QPoint) -> None:
        conversation = self._find_conversation(conversation_id)
        if conversation is None:
            return

        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        pin_label = "取消置顶" if conversation.get("pinned") else "置顶"
        pin_action = menu.addAction(pin_label)
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        if self._generating and self._current_conv_id == conversation_id:
            delete_action.setEnabled(False)

        selected = menu.exec(global_pos)
        if selected == rename_action:
            self._rename_conversation(conversation)
        elif selected == pin_action:
            self._toggle_pin_conversation(conversation)
        elif selected == delete_action:
            self._delete_conversation(conversation)

    def _rename_conversation(self, conversation: dict[str, Any]) -> None:
        title, accepted = QInputDialog.getText(
            self,
            "重命名对话",
            "对话标题：",
            text=str(conversation.get("title") or ""),
        )
        title = title.strip()
        if not accepted or not title:
            return
        if title == conversation.get("title"):
            return
        conversation["title"] = title
        self._save_history()
        self._refresh_history_list()
        self._update_conversation_title_label()

    def _toggle_pin_conversation(self, conversation: dict[str, Any]) -> None:
        conversation["pinned"] = not bool(conversation.get("pinned"))
        self._save_history()
        self._refresh_history_list()

    def _delete_conversation(self, conversation: dict[str, Any]) -> None:
        title = str(conversation.get("title") or "未命名对话")
        confirm = QMessageBox.question(
            self,
            "删除对话",
            f"确定删除“{title}”吗？\n该对话的内容将无法恢复。",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        conversation_id = str(conversation.get("id") or "")
        self._conversations.remove(conversation)
        self._save_history()
        if self._current_conv_id == conversation_id:
            self._start_new_chat()
        else:
            self._refresh_history_list()

    def _format_conversation_time(self, conversation: dict[str, Any]) -> str:
        updated_at = str(conversation.get("updated_at") or "")
        if not updated_at:
            return "最近对话时间未知"
        try:
            timestamp = datetime.fromisoformat(updated_at)
        except ValueError:
            return "最近对话时间未知"
        now = datetime.now()
        if timestamp.date() == now.date():
            return f"今天 {timestamp:%H:%M}"
        if timestamp.year == now.year:
            return f"{timestamp:%m-%d %H:%M}"
        return f"{timestamp:%Y-%m-%d}"

    def _elide_text(self, text: str, width: int) -> str:
        metrics = QFontMetrics(self.font())
        return metrics.elidedText(str(text), Qt.TextElideMode.ElideRight, width)

    def _add_disabled_item(self, list_widget: QListWidget, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(item)

    def _refresh_doc_list(self) -> None:
        self.doc_list.clear()
        if self.rag_service is None:
            self.stats_label.setText("未打开工作区")
            return

        docs = self.rag_service.get_indexed_documents()
        total_chunks = sum(d.get("chunks", 0) for d in docs)

        if not docs:
            self.stats_label.setText("索引为空，请点击「重建索引」构建知识库")
            item = QListWidgetItem("暂无索引文档")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.doc_list.addItem(item)
            return

        self.stats_label.setText(f"已索引 {len(docs)} 个文档，共 {total_chunks} 个片段")
        for doc in docs:
            title = doc.get("title", doc.get("source", "unknown"))
            chunks = doc.get("chunks", 0)
            item = QListWidgetItem(f"{title} · {chunks} 片段")
            item.setData(Qt.ItemDataRole.UserRole, doc)
            item.setToolTip(doc.get("source", ""))
            self.doc_list.addItem(item)

    def _show_doc_context_menu(self, position) -> None:
        item = self.doc_list.itemAt(position)
        if item is None:
            return

        doc_data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(doc_data, dict):
            return

        source = doc_data.get("source", "")
        if not source:
            return

        menu = QMenu(self)
        remove_action = menu.addAction("从知识库移除")
        action = menu.exec(self.doc_list.mapToGlobal(position))

        if action == remove_action and self.rag_service:
            self.rag_service.remove_document(source)
            self._refresh_doc_list()

    def _rebuild_index(self) -> None:
        if self.rag_service is None or self.workspace_root is None:
            return

        candidates = self.rag_service.list_index_candidates()
        if not candidates:
            QMessageBox.information(
                self,
                "没有可索引的文件",
                "当前工作区没有可建立索引的笔记、PDF 或 PPT 文件。",
            )
            return

        dialog = IndexFilePickerDialog(candidates, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_paths = dialog.selected_paths()
        if not selected_paths:
            confirm = QMessageBox.question(
                self,
                "未选择文件",
                "没有勾选任何文件，是否仍要继续？\n\n"
                "继续将清空当前知识库的索引，之后可重新建立。",
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        self.build_index_btn.setEnabled(False)
        self.clear_index_btn.setEnabled(False)
        self.stats_label.setText(
            f"正在为 {len(selected_paths)} 个文件建立索引并加载模型，请稍候..."
        )

        def rebuild_thread():
            self._loading_model = True
            try:
                result = self.rag_service.rebuild_index(selected_paths or None)
            except Exception as error:  # pragma: no cover - thread guard.
                result = {"success": False, "message": str(error)}
            finally:
                self._loading_model = False
            self._stream_signals.rebuild_done.emit(result)

        Thread(target=rebuild_thread, daemon=True).start()

    def _on_rebuild_done(self, result: dict) -> None:
        if result.get("success"):
            data = result.get("data", {})
            indexed = data.get("indexed", 0)
            chunks = data.get("chunks", 0)
            self.stats_label.setText(f"重建完成：索引了 {indexed} 个文档，共 {chunks} 个片段")
        else:
            msg = result.get("message", "重建失败")
            self.stats_label.setText(f"重建失败：{msg}")
        self._refresh_doc_list()
        self.build_index_btn.setEnabled(True)
        self.clear_index_btn.setEnabled(True)

    def _clear_index(self) -> None:
        if self.rag_service is None:
            return

        confirm = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空当前知识库的所有索引吗？\n\n需要重建才能再次使用问答功能。",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        result = self.rag_service.clear_index()
        if result.get("success"):
            self.stats_label.setText("索引已清空")
            self._refresh_doc_list()