from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget


def create_action(
    parent: QWidget,
    text: str,
    *,
    shortcut: str | None = None,
    status_tip: str = "",
    checkable: bool = False,
    checked: bool = False,
) -> QAction:
    action = QAction(text, parent)
    if shortcut:
        action.setShortcut(shortcut)
    if status_tip:
        action.setStatusTip(status_tip)
        action.setToolTip(status_tip)
    action.setCheckable(checkable)
    action.setChecked(checked)
    return action


@dataclass(slots=True)
class AgniActionSet:
    new_note: QAction
    open_workspace: QAction
    save_note: QAction
    delete_note: QAction
    open_pdf: QAction
    open_ppt: QAction
    previous_pdf_page: QAction
    next_pdf_page: QAction
    zoom_in_pdf: QAction
    zoom_out_pdf: QAction
    fit_pdf_width: QAction
    insert_pdf_excerpt: QAction
    insert_pdf_citation: QAction
    command_palette: QAction
    focus_search: QAction
    toggle_notes: QAction
    toggle_search: QAction
    toggle_outline: QAction
    toggle_kb: QAction
    toggle_main_toolbar: QAction
    refresh_workspace: QAction
    about: QAction

    @classmethod
    def build(cls, parent: QWidget) -> "AgniActionSet":
        return cls(
            new_note=create_action(
                parent,
                "新建笔记",
                shortcut="Ctrl+N",
                status_tip="创建一篇新的 Markdown 笔记",
            ),
            open_workspace=create_action(
                parent,
                "打开工作区",
                shortcut="Ctrl+O",
                status_tip="选择一个 NeuX 工作区目录",
            ),
            save_note=create_action(
                parent,
                "保存",
                shortcut="Ctrl+S",
                status_tip="保存当前笔记",
            ),
            delete_note=create_action(
                parent,
                "删除笔记",
                shortcut="Delete",
                status_tip="删除当前笔记",
            ),
            open_pdf=create_action(
                parent,
                "打开 PDF",
                shortcut="Ctrl+Shift+O",
                status_tip="从当前工作区选择并打开 PDF",
            ),
            open_ppt=create_action(
                parent,
                "打开 PPT",
                shortcut="Ctrl+Shift+P",
                status_tip="从当前工作区选择并打开 PPT (.pptx) 演示文稿",
            ),
            previous_pdf_page=create_action(
                parent,
                "上一页",
                shortcut="Alt+Left",
                status_tip="跳转到 PDF / PPT 上一页",
            ),
            next_pdf_page=create_action(
                parent,
                "下一页",
                shortcut="Alt+Right",
                status_tip="跳转到 PDF / PPT 下一页",
            ),
            zoom_in_pdf=create_action(
                parent,
                "放大",
                shortcut="Ctrl++",
                status_tip="放大当前页面",
            ),
            zoom_out_pdf=create_action(
                parent,
                "缩小",
                shortcut="Ctrl+-",
                status_tip="缩小当前页面",
            ),
            fit_pdf_width=create_action(
                parent,
                "适宽",
                status_tip="将当前页面适配窗口宽度",
            ),
            insert_pdf_excerpt=create_action(
                parent,
                "摘录到笔记",
                status_tip="将当前选区作为 Markdown 摘录插入笔记",
            ),
            insert_pdf_citation=create_action(
                parent,
                "插入引用",
                status_tip="向当前笔记插入文献引用占位",
            ),
            command_palette=create_action(
                parent,
                "命令面板",
                shortcut="Ctrl+K",
                status_tip="打开常用操作入口",
            ),
            focus_search=create_action(
                parent,
                "搜索",
                shortcut="Ctrl+F",
                status_tip="聚焦全局搜索面板",
            ),
            toggle_notes=create_action(
                parent,
                "资源库",
                status_tip="显示或隐藏左侧资源面板",
                checkable=True,
                checked=True,
            ),
            toggle_search=create_action(
                parent,
                "搜索与反链",
                status_tip="显示或隐藏搜索与反向链接面板",
                checkable=True,
                checked=True,
            ),
            toggle_outline=create_action(
                parent,
                "文档导航",
                status_tip="显示或隐藏大纲与 PDF 面板",
                checkable=True,
                checked=True,
            ),
            toggle_kb=create_action(
                parent,
                "本地知识库问答",
                status_tip="显示或隐藏本地知识库问答面板",
                checkable=True,
                checked=True,
            ),
            toggle_main_toolbar=create_action(
                parent,
                "收起工具栏",
                shortcut="Ctrl+Shift+T",
                status_tip="折叠或展开顶部主工具栏",
                checkable=True,
                checked=True,
            ),
            refresh_workspace=create_action(
                parent,
                "刷新工作区",
                shortcut="F5",
                status_tip="重新扫描笔记、文献与附件",
            ),
            about=create_action(
                parent,
                "关于 NeuX",
                status_tip="查看当前工作台说明",
            ),
        )


LIGHT_THEME = {
    "app_bg": "#F5F7FA",
    "window_bg": "#FFFFFF",
    "panel_bg": "#FFFFFF",
    "panel_subtle": "#F8FAFC",
    "canvas_bg": "#FBFCFE",
    "hover_bg": "#F3F6FA",
    "active_bg": "#EAF2FF",
    "selected_bg": "#E8F1FF",
    "border_light": "#E6EAF0",
    "border_normal": "#D9E1EC",
    "border_strong": "#CBD5E1",
    "border_focus": "#2563EB",
    "text_primary": "#111827",
    "text_secondary": "#374151",
    "text_muted": "#6B7280",
    "text_disabled": "#9CA3AF",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "primary_soft": "#EFF6FF",
    "info": "#0EA5E9",
    "success": "#22C55E",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "danger_text": "#DC2626",
    "danger_soft": "#FFF1F2",
    "purple": "#8B5CF6",
    "teal": "#14B8A6",
}


def build_app_stylesheet() -> str:
    t = LIGHT_THEME
    icon_root = Path(__file__).resolve().parent / "assets"
    tab_left_arrow = (icon_root / "tab_scroll_left.svg").as_posix()
    tab_right_arrow = (icon_root / "tab_scroll_right.svg").as_posix()
    return f"""
    QMainWindow#agni_main_window {{
        background: {t["app_bg"]};
    }}

    QWidget {{
        color: {t["text_primary"]};
        font-family: "Microsoft YaHei UI", "Segoe UI", Arial;
        font-size: 13px;
    }}

    QWidget#graph_cover_page {{
        background: {t["app_bg"]};
    }}

    QLabel#cover_title {{
        color: {t["text_primary"]};
        font-size: 30px;
        font-weight: 700;
    }}

    QLabel#cover_subtitle {{
        color: {t["text_secondary"]};
        font-size: 14px;
    }}

    QLabel#cover_hint {{
        color: {t["text_muted"]};
        font-size: 12px;
        padding: 2px 0 0 1px;
    }}

    QPushButton#cover_primary_button,
    QPushButton#cover_secondary_button,
    QPushButton#cover_danger_button {{
        min-height: 36px;
        min-width: 132px;
        max-width: 176px;
        padding: 0 18px;
        border-radius: 8px;
        font-weight: 600;
    }}

    QPushButton#cover_primary_button {{
        background: {t["primary"]};
        border: 1px solid {t["primary"]};
        color: #FFFFFF;
    }}

    QPushButton#cover_primary_button:hover {{
        background: {t["primary_hover"]};
        border-color: {t["primary_hover"]};
    }}

    QPushButton#cover_secondary_button {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_normal"]};
        color: {t["text_primary"]};
    }}

    QPushButton#cover_secondary_button:hover {{
        background: {t["hover_bg"]};
        border-color: {t["border_strong"]};
    }}

    QPushButton#cover_danger_button {{
        background: {t["window_bg"]};
        border: 1px solid #F3A6A6;
        color: {t["danger_text"]};
    }}

    QPushButton#cover_danger_button:hover {{
        background: {t["danger_soft"]};
        border-color: {t["danger"]};
    }}

    QWidget#graph_cover_page QGraphicsView#knowledge_graph_view {{
        background: #111827;
        border: 1px solid {t["border_normal"]};
        border-radius: 10px;
        padding: 0;
    }}

    QMenuBar {{
        background: {t["window_bg"]};
        color: {t["text_secondary"]};
        padding: 4px 8px;
        border-bottom: 1px solid {t["border_light"]};
    }}

    QMenuBar::item {{
        padding: 6px 10px;
        border-radius: 6px;
    }}

    QMenuBar::item:selected {{
        background: {t["primary_soft"]};
        color: {t["primary"]};
    }}

    QMenu {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_normal"]};
        padding: 6px;
    }}

    QMenu::item {{
        padding: 7px 26px 7px 12px;
        border-radius: 5px;
    }}

    QMenu::item:selected {{
        background: {t["primary_soft"]};
        color: {t["primary"]};
    }}

    QToolBar {{
        background: {t["window_bg"]};
        border: 0;
        border-bottom: 1px solid {t["border_light"]};
        spacing: 8px;
        padding: 8px 10px;
    }}

    QToolButton {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_normal"]};
        color: {t["text_secondary"]};
        padding: 7px 10px;
        border-radius: 7px;
    }}

    QToolButton:hover {{
        background: {t["hover_bg"]};
        border-color: {t["border_focus"]};
        color: {t["text_primary"]};
    }}

    QToolButton:pressed,
    QPushButton:pressed {{
        background: {t["active_bg"]};
    }}

    QToolButton:disabled,
    QPushButton:disabled {{
        background: {t["panel_subtle"]};
        border-color: {t["border_light"]};
        color: {t["text_disabled"]};
    }}

    QToolBar::separator {{
        background: {t["border_light"]};
        width: 1px;
        margin: 7px 6px;
    }}

    QStatusBar {{
        background: {t["window_bg"]};
        color: {t["text_muted"]};
        border-top: 1px solid {t["border_light"]};
    }}

    QDialog,
    QMessageBox,
    QInputDialog {{
        background: {t["window_bg"]};
        color: {t["text_primary"]};
    }}

    QDialog#command_palette_dialog {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_normal"]};
        border-radius: 10px;
    }}

    QDialog QLabel,
    QMessageBox QLabel,
    QInputDialog QLabel {{
        color: {t["text_primary"]};
        background: transparent;
    }}

    QDialogButtonBox {{
        background: transparent;
        padding-top: 8px;
    }}

    QMessageBox QPushButton,
    QInputDialog QPushButton,
    QDialogButtonBox QPushButton {{
        min-width: 74px;
        min-height: 30px;
    }}

    QDockWidget {{
        background: {t["app_bg"]};
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }}

    QDockWidget::title {{
        background: {t["panel_subtle"]};
        color: {t["text_secondary"]};
        padding: 8px 10px;
        border-bottom: 1px solid {t["border_light"]};
    }}

    QFrame#dock_surface,
    QWidget#dock_surface {{
        background: {t["panel_bg"]};
        border: 1px solid {t["border_light"]};
        border-radius: 8px;
    }}

    QTabWidget::pane {{
        border: 1px solid {t["border_light"]};
        border-radius: 8px;
        background: {t["panel_bg"]};
        top: -1px;
    }}

    QTabBar::tab {{
        background: {t["panel_subtle"]};
        color: {t["text_muted"]};
        min-height: 36px;
        padding: 7px 30px 7px 12px;
        border: 1px solid {t["border_light"]};
        border-bottom: 0;
        border-top-left-radius: 7px;
        border-top-right-radius: 7px;
        margin-right: 3px;
    }}

    QTabBar::tab:selected {{
        background: {t["window_bg"]};
        color: {t["primary"]};
        border-color: {t["border_normal"]};
        border-bottom: 2px solid {t["primary"]};
    }}

    QTabBar::scroller {{
        width: 58px;
    }}

    QTabBar QToolButton {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_normal"]};
        border-radius: 8px;
        min-width: 26px;
        max-width: 26px;
        min-height: 50px;
        max-height: 50px;
        margin: 0 2px;
        padding: 0;
    }}

    QTabBar QToolButton:hover {{
        background: {t["hover_bg"]};
        border-color: {t["border_strong"]};
    }}

    QTabBar QToolButton::left-arrow {{
        image: url("{tab_left_arrow}");
        width: 12px;
        height: 12px;
    }}

    QTabBar QToolButton::right-arrow {{
        image: url("{tab_right_arrow}");
        width: 12px;
        height: 12px;
    }}

    QToolButton#tab_close_button {{
        background: transparent;
        border: 0;
        color: {t["text_secondary"]};
        font-size: 18px;
        font-weight: 400;
        min-width: 24px;
        max-width: 24px;
        min-height: 24px;
        max-height: 24px;
        padding: 0;
        margin: 0 7px 0 0;
        border-radius: 6px;
    }}

    QToolButton#tab_close_button:hover {{
        background: #E5E7EB;
        color: {t["text_primary"]};
    }}

    QLineEdit,
    QComboBox,
    QSpinBox#pdf_page_spin,
    QPlainTextEdit,
    QTextEdit {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_normal"]};
        color: {t["text_primary"]};
        border-radius: 7px;
        padding: 8px;
        selection-background-color: #BFDBFE;
        selection-color: {t["text_primary"]};
    }}

    QLineEdit:disabled,
    QComboBox:disabled,
    QPlainTextEdit:disabled,
    QTextEdit:disabled {{
        background: {t["panel_subtle"]};
        color: {t["text_disabled"]};
    }}

    QSpinBox#pdf_page_spin {{
        min-height: 32px;
        padding: 4px 6px;
        font-weight: 600;
    }}

    QComboBox {{
        min-height: 32px;
        padding: 4px 8px;
    }}

    QComboBox::drop-down {{
        width: 28px;
        border: 0;
    }}

    QComboBox QAbstractItemView,
    QInputDialog QComboBox QAbstractItemView {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_normal"]};
        color: {t["text_primary"]};
        selection-background-color: {t["primary_soft"]};
        selection-color: {t["primary"]};
        outline: 0;
    }}

    QLineEdit:focus,
    QComboBox:focus,
    QSpinBox#pdf_page_spin:focus,
    QPlainTextEdit:focus,
    QTextEdit:focus {{
        border-color: {t["border_focus"]};
    }}

    QListWidget,
    QTreeWidget,
    QGraphicsView#knowledge_graph_view {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_light"]};
        border-radius: 7px;
        padding: 4px;
        outline: 0;
    }}

    QListWidget::item,
    QTreeWidget::item {{
        min-height: 30px;
        padding: 6px 8px;
        border-radius: 5px;
        color: {t["text_secondary"]};
    }}

    QListWidget::item:selected,
    QTreeWidget::item:selected {{
        background: {t["selected_bg"]};
        border-left: 2px solid {t["primary"]};
        color: {t["primary"]};
    }}

    QListWidget::item:hover,
    QTreeWidget::item:hover {{
        background: {t["hover_bg"]};
    }}

    QPushButton {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_normal"]};
        color: {t["text_primary"]};
        min-height: 32px;
        padding: 6px 14px;
        border-radius: 7px;
    }}

    QPushButton:hover {{
        background: {t["hover_bg"]};
        border-color: {t["border_focus"]};
    }}

    QPushButton#destructive_button {{
        background: {t["window_bg"]};
        border-color: #F3A6A6;
        color: {t["danger_text"]};
    }}

    QPushButton#destructive_button:hover {{
        background: {t["danger_soft"]};
        border-color: {t["danger"]};
    }}

    QLabel#section_label,
    QLabel#note_editor_title_label {{
        color: {t["text_primary"]};
        font-weight: 600;
    }}

    QLabel#knowledge_dashboard,
    QLabel#inspector_label,
    QLabel#pdf_preview_surface {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_light"]};
        border-radius: 8px;
        color: {t["text_secondary"]};
        line-height: 1.5;
    }}

    QLabel#muted_label {{
        color: {t["text_muted"]};
    }}

    QListWidget#pdf_thumbnail_list,
    QTextEdit#pdf_selection_box {{
        background: {t["window_bg"]};
        border: 1px solid {t["border_light"]};
        border-radius: 8px;
    }}

    QWidget#pdf_viewer_widget,
    QWidget#pdf_inspector_panel {{
        background: {t["panel_bg"]};
    }}

    QDialog QLabel#section_label {{
        color: {t["text_primary"]};
        font-size: 15px;
    }}

    QSplitter::handle {{
        background: {t["border_light"]};
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 2px;
    }}

    QScrollBar::handle:vertical,
    QScrollBar::handle:horizontal {{
        background: {t["border_strong"]};
        border-radius: 4px;
        min-height: 28px;
        min-width: 28px;
    }}

    QScrollBar::handle:vertical:hover,
    QScrollBar::handle:horizontal:hover {{
        background: #94A3B8;
    }}

    QScrollBar::add-line,
    QScrollBar::sub-line,
    QScrollBar::add-page,
    QScrollBar::sub-page {{
        background: transparent;
        border: 0;
        width: 0;
        height: 0;
    }}
    """
