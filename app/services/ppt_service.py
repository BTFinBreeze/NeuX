"""Conversion helpers for rendering PowerPoint (.pptx) files.

The app has no built-in PPT renderer, so slides are converted to a PDF via a
headless LibreOffice installation. The resulting PDF is cached under the
workspace so subsequent opens are instant.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

PPT_SUFFIXES: frozenset[str] = frozenset({".pptx"})

_COMMON_SOFFICE_PATHS: tuple[str, ...] = (
    # Windows
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    # macOS
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    # Linux (snap / apt / flatpak)
    "/usr/bin/libreoffice",
    "/usr/bin/soffice",
    "/snap/bin/libreoffice",
)

_CONVERSION_TIMEOUT_SECONDS = 240


def find_soffice_executable() -> str | None:
    """Locate the LibreOffice command-line binary."""
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for candidate in _COMMON_SOFFICE_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def soffice_missing_help() -> str:
    """Human readable help when LibreOffice cannot be found."""
    return (
        "当前系统没有检测到 LibreOffice，无法把 PPT (.pptx) 渲染成幻灯片。\n\n"
        "请先安装 LibreOffice：\n"
        "- Windows: https://www.libreoffice.org/download/download-libreoffice/\n"
        "- 或运行  winget install --id TheDocumentFoundation.LibreOffice\n\n"
        "安装完成后重新打开 PPT 即可。"
    )


def _soffice_user_profile_dir(cache_dir: Path) -> Path:
    profile_dir = cache_dir / ".lo_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def _cache_key_file(cache_dir: Path, pptx_path: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    stat = pptx_path.stat()
    fingerprint = f"{stat.st_size}-{stat.st_mtime_ns}"
    return cache_dir / f"{pptx_path.stem}-{fingerprint}.pdf"


def convert_pptx_to_pdf(pptx_path: str | Path, cache_dir: str | Path) -> Path:
    """Convert a .pptx file to a PDF and return the cached PDF path.

    Raises RuntimeError when LibreOffice is missing or conversion fails.
    """
    source = Path(pptx_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise RuntimeError(f"PPT 文件不存在：{source}")

    cache = Path(cache_dir).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    cached_pdf = _cache_key_file(cache, source)
    if cached_pdf.exists() and cached_pdf.stat().st_size > 0:
        return cached_pdf

    soffice = find_soffice_executable()
    if soffice is None:
        raise RuntimeError(soffice_missing_help())

    profile_dir = _soffice_user_profile_dir(cache)
    user_install_arg = f"-env:UserInstallation={profile_dir.as_uri()}"
    command = [
        soffice,
        "--headless",
        "--norestore",
        user_install_arg,
        "--convert-to",
        "pdf",
        "--outdir",
        str(cache),
        str(source),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(soffice_missing_help()) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("PPT 转 PDF 超时，请稍后重试。") from None
    except OSError as error:
        raise RuntimeError(f"启动 LibreOffice 失败：{error}") from None

    produced = cache / f"{source.stem}.pdf"
    if not produced.exists() or produced.stat().st_size <= 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        snippet = f"\n\n转换输出：{detail[:800]}" if detail else ""
        raise RuntimeError(f"LibreOffice 转换 PPT 失败（退出码 {completed.returncode}）。{snippet}")

    try:
        produced.replace(cached_pdf)
    except OSError:
        return produced
    return cached_pdf
