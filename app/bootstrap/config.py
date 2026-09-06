from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    app_name: str = "NeuX"
    organization_name: str = "NeuX Team"


@dataclass(slots=True)
class WorkspaceConfig:
    workspace_root: Path
    notes_dir: Path
    attachments_dir: Path
    exports_dir: Path
    agni_dir: Path
    db_path: Path
    state_path: Path
    cache_dir: Path