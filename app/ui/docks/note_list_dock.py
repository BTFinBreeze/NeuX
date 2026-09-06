from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.models.note_title_store import title_for_path
from app.ui.models.planet_store import (
    add_custom_planet,
    hide_planet,
    load_custom_planets,
    load_hidden_planets,
    remove_custom_planet,
    unhide_planet,
)
from app.ui.models.satellite_parser import extract_markdown_satellites
from app.ui.models.ui_items import (
    KnowledgeGraphNode,
    KnowledgeObjectKind,
    KnowledgeSelection,
    SatelliteItem,
)
from app.ui.widgets.knowledge_graph_widget import (
    PLANET_COLORS,
    PLANET_DEFAULT_COLOR,
    SUN_COLOR,
)


RELATIVE_PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
KNOWLEDGE_KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 2
KNOWLEDGE_PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 3
KNOWLEDGE_DESCRIPTION_ROLE = int(Qt.ItemDataRole.UserRole) + 4
KNOWLEDGE_LINE_ROLE = int(Qt.ItemDataRole.UserRole) + 5
KNOWLEDGE_OBJECT_KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 6
KNOWLEDGE_OBJECT_KEY_ROLE = int(Qt.ItemDataRole.UserRole) + 7
PLANET_KEY_ROLE = int(Qt.ItemDataRole.UserRole) + 8

DEFAULT_PLANETS = (
    ("Inbox", "收集箱", "快速收集、待整理的笔记与想法", "inbox"),
    ("Reading", "阅读资料", "文献、PDF 与阅读摘录", "reading"),
    ("Research", "研究主题", "长期研究主题与项目", "research"),
)
DEFAULT_PLANET_DISPLAY = {key: title for key, title, _description, _filter in DEFAULT_PLANETS}
DEFAULT_PLANET_KEYS = {key for key, _title, _description, _filter in DEFAULT_PLANETS}
UNASSIGNED_PLANET_KEY = "Unassigned"
UNASSIGNED_PLANET_TITLE = "未归类"


class NoteListDock(QDockWidget):
    note_selected = Signal(object)
    delete_note_requested = Signal(object)
    reference_selected = Signal(object)
    knowledge_selected = Signal(object)
    assign_to_planet_requested = Signal(object, str)
    star_map_requested = Signal()
    knowledge_model_changed = Signal()
    new_note_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("资源库", parent)
        self.workspace_root: Path | None = None
        self.notes_dir: Path | None = None
        self.attachments_dir: Path | None = None
        self.planet_overrides: dict[str, str] = {}
        self.custom_planets: list[str] = []
        self.hidden_planets: list[str] = []
        self._graph_galaxy: KnowledgeGraphNode | None = None
        self._graph_planets: list[KnowledgeGraphNode] = []
        self._graph_stars_by_planet: dict[str, list[KnowledgeGraphNode]] = {}
        self._controller_galaxy: dict[str, object] | None = None

        self.setObjectName("note_list_dock")
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

        title = QLabel("工作区资源", surface)
        title.setObjectName("section_label")
        root_layout.addWidget(title)

        self.tabs = QTabWidget(surface)
        self.model_page = self._build_model_page()
        self.notes_page = self._build_notes_page()
        self.references_page = self._build_references_page()
        self.tags_page = self._build_tags_page()
        self.tabs.addTab(self.model_page, "全部")
        self.tabs.addTab(self.notes_page, "笔记")
        self.tabs.addTab(self.references_page, "文献")
        self.tabs.addTab(self.tags_page, "标签")
        root_layout.addWidget(self.tabs, 1)

        self.setWidget(surface)

    def _build_model_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        hint = QLabel("工作区 → 分类 → 对象", page)
        hint.setObjectName("section_label")
        layout.addWidget(hint)

        self.open_star_map_button = QPushButton("打开知识结构图", page)
        self.open_star_map_button.setToolTip("进入星图查看当前工作区的分类、笔记、文献和关联")
        layout.addWidget(self.open_star_map_button)

        self.knowledge_tree = QTreeWidget(page)
        self.knowledge_tree.setHeaderHidden(True)
        self.knowledge_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.knowledge_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.knowledge_tree, 1)

        return page

    def _build_tags_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.tag_filter = QLineEdit(page)
        self.tag_filter.setPlaceholderText("搜索标签...")
        layout.addWidget(self.tag_filter)

        self.tag_list = QListWidget(page)
        self.tag_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        layout.addWidget(self.tag_list, 1)

        return page

    def _build_notes_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.note_filter = QLineEdit(page)
        self.note_filter.setPlaceholderText("筛选笔记...")
        layout.addWidget(self.note_filter)

        button_row = QHBoxLayout()
        self.new_note_button = QPushButton("新建", page)
        self.delete_note_button = QPushButton("删除", page)
        self.delete_note_button.setObjectName("destructive_button")
        self.refresh_button = QPushButton("刷新", page)
        button_row.addWidget(self.new_note_button)
        button_row.addWidget(self.delete_note_button)
        button_row.addWidget(self.refresh_button)
        layout.addLayout(button_row)

        self.note_list = QListWidget(page)
        self.note_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.note_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.note_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.note_list, 1)

        return page

    def _build_references_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.reference_filter = QLineEdit(page)
        self.reference_filter.setPlaceholderText("筛选文献或 PDF...")
        layout.addWidget(self.reference_filter)

        self.reference_list = QListWidget(page)
        self.reference_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.reference_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.reference_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.reference_list, 1)

        return page

    def _bind_signals(self) -> None:
        self.knowledge_tree.itemClicked.connect(self._emit_knowledge_selected)
        self.knowledge_tree.itemActivated.connect(self._emit_knowledge_selected)
        self.knowledge_tree.customContextMenuRequested.connect(self._show_knowledge_context_menu)
        self.note_filter.textChanged.connect(self._filter_notes)
        self.reference_filter.textChanged.connect(self._filter_references)
        self.tag_filter.textChanged.connect(self._filter_tags)
        self.note_list.itemActivated.connect(self._emit_note_selected)
        self.note_list.itemClicked.connect(self._emit_note_selected)
        self.note_list.customContextMenuRequested.connect(self._show_note_context_menu)
        self.reference_list.itemActivated.connect(self._emit_reference_selected)
        self.reference_list.itemClicked.connect(self._emit_reference_selected)
        self.reference_list.customContextMenuRequested.connect(self._show_reference_context_menu)
        self.open_star_map_button.clicked.connect(self.star_map_requested.emit)
        self.new_note_button.clicked.connect(self.new_note_requested.emit)
        self.delete_note_button.clicked.connect(self._emit_delete_selected)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)

    def set_workspace(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root)
        self.notes_dir = self.workspace_root / "notes"
        self.attachments_dir = self.workspace_root / "attachments"
        self.custom_planets = load_custom_planets(self.workspace_root)
        self.hidden_planets = load_hidden_planets(self.workspace_root)
        self.refresh()

    def refresh(self) -> None:
        if self.workspace_root is not None:
            self.custom_planets = load_custom_planets(self.workspace_root)
            self.hidden_planets = load_hidden_planets(self.workspace_root)
        self.refresh_knowledge_model()
        self.refresh_notes()
        self.refresh_references()
        self.refresh_tags()

    def set_knowledge_model(self, galaxy: dict[str, object] | None) -> None:
        self._controller_galaxy = dict(galaxy or {})
        self.refresh_knowledge_model()

    def planet_display_title(self, planet_key: str) -> str:
        return self._display_planet_title(planet_key)

    def planet_assignment_key(self, planet_title: str) -> str:
        return self._assignment_key_for_planet(planet_title)

    def visible_planets_for_actions(self) -> list[tuple[str, str]]:
        planets: list[tuple[str, str]] = []
        for key, title, _description, _filter in DEFAULT_PLANETS:
            if not self._planet_is_hidden(key):
                planets.append((key, title))
        planets.extend(
            (title.strip(), title.strip())
            for title in self.custom_planets
            if title.strip() and not self._planet_is_hidden(title)
        )
        return planets

    def add_planet(self, title: str) -> bool:
        if self.workspace_root is None:
            return False

        clean_title = title.strip()
        if not clean_title:
            return False

        assignment_key = self._assignment_key_for_planet(clean_title)
        display_title = self._display_planet_title(assignment_key)
        if assignment_key in DEFAULT_PLANET_KEYS:
            self.hidden_planets = unhide_planet(self.workspace_root, assignment_key)
            self.hidden_planets = unhide_planet(self.workspace_root, display_title)
            self.refresh_knowledge_model()
            self.knowledge_model_changed.emit()
            return True

        visible_titles = {title for _key, title in self.visible_planets_for_actions()}
        visible_titles.add(UNASSIGNED_PLANET_TITLE)
        if clean_title in visible_titles:
            return False

        self.hidden_planets = unhide_planet(self.workspace_root, clean_title)
        self.custom_planets = add_custom_planet(self.workspace_root, clean_title)
        self.refresh_knowledge_model()
        self.knowledge_model_changed.emit()
        return True

    def delete_planet(self, planet_key: str) -> bool:
        if self.workspace_root is None:
            return False

        assignment_key = self._assignment_key_for_planet(planet_key)
        display_title = self._display_planet_title(assignment_key)
        if assignment_key in {UNASSIGNED_PLANET_KEY, UNASSIGNED_PLANET_TITLE}:
            return False

        if assignment_key in DEFAULT_PLANET_KEYS:
            self.hidden_planets = hide_planet(self.workspace_root, assignment_key)
        else:
            self.custom_planets = remove_custom_planet(self.workspace_root, display_title)
        self.refresh_knowledge_model()
        self.knowledge_model_changed.emit()
        return True

    def stars_for_planet(self, planet_key: str) -> list[KnowledgeGraphNode]:
        display_title = self._display_planet_title(self._assignment_key_for_planet(planet_key))
        return list(self._graph_stars_by_planet.get(display_title, ()))

    def _create_custom_planet(self) -> None:
        if self.workspace_root is None:
            return

        title, accepted = QInputDialog.getText(self, "新增分类", "分类名称：")
        title = title.strip()
        if not accepted or not title:
            return

        existing_titles = {self._display_planet_title(key) for key in DEFAULT_PLANET_KEYS}
        existing_titles.update({UNASSIGNED_PLANET_TITLE, *self.custom_planets})
        if title in existing_titles:
            QMessageBox.information(self, "分类已存在", f"“{title}”已经在当前工作区中。")
            return

        self.custom_planets = add_custom_planet(self.workspace_root, title)
        self.refresh_knowledge_model()
        self.knowledge_model_changed.emit()

    def _delete_selected_custom_planet(self) -> None:
        planet_key = self._selected_planet_key()
        if planet_key is None:
            QMessageBox.information(self, "选择分类", "请先在“全部”视图中选中一个自定义分类。")
            return

        self._delete_custom_planet(planet_key)

    def _delete_custom_planet(self, planet_key: str) -> None:
        if self.workspace_root is None:
            return

        planet_title = self._display_planet_title(planet_key)
        if planet_key in DEFAULT_PLANET_KEYS or planet_title == UNASSIGNED_PLANET_TITLE:
            QMessageBox.information(self, "默认分类", "默认分类用于基础资源组织，暂不支持删除。")
            return

        if self._graph_stars_by_planet.get(planet_title):
            QMessageBox.information(
                self,
                "分类非空",
                "该分类下还有资源。请先把这些对象归入其他分类，再删除该分类。",
            )
            return

        if planet_title not in self.custom_planets:
            QMessageBox.information(self, "无法删除", "当前只能删除通过 UI 新增的自定义分类。")
            return

        self.custom_planets = remove_custom_planet(self.workspace_root, planet_title)
        self.refresh_knowledge_model()
        self.knowledge_model_changed.emit()

    def refresh_knowledge_model(self) -> None:
        self.knowledge_tree.clear()
        if self.workspace_root is None:
            self._graph_galaxy = None
            self._graph_planets = []
            self._graph_stars_by_planet = {}
            self._add_disabled_tree_item("尚未打开工作区")
            return

        if self._controller_galaxy:
            self._render_controller_knowledge_model(self._controller_galaxy)
            return

        graph_planets: list[KnowledgeGraphNode] = []
        graph_stars_by_planet: dict[str, list[KnowledgeGraphNode]] = {}
        galaxy = QTreeWidgetItem([f"工作区  {self.workspace_root.name}"])
        galaxy.setToolTip(0, str(self.workspace_root))
        galaxy.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.GALAXY.value)
        galaxy.setData(0, KNOWLEDGE_PATH_ROLE, str(self.workspace_root))
        galaxy.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "当前工作区代表一个知识体系。")
        self.knowledge_tree.addTopLevelItem(galaxy)

        planets = [
            planet
            for planet in DEFAULT_PLANETS
            if not self._planet_is_hidden(planet[0])
        ]
        planets.extend(
            (title.strip(), title.strip(), "自定义分类", "")
            for title in self.custom_planets
            if title.strip()
        )
        planets.append((UNASSIGNED_PLANET_KEY, UNASSIGNED_PLANET_TITLE, "尚未归入具体分类的对象", ""))
        planet_items: dict[str, QTreeWidgetItem] = {}
        for planet_key, title, description, filter_text in planets:
            title = title.strip()
            if not title:
                continue
            if planet_key != UNASSIGNED_PLANET_KEY and self._planet_is_hidden(planet_key):
                continue
            planet = QTreeWidgetItem([f"分类  {title}"])
            planet.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.PLANET.value)
            planet.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, description)
            planet.setData(0, PLANET_KEY_ROLE, planet_key)
            planet.setData(0, Qt.ItemDataRole.UserRole, filter_text)
            galaxy.addChild(planet)
            planet_items[title] = planet
            graph_planets.append(
                KnowledgeGraphNode(
                    kind=KnowledgeObjectKind.PLANET,
                    title=title,
                    color=PLANET_COLORS.get(title, PLANET_DEFAULT_COLOR),
                    description=description,
                    planet=title,
                )
            )
            graph_stars_by_planet[title] = []

        for note_path in self._iter_note_paths():
            planet_title = self._display_planet_title(self._guess_planet_for_path(note_path))
            note_title = self._note_display_title(note_path)
            satellites = tuple(self._extract_note_satellites(note_path))
            star = QTreeWidgetItem([f"{self._resource_kind_label(note_title, note_path, 'note', planet_title)}  {note_title}"])
            star.setToolTip(0, str(note_path))
            star.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.STAR_NOTE.value)
            star.setData(0, KNOWLEDGE_PATH_ROLE, str(note_path))
            star.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "Markdown 笔记")
            planet_items.get(planet_title, planet_items[UNASSIGNED_PLANET_TITLE]).addChild(star)
            graph_stars_by_planet.setdefault(planet_title, []).append(
                KnowledgeGraphNode(
                    kind=KnowledgeObjectKind.STAR_NOTE,
                    title=note_title,
                    color=PLANET_COLORS.get(planet_title, PLANET_DEFAULT_COLOR),
                    path=note_path,
                    description="Markdown 笔记",
                    planet=planet_title,
                    tags=("笔记", "Markdown"),
                    satellites=satellites,
                )
            )

            for satellite in satellites:
                item = QTreeWidgetItem([f"关联  {satellite.title}"])
                item.setToolTip(0, satellite.preview)
                item.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.SATELLITE.value)
                item.setData(0, KNOWLEDGE_PATH_ROLE, str(note_path))
                item.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, satellite.preview)
                item.setData(0, KNOWLEDGE_LINE_ROLE, satellite.line_number)
                star.addChild(item)

        for ref_path in self._iter_reference_paths():
            star = QTreeWidgetItem([f"文献  {ref_path.name}"])
            star.setToolTip(0, str(ref_path))
            star.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.STAR_REFERENCE.value)
            star.setData(0, KNOWLEDGE_PATH_ROLE, str(ref_path))
            star.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "文献或附件")
            reading_title = self._display_planet_title("Reading")
            target_planet_title = reading_title if reading_title in planet_items else UNASSIGNED_PLANET_TITLE
            planet_items[target_planet_title].addChild(star)

            satellite_item = SatelliteItem(
                title="元数据 / 批注占位",
                kind="pdf-placeholder",
                host_title=ref_path.name,
                line_number=None,
                preview="后续接入 PDF 批注、摘录、版本记录。",
            )
            graph_stars_by_planet.setdefault(target_planet_title, []).append(
                KnowledgeGraphNode(
                    kind=KnowledgeObjectKind.STAR_REFERENCE,
                    title=ref_path.name,
                    color=PLANET_COLORS.get(target_planet_title, PLANET_DEFAULT_COLOR),
                    path=ref_path,
                    description="文献或附件",
                    planet=target_planet_title,
                    tags=("文献", ref_path.suffix.lower().lstrip(".")),
                    satellites=(satellite_item,),
                )
            )

            satellite = QTreeWidgetItem([f"关联  {satellite_item.title}"])
            satellite.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.SATELLITE.value)
            satellite.setData(0, KNOWLEDGE_PATH_ROLE, str(ref_path))
            satellite.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, satellite_item.preview)
            satellite.setData(0, KNOWLEDGE_LINE_ROLE, None)
            star.addChild(satellite)

        self.knowledge_tree.expandToDepth(1)
        galaxy_node = KnowledgeGraphNode(
            kind=KnowledgeObjectKind.GALAXY,
            title=self.workspace_root.name,
            color=SUN_COLOR,
            path=self.workspace_root,
            description="当前工作区代表一个知识体系。",
            tags=("工作区",),
        )
        self._graph_galaxy = galaxy_node
        self._graph_planets = graph_planets
        self._graph_stars_by_planet = graph_stars_by_planet

    def _render_controller_knowledge_model(self, galaxy_payload: dict[str, object]) -> None:
        graph_planets: list[KnowledgeGraphNode] = []
        graph_stars_by_planet: dict[str, list[KnowledgeGraphNode]] = {}
        workspace_path = Path(str(galaxy_payload.get("workspace_root") or self.workspace_root))
        galaxy_title = str(galaxy_payload.get("title") or workspace_path.name)

        galaxy = QTreeWidgetItem([f"工作区  {galaxy_title}"])
        galaxy.setToolTip(0, str(workspace_path))
        galaxy.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.GALAXY.value)
        galaxy.setData(0, KNOWLEDGE_PATH_ROLE, str(workspace_path))
        galaxy.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "当前工作区代表一个知识体系。")
        self.knowledge_tree.addTopLevelItem(galaxy)

        seen_planets: set[str] = set()
        planet_items: dict[str, QTreeWidgetItem] = {}
        for planet_payload in tuple(galaxy_payload.get("planets") or ()):
            if not isinstance(planet_payload, dict):
                continue
            planet_key = str(planet_payload.get("title") or UNASSIGNED_PLANET_KEY)
            planet_title = self._display_planet_title(planet_key)
            if not planet_title.strip():
                continue
            if planet_key != UNASSIGNED_PLANET_KEY and self._planet_is_hidden(planet_key):
                continue
            planet_description = str(
                planet_payload.get("description") or self._planet_description(planet_key)
            )
            if planet_title in seen_planets:
                continue
            seen_planets.add(planet_title)
            planet = QTreeWidgetItem([f"分类  {planet_title}"])
            planet.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.PLANET.value)
            planet.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, planet_description)
            planet.setData(0, PLANET_KEY_ROLE, planet_key)
            galaxy.addChild(planet)
            planet_items[planet_title] = planet

            graph_planets.append(
                KnowledgeGraphNode(
                    kind=KnowledgeObjectKind.PLANET,
                    title=planet_title,
                    color=PLANET_COLORS.get(planet_title, PLANET_DEFAULT_COLOR),
                    description=planet_description,
                    planet=planet_title,
                )
            )
            graph_stars_by_planet.setdefault(planet_title, [])

            for star_payload in tuple(planet_payload.get("stars") or ()):
                if not isinstance(star_payload, dict):
                    continue
                object_kind = str(star_payload.get("object_kind") or "note")
                object_key = str(star_payload.get("object_key") or "")
                star_kind = (
                    KnowledgeObjectKind.STAR_REFERENCE
                    if object_kind == "reference"
                    else KnowledgeObjectKind.STAR_NOTE
                )
                path_value = star_payload.get("path")
                star_path = Path(str(path_value)) if path_value else None
                if star_path is not None and not star_path.is_absolute():
                    star_path = workspace_path / star_path
                if star_kind == KnowledgeObjectKind.STAR_NOTE and (
                    star_path is None or not star_path.exists() or not star_path.is_file()
                ):
                    continue
                if object_kind == "note" and star_path is not None:
                    star_title = self._note_display_title(star_path)
                else:
                    star_title = str(star_payload.get("title") or object_key or "Untitled")
                override_key = (
                    self.planet_overrides.get(str(star_path.resolve()))
                    if star_path is not None
                    else None
                )
                target_planet_title = (
                    self._display_planet_title(override_key) if override_key else planet_title
                )
                if self._planet_is_hidden(target_planet_title):
                    target_planet_title = UNASSIGNED_PLANET_TITLE
                if target_planet_title not in planet_items:
                    target_planet = QTreeWidgetItem([f"分类  {target_planet_title}"])
                    target_planet.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.PLANET.value)
                    target_planet.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "自定义分类")
                    target_planet.setData(0, PLANET_KEY_ROLE, override_key or target_planet_title)
                    galaxy.addChild(target_planet)
                    planet_items[target_planet_title] = target_planet
                    seen_planets.add(target_planet_title)
                    graph_planets.append(
                        KnowledgeGraphNode(
                            kind=KnowledgeObjectKind.PLANET,
                            title=target_planet_title,
                            color=PLANET_COLORS.get(target_planet_title, PLANET_DEFAULT_COLOR),
                            description="自定义分类",
                            planet=target_planet_title,
                        )
                    )
                    graph_stars_by_planet.setdefault(target_planet_title, [])
                planet_for_star = planet_items[target_planet_title]
                tags = tuple(str(tag) for tag in tuple(star_payload.get("tags") or ()))
                satellites = tuple(
                    self._satellite_from_controller_payload(item, star_title)
                    for item in tuple(star_payload.get("satellites") or ())
                    if isinstance(item, dict)
                )
                if star_kind == KnowledgeObjectKind.STAR_NOTE and star_path is not None:
                    satellites = self._merge_satellites(
                        satellites,
                        tuple(self._extract_note_satellites(star_path)),
                    )

                star = QTreeWidgetItem([f"{self._resource_kind_label(star_title, star_path, object_kind, target_planet_title)}  {star_title}"])
                if star_path is not None:
                    star.setToolTip(0, str(star_path))
                    star.setData(0, KNOWLEDGE_PATH_ROLE, str(star_path))
                star.setData(0, KNOWLEDGE_KIND_ROLE, star_kind.value)
                star.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "Markdown 笔记" if object_kind == "note" else "文献或附件")
                star.setData(0, KNOWLEDGE_OBJECT_KIND_ROLE, object_kind)
                star.setData(0, KNOWLEDGE_OBJECT_KEY_ROLE, object_key)
                planet_for_star.addChild(star)

                graph_stars_by_planet.setdefault(target_planet_title, []).append(
                    KnowledgeGraphNode(
                        kind=star_kind,
                        title=star_title,
                        color=PLANET_COLORS.get(target_planet_title, PLANET_DEFAULT_COLOR),
                        path=star_path,
                        description=star.data(0, KNOWLEDGE_DESCRIPTION_ROLE),
                        planet=target_planet_title,
                        tags=tags,
                        satellites=satellites,
                    )
                )

                for satellite in satellites:
                    item = QTreeWidgetItem([f"关联  {satellite.title}"])
                    item.setToolTip(0, satellite.preview)
                    item.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.SATELLITE.value)
                    if star_path is not None:
                        item.setData(0, KNOWLEDGE_PATH_ROLE, str(star_path))
                    item.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, satellite.preview)
                    item.setData(0, KNOWLEDGE_LINE_ROLE, satellite.line_number)
                    item.setData(0, KNOWLEDGE_OBJECT_KIND_ROLE, object_kind)
                    item.setData(0, KNOWLEDGE_OBJECT_KEY_ROLE, object_key)
                    star.addChild(item)

        self.knowledge_tree.expandToDepth(1)
        for custom_planet in self.custom_planets:
            if self._planet_is_hidden(custom_planet):
                continue
            if custom_planet in seen_planets:
                continue
            planet = QTreeWidgetItem([f"分类  {custom_planet}"])
            planet.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.PLANET.value)
            planet.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "自定义分类")
            planet.setData(0, PLANET_KEY_ROLE, custom_planet)
            galaxy.addChild(planet)
            seen_planets.add(custom_planet)
            graph_planets.append(
                KnowledgeGraphNode(
                    kind=KnowledgeObjectKind.PLANET,
                    title=custom_planet,
                    color=PLANET_COLORS.get(custom_planet, PLANET_DEFAULT_COLOR),
                    description="自定义分类",
                    planet=custom_planet,
                )
            )
            graph_stars_by_planet.setdefault(custom_planet, [])

        # 工作区里尚未登记为参考文献的文档（例如 PowerPoint 附件）也追加到
        # “全部”树中，保证每个 workspace 文档都能被发现与打开。
        galaxy_item = self.knowledge_tree.topLevelItem(0)
        if galaxy_item is not None:
            rendered_paths: set[Path] = set()
            for planet_index in range(galaxy_item.childCount()):
                planet_item = galaxy_item.child(planet_index)
                for star_index in range(planet_item.childCount()):
                    star_item = planet_item.child(star_index)
                    if (
                        star_item.data(0, KNOWLEDGE_KIND_ROLE)
                        == KnowledgeObjectKind.STAR_REFERENCE.value
                    ):
                        path_value = star_item.data(0, KNOWLEDGE_PATH_ROLE)
                        if path_value:
                            rendered_paths.add(Path(str(path_value)).resolve())
            for doc_path in self._iter_reference_paths():
                if doc_path.suffix.lower() != ".pptx":
                    continue
                try:
                    if doc_path.resolve() in rendered_paths:
                        continue
                except OSError:
                    continue
                target_planet_title = self._display_planet_title("Reading")
                if target_planet_title not in planet_items:
                    if self._planet_is_hidden("Reading"):
                        target_planet_title = UNASSIGNED_PLANET_TITLE
                    else:
                        reading_planet = QTreeWidgetItem([f"分类  {target_planet_title}"])
                        reading_planet.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.PLANET.value)
                        reading_planet.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "文献、PDF 与阅读摘录")
                        reading_planet.setData(0, PLANET_KEY_ROLE, "Reading")
                        galaxy_item.addChild(reading_planet)
                        planet_items[target_planet_title] = reading_planet
                        graph_planets.append(
                            KnowledgeGraphNode(
                                kind=KnowledgeObjectKind.PLANET,
                                title=target_planet_title,
                                color=PLANET_COLORS.get(target_planet_title, PLANET_DEFAULT_COLOR),
                                description="文献、PDF 与阅读摘录",
                                planet=target_planet_title,
                            )
                        )
                if target_planet_title not in planet_items:
                    unassigned_planet = QTreeWidgetItem([f"分类  {UNASSIGNED_PLANET_TITLE}"])
                    unassigned_planet.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.PLANET.value)
                    unassigned_planet.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "尚未归入具体分类的对象")
                    unassigned_planet.setData(0, PLANET_KEY_ROLE, UNASSIGNED_PLANET_KEY)
                    galaxy_item.addChild(unassigned_planet)
                    planet_items[target_planet_title] = unassigned_planet
                    if not any(node.title == target_planet_title for node in graph_planets):
                        graph_planets.append(
                            KnowledgeGraphNode(
                                kind=KnowledgeObjectKind.PLANET,
                                title=target_planet_title,
                                color=PLANET_COLORS.get(target_planet_title, PLANET_DEFAULT_COLOR),
                                description="尚未归入具体分类的对象",
                                planet=target_planet_title,
                            )
                        )

                star = QTreeWidgetItem([f"文献  {doc_path.name}"])
                star.setToolTip(0, str(doc_path))
                star.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.STAR_REFERENCE.value)
                star.setData(0, KNOWLEDGE_PATH_ROLE, str(doc_path))
                star.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, "文献或附件")
                planet_items[target_planet_title].addChild(star)

                satellite_item = SatelliteItem(
                    title="元数据 / 批注占位",
                    kind="pdf-placeholder",
                    host_title=doc_path.name,
                    line_number=None,
                    preview="后续接入 PDF 批注、摘录、版本记录。",
                )
                graph_stars_by_planet.setdefault(target_planet_title, []).append(
                    KnowledgeGraphNode(
                        kind=KnowledgeObjectKind.STAR_REFERENCE,
                        title=doc_path.name,
                        color=PLANET_COLORS.get(target_planet_title, PLANET_DEFAULT_COLOR),
                        path=doc_path,
                        description="文献或附件",
                        planet=target_planet_title,
                        tags=("文献", doc_path.suffix.lower().lstrip(".")),
                        satellites=(satellite_item,),
                    )
                )
                satellite = QTreeWidgetItem([f"关联  {satellite_item.title}"])
                satellite.setData(0, KNOWLEDGE_KIND_ROLE, KnowledgeObjectKind.SATELLITE.value)
                satellite.setData(0, KNOWLEDGE_PATH_ROLE, str(doc_path))
                satellite.setData(0, KNOWLEDGE_DESCRIPTION_ROLE, satellite_item.preview)
                satellite.setData(0, KNOWLEDGE_LINE_ROLE, None)
                star.addChild(satellite)

        self.knowledge_tree.expandToDepth(1)
        galaxy_node = KnowledgeGraphNode(
            kind=KnowledgeObjectKind.GALAXY,
            title=galaxy_title,
            color=SUN_COLOR,
            path=workspace_path,
            description="当前工作区代表一个知识体系。",
            tags=("工作区",),
        )
        self._graph_galaxy = galaxy_node
        self._graph_planets = graph_planets
        self._graph_stars_by_planet = graph_stars_by_planet

    def _satellite_from_controller_payload(
        self,
        payload: dict[str, object],
        host_title: str,
    ) -> SatelliteItem:
        line_number = payload.get("line_number")
        return SatelliteItem(
            title=str(payload.get("title") or "Satellite")[:60],
            kind=str(payload.get("kind") or "entry"),
            host_title=host_title,
            line_number=int(line_number) if line_number else None,
            preview=str(payload.get("preview") or ""),
        )

    def _merge_satellites(
        self,
        primary: tuple[SatelliteItem, ...],
        supplemental: tuple[SatelliteItem, ...],
    ) -> tuple[SatelliteItem, ...]:
        merged: list[SatelliteItem] = []
        seen: set[tuple[str, str, int | None]] = set()
        for satellite in (*primary, *supplemental):
            key = (satellite.kind, satellite.title, satellite.line_number)
            if key in seen:
                continue
            seen.add(key)
            merged.append(satellite)
        return tuple(merged[:18])

    def knowledge_graph_snapshot(
        self,
    ) -> tuple[KnowledgeGraphNode, list[KnowledgeGraphNode], dict[str, list[KnowledgeGraphNode]]] | None:
        if self._graph_galaxy is None:
            return None
        return (
            self._graph_galaxy,
            list(self._graph_planets),
            dict(self._graph_stars_by_planet),
        )

    def refresh_notes(self) -> None:
        self.note_list.clear()
        if self.notes_dir is None or not self.notes_dir.exists():
            self._add_disabled_item(self.note_list, "尚未发现 notes 目录")
            return

        note_paths = self._iter_note_paths()
        if not note_paths:
            self._add_disabled_item(self.note_list, "暂无 Markdown 笔记")
            return

        for note_path in note_paths:
            rel_path = note_path.relative_to(self.notes_dir)
            item = QListWidgetItem(self._note_display_title(note_path))
            item.setToolTip(str(note_path))
            item.setData(Qt.ItemDataRole.UserRole, str(note_path))
            item.setData(RELATIVE_PATH_ROLE, str(rel_path))
            self.note_list.addItem(item)

        self._filter_notes(self.note_filter.text())

    def refresh_references(self) -> None:
        self.reference_list.clear()
        if self.workspace_root is None:
            self._add_disabled_item(self.reference_list, "尚未打开工作区")
            return

        candidates = self._iter_reference_paths()

        if not candidates:
            self._add_disabled_item(self.reference_list, "暂无文献文件")
            return

        for ref_path in sorted(candidates, key=lambda item: item.name.lower()):
            item = QListWidgetItem(ref_path.name)
            item.setToolTip(str(ref_path))
            item.setData(Qt.ItemDataRole.UserRole, str(ref_path))
            self.reference_list.addItem(item)

        self._filter_references(self.reference_filter.text())

    def refresh_tags(self) -> None:
        self.tag_list.clear()
        tags: dict[str, int] = {}
        for note_path in self._iter_note_paths():
            for satellite in self._extract_note_satellites(note_path):
                if satellite.kind != "tag":
                    continue
                tag = satellite.title.lstrip("#").strip()
                if tag:
                    tags[tag] = tags.get(tag, 0) + 1

        if not tags:
            self._add_disabled_item(self.tag_list, "暂无标签")
            return

        for tag, count in sorted(tags.items(), key=lambda item: item[0].lower()):
            self.tag_list.addItem(QListWidgetItem(f"# {tag}  ·  {count}"))

        self._filter_tags(self.tag_filter.text())

    def select_note_path(self, note_path: str | Path) -> None:
        expected = str(note_path)
        for row in range(self.note_list.count()):
            item = self.note_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == expected:
                self.note_list.setCurrentItem(item)
                break

    def assign_path_to_planet(self, path: str | Path, planet: str) -> None:
        self.planet_overrides[str(Path(path).resolve())] = planet
        self.refresh_knowledge_model()

    def selected_note_path(self) -> Path | None:
        item = self.note_list.currentItem()
        if item is None:
            return None

        note_path = item.data(Qt.ItemDataRole.UserRole)
        return Path(note_path) if note_path else None

    def _filter_notes(self, query: str) -> None:
        self._filter_list(self.note_list, query)

    def _filter_references(self, query: str) -> None:
        self._filter_list(self.reference_list, query)

    def _filter_tags(self, query: str) -> None:
        self._filter_list(self.tag_list, query)

    def _filter_list(self, list_widget: QListWidget, query: str) -> None:
        normalized = query.strip().lower()
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            haystack = f"{item.text()} {item.toolTip()}".lower()
            item.setHidden(bool(normalized) and normalized not in haystack)

    def _emit_note_selected(self, item: QListWidgetItem) -> None:
        note_path = item.data(Qt.ItemDataRole.UserRole)
        if note_path:
            self.note_selected.emit(Path(note_path))

    def _emit_delete_selected(self) -> None:
        note_path = self.selected_note_path()
        if note_path is not None:
            self.delete_note_requested.emit(note_path)

    def _emit_reference_selected(self, item: QListWidgetItem) -> None:
        reference_path = item.data(Qt.ItemDataRole.UserRole)
        if reference_path:
            self.reference_selected.emit(Path(reference_path))

    def _emit_knowledge_selected(self, item: QTreeWidgetItem) -> None:
        selection = self._selection_from_tree_item(item)
        if selection is not None:
            self.knowledge_selected.emit(selection)

    def _show_note_context_menu(self, position) -> None:
        item = self.note_list.itemAt(position)
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return

        note_path = Path(item.data(Qt.ItemDataRole.UserRole))
        menu = QMenu(self)
        open_action = QAction("打开", menu)
        delete_action = QAction("删除", menu)
        copy_path_action = QAction("复制路径", menu)
        assign_menu = QMenu("归入分类", menu)
        assign_actions = {
            planet_key: QAction(planet_title, assign_menu)
            for planet_key, planet_title in self._assignment_planets()
        }
        for action in assign_actions.values():
            assign_menu.addAction(action)
        menu.addAction(open_action)
        menu.addAction(delete_action)
        menu.addMenu(assign_menu)
        menu.addSeparator()
        menu.addAction(copy_path_action)

        open_action.triggered.connect(lambda: self.note_selected.emit(note_path))
        delete_action.triggered.connect(lambda: self.delete_note_requested.emit(note_path))
        assignment_target = {
            "object_kind": "note",
            "object_key": note_path.stem,
            "path": str(note_path),
        }
        for planet, action in assign_actions.items():
            action.triggered.connect(
                lambda _checked=False, target=planet: self.assign_to_planet_requested.emit(
                    assignment_target,
                    target,
                )
            )
        copy_path_action.triggered.connect(lambda: QApplication.clipboard().setText(str(note_path)))
        menu.exec(self.note_list.mapToGlobal(position))

    def _show_reference_context_menu(self, position) -> None:
        item = self.reference_list.itemAt(position)
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return

        reference_path = Path(item.data(Qt.ItemDataRole.UserRole))
        menu = QMenu(self)
        open_action = QAction("打开文献", menu)
        copy_path_action = QAction("复制路径", menu)
        menu.addAction(open_action)
        menu.addAction(copy_path_action)

        open_action.triggered.connect(lambda: self.reference_selected.emit(reference_path))
        copy_path_action.triggered.connect(
            lambda: QApplication.clipboard().setText(str(reference_path))
        )
        menu.exec(self.reference_list.mapToGlobal(position))

    def _show_knowledge_context_menu(self, position) -> None:
        item = self.knowledge_tree.itemAt(position)
        if item is None:
            return

        selection = self._selection_from_tree_item(item)
        if selection is None:
            return

        menu = QMenu(self)
        open_action = QAction("打开 / 查看", menu)
        copy_path_action = QAction("复制路径", menu)
        add_planet_action = QAction("新增分类", menu)
        delete_planet_action = QAction("删除该分类", menu)
        assign_menu = QMenu("归入分类", menu)
        assign_actions = {
            planet_key: QAction(planet_title, assign_menu)
            for planet_key, planet_title in self._assignment_planets()
        }
        for action in assign_actions.values():
            assign_menu.addAction(action)
        menu.addAction(open_action)
        if selection.kind == KnowledgeObjectKind.PLANET:
            menu.addAction(add_planet_action)
            menu.addAction(delete_planet_action)
        if selection.path is not None:
            menu.addAction(copy_path_action)
        if selection.kind in {
            KnowledgeObjectKind.STAR_NOTE,
            KnowledgeObjectKind.STAR_REFERENCE,
        }:
            menu.addMenu(assign_menu)

        open_action.triggered.connect(lambda: self.knowledge_selected.emit(selection))
        add_planet_action.triggered.connect(self._create_custom_planet)
        delete_planet_action.triggered.connect(
            lambda: self._delete_custom_planet(str(item.data(0, PLANET_KEY_ROLE) or selection.title))
        )
        assignment_target = self._assignment_target_from_tree_item(item, selection)
        if selection.path is not None:
            copy_path_action.triggered.connect(
                lambda: QApplication.clipboard().setText(str(selection.path))
            )
            for planet, action in assign_actions.items():
                action.triggered.connect(
                    lambda _checked=False, target=planet: self.assign_to_planet_requested.emit(
                        assignment_target,
                        target,
                    )
                )
        menu.exec(self.knowledge_tree.mapToGlobal(position))

    def _assignment_target_from_tree_item(
        self,
        item: QTreeWidgetItem,
        selection: KnowledgeSelection,
    ) -> dict[str, object]:
        object_kind = item.data(0, KNOWLEDGE_OBJECT_KIND_ROLE)
        object_key = item.data(0, KNOWLEDGE_OBJECT_KEY_ROLE)
        if object_kind and object_key:
            return {
                "object_kind": str(object_kind),
                "object_key": str(object_key),
                "path": str(selection.path) if selection.path is not None else "",
            }

        fallback_kind = "reference" if selection.kind == KnowledgeObjectKind.STAR_REFERENCE else "note"
        fallback_key = selection.path.stem if selection.path is not None else selection.title
        return {
            "object_kind": fallback_kind,
            "object_key": fallback_key,
            "path": str(selection.path) if selection.path is not None else "",
        }

    def _selection_from_tree_item(self, item: QTreeWidgetItem) -> KnowledgeSelection | None:
        kind_value = item.data(0, KNOWLEDGE_KIND_ROLE)
        if not kind_value:
            return None

        path_value = item.data(0, KNOWLEDGE_PATH_ROLE)
        path = Path(path_value) if path_value else None
        description = item.data(0, KNOWLEDGE_DESCRIPTION_ROLE) or ""
        title = self._strip_resource_prefix(item.text(0))
        return KnowledgeSelection(
            kind=KnowledgeObjectKind(kind_value),
            title=title,
            path=path,
            description=description,
            tags=self._infer_tags_for_title(title),
            satellites=tuple(self._satellites_for_tree_item(item)),
        )

    def _satellites_for_tree_item(self, item: QTreeWidgetItem) -> list[SatelliteItem]:
        satellites: list[SatelliteItem] = []
        children: list[QTreeWidgetItem] = []

        if item.data(0, KNOWLEDGE_KIND_ROLE) == KnowledgeObjectKind.SATELLITE.value:
            children.append(item)
        else:
            for index in range(item.childCount()):
                child = item.child(index)
                if child.data(0, KNOWLEDGE_KIND_ROLE) == KnowledgeObjectKind.SATELLITE.value:
                    children.append(child)

        for child in children:
            title = self._strip_resource_prefix(child.text(0))
            line_number = child.data(0, KNOWLEDGE_LINE_ROLE)
            satellites.append(
                SatelliteItem(
                    title=title,
                    kind="ui-entry",
                    host_title=item.text(0),
                    line_number=int(line_number) if line_number else None,
                    preview=child.data(0, KNOWLEDGE_DESCRIPTION_ROLE) or "",
                )
            )
        return satellites

    def _assignment_planets(self) -> list[tuple[str, str]]:
        return self.visible_planets_for_actions()

    def _assignment_key_for_planet(self, planet_title: str) -> str:
        clean_title = planet_title.strip() if planet_title else UNASSIGNED_PLANET_KEY
        for key, title, _description, _filter in DEFAULT_PLANETS:
            if clean_title in {key, title}:
                return key
        if clean_title in {UNASSIGNED_PLANET_KEY, UNASSIGNED_PLANET_TITLE}:
            return UNASSIGNED_PLANET_KEY
        return clean_title

    def _planet_is_hidden(self, planet_key: str) -> bool:
        clean_key = planet_key.strip() if planet_key else UNASSIGNED_PLANET_KEY
        display_title = self._display_planet_title(clean_key)
        return clean_key in self.hidden_planets or display_title in self.hidden_planets

    def _display_planet_title(self, planet_key: str) -> str:
        clean_key = planet_key.strip() if planet_key else UNASSIGNED_PLANET_KEY
        if clean_key in DEFAULT_PLANET_DISPLAY:
            return DEFAULT_PLANET_DISPLAY[clean_key]
        if clean_key in {UNASSIGNED_PLANET_KEY, "未归类"}:
            return UNASSIGNED_PLANET_TITLE
        return clean_key

    def _planet_description(self, planet_key: str) -> str:
        clean_key = planet_key.strip() if planet_key else UNASSIGNED_PLANET_KEY
        for key, _title, description, _filter in DEFAULT_PLANETS:
            if key == clean_key:
                return description
        if clean_key in {UNASSIGNED_PLANET_KEY, "未归类"}:
            return "尚未归入具体分类的对象"
        return "自定义分类"

    def _selected_planet_key(self) -> str | None:
        item = self.knowledge_tree.currentItem()
        while item is not None:
            if item.data(0, KNOWLEDGE_KIND_ROLE) == KnowledgeObjectKind.PLANET.value:
                key = item.data(0, PLANET_KEY_ROLE)
                return str(key) if key else self._strip_resource_prefix(item.text(0))
            item = item.parent()
        return None

    def _strip_resource_prefix(self, text: str) -> str:
        for prefix in (
            "工作区  ",
            "分类  ",
            "笔记  ",
            "文献  ",
            "主题  ",
            "资源  ",
            "关联  ",
            "星系  ",
            "行星  ",
            "星球  ",
            "卫星  ",
        ):
            if text.startswith(prefix):
                return text[len(prefix) :]
        return text

    def _resource_kind_label(
        self,
        title: str,
        path: Path | None,
        object_kind: str,
        planet_title: str,
    ) -> str:
        if object_kind == "reference":
            return "文献"

        haystack = f"{title} {path.name if path is not None else ''}".lower()
        planet = planet_title.lower()
        if planet_title == self._display_planet_title("Research") or any(
            token in haystack for token in ("研究", "research", "topic", "主题")
        ):
            return "主题"
        if planet.startswith("research"):
            return "主题"
        if planet_title == self._display_planet_title("Reading") or any(
            token in haystack for token in ("pdf", "avila", "srs_template", "r1", "r2", "r3", "r4")
        ):
            return "文献"
        return "笔记"

    def _iter_note_paths(self) -> list[Path]:
        if self.notes_dir is None or not self.notes_dir.exists():
            return []
        return sorted(self.notes_dir.rglob("*.md"), key=lambda item: item.name.lower())

    def _iter_reference_paths(self) -> list[Path]:
        if self.workspace_root is None:
            return []

        candidates: list[Path] = []
        for folder_name in ("references", "attachments"):
            folder = self.workspace_root / folder_name
            if folder.exists():
                candidates.extend(
                    path
                    for path in folder.rglob("*")
                    if path.is_file()
                    and path.suffix.lower() in {".pdf", ".pptx", ".bib", ".ris"}
                )
        return sorted(candidates, key=lambda item: item.name.lower())

    def _guess_planet_for_path(self, note_path: Path) -> str:
        override = self.planet_overrides.get(str(note_path.resolve()))
        if override:
            return override

        lowered = str(note_path).lower()
        if "inbox" in lowered:
            return "Inbox"
        if "reading" in lowered or "paper" in lowered or "pdf" in lowered:
            return "Reading"
        if "research" in lowered or "project" in lowered:
            return "Research"
        return "未归类"

    def _note_display_title(self, note_path: Path) -> str:
        return title_for_path(self.workspace_root, note_path) or note_path.stem

    def _extract_note_satellites(self, note_path: Path) -> list[SatelliteItem]:
        if not note_path.exists() or not note_path.is_file():
            return []
        try:
            text = note_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        return list(extract_markdown_satellites(text, self._note_display_title(note_path)))

    def _infer_tags_for_title(self, title: str) -> tuple[str, ...]:
        tags = []
        lowered = title.lower()
        if "pdf" in lowered or "文献" in title:
            tags.append("文献")
        if "inbox" in lowered:
            tags.append("收集箱")
        if "笔记" in title or title.endswith(".md"):
            tags.append("笔记")
        return tuple(tags)

    def _add_disabled_item(self, list_widget: QListWidget, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(item)

    def _add_disabled_tree_item(self, text: str) -> None:
        item = QTreeWidgetItem([text])
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.knowledge_tree.addTopLevelItem(item)
