"""Small helpers for ASCII-box rendering shared by the hero renderers."""

from __future__ import annotations


def state_dot(state: str) -> str:
    """Return a coloured state indicator string suitable for plain-text output.

    We don't use rich markup here because renderer output is also fed to the
    LLM — use unambiguous ASCII. The ``●`` plus the state name conveys state.
    """
    return f"● {state.upper()}"


def progress_bar(used: float, total: float | None, width: int = 26) -> str:
    """Render a [██░░░] progress bar. ``total is None`` means unlimited."""
    if total is None or total <= 0:
        return "[" + "─" * width + "]"
    ratio = 0.0 if total == 0 else max(0.0, min(1.0, used / total))
    filled = int(round(ratio * width))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def box(lines: list[str], *, title: str, width: int = 62) -> str:
    """Wrap ``lines`` in a unicode ASCII box with ``title`` in the top border."""
    inner = width - 2
    top = f"┌─ {title} " + "─" * max(0, inner - len(title) - 3) + "┐"
    bottom = "└" + "─" * inner + "┘"
    body = []
    for raw in lines:
        # pad/truncate to fit
        if len(raw) > inner - 2:
            raw = raw[: inner - 2]
        body.append("│ " + raw.ljust(inner - 2) + " │")
    return "\n".join([top, *body, bottom])


def format_msisdn(msisdn: str) -> str:
    """Format an 8-digit MSISDN as 'XXXX XXXX'."""
    s = str(msisdn or "")
    if len(s) == 8:
        return f"{s[:4]} {s[4:]}"
    return s


def format_iccid(iccid: str) -> str:
    """Format an ICCID with spaces every 4 digits."""
    s = str(iccid or "")
    return " ".join(s[i : i + 4] for i in range(0, len(s), 4))
