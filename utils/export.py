"""Helpers for exporting generated projects."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Iterable


def _get(item: Any, key: str) -> str:
    """Read ``key`` from a dict or from an object attribute."""
    if isinstance(item, dict):
        return item[key]
    return getattr(item, key)


def _check_filename(filename: str) -> str:
    if (
        not filename
        or filename.startswith(("/", "\\"))
        or "\\" in filename
        or ".." in filename.split("/")
    ):
        raise ValueError(f"Unsafe filename in generated project: {filename!r}")
    return filename


def create_zip(files: Iterable[Any]) -> bytes:
    """Create a ZIP archive from generated files and return its bytes.

    ``files`` may contain GeneratedFile objects or dicts with ``filename`` and
    ``code`` keys. Nothing is executed; the code is only written as text.
    """
    files = list(files)
    if not files:
        raise ValueError("There are no files to export.")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in files:
            filename = _check_filename(_get(item, "filename"))
            archive.writestr(filename, _get(item, "code"))
    return buffer.getvalue()


def slugify(text: str, default: str = "project") -> str:
    """Turn an app name into a safe file-name stem."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or default
