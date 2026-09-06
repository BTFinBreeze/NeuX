"""PPT (.pptx) reader built on top of the PDF viewer.

Slides are rendered as a PDF through a headless LibreOffice conversion, then
reused by the PDF viewer pipeline so users get the same reading/excerpt UX as
PDFs: page list, zoom, drag-to-select text and "摘录到笔记" / "插入引用".
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem, QWidget

from app.services.ppt_service import convert_pptx_to_pdf
from app.ui.widgets.pdf_viewer_widget import PdfViewerWidget


class PptViewerWidget(PdfViewerWidget):
    """Renders each PPT slide like a PDF page with excerpt/citation actions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title_label.setText("PPT 阅读器")
        self.highlight_button.hide()  # PPT 不保存批注，只做摘录与引用
        self._pptx_path: Path | None = None

    # -- Loading -----------------------------------------------------------

    def load_pptx(
        self,
        pptx_path: str | Path,
        *,
        reference_key: str = "",
        cache_dir: str | Path | None = None,
    ) -> None:
        path = Path(pptx_path).expanduser().resolve()
        cache = Path(cache_dir) if cache_dir is not None else self._default_cache_dir(path)

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            converted_pdf = convert_pptx_to_pdf(path, cache)
        except Exception as error:
            self._show_render_error(path, str(error))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self._pptx_path = path
        self._open_converted_pdf(converted_pdf, source_path=path, reference_key=reference_key)

    def _open_converted_pdf(
        self,
        converted_pdf: Path,
        *,
        source_path: Path,
        reference_key: str,
    ) -> None:
        super().load_pdf(converted_pdf, reference_key=reference_key)
        if self.pdf_item is not None:
            self.pdf_item.title = source_path.name
        self.title_label.setText(source_path.name)
        self.path_label.setText(str(source_path))
        self._metadata_title = source_path.name
        self._metadata_relative_path = source_path.name
        self._metadata_file_size = source_path.stat().st_size if source_path.exists() else 0
        self._update_pdf_state(self._build_document_info_text())
        if self.pdf_document is not None:
            # 幻灯片默认按视口宽度缩放，便于逐张阅读；待控件完成布局后再执行。
            QTimer.singleShot(0, self._fit_to_viewport_width)

    def _fit_to_viewport_width(self) -> None:
        if self.pdf_document is None:
            return
        try:
            self.fit_width()
        except Exception:
            self.zoom_factor = 1.0
            self._render_current_page()

    def _default_cache_dir(self, pptx_path: Path) -> Path:
        parent_name = pptx_path.parent.name.lower()
        if parent_name in {"attachments", "references"}:
            return pptx_path.parent.parent / ".agni" / "ppt_cache"
        return pptx_path.parent / ".ppt_cache"

    # -- PPT wording -------------------------------------------------------

    def _set_empty_state(self) -> None:
        self.page_image_label.setText("从左侧文献列表或“打开 PPT”选择演示文稿。")
        self._sync_page_controls()
        self._update_pdf_state("尚未打开 PPT。")

    def _populate_thumbnails(self) -> None:
        self.thumbnail_list.clear()
        for page_number in range(1, self.page_count + 1):
            item = QListWidgetItem(f"幻灯片 {page_number}")
            item.setData(Qt.ItemDataRole.UserRole, page_number)
            self.thumbnail_list.addItem(item)

    def _build_document_info_text(
        self,
        *,
        title: str | None = None,
        relative_path: str = "",
        file_size: int = 0,
        page_count: object | None = None,
    ) -> str:
        item_title = title or (self.pdf_item.title if self.pdf_item is not None else self.title_label.text())
        if not title and self._metadata_title:
            item_title = self._metadata_title
        if not relative_path:
            relative_path = self._metadata_relative_path
        if not relative_path and self.pdf_item is not None:
            relative_path = self.pdf_item.path.name
        if not file_size:
            file_size = self._metadata_file_size
        effective_page_count = page_count if page_count is not None else self.page_count
        size_line = f"\n大小：{self._format_file_size(file_size)}" if file_size else ""
        return (
            "当前演示文稿已就绪。\n\n"
            f"文件：{item_title}\n"
            f"位置：{relative_path or '当前工作区附件'}{size_line}\n"
            f"幻灯片数：{effective_page_count}\n"
            f"当前：第 {self.current_page} 张\n\n"
            "可用操作：\n"
            "1. 在幻灯片上拖拽选择文字，选区会显示在下方编辑框。\n"
            "2. 编辑选区内容后，可摘录到当前笔记或插入引用。\n"
            "3. 使用“插入引用”可把当前幻灯片引用标记写入笔记。"
        )

    # -- 摘录 / 引用（复制 PDF 阅读器的摘抄流程） ---------------------------

    def request_excerpt_insert(self) -> None:
        text = self._selected_or_current_page_text()
        if not text:
            self._update_pdf_state("当前幻灯片没有可提取文字，无法摘录。")
            return
        key = self.reference_key_input.text().strip()
        citation = (
            f" [@{key}, 幻灯片 {self.current_page}]" if key else f" [幻灯片 {self.current_page}]"
        )
        excerpt_lines = "\n".join(f"> {line}" if line else ">" for line in text.splitlines())
        self.excerpt_insert_requested.emit(
            f"{excerpt_lines}\n>\n> Source: {self.title_label.text()}{citation}\n\n"
        )
        self._update_pdf_state("已把当前幻灯片摘录发送到 Markdown 笔记。")

    def request_citation_insert(self) -> None:
        key = self.reference_key_input.text().strip()
        if not key and self._pptx_path is not None:
            key = self._pptx_path.stem
        token = f"[@{key}, 幻灯片 {self.current_page}]" if key else f"[幻灯片 {self.current_page}]"
        self.citation_insert_requested.emit(token)
        self._update_pdf_state("已把引用标记发送到 Markdown 笔记。")

    def _emit_external_open_requested(self) -> None:
        if self._pptx_path is not None:
            self.external_open_requested.emit(self._pptx_path)
            return
        super()._emit_external_open_requested()
