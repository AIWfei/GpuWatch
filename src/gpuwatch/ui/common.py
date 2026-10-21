from __future__ import annotations

from PySide6.QtWidgets import QWidget


def set_invalid(widget: QWidget, invalid: bool, tip: str = "") -> None:
    widget.setProperty("invalid", bool(invalid))
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.setToolTip(tip if invalid else "")


def clear_invalid(widgets: list[QWidget]) -> None:
    for widget in widgets:
        set_invalid(widget, False)


def mark_invalid(errors: list[tuple[QWidget, str]]) -> list[QWidget]:
    marked: list[QWidget] = []
    for widget, message in errors:
        set_invalid(widget, True, message)
        marked.append(widget)
    return marked


def format_mib_pair(used: int | None, total: int | None) -> str:
    if used is None or total is None:
        return "N/A"
    return f"{used / 1024:.1f} / {total / 1024:.1f} GiB"
