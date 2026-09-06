from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.bootstrap.config import AppConfig
from app.controllers.citation_controller import CitationController
from app.controllers.knowledge_controller import KnowledgeController
from app.controllers.note_controller import NoteController
from app.controllers.pdf_controller import PdfController
from app.controllers.reference_controller import ReferenceController
from app.controllers.search_controller import SearchController
from app.controllers.workspace_controller import WorkspaceController
from app.services.citation_service import CitationService
from app.services.knowledge_model_service import KnowledgeModelService
from app.services.link_service import LinkService
from app.services.note_service import NoteService
from app.services.pdf_service import PdfService
from app.services.reference_service import ReferenceService
from app.services.search_service import SearchService
from app.services.workspace_service import WorkspaceService
from app.services.ppt_service import PPT_SUFFIXES
from app.ui.actions import AgniActionSet, build_app_stylesheet
from app.ui.dialogs.command_palette_dialog import CommandPaletteDialog
from app.ui.dialogs.workspace_picker_dialog import WorkspacePickerDialog
from app.ui.docks.note_list_dock import NoteListDock
from app.ui.docks.outline_dock import OutlineDock
from app.ui.docks.rag_kb_dock import RagKbDock
from app.ui.docks.search_dock import SearchDock
from app.ui.models.note_title_store import (
    remove_title_for_path,
    set_title_for_path,
    title_for_path,
)
from app.ui.models.satellite_parser import extract_markdown_satellites
from app.ui.models.ui_items import (
    CommandItem,
    KnowledgeGraphNode,
    KnowledgeObjectKind,
    KnowledgeSelection,
    SatelliteItem,
)
from app.ui.widgets.knowledge_graph_widget import KnowledgeGraphWidget, PLANET_DEFAULT_COLOR, SUN_COLOR
from app.ui.widgets.note_editor_widget import NoteEditorWidget
from app.ui.widgets.pdf_viewer_widget import PdfViewerWidget
from app.ui.widgets.ppt_viewer_widget import PptViewerWidget


class MainWindow(QMainWindow):
    def __init__(self, app_context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app_context = app_context
        self.workspace_root = Path(app_context.workspace_root)
        self.notes_dir = self.workspace_root / "notes"
        self.current_note_path: Path | None = None
        self.workspace_service = (
            getattr(app_context, "workspace_service", None)
            or getattr(getattr(app_context, "note_service", None), "workspace_service", None)
            or getattr(getattr(app_context, "reference_service", None), "workspace_service", None)
            or WorkspaceService(AppConfig())
        )
        self.workspace_controller = (
            getattr(app_context, "workspace_controller", None)
            or WorkspaceController(self.workspace_service)
        )
        self.note_service = getattr(app_context, "note_service", None) or NoteService(
            self.workspace_service
        )
        self.reference_service = getattr(app_context, "reference_service", None) or ReferenceService(
            self.workspace_service
        )
        self.link_service = getattr(app_context, "link_service", None) or LinkService(
            self.workspace_service
        )
        self.search_service = getattr(app_context, "search_service", None) or SearchService(
            self.workspace_service
        )
        self.knowledge_model_service = (
            getattr(app_context, "knowledge_model_service", None)
            or KnowledgeModelService(self.workspace_service)
        )
        self.pdf_service = getattr(app_context, "pdf_service", None) or PdfService(
            self.workspace_service,
            self.reference_service,
        )
        self.note_controller = getattr(app_context, "note_controller", None) or NoteController(
            self.note_service
        )
        self.reference_controller = (
            getattr(app_context, "reference_controller", None)
            or ReferenceController(self.reference_service)
        )
        self.search_controller = getattr(app_context, "search_controller", None) or SearchController(
            self.search_service,
            self.link_service,
        )
        self.knowledge_controller = (
            getattr(app_context, "knowledge_controller", None)
            or KnowledgeController(self.knowledge_model_service)
        )
        self.pdf_controller = getattr(app_context, "pdf_controller", None) or PdfController(
            self.pdf_service
        )
        self.citation_controller = getattr(app_context, "citation_controller", None) or CitationController(
            CitationService(
                self.workspace_service,
                self.note_service,
                self.pdf_service,
                self.reference_service,
            )
        )

        self.setObjectName("agni_main_window")
        self.setWindowTitle(f"NeuX - {self.workspace_root.name}")
        self.project_root = Path(__file__).resolve().parents[2]
        self.workspace_store_root = self.project_root
        self.resize(1360, 820)
        self.setMinimumSize(1080, 680)
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AnimatedDocks
        )

        self.actions = AgniActionSet.build(self)
        self.central_stack = QStackedWidget(self)
        self.cover_page = QWidget(self)
        self.cover_graph = KnowledgeGraphWidget(self, cover_mode=True)
        self.cover_storage_button = QPushButton("选择工作区目录", self)
        self.cover_new_workspace_button = QPushButton("新建工作区", self)
        self.cover_delete_workspace_button = QPushButton("删除工作区", self)
        self.cover_return_button = QPushButton("返回工作台", self)
        self.workspace_tabs = QTabWidget(self)
        self.editor = NoteEditorWidget(self)
        self.note_dock = NoteListDock(self)
        self.search_dock = SearchDock(self)
        self.outline_dock = OutlineDock(self)
        self.kb_dock = RagKbDock(self)
        self.main_toolbar: QToolBar | None = None
        self._active_right_sidebar = "outline"
        self.workspace_label = QLabel(self)
        self.status_label = QLabel("就绪", self)

        self._build_ui()
        self._bind_signals()
        self._install_app_shortcut_filter()
        self._load_workspace()
        self._open_initial_note()
        self.show_star_map_cover()

    def _build_ui(self) -> None:
        self.setStyleSheet(build_app_stylesheet())
        self.cover_page = self._build_cover_page()
        self.workspace_tabs.setObjectName("workspace_tabs")
        self.workspace_tabs.setTabsClosable(False)
        self.workspace_tabs.setMovable(True)
        self.workspace_tabs.addTab(self.editor, "未命名")
        self._refresh_tab_close_buttons()
        self.central_stack.addWidget(self.cover_page)
        self.central_stack.addWidget(self.workspace_tabs)
        self.setCentralWidget(self.central_stack)

        self._build_menu_bar()
        self._build_toolbar()
        self._build_docks()
        self._build_status_bar()

    def _build_cover_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("graph_cover_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(10)

        title = QLabel("NeuX 星图", page)
        title.setObjectName("cover_title")
        subtitle = QLabel("从工作区进入知识结构，用分类组织笔记、文献、主题和关联。", page)
        subtitle.setObjectName("cover_subtitle")
        hint = QLabel(
            "操作提示：左键拖拽移动结构或节点，按住左键并滚动鼠标滚轮缩放星图；双击资源进入编辑，右键打开管理菜单。",
            page,
        )
        hint.setObjectName("cover_hint")
        hint.setWordWrap(True)

        self.cover_storage_button.setObjectName("cover_secondary_button")
        self.cover_new_workspace_button.setObjectName("cover_primary_button")
        self.cover_delete_workspace_button.setObjectName("cover_danger_button")
        self.cover_return_button.setObjectName("cover_secondary_button")
        self.cover_storage_button.clicked.connect(self.choose_workspace_store_root)
        self.cover_new_workspace_button.clicked.connect(self.create_new_workspace)
        self.cover_delete_workspace_button.clicked.connect(self.delete_workspace_from_store)
        self.cover_return_button.clicked.connect(self.show_workbench)
        self.cover_return_button.hide()

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(12)
        button_layout.addWidget(self.cover_new_workspace_button)
        button_layout.addWidget(self.cover_storage_button)
        button_layout.addWidget(self.cover_delete_workspace_button)
        button_layout.addWidget(self.cover_return_button)
        button_layout.addStretch(1)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(button_layout)
        layout.addWidget(hint)
        layout.addWidget(self.cover_graph, 1)
        return page

    def _build_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.actions.new_note)
        file_menu.addAction(self.actions.open_workspace)
        file_menu.addAction(self.actions.save_note)
        file_menu.addAction(self.actions.delete_note)
        file_menu.addSeparator()
        file_menu.addAction(self.actions.refresh_workspace)

        view_menu = self.menuBar().addMenu("视图")
        view_menu.addAction(self.actions.toggle_notes)
        right_sidebar_menu = view_menu.addMenu("右侧边栏")
        right_sidebar_menu.addAction(self.actions.toggle_outline)
        right_sidebar_menu.addAction(self.actions.toggle_search)
        right_sidebar_menu.addAction(self.actions.toggle_kb)
        view_menu.addSeparator()
        view_menu.addAction(self.actions.toggle_main_toolbar)

        tools_menu = self.menuBar().addMenu("工具")
        tools_menu.addAction(self.actions.command_palette)
        tools_menu.addAction(self.actions.focus_search)

        pdf_menu = self.menuBar().addMenu("文档")
        pdf_menu.addAction(self.actions.open_pdf)
        pdf_menu.addAction(self.actions.open_ppt)
        pdf_menu.addSeparator()
        pdf_menu.addAction(self.actions.previous_pdf_page)
        pdf_menu.addAction(self.actions.next_pdf_page)
        pdf_menu.addAction(self.actions.zoom_in_pdf)
        pdf_menu.addAction(self.actions.zoom_out_pdf)
        pdf_menu.addAction(self.actions.fit_pdf_width)
        pdf_menu.addSeparator()
        pdf_menu.addAction(self.actions.insert_pdf_excerpt)
        pdf_menu.addAction(self.actions.insert_pdf_citation)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction(self.actions.about)
        self.menuBar().addAction(self.actions.toggle_main_toolbar)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏", self)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.addAction(self.actions.open_workspace)
        toolbar.addAction(self.actions.refresh_workspace)
        toolbar.addSeparator()
        toolbar.addAction(self.actions.new_note)
        toolbar.addAction(self.actions.save_note)
        toolbar.addAction(self.actions.delete_note)
        toolbar.addSeparator()
        toolbar.addAction(self.actions.open_pdf)
        toolbar.addAction(self.actions.open_ppt)
        toolbar.addSeparator()
        toolbar.addAction(self.actions.command_palette)
        toolbar.addSeparator()
        toolbar.addAction(self.actions.toggle_main_toolbar)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.main_toolbar = toolbar

    def _build_docks(self) -> None:
        self.setCorner(Qt.Corner.TopRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.setTabPosition(Qt.DockWidgetArea.RightDockWidgetArea, QTabWidget.TabPosition.North)
        self.search_dock.setMinimumWidth(320)
        self.outline_dock.setMinimumWidth(320)
        self.kb_dock.setMinimumWidth(320)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.note_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.search_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.outline_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.kb_dock)
        self.tabifyDockWidget(self.search_dock, self.outline_dock)
        self.tabifyDockWidget(self.outline_dock, self.kb_dock)
        self.outline_dock.raise_()
        self.resizeDocks([self.note_dock], [300], Qt.Orientation.Horizontal)
        self.resizeDocks(
            [self.note_dock, self.search_dock],
            [300, 360],
            Qt.Orientation.Horizontal,
        )

    def _build_status_bar(self) -> None:
        self.workspace_label.setText(f"工作区：{self.workspace_root}")
        self.statusBar().addWidget(self.workspace_label, 1)
        self.statusBar().addPermanentWidget(self.status_label)

    def show_star_map_cover(self, *, from_workbench: bool = False) -> None:
        self._sync_cover_graph()
        self.cover_return_button.setVisible(from_workbench)
        self.central_stack.setCurrentWidget(self.cover_page)
        self.menuBar().hide()
        if self.main_toolbar is not None:
            self.main_toolbar.hide()
        self.note_dock.hide()
        self.search_dock.hide()
        self.outline_dock.hide()
        self.kb_dock.hide()
        self.statusBar().hide()
        self.status_label.setText("星图封面")

    def show_workbench(self) -> None:
        self.central_stack.setCurrentWidget(self.workspace_tabs)
        self.menuBar().show()
        self._set_main_toolbar_expanded(self.actions.toggle_main_toolbar.isChecked())
        self.statusBar().show()
        self.note_dock.show()
        self.actions.toggle_notes.setChecked(True)
        self._show_right_sidebar(self._active_right_sidebar)
        self.status_label.setText("工作台")

    def _stabilize_right_docks(self, active: str | None = None) -> None:
        self.setTabPosition(Qt.DockWidgetArea.RightDockWidgetArea, QTabWidget.TabPosition.North)
        if active in {"search", "outline", "kb"}:
            self._show_right_sidebar(active)
            return

        if self.search_dock.isVisible() and self.outline_dock.isVisible():
            self._show_right_sidebar(self._active_right_sidebar)
        elif self.search_dock.isVisible():
            self._active_right_sidebar = "search"
            self._sync_right_sidebar_actions("search")
        elif self.outline_dock.isVisible():
            self._active_right_sidebar = "outline"
            self._sync_right_sidebar_actions("outline")
        elif self.kb_dock.isVisible():
            self._active_right_sidebar = "kb"
            self._sync_right_sidebar_actions("kb")
        else:
            self._sync_right_sidebar_actions(None)

    def _sync_right_sidebar_actions(self, active: str | None) -> None:
        blockers = [
            QSignalBlocker(self.actions.toggle_search),
            QSignalBlocker(self.actions.toggle_outline),
            QSignalBlocker(self.actions.toggle_kb),
        ]
        self.actions.toggle_search.setChecked(active == "search")
        self.actions.toggle_outline.setChecked(active == "outline")
        self.actions.toggle_kb.setChecked(active == "kb")
        del blockers

    def _show_right_sidebar(self, active: str, *, focus: bool = False) -> None:
        if active not in {"search", "outline", "kb"}:
            active = "outline"

        self._active_right_sidebar = active
        self.setTabPosition(Qt.DockWidgetArea.RightDockWidgetArea, QTabWidget.TabPosition.North)
        self.tabifyDockWidget(self.search_dock, self.outline_dock)
        self.tabifyDockWidget(self.outline_dock, self.kb_dock)

        if active == "search":
            self.outline_dock.hide()
            self.kb_dock.hide()
            self.search_dock.show()
            self.search_dock.raise_()
            if focus:
                self.search_dock.focus_search()
        elif active == "kb":
            self.search_dock.hide()
            self.outline_dock.hide()
            self.kb_dock.show()
            self.kb_dock.raise_()
            if focus:
                self.kb_dock.focus_default()
        else:
            self.search_dock.hide()
            self.kb_dock.hide()
            self.outline_dock.show()
            self.outline_dock.raise_()
            if focus:
                self.outline_dock.focus_default()

        self._sync_right_sidebar_actions(active)

    def _hide_right_sidebar(self) -> None:
        self.search_dock.hide()
        self.outline_dock.hide()
        self.kb_dock.hide()
        self._sync_right_sidebar_actions(None)

    def _handle_search_visibility_action(self, checked: bool) -> None:
        if checked:
            self._show_right_sidebar("search", focus=True)
        elif self._active_right_sidebar == "search":
            self._hide_right_sidebar()

    def _handle_outline_visibility_action(self, checked: bool) -> None:
        if checked:
            self._show_right_sidebar("outline", focus=True)
        elif self._active_right_sidebar == "outline":
            self._hide_right_sidebar()

    def _handle_kb_visibility_action(self, checked: bool) -> None:
        if checked:
            self._show_right_sidebar("kb", focus=True)
        elif self._active_right_sidebar == "kb":
            self._hide_right_sidebar()

    def _set_main_toolbar_expanded(self, expanded: bool) -> None:
        self.actions.toggle_main_toolbar.setText("收起工具栏" if expanded else "展开工具栏")
        if self.central_stack.currentWidget() is self.cover_page:
            if self.main_toolbar is not None:
                self.main_toolbar.hide()
            return

        if self.main_toolbar is not None:
            self.main_toolbar.setVisible(expanded)

    def _sync_cover_graph(self) -> None:
        systems = self._workspace_graph_systems()
        self.cover_graph.set_cover_graphs(systems)

    def _workspace_graph_systems(
        self,
    ) -> list[tuple[KnowledgeGraphNode, list[KnowledgeGraphNode], dict[str, list[KnowledgeGraphNode]]]]:
        systems: list[
            tuple[KnowledgeGraphNode, list[KnowledgeGraphNode], dict[str, list[KnowledgeGraphNode]]]
        ] = []
        for workspace_root in self._workspace_candidates():
            snapshot = self._graph_snapshot_for_workspace(workspace_root)
            if snapshot is not None:
                systems.append(snapshot)
        return systems

    def _workspace_candidates(self) -> list[Path]:
        store_root = self.workspace_store_root.expanduser().resolve()
        candidates: list[Path] = []
        if store_root.exists() and store_root.is_dir():
            candidates = [
                path.resolve()
                for path in sorted(store_root.iterdir(), key=lambda item: item.name.lower())
                if self._is_workspace_dir(path)
            ]

        current_root = self.workspace_root.resolve()
        if current_root.parent == store_root and current_root not in candidates and self._is_workspace_dir(current_root):
            candidates.append(current_root)
        return candidates

    def _is_workspace_dir(self, path: Path) -> bool:
        return path.is_dir() and (path / ".agni").is_dir() and (path / "notes").is_dir()

    def _graph_snapshot_for_workspace(
        self,
        workspace_root: Path,
    ) -> tuple[KnowledgeGraphNode, list[KnowledgeGraphNode], dict[str, list[KnowledgeGraphNode]]] | None:
        if workspace_root.resolve() == self.workspace_root.resolve():
            snapshot = self.note_dock.knowledge_graph_snapshot()
            if snapshot is not None:
                return snapshot

        result = self.knowledge_controller.get_knowledge_model(workspace_root)
        if not result.get("success"):
            return None
        data = result.get("data", {})
        galaxy_payload = data.get("galaxy") if isinstance(data, dict) else None
        if not isinstance(galaxy_payload, dict):
            return None

        galaxy_title = str(galaxy_payload.get("title") or workspace_root.name)
        galaxy_node = KnowledgeGraphNode(
            kind=KnowledgeObjectKind.GALAXY,
            title=galaxy_title,
            color=SUN_COLOR,
            path=workspace_root,
            description="NeuX 工作区",
            tags=("工作区",),
        )
        planets: list[KnowledgeGraphNode] = []
        stars_by_planet: dict[str, list[KnowledgeGraphNode]] = {}

        for planet_payload in tuple(galaxy_payload.get("planets") or ()):
            if not isinstance(planet_payload, dict):
                continue
            raw_planet = str(planet_payload.get("title") or "Unassigned")
            planet_title = self.note_dock.planet_display_title(raw_planet)
            if not planet_title.strip():
                continue
            planet_node = KnowledgeGraphNode(
                kind=KnowledgeObjectKind.PLANET,
                title=planet_title,
                color=self._planet_color(planet_title),
                description=str(planet_payload.get("description") or ""),
                planet=planet_title,
            )
            planets.append(planet_node)
            stars_by_planet.setdefault(planet_title, [])

            for star_payload in tuple(planet_payload.get("stars") or ()):
                if not isinstance(star_payload, dict):
                    continue
                object_kind = str(star_payload.get("object_kind") or "note")
                star_path_value = star_payload.get("path")
                star_path = Path(str(star_path_value)) if star_path_value else None
                if star_path is not None and not star_path.is_absolute():
                    star_path = workspace_root / star_path
                star_kind = (
                    KnowledgeObjectKind.STAR_REFERENCE
                    if object_kind == "reference"
                    else KnowledgeObjectKind.STAR_NOTE
                )
                if star_kind == KnowledgeObjectKind.STAR_NOTE and (
                    star_path is None or not star_path.exists() or not star_path.is_file()
                ):
                    continue
                if object_kind == "note" and star_path is not None:
                    star_title = title_for_path(workspace_root, star_path) or star_path.stem
                    try:
                        star_text = star_path.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        satellites = ()
                    else:
                        satellites = extract_markdown_satellites(star_text, star_title)
                else:
                    star_title = str(
                        star_payload.get("title")
                        or star_payload.get("object_key")
                        or "Untitled"
                    )
                    satellites = ()
                stars_by_planet[planet_title].append(
                    KnowledgeGraphNode(
                        kind=star_kind,
                        title=star_title,
                        color=self._planet_color(planet_title),
                        path=star_path,
                        description="文献或附件" if object_kind == "reference" else "Markdown 笔记",
                        planet=planet_title,
                        tags=tuple(str(tag) for tag in tuple(star_payload.get("tags") or ())),
                        satellites=satellites,
                    )
                )

        return galaxy_node, planets, stars_by_planet

    def _planet_color(self, planet_title: str) -> str:
        from app.ui.widgets.knowledge_graph_widget import PLANET_COLORS

        return PLANET_COLORS.get(planet_title, PLANET_DEFAULT_COLOR)

    def _bind_signals(self) -> None:
        self.actions.new_note.triggered.connect(self.create_new_note)
        self.actions.open_workspace.triggered.connect(self.show_workspace_picker)
        self.actions.save_note.triggered.connect(self.save_current_note)
        self.actions.delete_note.triggered.connect(self.delete_current_note)
        self.actions.open_pdf.triggered.connect(self.open_pdf_from_dialog)
        self.actions.open_ppt.triggered.connect(self.open_ppt_from_dialog)
        self.actions.previous_pdf_page.triggered.connect(self.go_previous_pdf_page)
        self.actions.next_pdf_page.triggered.connect(self.go_next_pdf_page)
        self.actions.zoom_in_pdf.triggered.connect(self.zoom_in_pdf)
        self.actions.zoom_out_pdf.triggered.connect(self.zoom_out_pdf)
        self.actions.fit_pdf_width.triggered.connect(self.fit_pdf_width)
        self.actions.insert_pdf_excerpt.triggered.connect(self.insert_pdf_excerpt)
        self.actions.insert_pdf_citation.triggered.connect(self.insert_pdf_citation)
        self.actions.command_palette.triggered.connect(self.show_command_palette)
        self.actions.focus_search.triggered.connect(self.focus_search_panel)
        self.actions.refresh_workspace.triggered.connect(self.refresh_workspace)
        self.actions.about.triggered.connect(self.show_about_dialog)
        self.actions.toggle_main_toolbar.toggled.connect(self._set_main_toolbar_expanded)

        self.actions.toggle_notes.toggled.connect(self.note_dock.setVisible)
        self.actions.toggle_search.triggered.connect(self._handle_search_visibility_action)
        self.actions.toggle_outline.triggered.connect(self._handle_outline_visibility_action)
        self.actions.toggle_kb.triggered.connect(self._handle_kb_visibility_action)
        self.note_dock.visibilityChanged.connect(self.actions.toggle_notes.setChecked)

        self.note_dock.note_selected.connect(self.open_note)
        self.note_dock.delete_note_requested.connect(self.delete_note)
        self.note_dock.reference_selected.connect(self._open_document_file)
        self.note_dock.knowledge_selected.connect(self.open_knowledge_object)
        self.cover_graph.node_selected.connect(self.open_knowledge_object)
        self.cover_graph.add_planet_requested.connect(self.add_planet_from_graph)
        self.cover_graph.delete_planet_requested.connect(self.delete_planet_from_graph)
        self.cover_graph.add_star_requested.connect(self.add_star_from_graph)
        self.cover_graph.delete_star_requested.connect(self.delete_star_from_graph)
        self.cover_graph.assign_to_planet_requested.connect(self.assign_graph_node_to_planet)
        self.note_dock.assign_to_planet_requested.connect(self.show_planet_assignment_placeholder)
        self.note_dock.star_map_requested.connect(lambda: self.show_star_map_cover(from_workbench=True))
        self.note_dock.knowledge_model_changed.connect(self._sync_cover_graph)
        self.note_dock.new_note_requested.connect(self.create_new_note)
        self.note_dock.refresh_requested.connect(self.refresh_workspace)
        self.search_dock.result_selected.connect(self._open_search_result)
        self.outline_dock.heading_selected.connect(self.goto_line)
        self.outline_dock.pdf_selected.connect(self.open_pdf_placeholder)
        self.outline_dock.annotation_delete_requested.connect(self.delete_pdf_annotation)

        self.workspace_tabs.currentChanged.connect(self._on_tab_changed)
        self.workspace_tabs.tabCloseRequested.connect(self._close_tab)
        self._connect_editor(self.editor)

    def _install_app_shortcut_filter(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if self._is_save_shortcut_event(event):
            if self.central_stack.currentWidget() is self.cover_page:
                return False
            if event.type() == QEvent.Type.ShortcutOverride:
                return True
            self.save_current_note()
            return True
        return super().eventFilter(watched, event)

    def _connect_editor(self, editor: NoteEditorWidget) -> None:
        self._disable_editor_local_save_shortcut(editor)
        editor.content_changed.connect(self._on_editor_content_changed)
        editor.document_changed.connect(lambda _document, target=editor: self._on_editor_document_changed(target))
        editor.cursor_position_changed.connect(lambda position, target=editor: self._on_editor_cursor_changed(target, position))
        editor.status_changed.connect(self._on_editor_status_changed)
        editor.title_changed.connect(lambda _title, target=editor: self._on_editor_title_changed(target))
        editor.save_requested.connect(lambda _payload: self.save_current_note())

    def _is_save_shortcut_event(self, event: QEvent) -> bool:
        if event.type() not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return False
        if QApplication.activeModalWidget() is not None:
            return False

        focus_widget = QApplication.focusWidget()
        if focus_widget is not None and focus_widget is not self and not self.isAncestorOf(focus_widget):
            return False

        if not event.matches(QKeySequence.StandardKey.Save):
            return False

        event.accept()
        return True

    def _disable_editor_local_save_shortcut(self, editor: NoteEditorWidget) -> None:
        save_sequence = QKeySequence("Ctrl+S")
        for action in editor.actions():
            shortcut = action.shortcut()
            if shortcut and shortcut.matches(save_sequence) != QKeySequence.SequenceMatch.NoMatch:
                action.setShortcut(QKeySequence())

    def _current_editor(self) -> NoteEditorWidget:
        widget = self.workspace_tabs.currentWidget()
        if isinstance(widget, NoteEditorWidget):
            return widget
        return self.editor

    def _current_pdf_viewer(self) -> PdfViewerWidget | None:
        widget = self.workspace_tabs.currentWidget()
        if isinstance(widget, PdfViewerWidget):
            return widget
        return None

    def _current_note_path(self) -> Path | None:
        editor = self._current_editor()
        file_path = editor.get_document().file_path
        return Path(file_path) if file_path else self.current_note_path

    def _add_note_tab(self, editor: NoteEditorWidget, title: str, note_path: Path | None) -> None:
        index = self.workspace_tabs.addTab(editor, title or "未命名")
        self.workspace_tabs.setTabToolTip(index, str(note_path) if note_path else "未保存笔记")
        self._refresh_tab_close_buttons()
        self.workspace_tabs.setCurrentIndex(index)
        self.editor = editor
        self.current_note_path = note_path
        self._connect_editor(editor)

    def _add_pdf_tab(self, viewer: PdfViewerWidget, pdf_path: Path) -> None:
        index = self.workspace_tabs.addTab(viewer, pdf_path.name)
        self.workspace_tabs.setTabToolTip(index, str(pdf_path))
        self._refresh_tab_close_buttons()
        self.workspace_tabs.setCurrentIndex(index)
        self._connect_pdf_viewer(viewer)

    def _refresh_tab_close_buttons(self) -> None:
        tab_bar = self.workspace_tabs.tabBar()
        for index in range(self.workspace_tabs.count()):
            tab_bar.setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)
            button = tab_bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if button is None or button.objectName() != "tab_close_button":
                close_button = QToolButton(tab_bar)
                close_button.setObjectName("tab_close_button")
                close_button.setText("×")
                close_button.clicked.connect(
                    lambda _checked=False, target=close_button: self._close_tab_from_button(target)
                )
                button = close_button
                tab_bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)
            button.setToolTip("")
            button.setFixedSize(24, 24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

    def _close_tab_from_button(self, button: QWidget) -> None:
        tab_bar = self.workspace_tabs.tabBar()
        for index in range(self.workspace_tabs.count()):
            if tab_bar.tabButton(index, QTabBar.ButtonPosition.RightSide) is button:
                self._close_tab(index)
                return

    def _connect_pdf_viewer(self, viewer: PdfViewerWidget) -> None:
        viewer.page_changed.connect(lambda page, target=viewer: self._on_pdf_page_changed(target, page))
        viewer.zoom_changed.connect(lambda zoom, target=viewer: self._on_pdf_zoom_changed(target, zoom))
        viewer.annotation_requested.connect(self._handle_pdf_annotation_request)
        viewer.excerpt_insert_requested.connect(self._insert_markdown_into_current_note)
        viewer.citation_insert_requested.connect(self._insert_markdown_into_current_note)
        viewer.external_open_requested.connect(self._open_external_file)

    def _find_note_tab(self, note_path: Path) -> int:
        expected = str(note_path.resolve())
        for index in range(self.workspace_tabs.count()):
            widget = self.workspace_tabs.widget(index)
            if not isinstance(widget, NoteEditorWidget):
                continue
            file_path = widget.get_document().file_path
            if file_path and str(Path(file_path).resolve()) == expected:
                return index
        return -1

    def _update_tab_title(self, editor: NoteEditorWidget | None = None) -> None:
        target = editor or self._current_editor()
        index = self.workspace_tabs.indexOf(target)
        if index < 0:
            return

        title = target.get_title() or target.get_document().get_title_from_content()
        marker = "*" if target.has_unsaved_changes() else ""
        self.workspace_tabs.setTabText(index, f"{marker}{title}")
        file_path = target.get_document().file_path
        self.workspace_tabs.setTabToolTip(index, file_path or "未保存笔记")
        self._refresh_tab_close_buttons()

    def _on_tab_changed(self, index: int) -> None:
        widget = self.workspace_tabs.widget(index)
        if isinstance(widget, NoteEditorWidget):
            self.editor = widget
            self.current_note_path = self._current_note_path()
            if self.current_note_path is not None:
                self.note_dock.select_note_path(self.current_note_path)
            self._refresh_document_panels()
        elif widget is not None:
            self.current_note_path = None
            if isinstance(widget, PptViewerWidget):
                self.status_label.setText("PPT 阅读器")
            elif isinstance(widget, PdfViewerWidget):
                self.status_label.setText("PDF 阅读器")
            else:
                self.status_label.setText("工作台页面")

    def _close_tab(self, index: int) -> None:
        widget = self.workspace_tabs.widget(index)
        if isinstance(widget, NoteEditorWidget) and not widget.maybe_save_before_close():
            return

        if self.workspace_tabs.count() == 1:
            if isinstance(widget, NoteEditorWidget):
                widget.load_empty_document(title="未命名笔记")
                self.current_note_path = None
                self._update_tab_title(widget)
                self._refresh_document_panels()
                self._refresh_tab_close_buttons()
            return

        self.workspace_tabs.removeTab(index)
        widget.deleteLater()
        self._refresh_tab_close_buttons()

    def _load_workspace(self) -> None:
        self.search_dock.set_search_controller(self.search_controller)
        self.outline_dock.set_reference_controller(self.reference_controller)
        self.note_dock.set_workspace(self.workspace_root)
        self.search_dock.set_workspace(self.workspace_root)
        self.outline_dock.set_workspace(self.workspace_root)
        self.kb_dock.set_workspace(self.workspace_root)
        self._sync_workspace_pdfs_to_references()
        self._refresh_knowledge_model_from_controller()
        self._sync_cover_graph()

    def _refresh_knowledge_model_from_controller(self) -> bool:
        result = self.knowledge_controller.get_knowledge_model(self.workspace_root)
        if not result.get("success"):
            self.status_label.setText(str(result.get("message") or "知识模型加载失败"))
            return False

        data = result.get("data", {})
        galaxy = data.get("galaxy") if isinstance(data, dict) else None
        if not isinstance(galaxy, dict):
            self.status_label.setText("知识模型数据格式异常")
            return False

        self.note_dock.set_knowledge_model(galaxy)
        return True

    def _open_initial_note(self) -> None:
        inbox = self.notes_dir / "Inbox.md"
        if inbox.exists():
            self.open_note(inbox)
            return

        self.editor.load_empty_document(title="未命名笔记")
        self._update_tab_title(self.editor)
        self._refresh_document_panels()

    def _open_search_result(self, payload: object) -> None:
        if isinstance(payload, dict):
            object_kind = str(payload.get("object_kind") or "")
            path_value = (
                payload.get("file_path")
                or payload.get("pdf_path")
                or payload.get("display_path")
                or payload.get("source_path")
                or payload.get("path")
            )
            if not path_value:
                self.status_label.setText("搜索结果缺少可打开路径")
                return

            path = self._workspace_relative_path(path_value)
            if object_kind == "reference" or path.suffix.lower() == ".pdf":
                self.open_pdf_placeholder(path)
            else:
                self.open_note(path)
            return

        self.open_note(payload)

    def open_note(self, note_path: object) -> None:
        self.show_workbench()
        path = Path(note_path)
        result = self.note_controller.open_note(self.workspace_root, path)
        if not result.get("success"):
            self._show_message(
                QMessageBox.Icon.Warning,
                "无法打开",
                str(result.get("message") or "无法打开所选 Markdown 文档。"),
            )
            return

        data = result.get("data", {})
        note = data.get("note", {}) if isinstance(data, dict) else {}
        if not isinstance(note, dict):
            self.status_label.setText("笔记数据格式异常")
            return

        path = Path(str(note.get("file_path") or path))
        text = str(note.get("markdown_content") or "")
        note_id = str(note.get("note_id") or path.stem)
        note_title = title_for_path(self.workspace_root, path) or path.stem
        file_mtime = float(note.get("file_mtime") or path.stat().st_mtime)

        existing_index = self._find_note_tab(path)
        if existing_index >= 0:
            self.workspace_tabs.setCurrentIndex(existing_index)
            self._refresh_document_panels()
            self.outline_dock.set_object_context(self._selection_for_note(path))
            self.status_label.setText(f"已切换: {path.name}")
            return

        editor = self._current_editor()
        if not (
            self.workspace_tabs.count() == 1
            and editor.get_document().file_path is None
            and not editor.get_text().strip()
        ):
            editor = NoteEditorWidget(self)

        editor.load_document(
            text=text,
            note_id=note_id,
            title=note_title,
            file_path=str(path),
            file_mtime=file_mtime,
        )
        if self.workspace_tabs.indexOf(editor) >= 0:
            self.current_note_path = path
            self.editor = editor
            self._update_tab_title(editor)
        else:
            self._add_note_tab(editor, note_title, path)
        self.note_dock.select_note_path(path)
        self.status_label.setText(f"已打开: {path.name}")
        self._refresh_document_panels()
        self.outline_dock.set_object_context(self._selection_for_note(path))

    def create_new_note(self) -> None:
        self.show_workbench()
        dialog = QInputDialog(self)
        dialog.setWindowTitle("新建笔记")
        dialog.setLabelText("笔记标题：")
        dialog.setTextValue("Untitled")
        dialog.setStyleSheet(build_app_stylesheet())
        dialog.resize(360, 160)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        title = dialog.textValue().strip() or "Untitled"
        safe_name = self._safe_filename(title)
        candidate = self.notes_dir / f"{safe_name}.md"
        counter = 2
        while candidate.exists():
            candidate = self.notes_dir / f"{safe_name}-{counter}.md"
            counter += 1

        editor = NoteEditorWidget(self)
        editor.load_empty_document(note_id=candidate.stem, title=title, file_path=str(candidate))
        editor.set_text(f"# {title}\n\n")
        self._add_note_tab(editor, title, candidate)
        editor.focus_editor()
        self.status_label.setText("新笔记已创建，保存后写入工作区")
        self._refresh_document_panels()

    def save_current_note(self) -> None:
        if not isinstance(self.workspace_tabs.currentWidget(), NoteEditorWidget):
            self.status_label.setText("当前标签页不是 Markdown 笔记")
            return

        editor = self._current_editor()
        payload = editor.build_save_payload()
        current_path = self._current_note_path()
        title = str(payload.get("title") or editor.get_document().get_title_from_content())
        if current_path is None:
            current_path = self.notes_dir / f"{self._safe_filename(title)}.md"

        old_path = current_path
        save_payload = dict(payload)
        save_payload["title"] = title
        save_payload["file_path"] = str(current_path)
        save_payload["markdown_content"] = str(
            save_payload.get("markdown_content", editor.get_text())
        )

        result = self.note_controller.save_note(self.workspace_root, save_payload)
        if not result.get("success"):
            editor.mark_save_failed()
            self._show_message(
                QMessageBox.Icon.Critical,
                "保存失败",
                str(result.get("message") or "后端保存笔记失败。"),
            )
            return

        data = result.get("data", {})
        note = data.get("note", {}) if isinstance(data, dict) else {}
        if not isinstance(note, dict):
            editor.mark_save_failed()
            self._show_message(QMessageBox.Icon.Critical, "保存失败", "后端返回的笔记数据格式异常。")
            return

        target_path = Path(str(note.get("file_path") or current_path))
        file_mtime = float(note.get("file_mtime") or target_path.stat().st_mtime)
        title = str(note.get("title") or title)
        try:
            if target_path.resolve() != old_path.resolve():
                remove_title_for_path(self.workspace_root, old_path)
            set_title_for_path(self.workspace_root, target_path, title)
        except OSError:
            pass

        self.current_note_path = target_path
        editor.get_document().bind_file_path(target_path)
        editor.mark_saved(file_mtime=file_mtime)
        self._update_tab_title(editor)
        self.note_dock.refresh()
        self._refresh_knowledge_model_from_controller()
        self._sync_cover_graph()
        self.note_dock.select_note_path(target_path)
        self.search_dock.perform_search()
        self._refresh_document_panels()
        self.outline_dock.set_object_context(self._selection_for_note(target_path))
        self.status_label.setText(f"已保存: {target_path.name}")

    def delete_current_note(self) -> None:
        editor = self._current_editor()
        current_path = self._current_note_path()
        if current_path is None or not current_path.exists():
            if editor.get_text().strip() and self._ask_confirmation(
                "丢弃未保存笔记",
                "当前笔记尚未保存。确定要丢弃这篇未保存的笔记吗？",
                confirm_text="丢弃",
            ):
                editor.load_empty_document(title="未命名笔记")
                self.current_note_path = None
                self._update_tab_title(editor)
                self._refresh_document_panels()
                self.status_label.setText("未保存笔记已丢弃")
            return

        self.delete_note(current_path)

    def delete_note(self, note_path: object) -> None:
        path = Path(note_path)
        if not self._is_deletable_note_path(path):
            self._show_message(
                QMessageBox.Icon.Warning,
                "无法删除",
                "只能删除当前工作区 notes 目录下的 Markdown 笔记。",
            )
            return

        if not path.exists():
            self.refresh_workspace()
            self.status_label.setText("笔记已不存在，工作区已刷新")
            return

        if not self._ask_confirmation(
            "删除笔记",
            f"确定要删除笔记“{path.stem}”吗？\n\n该操作会删除工作区中的 Markdown 文件。",
        ):
            return

        was_current_note = self.current_note_path is not None and (
            path.resolve() == self.current_note_path.resolve()
        )

        result = self.note_controller.delete_note(self.workspace_root, path)
        if not result.get("success"):
            self._show_message(
                QMessageBox.Icon.Critical,
                "删除失败",
                str(result.get("message") or "后端删除笔记失败。"),
            )
            return

        try:
            remove_title_for_path(self.workspace_root, path)
        except OSError:
            pass

        self.note_dock.refresh()
        self._refresh_knowledge_model_from_controller()
        self._sync_cover_graph()
        self.search_dock.perform_search()

        if was_current_note:
            self.current_note_path = None
            current_index = self.workspace_tabs.currentIndex()
            current_widget = self.workspace_tabs.currentWidget()
            if isinstance(current_widget, NoteEditorWidget) and self.workspace_tabs.count() > 1:
                self.workspace_tabs.removeTab(current_index)
                current_widget.deleteLater()
            next_note = self._find_first_note()
            if next_note is not None:
                self.open_note(next_note)
            else:
                self._current_editor().load_empty_document(title="未命名笔记")
                self._update_tab_title()
                self._refresh_document_panels()

        self.status_label.setText(f"已删除: {path.name}")

    def add_planet_from_graph(self, payload: object) -> None:
        system_index = self._system_index_from_graph_payload(payload)
        if not self._activate_workspace_from_graph_payload(payload):
            return

        title = self._prompt_text("新增分类", "分类名称：", "新分类")
        if not title:
            return

        if not self.note_dock.add_planet(title):
            self._show_message(QMessageBox.Icon.Information, "分类已存在", f"“{title}”已经在当前工作区中。")
            return

        planet_key = self.note_dock.planet_assignment_key(title)
        self._create_graph_star_note(title, planet_key)
        self._refresh_cover_after_graph_change(system_index)
        self.status_label.setText(f"已新增分类并创建同名资源: {title}")

    def delete_planet_from_graph(self, payload: object) -> None:
        system_index = self._system_index_from_graph_payload(payload)
        if not self._activate_workspace_from_graph_payload(payload):
            return

        candidates = self.note_dock.visible_planets_for_actions()
        if not candidates:
            self._show_message(QMessageBox.Icon.Information, "暂无可删除分类", "当前工作区中没有可删除的分类。")
            return

        selected = self._choose_keyed_item("删除分类", "选择要删除的分类：", candidates)
        if selected is None:
            return
        planet_key, planet_title = selected

        stars = self.note_dock.stars_for_planet(planet_key)
        if not self._ask_confirmation(
            "确认删除分类",
            f"将删除分类“{planet_title}”。\n\n其下 {len(stars)} 个资源会先归入“未归类”，后续分类会自动补齐。",
            confirm_text="删除分类",
        ):
            return

        for star in stars:
            self._assign_graph_node_to_planet(star, "Unassigned")

        if not self.note_dock.delete_planet(planet_key):
            self._show_message(QMessageBox.Icon.Warning, "删除失败", "该分类暂不能删除。")
            return

        self._refresh_cover_after_graph_change(system_index)
        self.status_label.setText(f"已删除分类: {planet_title}")

    def add_star_from_graph(self, payload: object) -> None:
        system_index = self._system_index_from_graph_payload(payload)
        if not self._activate_workspace_from_graph_payload(payload):
            return

        planet_title = self._planet_from_graph_payload(payload)
        planet_key = self.note_dock.planet_assignment_key(planet_title)
        title = self._prompt_text("新增资源", "资源名称：", "新资源")
        if not title:
            return

        self._create_graph_star_note(title, planet_key)
        self._refresh_cover_after_graph_change(system_index)
        self.status_label.setText(f"已在“{self.note_dock.planet_display_title(planet_key)}”分类新增资源: {title}")

    def delete_star_from_graph(self, payload: object) -> None:
        system_index = self._system_index_from_graph_payload(payload)
        if not self._activate_workspace_from_graph_payload(payload):
            return

        node = self._node_from_graph_payload(payload)
        target = None
        if node is not None and node.kind == KnowledgeObjectKind.STAR_NOTE:
            target = node
        else:
            planet_title = self._planet_from_graph_payload(payload)
            candidates = [
                star
                for star in self.note_dock.stars_for_planet(planet_title)
                if star.kind == KnowledgeObjectKind.STAR_NOTE and star.path is not None
            ]
            if not candidates:
                self._show_message(QMessageBox.Icon.Information, "暂无可删除资源", "该分类下没有可从星图删除的 Markdown 资源。")
                return
            selected = self._choose_keyed_item(
                "删除资源",
                "选择要删除的资源：",
                [(str(star.path), star.title) for star in candidates if star.path is not None],
            )
            if selected is None:
                return
            target_path = Path(selected[0])
            target = next((star for star in candidates if star.path == target_path), None)

        if target is None or target.path is None:
            return
        self.delete_note(target.path)
        self._refresh_cover_after_graph_change(system_index)

    def _create_graph_star_note(self, title: str, planet: str) -> Path | None:
        safe_name = self._safe_filename(title)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        candidate = self.notes_dir / f"{safe_name}.md"
        counter = 2
        while candidate.exists():
            candidate = self.notes_dir / f"{safe_name}-{counter}.md"
            counter += 1

        try:
            candidate.write_text(f"# {title}\n\n", encoding="utf-8")
            set_title_for_path(self.workspace_root, candidate, title)
        except OSError as error:
            self._show_message(QMessageBox.Icon.Critical, "创建资源失败", str(error))
            return None

        target = {
            "object_kind": "note",
            "object_key": candidate.stem,
            "path": str(candidate),
        }
        self.show_planet_assignment_placeholder(target, planet)
        self.note_dock.select_note_path(candidate)
        return candidate

    def _assign_graph_node_to_planet(self, node: KnowledgeGraphNode, planet: str) -> bool:
        object_kind = "reference" if node.kind == KnowledgeObjectKind.STAR_REFERENCE else "note"
        object_key = node.path.stem if node.path is not None else node.title
        result = self.knowledge_controller.assign_object_to_planet(
            self.workspace_root,
            object_kind=object_kind,
            object_key=object_key,
            planet=planet,
        )
        if not result.get("success"):
            self.status_label.setText(f"归类失败: {node.title}")
            return False
        if node.path is not None:
            self.note_dock.assign_path_to_planet(node.path, planet)
        return True

    def assign_graph_node_to_planet(self, payload: object, planet_title: str) -> None:
        node = self._node_from_graph_payload(payload)
        if node is None:
            return
        if not self._activate_workspace_from_graph_payload(payload):
            return

        planet_key = self.note_dock.planet_assignment_key(planet_title)
        target = {
            "object_kind": "reference" if node.kind == KnowledgeObjectKind.STAR_REFERENCE else "note",
            "object_key": node.path.stem if node.path is not None else node.title,
            "path": str(node.path) if node.path is not None else "",
        }
        self.show_planet_assignment_placeholder(target, planet_key)

    def _refresh_cover_after_graph_change(self, system_index: int | None) -> None:
        was_cover = self.central_stack.currentWidget() is self.cover_page
        was_system = self.cover_graph.current_layer == "cover_system"
        self.note_dock.refresh()
        self._refresh_knowledge_model_from_controller()
        self._sync_cover_graph()
        if was_cover and was_system and system_index is not None:
            system_count = len(getattr(self.cover_graph, "_galaxy_systems", ()))
            if system_count:
                self.cover_graph.render_cover_system(min(system_index, system_count - 1))

    def _activate_workspace_from_graph_payload(self, payload: object) -> bool:
        workspace_root = self._workspace_root_from_graph_payload(payload)
        if workspace_root is None:
            return True
        if workspace_root.resolve() != self.workspace_root.resolve():
            self.switch_workspace(workspace_root)
        return workspace_root.resolve() == self.workspace_root.resolve()

    def _workspace_root_from_graph_payload(self, payload: object) -> Path | None:
        if isinstance(payload, dict):
            system_index = payload.get("system_index")
            systems = getattr(self.cover_graph, "_galaxy_systems", ())
            if isinstance(system_index, int) and 0 <= system_index < len(systems):
                galaxy = systems[system_index][0]
                return Path(galaxy.path) if galaxy.path is not None else None
            node = payload.get("node")
            if isinstance(node, KnowledgeGraphNode) and node.path is not None:
                return Path(node.path)
        return None

    def _system_index_from_graph_payload(self, payload: object) -> int | None:
        if isinstance(payload, dict) and isinstance(payload.get("system_index"), int):
            return int(payload["system_index"])
        return None

    def _planet_from_graph_payload(self, payload: object) -> str:
        if isinstance(payload, dict):
            planet = str(payload.get("planet") or "").strip()
            if planet:
                return planet
            node = payload.get("node")
            if isinstance(node, KnowledgeGraphNode):
                return node.planet or node.title
        return "Unassigned"

    def _node_from_graph_payload(self, payload: object) -> KnowledgeGraphNode | None:
        if isinstance(payload, dict) and isinstance(payload.get("node"), KnowledgeGraphNode):
            return payload["node"]
        return None

    def _prompt_text(self, title: str, label: str, default: str = "") -> str:
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextValue(default)
        dialog.setStyleSheet(build_app_stylesheet())
        dialog.resize(360, 160)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return ""
        return dialog.textValue().strip()

    def _choose_keyed_item(
        self,
        title: str,
        label: str,
        items: list[tuple[str, str]],
    ) -> tuple[str, str] | None:
        if not items:
            return None

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setStyleSheet(build_app_stylesheet())
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(QLabel(label, dialog))

        list_widget = QListWidget(dialog)
        for key, text in items:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, key)
            list_widget.addItem(item)
        list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button is not None:
            ok_button.setText("确定")
        if cancel_button is not None:
            cancel_button.setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        list_widget.itemDoubleClicked.connect(lambda _item: dialog.accept())
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        current = list_widget.currentItem()
        if current is None:
            return None
        key = str(current.data(Qt.ItemDataRole.UserRole) or "")
        return key, current.text()

    def refresh_workspace(self) -> None:
        self._load_workspace()
        self._sync_cover_graph()
        self._refresh_document_panels()
        self.status_label.setText("工作区已刷新")

    def show_workspace_picker(self) -> None:
        dialog = WorkspacePickerDialog(initial_path=self.workspace_root, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dialog.selected_workspace()
        if selected is None:
            return

        self.switch_workspace(selected)

    def choose_workspace_store_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择工作区总目录",
            str(self.workspace_store_root),
        )
        if not selected:
            return

        self.workspace_store_root = Path(selected).expanduser().resolve()
        self._sync_cover_graph()
        self._show_message(
            QMessageBox.Icon.Information,
            "工作区总目录已设置",
            f"当前工作区总目录：\n{self.workspace_store_root}\n\n"
            "此后新建的工作区都会创建在这个目录下，星图也会从这里扫描工作区。",
        )

    def create_new_workspace(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建工作区", "工作区名称：")
        safe_name = self._safe_filename(name)
        if not accepted or not safe_name:
            return

        self.workspace_store_root.mkdir(parents=True, exist_ok=True)
        target = self.workspace_store_root / safe_name
        if target.exists() and any(target.iterdir()):
            self._show_message(
                QMessageBox.Icon.Warning,
                "工作区已存在",
                "该目录已存在且不是空目录。请选择其他名称，或通过星图选择已有工作区。",
            )
            return

        self.switch_workspace(target)
        self._sync_cover_graph()

    def delete_workspace_from_store(self) -> None:
        candidates = self._workspace_candidates()
        if not candidates:
            self._show_message(
                QMessageBox.Icon.Information,
                "暂无可删除工作区",
                "当前工作区总目录下还没有可删除的 NeuX 工作区。",
            )
            return

        selected = self._choose_keyed_item(
            "删除工作区",
            "选择要删除的工作区：",
            [(str(path), path.name) for path in candidates],
        )
        if selected is None:
            return

        target = Path(selected[0])
        if target.resolve() == self.workspace_root.resolve():
            self._show_message(
                QMessageBox.Icon.Warning,
                "无法删除当前工作区",
                "请先切换到其他工作区，再删除当前正在使用的工作区。",
            )
            return

        if not self._is_workspace_in_store(target):
            self._show_message(
                QMessageBox.Icon.Warning,
                "删除范围无效",
                "只能删除当前工作区总目录下的 NeuX 工作区。",
            )
            return

        if not self._ask_confirmation(
            "确认删除工作区",
            f"将永久删除该工作区目录及其中所有文件：\n{target}\n\n"
            "该操作不可撤销。",
            confirm_text="删除",
        ):
            return

        try:
            shutil.rmtree(target)
        except OSError as error:
            self._show_message(QMessageBox.Icon.Critical, "删除工作区失败", str(error))
            return

        self._sync_cover_graph()
        self._show_message(
            QMessageBox.Icon.Information,
            "工作区已删除",
            f"已删除：{target.name}\n\n星图已同步刷新。",
        )

    def _is_workspace_in_store(self, workspace_root: Path) -> bool:
        try:
            workspace_root.resolve().relative_to(self.workspace_store_root.resolve())
        except ValueError:
            return False
        return workspace_root.resolve() != self.workspace_store_root.resolve()

    def switch_workspace(self, workspace_path: str | Path) -> None:
        selected = Path(workspace_path).expanduser()
        if not self._maybe_save_note_tabs_before_workspace_switch():
            self.status_label.setText("已取消切换工作区")
            return

        result = self.workspace_controller.open_workspace(selected)
        if not result.get("success"):
            self._show_message(
                QMessageBox.Icon.Warning,
                "工作区打开失败",
                str(result.get("message") or "WorkspaceController.open_workspace() 未能打开该目录。"),
            )
            return

        data = result.get("data", {})
        workspace_context = data.get("workspace_context") if isinstance(data, dict) else None
        workspace_root = data.get("workspace_root") if isinstance(data, dict) else None
        new_root = Path(workspace_root or selected).resolve()

        self.workspace_root = new_root
        self.notes_dir = new_root / "notes"
        self.app_context.workspace_root = new_root
        if workspace_context is not None and hasattr(workspace_context, "database_path"):
            self.app_context.db_path = Path(workspace_context.database_path)

        self.setWindowTitle(f"NeuX - {self.workspace_root.name}")
        self.workspace_label.setText(f"工作区：{self.workspace_root}")
        self._reset_tabs_for_workspace()
        self._load_workspace()
        self._open_initial_note()
        self.show_star_map_cover()
        self.status_label.setText(f"已切换工作区: {self.workspace_root.name}")

    def _maybe_save_note_tabs_before_workspace_switch(self) -> bool:
        for index in range(self.workspace_tabs.count()):
            widget = self.workspace_tabs.widget(index)
            if isinstance(widget, NoteEditorWidget) and not widget.maybe_save_before_close():
                self.workspace_tabs.setCurrentIndex(index)
                return False
        return True

    def _reset_tabs_for_workspace(self) -> None:
        while self.workspace_tabs.count():
            widget = self.workspace_tabs.widget(0)
            self.workspace_tabs.removeTab(0)
            widget.deleteLater()

        self.current_note_path = None
        self.editor = NoteEditorWidget(self)
        self.editor.load_empty_document(title="未命名笔记")
        self.workspace_tabs.addTab(self.editor, "未命名")
        self.workspace_tabs.setTabToolTip(0, "未保存笔记")
        self._refresh_tab_close_buttons()
        self.workspace_tabs.setCurrentIndex(0)
        self._connect_editor(self.editor)

    def goto_line(self, line_number: int) -> None:
        editor = self._current_editor()
        editor.set_cursor_position(self._line_number_to_cursor_position(editor.get_text(), line_number))
        editor.focus_editor()

    def show_command_palette(self) -> None:
        commands = [
            CommandItem("新建笔记", self.create_new_note, "创建一个新的 Markdown 编辑页"),
            CommandItem("打开工作区", self.show_workspace_picker, "选择工作区目录"),
            CommandItem("保存当前笔记", self.save_current_note, "保存当前标签页中的 Markdown"),
            CommandItem("删除当前笔记", self.delete_current_note, "删除当前工作区 notes 下的 Markdown"),
            CommandItem("打开 PDF", self.open_pdf_from_dialog, "从 references 或 attachments 打开 PDF 阅读器"),
            CommandItem("打开 PPT", self.open_ppt_from_dialog, "从 references 或 attachments 打开 PPT (.pptx) 演示文稿"),
            CommandItem("PDF 摘录到笔记", self.insert_pdf_excerpt, "把 PDF 当前选区插入 Markdown 笔记"),
            CommandItem("插入 PDF 引用", self.insert_pdf_citation, "把 PDF citation key 插入当前笔记"),
            CommandItem("打开知识结构图", self.focus_knowledge_model, "聚焦工作区、分类、资源和关联结构"),
            CommandItem("聚焦搜索", self.focus_search_panel, "跳转到右侧搜索与反链面板"),
            CommandItem("聚焦文档导航", self.focus_outline_panel, "跳转到右侧大纲、PDF、元数据与关联面板"),
            CommandItem("刷新工作区", self.refresh_workspace, "重新扫描工作区资源"),
        ]
        dialog = CommandPaletteDialog(commands, self)
        dialog.exec()

    def focus_knowledge_model(self) -> None:
        self.show_star_map_cover(from_workbench=True)
        self.status_label.setText("已聚焦知识结构图")

    def focus_search_panel(self) -> None:
        self.show_workbench()
        self._show_right_sidebar("search", focus=True)

    def focus_outline_panel(self) -> None:
        self.show_workbench()
        self._show_right_sidebar("outline", focus=True)

    def open_knowledge_object(self, selection: KnowledgeSelection) -> None:
        if selection.path is not None and not self._ensure_workspace_for_path(selection.path):
            return

        if selection.kind == KnowledgeObjectKind.STAR_NOTE and selection.path is not None:
            self.open_note(selection.path)
            self.outline_dock.set_object_context(selection)
            return

        if selection.kind == KnowledgeObjectKind.STAR_REFERENCE and selection.path is not None:
            self._open_document_file(selection.path)
            self.outline_dock.set_object_context(selection)
            return

        if selection.kind == KnowledgeObjectKind.SATELLITE and selection.path is not None:
            if selection.path.suffix.lower() == ".md":
                self.open_note(selection.path)
                if selection.satellites and selection.satellites[0].line_number:
                    self.goto_line(selection.satellites[0].line_number)
            else:
                self._open_document_file(selection.path)
            self.outline_dock.set_object_context(selection)
            return

        self.open_knowledge_dashboard(selection)
        self.outline_dock.set_object_context(selection)

    def _ensure_workspace_for_path(self, path: Path) -> bool:
        workspace_root = self._workspace_root_for_path(path)
        if workspace_root is None or workspace_root.resolve() == self.workspace_root.resolve():
            return True

        self.switch_workspace(workspace_root)
        return self.workspace_root.resolve() == workspace_root.resolve()

    def _workspace_root_for_path(self, path: Path) -> Path | None:
        resolved_path = path.resolve()
        for workspace_root in self._workspace_candidates():
            try:
                resolved_path.relative_to(workspace_root.resolve())
            except ValueError:
                continue
            return workspace_root
        return None

    def open_knowledge_dashboard(self, selection: KnowledgeSelection) -> None:
        self.show_workbench()
        tab_key = f"knowledge:{selection.kind.value}:{selection.title}"
        for index in range(self.workspace_tabs.count()):
            if self.workspace_tabs.tabToolTip(index) == tab_key:
                self.workspace_tabs.setCurrentIndex(index)
                return

        body = QLabel(self._knowledge_dashboard_text(selection), self)
        body.setObjectName("knowledge_dashboard")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        body.setMargin(24)
        index = self.workspace_tabs.addTab(body, selection.title)
        self.workspace_tabs.setTabToolTip(index, tab_key)
        self._refresh_tab_close_buttons()
        self.workspace_tabs.setCurrentIndex(index)

    def _normalize_assignment_target(self, target: object) -> dict[str, str]:
        if isinstance(target, dict):
            object_kind = str(target.get("object_kind") or "note")
            object_key = str(target.get("object_key") or "").strip()
            path_value = target.get("path")
            if not object_key and path_value:
                object_key = Path(str(path_value)).stem
            return {
                "object_kind": object_kind,
                "object_key": object_key,
                "path": str(path_value or ""),
            }

        target_path = Path(target)
        return {
            "object_kind": "note" if target_path.suffix.lower() == ".md" else "reference",
            "object_key": target_path.stem,
            "path": str(target_path),
        }

    def show_planet_assignment_placeholder(self, path: object, planet: str) -> None:
        target = self._normalize_assignment_target(path)
        result = self.knowledge_controller.assign_object_to_planet(
            self.workspace_root,
            object_kind=target["object_kind"],
            object_key=target["object_key"],
            planet=planet,
        )
        if not result.get("success"):
            self._show_message(
                QMessageBox.Icon.Warning,
                "知识对象归类失败",
                str(result.get("message") or "后端未能保存归类结果。"),
            )
            return

        if target["path"]:
            self.note_dock.assign_path_to_planet(target["path"], planet)
        self._refresh_knowledge_model_from_controller()
        self._sync_cover_graph()
        self.note_dock.tabs.setCurrentWidget(self.note_dock.model_page)
        planet_title = self.note_dock.planet_display_title(planet)
        self.status_label.setText(
            f"已归入 {planet_title} 分类: {target['object_kind']}:{target['object_key']}"
        )

    def open_pdf_from_dialog(self) -> None:
        start_dir = self._default_pdf_folder()
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "打开 PDF",
            str(start_dir),
            "PDF Files (*.pdf);;All Files (*.*)",
        )
        if not selected:
            return

        prepared_path = self._prepare_pdf_path_for_open(Path(selected))
        if prepared_path is not None:
            self.open_pdf_placeholder(prepared_path)

    def open_ppt_from_dialog(self) -> None:
        start_dir = self._default_pdf_folder()
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "打开 PPT",
            str(start_dir),
            "PowerPoint Files (*.pptx);;All Files (*.*)",
        )
        if not selected:
            return

        prepared_path = self._prepare_pptx_path_for_open(Path(selected))
        if prepared_path is not None:
            self.open_ppt_placeholder(prepared_path)

    def go_previous_pdf_page(self) -> None:
        viewer = self._current_pdf_viewer()
        if viewer is not None:
            viewer.go_previous_page()
        else:
            self.status_label.setText("当前标签页不是 PDF")

    def go_next_pdf_page(self) -> None:
        viewer = self._current_pdf_viewer()
        if viewer is not None:
            viewer.go_next_page()
        else:
            self.status_label.setText("当前标签页不是 PDF")

    def zoom_in_pdf(self) -> None:
        viewer = self._current_pdf_viewer()
        if viewer is not None:
            viewer.zoom_in()
        else:
            self.status_label.setText("当前标签页不是 PDF")

    def zoom_out_pdf(self) -> None:
        viewer = self._current_pdf_viewer()
        if viewer is not None:
            viewer.zoom_out()
        else:
            self.status_label.setText("当前标签页不是 PDF")

    def fit_pdf_width(self) -> None:
        viewer = self._current_pdf_viewer()
        if viewer is not None:
            viewer.fit_width()
        else:
            self.status_label.setText("当前标签页不是 PDF")

    def insert_pdf_excerpt(self) -> None:
        viewer = self._current_pdf_viewer()
        if viewer is not None:
            viewer.request_excerpt_insert()
        else:
            self.status_label.setText("当前标签页不是 PDF")

    def insert_pdf_citation(self) -> None:
        viewer = self._current_pdf_viewer()
        if viewer is not None:
            viewer.request_citation_insert()
        else:
            self.status_label.setText("当前标签页不是 PDF")

    def _open_document_file(self, document_path: object) -> None:
        path = Path(document_path)
        if path.suffix.lower() in PPT_SUFFIXES:
            self.open_ppt_placeholder(path)
            return
        self.open_pdf_placeholder(path)

    def open_pdf_placeholder(self, pdf_path: object) -> None:
        self.show_workbench()
        path = Path(pdf_path)
        open_result = self.pdf_controller.open_pdf(self.workspace_root, path)
        if not open_result.get("success"):
            self._show_message(
                QMessageBox.Icon.Warning,
                "PDF 打开失败",
                (
                    f"{open_result.get('message')}\n\n"
                    "当前后端只允许打开工作区 references/ 或 attachments/ 目录下的 PDF。"
                ),
            )
            return

        data = open_result.get("data", {})
        pdf_data = data.get("pdf") if isinstance(data, dict) else None
        if not isinstance(pdf_data, dict):
            self._show_message(
                QMessageBox.Icon.Warning,
                "PDF 打开失败",
                "PdfController.open_pdf() 返回的数据格式异常。",
            )
            return
        path = Path(str(pdf_data.get("file_path") or path))
        reference_id = self._ensure_pdf_reference_for_path(path)
        if reference_id:
            self._refresh_knowledge_model_from_controller()
            self._sync_cover_graph()

        for index in range(self.workspace_tabs.count()):
            if self.workspace_tabs.tabToolTip(index) == str(path):
                self.workspace_tabs.setCurrentIndex(index)
                self.outline_dock.set_object_context(
                    self._selection_for_pdf_reference(path=path, reference_id=reference_id)
                    if reference_id
                    else KnowledgeSelection(
                        kind=KnowledgeObjectKind.STAR_REFERENCE,
                        title=path.name,
                        path=path,
                        description="文献或附件。可在 PDF 阅读器中翻页、划词摘录、插入引用并保存批注。",
                        tags=("文献", path.suffix.lower().lstrip(".")),
                    )
                )
                return

        viewer = PdfViewerWidget(self)
        viewer.load_pdf(
            path,
            page_count=pdf_data.get("page_count"),
            reference_key=reference_id or self._guess_reference_key(path),
        )
        viewer.show_pdf_metadata(pdf_data)
        self._add_pdf_tab(viewer, path)
        self.outline_dock.set_object_context(
            self._selection_for_pdf_reference(path=path, reference_id=reference_id)
            if reference_id
            else KnowledgeSelection(
                    kind=KnowledgeObjectKind.STAR_REFERENCE,
                    title=path.name,
                    path=path,
                    description="文献或附件。可在 PDF 阅读器中翻页、划词摘录、插入引用并保存批注。",
                    tags=("文献", path.suffix.lower().lstrip(".")),
            )
        )
        self.status_label.setText(f"已打开 PDF 阅读器: {path.name}")

    def open_ppt_placeholder(self, pptx_path: object) -> None:
        self.show_workbench()
        path = Path(pptx_path)

        if not path.is_absolute():
            path = (self.workspace_root / path).resolve()

        for index in range(self.workspace_tabs.count()):
            if self.workspace_tabs.tabToolTip(index) == str(path):
                self.workspace_tabs.setCurrentIndex(index)
                self.status_label.setText(f"已打开 PPT 阅读器: {path.name}")
                return

        viewer = PptViewerWidget(self)
        viewer.load_pptx(
            path,
            reference_key=self._guess_reference_key(path),
            cache_dir=self.workspace_root / ".agni" / "ppt_cache",
        )
        self._add_pdf_tab(viewer, path)
        self.status_label.setText(f"已打开 PPT 阅读器: {path.name}")

    def _default_pdf_folder(self) -> Path:
        for folder_name in ("references", "attachments"):
            folder = self.workspace_root / folder_name
            if folder.exists():
                return folder
        return self.workspace_root

    def _prepare_pdf_path_for_open(self, pdf_path: Path) -> Path | None:
        if self._is_workspace_document_path(pdf_path):
            return pdf_path

        if pdf_path.suffix.lower() != ".pdf" or not pdf_path.exists() or not pdf_path.is_file():
            self._show_message(QMessageBox.Icon.Warning, "PDF 打开失败", "请选择一个存在的 .pdf 文件。")
            return None

        if not self._ask_confirmation(
            "导入 PDF 到工作区",
            f"该 PDF 不在当前工作区 references/ 或 attachments/ 下：\n{pdf_path}\n\n"
            "需要先复制到当前工作区 attachments/ 后才能由 PdfController 打开。",
            confirm_text="导入并打开",
        ):
            return None

        try:
            return self._copy_document_to_attachments(pdf_path)
        except OSError as error:
            self._show_message(QMessageBox.Icon.Critical, "PDF 导入失败", str(error))
            return None

    def _prepare_pptx_path_for_open(self, pptx_path: Path) -> Path | None:
        if self._is_workspace_document_path(pptx_path):
            return pptx_path

        if pptx_path.suffix.lower() not in PPT_SUFFIXES or not pptx_path.exists() or not pptx_path.is_file():
            self._show_message(
                QMessageBox.Icon.Warning,
                "PPT 打开失败",
                "请选择一个存在的 .pptx 演示文稿。",
            )
            return None

        if not self._ask_confirmation(
            "导入 PPT 到工作区",
            f"该 PPT 不在当前工作区 references/ 或 attachments/ 下：\n{pptx_path}\n\n"
            "需要先复制到当前工作区 attachments/ 后才能进行阅读与索引。",
            confirm_text="导入并打开",
        ):
            return None

        try:
            return self._copy_document_to_attachments(pptx_path)
        except OSError as error:
            self._show_message(QMessageBox.Icon.Critical, "PPT 导入失败", str(error))
            return None

    def _is_workspace_document_path(self, document_path: Path) -> bool:
        try:
            relative = document_path.resolve().relative_to(self.workspace_root.resolve())
        except ValueError:
            return False
        return bool(relative.parts) and relative.parts[0] in {"attachments", "references"}

    def _copy_document_to_attachments(self, document_path: Path) -> Path:
        attachments_dir = self.workspace_root / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        target = attachments_dir / document_path.name
        counter = 2
        while target.exists() and target.resolve() != document_path.resolve():
            target = attachments_dir / f"{document_path.stem}-{counter}{document_path.suffix}"
            counter += 1
        if target.resolve() != document_path.resolve():
            shutil.copy2(document_path, target)
        return target

    def _load_pdf_document_page_count(self, pdf_path: Path) -> int | None:
        # UI-only adapter point: replace with pdf_controller.open_pdf(path) later.
        if not pdf_path.exists():
            return None
        return 1

    def _guess_reference_key(self, pdf_path: Path) -> str:
        return pdf_path.stem.replace(" ", "_")

    def _ensure_pdf_reference_for_path(
        self,
        pdf_path: Path,
        *,
        preferred_reference_id: str | None = None,
        silent: bool = False,
    ) -> str | None:
        if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
            return None

        resolved_pdf = pdf_path.expanduser().resolve()
        existing_id = self._reference_id_for_pdf_path(resolved_pdf)
        if existing_id:
            self._bind_reference_pdf_if_needed(existing_id, resolved_pdf, silent=silent)
            return existing_id

        base_reference_id = (preferred_reference_id or self._guess_reference_key(resolved_pdf)).strip()
        existing_by_id = self.reference_controller.get_reference(
            self.workspace_root,
            base_reference_id,
        )
        if existing_by_id.get("success"):
            data = existing_by_id.get("data", {})
            reference = data.get("reference", {}) if isinstance(data, dict) else {}
            if isinstance(reference, dict) and not reference.get("pdf_path"):
                if self._bind_reference_pdf_if_needed(base_reference_id, resolved_pdf, silent=silent):
                    return base_reference_id

        reference_id = self._unique_reference_id(base_reference_id)
        create_result = self.reference_controller.create_reference(
            self.workspace_root,
            {
                "reference_id": reference_id,
                "title": resolved_pdf.stem,
                "authors": (),
                "year": None,
                "entry_type": "pdf",
                "source_format": "manual",
                "source_path": str(resolved_pdf),
            },
        )
        if not create_result.get("success"):
            if not silent:
                self._show_message(
                    QMessageBox.Icon.Warning,
                    "文献条目创建失败",
                    str(create_result.get("message") or "无法为该 PDF 创建文献记录。"),
                )
            return None

        bind_result = self.reference_controller.bind_pdf(
            self.workspace_root,
            reference_id,
            resolved_pdf,
        )
        if not bind_result.get("success"):
            if not silent:
                self._show_message(
                    QMessageBox.Icon.Warning,
                    "PDF 绑定文献失败",
                    str(bind_result.get("message") or "无法把 PDF 绑定到文献记录。"),
                )
            return None

        if not silent:
            self.status_label.setText(f"已登记 PDF 文献: {resolved_pdf.stem}")
        return reference_id

    def _bind_reference_pdf_if_needed(
        self,
        reference_id: str,
        pdf_path: Path,
        *,
        silent: bool = False,
    ) -> bool:
        existing = self.reference_controller.get_reference(self.workspace_root, reference_id)
        if not existing.get("success"):
            return False

        data = existing.get("data", {})
        reference = data.get("reference", {}) if isinstance(data, dict) else {}
        stored_pdf = reference.get("pdf_path") if isinstance(reference, dict) else None
        if stored_pdf:
            try:
                if self._workspace_relative_path(stored_pdf).expanduser().resolve() == pdf_path.expanduser().resolve():
                    return True
            except OSError:
                pass

        bind_result = self.reference_controller.bind_pdf(self.workspace_root, reference_id, pdf_path)
        if not bind_result.get("success"):
            if not silent:
                self._show_message(
                    QMessageBox.Icon.Warning,
                    "PDF 绑定文献失败",
                    str(bind_result.get("message") or "无法把 PDF 绑定到文献记录。"),
                )
            return False
        return True

    def _sync_workspace_pdfs_to_references(self) -> None:
        created_count = 0
        for pdf_path in self._iter_workspace_pdf_paths():
            before = self._reference_id_for_pdf_path(pdf_path)
            reference_id = self._ensure_pdf_reference_for_path(pdf_path, silent=True)
            if reference_id and before is None:
                created_count += 1
        if created_count:
            self.status_label.setText(f"已同步 {created_count} 个 PDF 文献")

    def _iter_workspace_pdf_paths(self) -> tuple[Path, ...]:
        pdfs: list[Path] = []
        for folder_name in ("references", "attachments"):
            folder = self.workspace_root / folder_name
            if folder.exists():
                pdfs.extend(path for path in folder.rglob("*.pdf") if path.is_file())
        return tuple(sorted(pdfs, key=lambda item: str(item).lower()))

    def _reference_id_for_pdf_path(self, pdf_path: Path) -> str | None:
        list_result = self.reference_controller.list_references(self.workspace_root)
        if not list_result.get("success"):
            return None

        data = list_result.get("data", {})
        references = data.get("references", ()) if isinstance(data, dict) else ()
        resolved_pdf = pdf_path.expanduser().resolve()
        target_key = self._pdf_identity_key(resolved_pdf)
        for reference in references:
            if not isinstance(reference, dict):
                continue
            stored_pdf = reference.get("pdf_path")
            if not stored_pdf:
                continue
            stored_path = self._workspace_relative_path(stored_pdf)
            try:
                if stored_path.expanduser().resolve() == resolved_pdf:
                    return str(reference.get("reference_id") or "")
            except OSError:
                pass
            if target_key and self._pdf_identity_key(stored_path) == target_key:
                return str(reference.get("reference_id") or "")
        return None

    def _pdf_identity_key(self, pdf_path: Path) -> tuple[str, ...] | None:
        parts = tuple(pdf_path.parts)
        lowered_parts = tuple(part.lower() for part in parts)
        for folder_name in ("references", "attachments"):
            if folder_name in lowered_parts:
                index = lowered_parts.index(folder_name)
                return tuple(part.lower() for part in parts[index:])
        if pdf_path.suffix.lower() == ".pdf":
            return (pdf_path.name.lower(),)
        return None

    def _unique_reference_id(self, reference_id: str) -> str:
        base = reference_id or "reference"
        candidate = base
        suffix = 2
        while self.reference_controller.get_reference(self.workspace_root, candidate).get("success"):
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _on_pdf_page_changed(self, viewer: PdfViewerWidget, page_number: int) -> None:
        if self.workspace_tabs.currentWidget() is viewer:
            if isinstance(viewer, PptViewerWidget):
                self.status_label.setText(f"PPT 第 {page_number} 张幻灯片")
            else:
                self.status_label.setText(f"PDF 第 {page_number} 页")

    def _on_pdf_zoom_changed(self, viewer: PdfViewerWidget, zoom_factor: float) -> None:
        if self.workspace_tabs.currentWidget() is viewer:
            self.status_label.setText(f"缩放 {int(zoom_factor * 100)}%")

    def _handle_pdf_annotation_request(self, draft: object) -> None:
        pdf_path = Path(getattr(draft, "pdf_path", ""))
        text = str(getattr(draft, "text", "") or "").strip()
        page_number = int(getattr(draft, "page_number", 1) or 1)
        if not pdf_path.exists() or not text:
            self.status_label.setText("PDF 批注缺少文件或文字内容")
            return

        reference_id = self._ensure_pdf_reference_for_annotation(draft)
        if not reference_id:
            return

        result = self.pdf_controller.create_annotation(
            self.workspace_root,
            reference_id,
            {
                "text": text,
                "page_number": page_number,
                "page_label": str(page_number),
                "rects": tuple(getattr(draft, "rects", ()) or ()),
                "comment": "",
                "color": "yellow",
            },
        )
        if not result.get("success"):
            self._show_message(
                QMessageBox.Icon.Warning,
                "PDF 批注保存失败",
                str(result.get("message") or "PdfController.create_annotation() 未能保存批注。"),
            )
            return

        self._refresh_knowledge_model_from_controller()
        self._sync_cover_graph()
        self.outline_dock.set_object_context(
            self._selection_for_pdf_reference(path=pdf_path, reference_id=reference_id)
        )
        self._show_right_sidebar("outline")
        self.outline_dock.focus_satellite_page()
        self.status_label.setText(f"已保存 PDF 批注: {reference_id} 第 {page_number} 页")

    def delete_pdf_annotation(self, annotation_id: str) -> None:
        annotation_id = str(annotation_id or "").strip()
        if not annotation_id:
            return
        if not self._ask_confirmation(
            "删除 PDF 批注",
            "确定删除这条 PDF 批注吗？删除后对应关联也会从文档导航和星图中移除。",
            confirm_text="删除批注",
        ):
            return

        result = self.pdf_controller.delete_annotation(self.workspace_root, annotation_id)
        if not result.get("success"):
            self._show_message(
                QMessageBox.Icon.Warning,
                "PDF 批注删除失败",
                str(result.get("message") or "PdfController.delete_annotation() 未能删除批注。"),
            )
            return

        data = result.get("data", {})
        annotation = data.get("annotation", {}) if isinstance(data, dict) else {}
        reference_id = str(annotation.get("reference_id") or "")
        pdf_path = Path(str(annotation.get("pdf_path") or ""))
        if not pdf_path.is_absolute():
            pdf_path = self.workspace_root / pdf_path

        self._refresh_knowledge_model_from_controller()
        self._sync_cover_graph()
        if reference_id and pdf_path.exists():
            self.outline_dock.set_object_context(
                self._selection_for_pdf_reference(path=pdf_path, reference_id=reference_id)
            )
            self._show_right_sidebar("outline")
            self.outline_dock.focus_satellite_page()
        self.status_label.setText("已删除 PDF 批注")

    def _selection_for_pdf_reference(
        self,
        *,
        path: Path,
        reference_id: str,
    ) -> KnowledgeSelection:
        satellites: list[SatelliteItem] = []
        result = self.pdf_controller.list_reference_annotations(self.workspace_root, reference_id)
        if result.get("success"):
            annotations = result.get("data", {}).get("annotations", ())
            if isinstance(annotations, tuple | list):
                for item in annotations:
                    if not isinstance(item, dict):
                        continue
                    page_label = str(item.get("page_label") or item.get("page_number") or "")
                    text = str(item.get("comment") or item.get("text") or "").strip()
                    title = f"PDF 批注 p.{page_label}" if page_label else "PDF 批注"
                    satellites.append(
                        SatelliteItem(
                            title=title,
                            kind="annotation",
                            host_title=path.stem,
                            preview=text,
                            object_id=str(item.get("annotation_id") or ""),
                        )
                    )

        return KnowledgeSelection(
            kind=KnowledgeObjectKind.STAR_REFERENCE,
            title=path.stem,
            path=path,
            description=(
                "文献或附件。PDF 批注会作为关联显示在这里；"
                "可在 PDF 阅读器中划词、摘录、批注或插入引用。"
            ),
            tags=("文献", path.suffix.lower().lstrip(".")),
            satellites=tuple(satellites),
        )

    def _insert_markdown_into_current_note(self, markdown: str) -> None:
        editor = self._target_editor_for_pdf_insert()
        editor.insert_text_at_cursor(markdown)
        self.workspace_tabs.setCurrentWidget(editor)
        editor.focus_editor()
        self._update_tab_title(editor)
        self._refresh_document_panels()
        self.status_label.setText("已插入 Markdown 内容")

    def _target_editor_for_pdf_insert(self) -> NoteEditorWidget:
        widget = self.workspace_tabs.currentWidget()
        if isinstance(widget, NoteEditorWidget):
            self.editor = widget
            return widget

        if isinstance(self.editor, NoteEditorWidget) and self.workspace_tabs.indexOf(self.editor) >= 0:
            return self.editor

        for index in range(self.workspace_tabs.count()):
            candidate = self.workspace_tabs.widget(index)
            if isinstance(candidate, NoteEditorWidget):
                self.editor = candidate
                return candidate

        editor = NoteEditorWidget(self)
        editor.load_empty_document(title="PDF 摘录")
        self._add_note_tab(editor, "PDF 摘录", None)
        return editor

    def _ensure_pdf_reference_for_annotation(self, draft: object) -> str | None:
        pdf_path = Path(getattr(draft, "pdf_path", ""))
        reference_id = str(getattr(draft, "citation_key", "") or "").strip()
        return self._ensure_pdf_reference_for_path(
            pdf_path,
            preferred_reference_id=reference_id or None,
        )

    def _open_external_file(self, path: object) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path))))

    def show_about_dialog(self) -> None:
        self._show_message(
            QMessageBox.Icon.Information,
            "关于 NeuX",
            "NeuX 当前工作台已接入笔记、搜索、反向链接、文献、PDF 与知识结构后端接口。界面继续保留三栏布局、Markdown 编辑、星图、文档导航和 PDF 阅读等现有交互。",
        )

    def _show_message(self, icon: QMessageBox.Icon, title: str, text: str) -> None:
        message_box = QMessageBox(self)
        message_box.setIcon(icon)
        message_box.setWindowTitle(title)
        message_box.setText(text)
        message_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        message_box.setStyleSheet(build_app_stylesheet())
        ok_button = message_box.button(QMessageBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("确定")
        message_box.exec()

    def _ask_confirmation(self, title: str, text: str, *, confirm_text: str = "删除") -> bool:
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setWindowTitle(title)
        message_box.setText(text)
        message_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.No)
        message_box.setStyleSheet(build_app_stylesheet())

        yes_button = message_box.button(QMessageBox.StandardButton.Yes)
        no_button = message_box.button(QMessageBox.StandardButton.No)
        if yes_button is not None:
            yes_button.setText(confirm_text)
            yes_button.setObjectName("destructive_button")
        if no_button is not None:
            no_button.setText("取消")

        return message_box.exec() == QMessageBox.StandardButton.Yes

    def _on_editor_content_changed(self, _text: str) -> None:
        self._update_tab_title()
        self._refresh_document_panels()

    def _on_editor_document_changed(self, editor: NoteEditorWidget) -> None:
        if self.workspace_tabs.currentWidget() is not editor:
            return
        self._update_tab_title(editor)
        self._refresh_document_panels()
        current_path = self._current_note_path()
        if current_path is not None:
            self.outline_dock.set_object_context(self._selection_for_note(current_path))

    def _on_editor_cursor_changed(self, editor: NoteEditorWidget, position: int) -> None:
        if self.workspace_tabs.currentWidget() is editor:
            self.status_label.setText(f"光标: {position}")

    def _on_editor_title_changed(self, editor: NoteEditorWidget) -> None:
        self._update_tab_title(editor)
        if self.workspace_tabs.currentWidget() is editor:
            self._refresh_document_panels()

    def _on_editor_status_changed(self, status: str) -> None:
        self._update_tab_title()
        status_text = {
            "idle": "就绪",
            "editing": "未保存",
            "saved": "已保存",
            "save_failed": "保存失败",
            "external_modified": "外部修改",
        }.get(status, status)
        self.status_label.setText(status_text)

    def _refresh_document_panels(self) -> None:
        document = self.editor.get_document()
        self.outline_dock.set_headings(document.extract_headings())
        title = document.title or document.get_title_from_content()
        self.search_dock.update_backlinks(self.current_note_path, title)

    def _selection_for_note(self, note_path: Path) -> KnowledgeSelection:
        editor = self._current_editor()
        document = editor.get_document()
        current_path = self.current_note_path
        title = title_for_path(self.workspace_root, note_path) or note_path.stem
        text = ""
        if current_path is not None and current_path.resolve() == note_path.resolve():
            title = editor.get_title() or document.title or document.get_title_from_content() or title
            text = editor.get_text()
        else:
            try:
                text = note_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = ""
        satellites = extract_markdown_satellites(text, title)
        return KnowledgeSelection(
            kind=KnowledgeObjectKind.STAR_NOTE,
            title=title,
            path=note_path,
            description="Markdown 笔记：标题、摘录、批注、引用、链接和标签会作为关联展示。",
            tags=("笔记", "Markdown"),
            satellites=satellites,
        )

    def _line_number_to_cursor_position(self, text: str, line_number: int) -> int:
        target_line = max(1, line_number)
        position = 0
        for current_line, line in enumerate(text.splitlines(keepends=True), start=1):
            if current_line >= target_line:
                return position
            position += len(line)
        return len(text)

    def _target_note_path_for_title(self, current_path: Path, title: str) -> Path:
        safe_title = self._safe_filename(title)
        if not safe_title or safe_title == current_path.stem:
            return current_path

        target = current_path.with_name(f"{safe_title}.md")
        if not target.exists() or target.resolve() == current_path.resolve():
            return target

        counter = 2
        while True:
            candidate = current_path.with_name(f"{safe_title}-{counter}.md")
            if not candidate.exists() or candidate.resolve() == current_path.resolve():
                return candidate
            counter += 1

    def _knowledge_dashboard_text(self, selection: KnowledgeSelection) -> str:
        model_hint = (
            "工作区：当前知识库\n"
            "分类：收集箱、阅读资料、研究主题等资源分组\n"
            "资源：笔记、文献或 PDF 等知识对象\n"
            "关联：标题、摘录、批注、反链、标签等附属信息"
        )
        path_text = str(selection.path) if selection.path is not None else "无文件路径"
        satellites = "\n".join(f"- {item.title}" for item in selection.satellites[:8])
        if not satellites:
            satellites = "- 暂无关联条目"
        return (
            f"{selection.title}\n\n"
            f"{selection.description or '知识结构展示入口'}\n\n"
            f"{model_hint}\n\n"
            f"路径：{path_text}\n\n"
            f"关联预览：\n{satellites}\n\n"
            "这是 UI 展示层入口，不在此处写入数据库关系。"
        )

    def _safe_filename(self, title: str) -> str:
        cleaned = "".join(char for char in title.strip() if char not in r'\/:*?"<>|')
        cleaned = "-".join(cleaned.split())
        return cleaned or "Untitled"

    def _workspace_relative_path(self, path_value: object) -> Path:
        path = Path(str(path_value))
        if not path.is_absolute():
            path = self.workspace_root / path
        return path

    def _is_deletable_note_path(self, note_path: Path) -> bool:
        try:
            resolved_note = note_path.resolve()
            resolved_notes_dir = self.notes_dir.resolve()
            resolved_note.relative_to(resolved_notes_dir)
        except ValueError:
            return False

        return resolved_note.suffix.lower() == ".md"

    def _find_first_note(self) -> Path | None:
        result = self.note_controller.list_notes(self.workspace_root)
        if result.get("success"):
            data = result.get("data", {})
            notes = data.get("notes", ()) if isinstance(data, dict) else ()
            for note in notes:
                if not isinstance(note, dict):
                    continue
                file_path = note.get("file_path")
                if file_path:
                    return Path(str(file_path))

        if not self.notes_dir.exists():
            return None
        notes = sorted(self.notes_dir.rglob("*.md"), key=lambda item: item.name.lower())
        return notes[0] if notes else None
