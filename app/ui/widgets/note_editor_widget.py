"""
app/ui/widgets/note_editor_widget.py

行级 Live Preview 版 NoteEditorWidget
当前行源码编辑，其他行保持 Markdown 渲染。

本版重点：
1. 统一浅色主题；
2. 当前编辑行背景与整体风格一致；
3. 当前编辑行文字更清晰；
4. 保持与 main_window.py 的现有接口兼容。
"""

from __future__ import annotations

from typing import Optional
import html
import re

from PySide6.QtCore import QEvent, Qt, Signal, QRect, QTimer
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QMessageBox,
    QTextBrowser,
    QPlainTextEdit,
    QFrame,
)

from app.editor.markdown_document import MarkdownDocument


EDITOR_FONT_FAMILY = "Microsoft YaHei UI"
EDITOR_FONT_POINT_SIZE = 11
EDITOR_CONTENT_PADDING_X = 24
EDITOR_CONTENT_PADDING_Y = 18
EDITOR_LINE_PADDING_Y = 3

# 表格分隔行的单元格（---、:--、--:、:--: 等）
_TABLE_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")
_TABLE_CELL_GAP_PX = 20.0


def _make_tab(position: float):
    tab = QTextOption.Tab()
    tab.position = float(position)
    return tab


class LinePreviewBrowser(QTextBrowser):
    """支持点击行的预览控件。"""

    line_clicked = Signal(int)

    def mousePressEvent(self, event):
        cursor = self.cursorForPosition(event.pos())
        line_index = max(0, cursor.blockNumber())
        self.line_clicked.emit(line_index)
        super().mousePressEvent(event)


class FloatingLineEditor(QPlainTextEdit):
    """覆盖在预览之上的当前行编辑器。"""

    line_commit_requested = Signal()
    move_up_requested = Signal()
    move_down_requested = Signal()
    split_line_requested = Signal(int)
    merge_prev_requested = Signal()
    merge_next_requested = Signal()
    # 粘贴/拖入的多行文本：悬浮编辑器是“单行”控件，行拆分必须在编辑器模型层完成，
    # 由 NoteEditorWidget 统一处理，避免把字面换行符写进 self._lines。
    multiline_insert_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setTabChangesFocus(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(0)
        text_option = self.document().defaultTextOption()
        text_option.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.document().setDefaultTextOption(text_option)
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(0, 0, 0, 0)

        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #FFFFFF;
                color: #111827;
                border: none;
                border-radius: 0;
                padding: 0;
                selection-background-color: #BFDBFE;
                selection-color: #111827;
            }
        """)

        # 悬浮层只是“单行源码编辑框”，绝不希望它拦截滚轮：当框内文本换行后
        # 高于框体时，QPlainTextEdit 会吞掉滚轮事件去滚动自己的内容，导致下层
        # 预览在编辑行附近“滚不动/抽搐”。这里把滚轮直接转交给父级预览处理。
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewport() and event.type() == QEvent.Type.Wheel:
            # 悬浮层是 QPlainTextEdit(滚动区)，当内部文字超出框体时会吞掉滚轮
            # 去滚动自己，导致下层预览滚不动。滚轮统一交给父级预览的 viewport。
            parent = self.parentWidget()
            target = None
            if isinstance(parent, QAbstractScrollArea):
                target = parent.viewport()
            elif parent is not None:
                target = parent
            if target is not None:
                QApplication.sendEvent(target, event)
                return True
        return super().eventFilter(obj, event)

    def insertFromMimeData(self, source) -> None:
        """拦截多行粘贴/拖入，交给编辑器做“行模型级”插入。

        QPlainTextEdit 默认会把含换行的文本直接插入文档，使悬浮编辑器短暂
        出现多行内容；随后 textChanged 吸收逻辑虽然能补救，但视觉上易跳动、
        行位置也可能因异步时序混乱。这里在插入前拦截，统一拆行。
        """
        if source is not None and source.hasText():
            text = source.text()
            if "\n" in text or "\r" in text:
                self.multiline_insert_requested.emit(text)
                return
        super().insertFromMimeData(source)

    def keyPressEvent(self, event):
        key = event.key()
        cursor = self.textCursor()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.split_line_requested.emit(cursor.position())
            event.accept()
            return

        if key == Qt.Key.Key_Up:
            if cursor.position() == 0:
                self.move_up_requested.emit()
                event.accept()
                return

        if key == Qt.Key.Key_Down:
            if cursor.position() == len(self.toPlainText()):
                self.move_down_requested.emit()
                event.accept()
                return

        if key == Qt.Key.Key_Backspace:
            if cursor.position() == 0:
                self.merge_prev_requested.emit()
                event.accept()
                return

        if key == Qt.Key.Key_Delete:
            if cursor.position() == len(self.toPlainText()):
                self.merge_next_requested.emit()
                event.accept()
                return

        super().keyPressEvent(event)


class NoteEditorWidget(QWidget):
    """
    行级 Live Preview 版 Markdown 编辑器。
    当前行源码编辑，其他行渲染。
    """

    content_changed = Signal(str)
    cursor_position_changed = Signal(int)
    save_requested = Signal(dict)
    document_changed = Signal(object)
    status_changed = Signal(str)
    title_changed = Signal(str)
    open_requested = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._document = MarkdownDocument.create_empty()
        self._is_loading = False
        self._read_only_mode = False
        self._normalizing_lines = False

        self._lines: list[str] = [""]
        self._current_line_index: int = 0
        self._table_row_info: dict[int, dict] = {}
        self._table_row_stops: dict[int, list[float]] = {}
        self._applied_font_key: tuple | None = None

        self._overlay_refresh_timer = QTimer(self)
        self._overlay_refresh_timer.setSingleShot(True)
        self._overlay_refresh_timer.setInterval(20)

        self._build_ui()
        self._bind_signals()
        self._build_actions()
        self._apply_document_to_view()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("note_editor_widget")
        self.setStyleSheet("""
            QWidget#note_editor_widget {
                background-color: #FFFFFF;
            }
            QLabel {
                color: #374151;
            }
            QLineEdit {
                background-color: #FFFFFF;
                color: #111827;
                border: 1px solid #D9E1EC;
                border-radius: 8px;
                min-height: 32px;
                padding: 4px 10px;
            }
            QLineEdit:focus {
                border: 1px solid #2563EB;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        title_hint_label = QLabel("标题：", self)
        self.title_edit = QLineEdit(self)
        self.title_edit.setPlaceholderText("请输入笔记标题")

        self.status_label = QLabel("idle", self)
        self.status_label.setObjectName("editor_status_label")
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setMinimumWidth(82)

        header_layout.addWidget(title_hint_label)
        header_layout.addWidget(self.title_edit, 1)
        header_layout.addWidget(self.status_label)
        self._set_status_indicator(self._document.session_status)

        self.preview = LinePreviewBrowser(self)
        self.preview.setOpenLinks(False)
        self.preview.setOpenExternalLinks(False)
        self.preview.setReadOnly(True)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        preview_font = QFont(EDITOR_FONT_FAMILY)
        preview_font.setPointSize(EDITOR_FONT_POINT_SIZE)
        self.preview.setFont(preview_font)
        self.preview.document().setDefaultFont(preview_font)
        self.preview.document().setDocumentMargin(0)
        self.preview.setViewportMargins(
            EDITOR_CONTENT_PADDING_X,
            EDITOR_CONTENT_PADDING_Y,
            EDITOR_CONTENT_PADDING_X,
            EDITOR_CONTENT_PADDING_Y,
        )

        self.preview.setStyleSheet("""
            QTextBrowser {
                background-color: #FFFFFF;
                color: #111827;
                border: 1px solid #E6EAF0;
                border-radius: 8px;
                padding: 0;
            }
        """)

        # 悬浮层不要直接挂在 viewport 上：实测若父对象是滚动区的 viewport 且
        # 悬浮层带自身样式表，Qt 会在 polish 时把它的字体重置为应用默认字体，
        # 导致悬浮层文字(约9pt)与预览文字(11pt)行高/换行不一致——文字发虚、错位、
        # 最后一行被裁。挂在 preview(滚动区) 自身即可避免该问题。
        self.line_editor = FloatingLineEditor(self.preview)
        editor_font = QFont(EDITOR_FONT_FAMILY)
        editor_font.setPointSize(EDITOR_FONT_POINT_SIZE)
        editor_font.setWeight(QFont.Weight.Normal)
        self.line_editor.setFont(editor_font)
        self.line_editor.document().setDefaultFont(editor_font)
        self.line_editor.hide()

        layout.addLayout(header_layout)
        layout.addWidget(self.preview, 1)

    def _bind_signals(self) -> None:
        self.title_edit.textEdited.connect(self._on_title_edited)
        self.preview.line_clicked.connect(self._on_preview_line_clicked)

        self.line_editor.textChanged.connect(self._on_line_editor_text_changed)
        self.line_editor.multiline_insert_requested.connect(self._insert_multiline_into_lines)
        self.line_editor.cursorPositionChanged.connect(self._on_line_editor_cursor_changed)
        self.line_editor.move_up_requested.connect(self._move_to_previous_line)
        self.line_editor.move_down_requested.connect(self._move_to_next_line)
        self.line_editor.split_line_requested.connect(self._split_current_line)
        self.line_editor.merge_prev_requested.connect(self._merge_with_previous_line)
        self.line_editor.merge_next_requested.connect(self._merge_with_next_line)

        self._overlay_refresh_timer.timeout.connect(self._reposition_line_editor)

        # 用户滚动预览时，让悬浮编辑器始终贴住当前编辑行
        self.preview.verticalScrollBar().valueChanged.connect(
            lambda _v: self._overlay_refresh_timer.start()
        )
        self.preview.horizontalScrollBar().valueChanged.connect(
            lambda _v: self._overlay_refresh_timer.start()
        )

    def _build_actions(self) -> None:
        self.save_action = QAction(self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.request_save)
        self.addAction(self.save_action)

    def _set_status_indicator(self, status: str) -> None:
        color_by_status = {
            "idle": "#22C55E",
            "editing": "#F59E0B",
            "saved": "#22C55E",
            "save_failed": "#EF4444",
            "external_modified": "#F59E0B",
        }
        label_by_status = {
            "idle": "idle",
            "editing": "editing",
            "saved": "saved",
            "save_failed": "error",
            "external_modified": "warning",
        }
        dot_color = color_by_status.get(status, "#9CA3AF")
        label = label_by_status.get(status, status or "idle")
        self.status_label.setText(
            "<span style='white-space: nowrap;'>"
            f"<span style='color:{dot_color}; font-size:16px;'>●</span>"
            "&nbsp;"
            f"<span style='color:#374151; font-size:13px;'>{html.escape(label)}</span>"
            "</span>"
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 每次显示都强制重设一次字体：Qt 样式引擎在 widget 被 polish 时可能把
        # 悬浮层字体回退成应用默认值，重设可兜底（见 _build_ui 中 parent 的注释）。
        self._applied_font_key = None
        self._apply_editor_fonts()
        self._overlay_refresh_timer.start()

    def _apply_editor_fonts(self) -> None:
        key = (EDITOR_FONT_FAMILY, EDITOR_FONT_POINT_SIZE)
        if self._applied_font_key == key:
            return
        self._applied_font_key = key
        editor_font = QFont(EDITOR_FONT_FAMILY)
        editor_font.setPointSize(EDITOR_FONT_POINT_SIZE)

        self.preview.setFont(editor_font)
        self.preview.document().setDefaultFont(editor_font)
        self.line_editor.setFont(editor_font)
        self.line_editor.document().setDefaultFont(editor_font)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def _set_lines_from_text(self, text: str) -> None:
        self._lines = text.split("\n")
        if not self._lines:
            self._lines = [""]
        self._current_line_index = max(0, min(self._current_line_index, len(self._lines) - 1))

    def _get_text_from_lines(self) -> str:
        return "\n".join(self._lines)

    def _force_full_document_layout(self) -> None:
        """强制 QTextDocument 完成整篇排版。

        setHtml 之后 Qt 采用“惰性排版”：滚动条范围只按已经排出来的块计算。
        如果在排版完成前就恢复滚动值/做可见性校正，底部区域的数值会不稳定，
        出现抽搐或滚不到底的现象。这里把所有块的排版坐标都读一遍，让文档
        总高度与滚动范围一次到位。
        """
        doc = self.preview.document()
        layout = doc.documentLayout()
        block = doc.begin()
        while block.isValid():
            layout.blockBoundingRect(block)
            block = block.next()
        layout.documentSize()

    def _sync_editing_placeholder(self) -> None:
        """把预览中“当前编辑行”的占位块文字更新为最新源码（白色隐形）。

        悬浮层下面预览里的占位段负责撑起文档排版：一旦输入使段落换行变多/变少，
        只有占位块同步更新并整篇重排后，后续各行的位置与滚动范围才会跟随变化，
        否则悬浮层会越画越高，盖住下一段的文字。
        """
        doc = self.preview.document()
        block = doc.findBlockByNumber(self._current_line_index)
        if not block.isValid():
            return
        text = self._lines[self._current_line_index]
        cursor = QTextCursor(block)
        cursor.beginEditBlock()
        try:
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()
            fmt = QTextCharFormat()
            fmt.setForeground(QBrush(QColor("#FFFFFF")))
            cursor.insertText(text if text else " ", fmt)
        finally:
            cursor.endEditBlock()
        self._force_full_document_layout()

    def _refresh_preview(self) -> None:
        sb = self.preview.verticalScrollBar()
        old_scroll = sb.value()

        html_text = self._render_document_html(self._lines, self._current_line_index)
        self.preview.setHtml(html_text)

        # 表格行在 setHtml 后按单行块重建（保留“1 逻辑行 == 1 QTextBlock”）
        self._apply_table_blocks()

        # setHtml 会把滚动位置重置到文档顶部；先强制整篇排版，保证滚动条
        # 范围是最新的，再恢复原位置并让当前编辑行保持在可视区内。
        self._force_full_document_layout()
        # setHtml 会把连续空格/制表符折叠，导致编辑行占位段的换行数暂时比
        # 真实源码少一行而高度偏小；立即用 insertText 写回原文以同步占位几何。
        self._sync_editing_placeholder()
        if sb.maximum() > 0:
            sb.setValue(min(old_scroll, sb.maximum()))
        self._ensure_current_line_visible()
        # 直接定位一次（行切换/回车拆分后不再等 20ms 定时器，避免悬浮层在
        # 下一帧仍停留在旧行）；滚动条的 valueChanged 仍会走定时器做防抖。
        self._reposition_line_editor()
        self._overlay_refresh_timer.start()

    _INLINE_TOKEN_RE = re.compile(
        r"(?P<code>`[^`\n]+`)|"
        r"(?P<wiki>\[\[[^\]\n]+\]\])|"
        r"(?P<cite>\[@[^\]\n]+\])|"
        r"(?P<link>\[[^\]\n]+\]\([^)\s]+\))|"
        r"(?P<strong>\*\*.+?\*\*)|"
        r"(?P<strike>~~.+?~~)|"
        r"(?P<under>__.+?__)|"
        r"(?P<em>\*.+?\*)"
    )

    _BODY_MARGIN = "margin-top:4px;margin-bottom:4px;"
    _QUOTE_MARGIN = "margin-top:2px;margin-bottom:2px;"
    _CODE_MARGIN = "margin-top:1px;margin-bottom:1px;"
    _HEADING_SIZES = {1: 20, 2: 17, 3: 15, 4: 13, 5: 12, 6: 11}
    _HEADING_TOPS = {1: 12, 2: 10, 3: 8, 4: 6, 5: 4, 6: 4}

    @staticmethod
    def _wrap_style(style: str) -> str:
        return f'style="{style}"'

    def _render_document_html(self, lines: list[str], editing_line_index: int) -> str:
        """整篇预览 HTML。

        注意：Qt 富文本只识别真实标签与内联 style，会忽略 <style> 里的 class
        规则，因此所有视觉样式都以内联属性给出。同时保证“每个逻辑行恰好生成
        一个 QTextBlock”，否则悬浮编辑器用 findBlockByNumber() 定位会错行。
        """
        body_parts = []
        code_flags = self._compute_code_flags(lines)
        self._collect_table_layout(lines, code_flags)
        is_empty_document = not any(line.strip() for line in lines)
        for i, line in enumerate(lines):
            if i == editing_line_index:
                # 当前编辑行：预览里放占位源码（白色悬浮编辑器覆盖其上）
                body_parts.append(self._render_editing_line(line))
            elif code_flags[i]:
                body_parts.append(self._render_code_line(line))
            elif i in self._table_row_info:
                # 表格行：先留一个空块占位，稍后在 _apply_table_blocks 中按
                # “真实 tab + 块级 tab stop”重建，保证仍是 1 逻辑行 == 1 块。
                body_parts.append(self._render_table_placeholder())
            else:
                body_parts.append(self._render_line_to_html(line))
        if is_empty_document:
            body_parts.append(
                '<p style="margin-top:12px;color:#9CA3AF;">'
                "开始记录你的阅读笔记…<br/>"
                "支持 Markdown、[[双向链接]]、@文献引用 与 #标签"
                "</p>"
            )
        return "<html><body>{}</body></html>".format("".join(body_parts))

    def _compute_code_flags(self, lines: list[str]) -> list[bool]:
        """标记代码区域：围栏代码块以及“制表符/4 空格缩进”的代码行。

        状态机基于源码 lines 计算，因此即使当前行正在编辑（其源码已包含
        ``` 标记），其余行的渲染状态依然正确。
        """
        flags = [False] * len(lines)
        fence = None
        for i, raw in enumerate(lines):
            stripped = raw.strip()
            if fence is not None:
                flags[i] = True
                if stripped.startswith(fence):
                    fence = None
                continue
            m = re.match(r"^(```+|~~~+)", stripped)
            if m is not None and len(m.group(1)) >= 3:
                flags[i] = True
                fence = "```" if m.group(1).startswith("`") else "~~~"
                continue
            if raw.startswith("\t") or raw.startswith("    "):
                flags[i] = True
        return flags

    # ------------------------------------------------------------------
    # 表格渲染（保留“1 逻辑行 == 1 QTextBlock”）
    # ------------------------------------------------------------------

    def _parse_table_cells(self, raw: str) -> list[str]:
        """按 Markdown 表格语法拆分一行的单元格（容忍外侧可省略的 |）。"""
        s = raw.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    def _is_table_separator_row(self, raw: str) -> bool:
        cells = self._parse_table_cells(raw)
        if not cells:
            return False
        return any(cells) and all(
            bool(_TABLE_SEP_CELL_RE.fullmatch(c)) for c in cells
        )

    def _collect_table_layout(
        self,
        lines: list[str],
        code_flags: list[bool],
    ) -> None:
        """识别连续的管道表格，记录每行角色与列 tab stop。

        只处理 `| ... |` 且第二行为分隔行的连续区段；代码行不会被误判。
        """
        self._table_row_info = {}
        self._table_row_stops = {}
        n = len(lines)
        i = 0
        while i < n - 1:
            if code_flags[i] or not lines[i].strip().startswith("|"):
                i += 1
                continue
            if not lines[i + 1].strip().startswith("|"):
                i += 1
                continue
            if not self._is_table_separator_row(lines[i + 1]):
                i += 1
                continue
            rows: list[int] = []
            j = i
            while j < n and not code_flags[j] and lines[j].strip().startswith("|"):
                rows.append(j)
                j += 1
            if len(rows) < 2:
                i = j
                continue
            col_count = max(
                len(self._parse_table_cells(lines[r])) for r in rows
            )
            stops = self._measure_table_column_stops(lines, rows, col_count)
            for r in rows:
                role = "header" if r == rows[0] else (
                    "sep" if r == rows[1] else "body"
                )
                self._table_row_info[r] = {
                    "role": role,
                    "cells": self._parse_table_cells(lines[r]),
                }
                self._table_row_stops[r] = stops
            i = j

    def _measure_table_column_stops(
        self,
        lines: list[str],
        rows: list[int],
        col_count: int,
    ) -> list[float]:
        """根据各列最宽单元格（用当前预览字体实测）计算后续列的 tab stop。"""
        fm = QFontMetrics(self.preview.font())
        widths = [0.0] * col_count
        for r in rows:
            cells = self._parse_table_cells(lines[r])
            for ci, cell in enumerate(cells):
                if ci >= col_count:
                    break
                w = fm.horizontalAdvance(cell)
                if w > widths[ci]:
                    widths[ci] = w
        stops: list[float] = []
        acc = 0.0
        for ci in range(col_count - 1):
            acc += widths[ci] + _TABLE_CELL_GAP_PX
            stops.append(acc)
        return stops

    def _render_table_placeholder(self) -> str:
        return (
            '<p style="margin-top:1px;margin-bottom:1px;'
            "color:#374151;\">&nbsp;</p>"
        )

    def _apply_table_blocks(self) -> None:
        """setHtml 之后把表格行块重建成“单元格文本 + 制表符对齐”的单行块。

        必须在 _render_document_html 之后、悬浮定位测量之前调用；重建只改
        块内文本/格式，不改动块数量，因此行号映射不受影响。
        """
        if not self._table_row_info:
            return
        doc = self.preview.document()
        current = self._current_line_index
        for line_index, meta in self._table_row_info.items():
            if line_index == current:
                # 正在编辑的行保留原始源码（悬浮编辑器覆盖其上）
                continue
            block = doc.findBlockByNumber(line_index)
            if not block.isValid():
                continue
            self._fill_table_row_block(
                block,
                meta["role"],
                meta["cells"],
                self._table_row_stops.get(line_index, []),
            )
        self._table_row_info = {}
        self._table_row_stops = {}

    def _fill_table_row_block(
        self,
        block,
        role: str,
        cells: list[str],
        stops: list[float],
    ) -> None:
        cursor = QTextCursor(block)
        cursor.beginEditBlock()
        try:
            # 只选中本块内文本（不含段末分隔符），insertText 才不会合并相邻块
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )

            if role == "sep":
                # 分隔行：不再显示 --- 文本，渲染成一条细的水平分隔线（整行浅灰）。
                # 用一个超小字号的空格字符，把这一行压缩到几像素高。
                band_fmt = QTextCharFormat()
                band_fmt.setFontPointSize(2.0)
                block_format = QTextBlockFormat(block.blockFormat())
                block_format.setBackground(QBrush(QColor("#CBD5E1")))
                block_format.setTopMargin(0.0)
                block_format.setBottomMargin(0.0)
                cursor.insertText(" ", band_fmt)
                cursor.setBlockFormat(block_format)
                return

            block_format = QTextBlockFormat(block.blockFormat())
            if stops:
                block_format.setTabPositions([_make_tab(x) for x in stops])

            char_format = QTextCharFormat()
            if role == "header":
                block_format.setBackground(QBrush(QColor("#DBEAFE")))
                char_format.setFontWeight(QFont.Weight.Bold)
                char_format.setForeground(QBrush(QColor("#111827")))
            else:
                block_format.setBackground(QBrush(QColor("#F9FAFB")))
                char_format.setForeground(QBrush(QColor("#374151")))

            text = "\t".join(cells)
            cursor.insertText(text)

            # 插入后对整个块内部应用字符格式（merge 不会覆盖单元格内的差异）
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.mergeCharFormat(char_format)
            cursor.setBlockFormat(block_format)
        finally:
            cursor.endEditBlock()

    def _render_editing_line(self, line: str) -> str:
        """当前编辑行的占位 HTML（文字用白色隐藏）。

        悬浮编辑器覆盖其上负责真正显示文字。预览里的占位段保留与普通段落一致的
        margin 与换行排版，用于撑住文档后续各行的位置；文字若与悬浮层重复绘制，
        两套排版引擎的细微差异会叠出“重影/发虚”，因此这里统一做成隐形。
        """
        text = html.escape(line, quote=False) if line else "&nbsp;"
        invisible = f'<span style="color:#FFFFFF;">{text}</span>'
        return f'<p {self._wrap_style(self._BODY_MARGIN)}>{invisible}</p>'

    def _preserve_whitespace_html(self, text: str) -> str:
        """把文本渲染为保留空白的 HTML。

        Qt 富文本（非 pre 段落）会折叠连续普通空格，制表符也不会按预期占宽，
        这里统一把制表符展开为 4 空格、把连续空格转成 &nbsp;，实现等宽展示。
        """
        text = text.replace("\t", "    ")
        escaped = html.escape(text, quote=False)
        parts = re.split(r"( +)", escaped)
        out = []
        for part in parts:
            if part == "":
                continue
            if part and set(part) == {" "}:
                out.append("&nbsp;" * len(part) if len(part) > 1 else " ")
            else:
                out.append(part)
        return "".join(out) or "&nbsp;"

    def _render_code_line(self, line: str) -> str:
        body = self._preserve_whitespace_html(line)
        block_style = self._CODE_MARGIN + "background-color:#F6F8FA;"
        font_style = (
            "font-family:Consolas,'Courier New',monospace;"
            "font-size:10pt;color:#24292F;"
        )
        return (
            f'<p {self._wrap_style(block_style)}>'
            f'<span {self._wrap_style(font_style)}>{body}</span>'
            "</p>"
        )

    def _render_line_to_html(self, line: str) -> str:
        stripped = line.rstrip()

        if stripped == "":
            return self._render_editing_line("")

        # Markdown 分隔线：---  ___  ***
        if re.match(r"^ {0,3}([-*_])\s*(\1\s*){2,}$", stripped):
            return '<hr style="margin-top:8px;margin-bottom:8px;"/>'

        # 标题：#~######
        m = re.match(r"^ {0,3}(#{1,6})\s+(.*)$", stripped)
        if m is not None:
            level = len(m.group(1))
            content = self._render_inline_html(m.group(2).rstrip())
            size = self._HEADING_SIZES.get(level, 11)
            top = self._HEADING_TOPS.get(level, 4)
            block_style = f"margin-top:{top}px;margin-bottom:6px;"
            font_style = f"font-size:{size}pt;font-weight:700;color:#111827;"
            return (
                f'<p {self._wrap_style(block_style)}>'
                f'<span {self._wrap_style(font_style)}>{content}</span>'
                "</p>"
            )

        # 引用：> 与嵌套 >>
        m = re.match(r"^ {0,3}(>+)[ \t]*(.*)$", stripped)
        if m is not None:
            return self._render_blockquote_line(len(m.group(1)), m.group(2))

        # 无序列表：- + *（允许缩进，缩进代码已在代码区处理）
        m = re.match(r"^([ \t]*)([-*+])[ \t]+(.*)$", line)
        if m is not None and not m.group(1).startswith(("    ", "\t")):
            content = self._render_inline_html(m.group(3))
            return self._render_list_item("•", content, indent=len(m.group(1)))

        # 有序列表：1. 1)
        m = re.match(r"^([ \t]*)(\d+)[.)][ \t]+(.*)$", line)
        if m is not None and not m.group(1).startswith(("    ", "\t")):
            content = self._render_inline_html(m.group(3))
            return self._render_list_item(m.group(2) + ".", content, indent=len(m.group(1)))

        # 普通段落
        content = self._render_inline_html(stripped)
        return f'<p {self._wrap_style(self._BODY_MARGIN)}>{content}</p>'

    def _render_blockquote_line(self, level: int, content: str) -> str:
        block_style = self._QUOTE_MARGIN + "background-color:#EFF6FF;"
        if content.strip() == "":
            body = "&nbsp;"
        else:
            body = self._render_inline_html(content)
        marks = "".join(
            f'<span {self._wrap_style("color:#3B82F6;")}>&#9613;</span>'
            for _ in range(level)
        )
        return (
            f'<p {self._wrap_style(block_style)}>{marks}'
            f'<span {self._wrap_style("color:#374151;")}>{body}</span>'
            "</p>"
        )

    def _render_list_item(self, marker: str, content_html: str, indent: int = 0) -> str:
        if content_html == "":
            content_html = "&nbsp;"
        pad = "&nbsp;&nbsp;" * (indent // 2)
        return (
            f'<p {self._wrap_style(self._BODY_MARGIN)}>{pad}'
            f'<span {self._wrap_style("color:#6B7280;")}>{marker}</span>&nbsp;'
            f"{content_html}</p>"
        )

    def _render_inline_html(self, text: str) -> str:
        """行内 Markdown 解析：行内代码、粗体、斜体、删除线、链接等。

        实现为从左到右扫描 token（先保护行内代码/链接），因此不会发生“先替换
        ** 后把代码内容再处理一次”这类互相污染的问题。
        """
        if text == "":
            return ""
        out = []
        pos = 0
        for m in self._INLINE_TOKEN_RE.finditer(text):
            if m.start() > pos:
                out.append(html.escape(text[pos : m.start()], quote=False))
            kind = m.lastgroup
            raw = m.group(0)
            if kind == "code":
                out.append(
                    '<span '
                    + self._wrap_style(
                        "font-family:Consolas,'Courier New',monospace;"
                        "font-size:10pt;color:#B45309;background-color:#EEF2FF;"
                    )
                    + ">"
                    + self._preserve_whitespace_html(raw[1:-1])
                    + "</span>"
                )
            elif kind == "wiki":
                inner = raw[2:-2]
                if "|" in inner:
                    parts = inner.rsplit("|", 1)
                    display = parts[1] if parts[1] else parts[0]
                else:
                    display = inner
                out.append(
                    '<span '
                    + self._wrap_style("color:#2563EB;font-weight:600;")
                    + ">"
                    + html.escape(display, quote=False)
                    + "</span>"
                )
            elif kind == "cite":
                out.append(
                    '<span '
                    + self._wrap_style("color:#8B5CF6;font-weight:600;")
                    + ">"
                    + html.escape(raw, quote=False)
                    + "</span>"
                )
            elif kind == "link":
                inner = raw[1:]
                if "](" in inner:
                    label, url = inner.split("](", 1)
                    url = url[:-1]
                else:
                    label, url = raw, ""
                url = html.escape(url, quote=True)
                out.append(
                    '<a href="'
                    + url
                    + '" '
                    + self._wrap_style("color:#2563EB;text-decoration:none;")
                    + ">"
                    + self._render_inline_html(label)
                    + "</a>"
                )
            elif kind == "strong":
                out.append("<strong>" + self._render_inline_html(raw[2:-2]) + "</strong>")
            elif kind == "em":
                out.append("<em>" + self._render_inline_html(raw[1:-1]) + "</em>")
            elif kind == "strike":
                out.append(
                    '<span '
                    + self._wrap_style("color:#6B7280;text-decoration:line-through;")
                    + ">"
                    + self._render_inline_html(raw[2:-2])
                    + "</span>"
                )
            elif kind == "under":
                out.append("<u>" + self._render_inline_html(raw[2:-2]) + "</u>")
            pos = m.end()
        if pos < len(text):
            out.append(html.escape(text[pos:], quote=False))
        return "".join(out)

    # ------------------------------------------------------------------
    # 行编辑器定位与切换
    # ------------------------------------------------------------------

    def _ensure_current_line_visible(self) -> None:
        """让当前编辑行保持在预览可视区内（不跳回文档顶部）。

        布局坐标与视口坐标的换算：可见 y = 块的文档坐标 - 垂直滚动值。
        """
        block = self.preview.document().findBlockByNumber(self._current_line_index)
        if not block.isValid():
            return
        rect = self.preview.document().documentLayout().blockBoundingRect(block)
        sb = self.preview.verticalScrollBar()
        view_height = self.preview.viewport().height()
        value = sb.value()

        top = rect.top()
        bottom = rect.bottom()
        if top < value:
            sb.setValue(max(0, int(top - 16)))
        elif bottom > value + view_height:
            sb.setValue(max(0, int(bottom - view_height + 16)))

    def _reposition_line_editor(self) -> None:
        doc = self.preview.document()
        block = doc.findBlockByNumber(self._current_line_index)
        if not block.isValid():
            self.line_editor.hide()
            return

        self._apply_editor_fonts()

        # 文档坐标 -> preview(控件)坐标换算：
        # setViewportMargins 只是把 viewport 物理内缩（边框+四周留白），文档原点
        # 就画在 viewport 原点。实测 cursorRect / blockBoundingRect 与像素完全吻合：
        #   preview坐标 = 文档坐标 - 滚动值 + viewport在preview里的位置(vp_pos)
        # 不能再叠加 viewportMargins，否则悬浮层会整体向右/下偏移（左缘错开约24px、
        # 顶部下移约18px），导致悬浮文字与段落文字不对齐。
        sb_v = self.preview.verticalScrollBar().value()
        sb_h = self.preview.horizontalScrollBar().value()
        vp_pos = self.preview.viewport().pos()

        layout = doc.documentLayout()
        block_rect = layout.blockBoundingRect(block)
        # 当前块由 _render_editing_line 生成，占位段第一行文字顶线 == 块矩形顶。
        # 悬浮层内部（documentMargin/帧/边距均 0）第一行也顶到控件 y=0，两者同高
        # 同宽换行，因此把悬浮层顶对齐块顶即可让逐行文字与占位段逐像素重合。
        y0 = int(round(block_rect.top())) - sb_v
        x0 = -sb_h

        # 换行宽度必须与预览完全一致，悬浮层文字才可能与占位段逐行对齐。
        text_width = float(doc.textWidth())
        if text_width <= 1.0:
            text_width = max(120.0, float(self.preview.viewport().width() - x0))
        width = max(120, int(text_width))

        # 下一段的第一行文字顶线作为下边界，防止悬浮层盖住它下面的内容。
        limit_y = None
        next_block = block.next()
        if next_block.isValid():
            next_rect = layout.blockBoundingRect(next_block)
            limit_y = int(round(next_rect.top())) - sb_v

        # 高度取占位段文字块高度：占位块已由 _sync_editing_placeholder 同步为最新
        # 源码，能反映当前换行数；预览与悬浮层用同一字体/换行宽度，行高一致。
        # +2 容差兜底两个排版引擎的亚像素取整；限界保证不越入下一段文字区。
        height = int(round(block_rect.height())) + 2
        if limit_y is not None:
            available = limit_y - y0 - 1
            if available > 0 and available < height:
                height = max(1, available)
        height = max(height, 22)

        editor = self.line_editor
        editor.setGeometry(
            QRect(x0 + vp_pos.x(), y0 + vp_pos.y(), width, max(1, height))
        )
        editor.show()
        editor.raise_()

    def _switch_to_line(self, line_index: int, *, focus: bool = True) -> None:
        line_index = max(0, min(line_index, len(self._lines) - 1))
        self._current_line_index = line_index

        self.line_editor.blockSignals(True)
        self.line_editor.setPlainText(self._lines[self._current_line_index])
        self._apply_editor_fonts()
        self.line_editor.blockSignals(False)

        cursor = self.line_editor.textCursor()
        cursor.setPosition(len(self._lines[self._current_line_index]))
        self.line_editor.setTextCursor(cursor)

        self._refresh_preview()

        if focus:
            self.line_editor.setFocus()

    def _on_preview_line_clicked(self, line_index: int) -> None:
        self._switch_to_line(line_index, focus=True)

    # ------------------------------------------------------------------
    # 行编辑逻辑
    # ------------------------------------------------------------------

    def _on_line_editor_text_changed(self) -> None:
        if self._is_loading or self._normalizing_lines:
            return

        content = self.line_editor.toPlainText()
        # 悬浮编辑器里不应出现真正的换行：粘贴多行文本时按行拆分，
        # 否则当前“行”会内嵌 \n，导致后续行错位、回车产生多余空行。
        if "\n" in content:
            self._absorb_multiline_content(content)
            return

        self._lines[self._current_line_index] = content

        self._commit_line_model_change()

        # 输入会改变段落换行数：同步预览占位块并整篇重排，让后续行/滚动范围
        # 实时跟随，同时让悬浮层能按最新占位几何对齐（避免盖住下一段）。
        self._sync_editing_placeholder()
        self._ensure_current_line_visible()
        self._reposition_line_editor()

    def _insert_multiline_into_lines(self, text: str) -> None:
        """FloatingLineEditor 粘贴/拖入多行文本时的入口。

        悬浮编辑器是单行控件；这里把“插入到光标/选区”的多行文本拆成行模型
        级更新，避免把字面换行符写进 self._lines 或编辑控件。
        """
        editor = self.line_editor
        cursor = editor.textCursor()
        old_text = editor.toPlainText()
        sel_start = cursor.selectionStart()
        sel_end = cursor.selectionEnd()
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        combined = old_text[:sel_start] + normalized + old_text[sel_end:]
        caret = sel_start + len(normalized)
        self._apply_content_with_caret(combined, caret)

    def _apply_content_with_caret(self, content: str, caret: int) -> None:
        """把 content 作为“当前行所在的整段文本”应用（可能含多行）。

        若含换行：拆成行片段替换模型并切换悬浮层到目标片段；
        否则视为单行直接更新当前单元格。caret 是 content 内绝对下标。
        """
        if "\n" not in content:
            self._lines[self._current_line_index] = content
            self._commit_line_model_change()
            return
        segments = content.split("\n")
        target_segment, target_column = self._locate_caret(segments, caret)
        self._finish_multiline_insert(segments, target_segment, target_column)

    @staticmethod
    def _locate_caret(segments: list[str], caret: int) -> tuple[int, int]:
        """返回 caret 在按换行拆分后的片段中的 (行下标, 列下标)。"""
        offset = 0
        for index, segment in enumerate(segments):
            if caret <= offset + len(segment):
                return index, caret - offset
            offset += len(segment) + 1
        return len(segments) - 1, len(segments[-1])

    def _commit_line_model_change(self) -> None:
        """把行模型的最新内容同步到文档与上层信号。"""
        full_text = self._get_text_from_lines()
        self._document.set_text(full_text, mark_dirty=True)
        self._set_status_indicator(self._document.session_status)
        self.content_changed.emit(full_text)
        self.document_changed.emit(self._document)
        self.status_changed.emit(self._document.session_status)

    def _finish_multiline_insert(
        self,
        segments: list[str],
        target_segment: int,
        target_column: int,
    ) -> None:
        """把 self._lines 的当前行展开为 segments，并把悬浮层切到目标行。

        写入编辑控件的始终只有目标行的单行源码；真正的多行内容通过
        self._lines 完成，从而保证“逻辑行数 === 渲染块数”。
        """
        line_index = self._current_line_index
        self._lines[line_index : line_index + 1] = segments
        self._current_line_index = line_index + target_segment

        self._normalizing_lines = True
        try:
            self.line_editor.blockSignals(True)
            self.line_editor.setPlainText(segments[target_segment])
            self.line_editor.blockSignals(False)
        finally:
            self._normalizing_lines = False

        cursor = self.line_editor.textCursor()
        cursor.setPosition(min(target_column, len(segments[target_segment])))
        self.line_editor.setTextCursor(cursor)

        self._commit_line_model_change()
        self._refresh_preview()

    def _absorb_multiline_content(self, content: str) -> None:
        """兜底：编辑控件中万一混入换行（绕过粘贴拦截的路径）时再拆一次。"""
        caret = self.line_editor.textCursor().position()
        caret = max(0, min(caret, len(content)))
        self._apply_content_with_caret(content, caret)

    def _on_line_editor_cursor_changed(self) -> None:
        cursor = self.line_editor.textCursor()
        position_in_line = cursor.position()
        absolute = self._line_column_to_absolute_position(
            self._current_line_index,
            position_in_line,
        )
        self._document.update_cursor_position(absolute)
        self.cursor_position_changed.emit(absolute)

    def _split_current_line(self, position: int) -> None:
        current = self._lines[self._current_line_index]
        left = current[:position]
        right = current[position:]

        self._lines[self._current_line_index] = left
        self._lines.insert(self._current_line_index + 1, right)

        self._document.set_text(self._get_text_from_lines(), mark_dirty=True)
        self._switch_to_line(self._current_line_index + 1, focus=True)

    def _merge_with_previous_line(self) -> None:
        if self._current_line_index == 0:
            return

        prev_line = self._lines[self._current_line_index - 1]
        current_line = self._lines[self._current_line_index]
        new_line = prev_line + current_line

        self._lines[self._current_line_index - 1] = new_line
        del self._lines[self._current_line_index]

        self._document.set_text(self._get_text_from_lines(), mark_dirty=True)
        self._switch_to_line(self._current_line_index - 1, focus=True)

        cursor = self.line_editor.textCursor()
        cursor.setPosition(len(prev_line))
        self.line_editor.setTextCursor(cursor)

    def _merge_with_next_line(self) -> None:
        if self._current_line_index >= len(self._lines) - 1:
            return

        current_line = self._lines[self._current_line_index]
        next_line = self._lines[self._current_line_index + 1]
        self._lines[self._current_line_index] = current_line + next_line
        del self._lines[self._current_line_index + 1]

        self._document.set_text(self._get_text_from_lines(), mark_dirty=True)
        self._switch_to_line(self._current_line_index, focus=True)

        cursor = self.line_editor.textCursor()
        cursor.setPosition(len(current_line))
        self.line_editor.setTextCursor(cursor)

    def _move_to_previous_line(self) -> None:
        if self._current_line_index > 0:
            self._switch_to_line(self._current_line_index - 1, focus=True)

    def _move_to_next_line(self) -> None:
        if self._current_line_index < len(self._lines) - 1:
            self._switch_to_line(self._current_line_index + 1, focus=True)

    # ------------------------------------------------------------------
    # 标题 / 文档同步
    # ------------------------------------------------------------------

    def _on_title_edited(self, title: str) -> None:
        if self._is_loading:
            return

        self._document.set_title(title)
        self._set_status_indicator(self._document.session_status)

        self.title_changed.emit(title)
        self.document_changed.emit(self._document)
        self.status_changed.emit(self._document.session_status)

    def _absolute_position_to_line_column(self, absolute_pos: int) -> tuple[int, int]:
        text = self._get_text_from_lines()
        absolute_pos = max(0, min(absolute_pos, len(text)))

        lines = self._lines
        current = 0
        for i, line in enumerate(lines):
            line_len = len(line)
            if absolute_pos <= current + line_len:
                return i, absolute_pos - current
            current += line_len + 1

        return len(lines) - 1, len(lines[-1])

    def _line_column_to_absolute_position(self, line_index: int, column: int) -> int:
        line_index = max(0, min(line_index, len(self._lines) - 1))
        absolute = 0
        for i in range(line_index):
            absolute += len(self._lines[i]) + 1
        absolute += max(0, min(column, len(self._lines[line_index])))
        return absolute

    def _apply_document_to_view(self) -> None:
        self._is_loading = True
        try:
            self.title_edit.setText(self._document.title or "")
            self._set_status_indicator(self._document.session_status)

            self._set_lines_from_text(self._document.get_text())

            line_index, column = self._absolute_position_to_line_column(
                self._document.restore_cursor_position()
            )
            self._current_line_index = line_index

            self._switch_to_line(self._current_line_index, focus=False)

            cursor = self.line_editor.textCursor()
            cursor.setPosition(column)
            self.line_editor.setTextCursor(cursor)

            self.status_changed.emit(self._document.session_status)
        finally:
            self._is_loading = False

    # ------------------------------------------------------------------
    # 文档装载与创建
    # ------------------------------------------------------------------

    def get_document(self) -> MarkdownDocument:
        return self._document

    def set_document(self, document: MarkdownDocument) -> None:
        self._document = document
        self._apply_document_to_view()
        self.document_changed.emit(self._document)

    def new_note(
        self,
        *,
        note_id: str | None = None,
        title: str = "",
        file_path: str | None = None,
    ) -> None:
        self._document = MarkdownDocument.create_empty(
            note_id=note_id,
            title=title,
            file_path=file_path,
        )
        self._apply_document_to_view()
        self.document_changed.emit(self._document)

    def open_note(
        self,
        *,
        text: str,
        note_id: str | None = None,
        title: str | None = None,
        file_path: str | None = None,
        file_mtime: float | None = None,
        version: int | None = None,
        cursor_position: int | None = None,
    ) -> None:
        self._document.load_from_text(
            text=text,
            note_id=note_id,
            title=title,
            file_path=file_path,
            file_mtime=file_mtime,
            version=version,
            cursor_position=cursor_position,
        )
        self._apply_document_to_view()
        self.document_changed.emit(self._document)

    def reload_note(
        self,
        *,
        text: str,
        file_mtime: float | None = None,
        version: int | None = None,
    ) -> None:
        self._document.load_from_text(
            text=text,
            note_id=self._document.note_id,
            title=self._document.title,
            file_path=self._document.file_path,
            file_mtime=file_mtime,
            version=version if version is not None else self._document.version,
            cursor_position=self._document.cursor_position,
        )
        self._apply_document_to_view()
        self.document_changed.emit(self._document)

    def load_document(
        self,
        *,
        text: str,
        note_id: str | None = None,
        title: str | None = None,
        file_path: str | None = None,
        file_mtime: float | None = None,
        version: int | None = None,
    ) -> None:
        self.open_note(
            text=text,
            note_id=note_id,
            title=title,
            file_path=file_path,
            file_mtime=file_mtime,
            version=version,
            cursor_position=0,
        )

    def load_empty_document(
        self,
        *,
        note_id: str | None = None,
        title: str = "",
        file_path: str | None = None,
    ) -> None:
        self.new_note(note_id=note_id, title=title, file_path=file_path)

    # ------------------------------------------------------------------
    # 基础接口
    # ------------------------------------------------------------------

    def set_text(self, text: str) -> None:
        self._document.set_text(text, mark_dirty=False)
        self._apply_document_to_view()

    def get_text(self) -> str:
        return self._get_text_from_lines()

    def get_title(self) -> str:
        return self.title_edit.text().strip()

    def update_title(self, title: str) -> None:
        self._document.set_title(title or "")
        self._apply_document_to_view()
        self.document_changed.emit(self._document)

    def clear(self) -> None:
        self._document.clear()
        self._apply_document_to_view()
        self.document_changed.emit(self._document)

    def focus_editor(self) -> None:
        self.line_editor.setFocus()

    def insert_text_at_cursor(self, text: str) -> None:
        if not text:
            return
        if "\n" in text or "\r" in text:
            self._insert_multiline_into_lines(text)
            return
        cursor = self.line_editor.textCursor()
        cursor.insertText(text)
        self.line_editor.setTextCursor(cursor)

    def replace_selection(self, text: str) -> None:
        if "\n" in text or "\r" in text:
            self._insert_multiline_into_lines(text)
            return
        cursor = self.line_editor.textCursor()
        cursor.insertText(text)

    def get_cursor_position(self) -> int:
        return self._document.cursor_position

    def set_cursor_position(self, position: int) -> None:
        line_index, column = self._absolute_position_to_line_column(position)
        self._switch_to_line(line_index, focus=True)

        cursor = self.line_editor.textCursor()
        cursor.setPosition(column)
        self.line_editor.setTextCursor(cursor)

        self._document.update_cursor_position(position)
        self.cursor_position_changed.emit(position)

    def is_dirty(self) -> bool:
        return self._document.is_dirty

    def has_unsaved_changes(self) -> bool:
        return self._document.has_unsaved_changes()

    def set_read_only_mode(self, enabled: bool) -> None:
        self._read_only_mode = enabled
        self.line_editor.setReadOnly(enabled)
        self.title_edit.setReadOnly(enabled)

    # ------------------------------------------------------------------
    # 保存 / 打开 payload
    # ------------------------------------------------------------------

    def build_save_payload(self) -> dict:
        self._document.set_title(self.get_title())
        return self._document.to_save_payload()

    def build_open_payload(self) -> dict:
        self._document.set_title(self.get_title())
        return self._document.to_open_payload()

    def request_save(self) -> None:
        self.save_requested.emit(self.build_save_payload())

    def request_open(self) -> None:
        self.open_requested.emit(self.build_open_payload())

    def mark_saved(
        self,
        *,
        file_mtime: float | None = None,
        version: int | None = None,
    ) -> None:
        self._document.restore_after_save(file_mtime=file_mtime, version=version)
        self._set_status_indicator(self._document.session_status)
        self.status_changed.emit(self._document.session_status)
        self.document_changed.emit(self._document)

    def mark_save_failed(self) -> None:
        self._document.mark_save_failed()
        self._set_status_indicator(self._document.session_status)
        self.status_changed.emit(self._document.session_status)
        self.document_changed.emit(self._document)

    def mark_external_modified(self) -> None:
        self._document.mark_external_modified()
        self._set_status_indicator(self._document.session_status)
        self.status_changed.emit(self._document.session_status)
        self.document_changed.emit(self._document)

    def maybe_save_before_close(self) -> bool:
        if not self.has_unsaved_changes():
            return True

        result = QMessageBox.question(
            self,
            "未保存更改",
            "当前笔记有未保存内容，是否继续关闭？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------------
    # 扩展接口
    # ------------------------------------------------------------------

    def get_selected_text(self) -> str:
        return self.line_editor.textCursor().selectedText()

    def get_plain_text(self) -> str:
        return self._document.get_plain_text()

    def extract_headings(self):
        return self._document.extract_headings()

    def refresh_preview_now(self) -> None:
        self._refresh_preview()
