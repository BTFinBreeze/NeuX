"""Dialog for picking which workspace files should be indexed into the KB."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 1

KIND_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("markdown", "笔记（Markdown）", "md"),
    ("pdf", "PDF 文档", "pdf"),
    ("pptx", "PPT 演示文稿", "pptx"),
)


class _SelectAllCheckBox(QCheckBox):
    """Tri-state checkbox whose clicks always go between all and none.

    A partial state is only shown when some (but not all) files are checked;
    clicking it selects everything, and clicking a fully checked box clears it.
    """

    def nextCheckState(self) -> None:  # noqa: N802 - Qt override.
        if self.checkState() == Qt.CheckState.Checked:
            self.setCheckState(Qt.CheckState.Unchecked)
        else:
            self.setCheckState(Qt.CheckState.Checked)


class IndexFilePickerDialog(QDialog):
    """Present every indexable file grouped by type with a select-all header.

    The dialog returns the workspace-relative paths of the files the user
    checked. Files that stay unchecked are not indexed.
    """

    def __init__(
        self,
        candidates: list[dict[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("index_file_picker_dialog")
        self.setWindowTitle("选择需要建立索引的文件")
        self.setModal(True)
        self.resize(560, 520)
        self._candidates = list(candidates)
        self._leaf_items: list[QTreeWidgetItem] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        title = QLabel("选择需要建立索引的文件", self)
        title.setObjectName("section_label")
        layout.addWidget(title)

        hint = QLabel(
            "知识库将只对勾选的文件建立索引。\n"
            "笔记来自 notes/，PDF 与 PPT 来自 attachments/ 与 references/。",
            self,
        )
        hint.setObjectName("muted_label")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        select_all_layout = QHBoxLayout()
        self.select_all_checkbox = _SelectAllCheckBox("全选", self)
        self.select_all_checkbox.setTristate(True)
        self.select_all_checkbox.setCheckState(Qt.CheckState.Checked)
        self.count_label = QLabel("", self)
        self.count_label.setObjectName("muted_label")
        select_all_layout.addWidget(self.select_all_checkbox)
        select_all_layout.addStretch(1)
        select_all_layout.addWidget(self.count_label)
        layout.addLayout(select_all_layout)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setObjectName("index_file_picker_tree")
        self.tree.setIndentation(18)
        layout.addWidget(self.tree, 1)

        for kind, group_title, _badge in KIND_GROUPS:
            self._append_group(kind, group_title)

        self.tree.expandAll()

        buttons = QDialogButtonBox(self)
        ok_button = QPushButton("开始建立索引", buttons)
        ok_button.setDefault(True)
        cancel_button = QPushButton("取消", buttons)
        buttons.addButton(ok_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync_select_all_checkbox()
        self._update_count_label()
        self.select_all_checkbox.toggled.connect(self._on_select_all_toggled)
        self.tree.itemChanged.connect(self._on_item_changed)

    def _append_group(self, kind: str, group_title: str) -> None:
        group_items = [c for c in self._candidates if c.get("kind") == kind]
        if not group_items:
            return

        group = QTreeWidgetItem(self.tree)
        group.setText(0, f"{group_title}（{len(group_items)}）")
        group.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = group.font(0)
        font.setBold(True)
        group.setFont(0, font)

        for candidate in sorted(
            group_items,
            key=lambda item: str(item.get("title") or "").lower(),
        ):
            path = str(candidate.get("path") or "")
            title = str(candidate.get("title") or path)
            item = QTreeWidgetItem(group)
            item.setText(0, title)
            item.setToolTip(0, path)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setData(0, PATH_ROLE, path)
            self._leaf_items.append(item)

    def _leaf_paths(self) -> list[str]:
        return [item.data(0, PATH_ROLE) for item in self._leaf_items]

    def _checked_paths(self) -> list[str]:
        return [
            path
            for path, item in zip(self._leaf_paths(), self._leaf_items)
            if item.checkState(0) == Qt.CheckState.Checked
        ]

    def _all_checked(self) -> bool:
        return bool(self._leaf_items) and all(
            item.checkState(0) == Qt.CheckState.Checked for item in self._leaf_items
        )

    def _none_checked(self) -> bool:
        return not any(
            item.checkState(0) == Qt.CheckState.Checked for item in self._leaf_items
        )

    def _sync_select_all_checkbox(self) -> None:
        if self._all_checked():
            state = Qt.CheckState.Checked
        elif self._none_checked():
            state = Qt.CheckState.Unchecked
        else:
            state = Qt.CheckState.PartiallyChecked
        with QSignalBlocker(self.select_all_checkbox):
            self.select_all_checkbox.setCheckState(state)
        self._update_count_label()

    def _update_count_label(self) -> None:
        checked = len(self._checked_paths())
        total = len(self._leaf_items)
        self.count_label.setText(f"已选择 {checked} / {total} 个文件")

    def _on_select_all_toggled(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item in self._leaf_items:
            item.setCheckState(0, state)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if item in self._leaf_items:
            self._sync_select_all_checkbox()

    def selected_paths(self) -> list[str]:
        """Return workspace-relative paths of the checked files."""
        return self._checked_paths()
