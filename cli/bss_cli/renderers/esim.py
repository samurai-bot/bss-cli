"""eSIM activation renderer — ICCID/IMSI/MSISDN + QR ASCII of the LPA string."""

from __future__ import annotations

from typing import Any

import qrcode

from ._box import format_iccid, format_msisdn


def _qr_ascii(payload: str, border: int = 1) -> list[str]:
    """Return the QR code as a list of ASCII lines using ▓/space blocks."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    # Pair rows to halve vertical size using block characters.
    # Use simple full/half block rendering: filled=▓▓, empty='  '.
    lines: list[str] = []
    for row in matrix:
        lines.append("".join("▓▓" if cell else "  " for cell in row))
    return lines


def render_esim_activation(activation: dict[str, Any]) -> str:
    """Render the eSIM activation card with ASCII QR code.

    Expects ``activation`` shaped like ``{iccid, imsi, msisdn, activationCode}``.
    """
    iccid = activation.get("iccid", "—")
    imsi = activation.get("imsi", "—")
    msisdn = activation.get("msisdn") or ""
    code = activation.get("activationCode", "")

    lpa = code if code.startswith("LPA:") else f"LPA:1${code}" if code else ""

    qr_lines = _qr_ascii(lpa or "LPA:1$smdp.bss-cli.local$UNKNOWN")
    qr_width = max(len(line) for line in qr_lines)

    imsi_fmt = imsi
    if imsi and len(imsi) >= 5:
        imsi_fmt = f"{imsi[:3]} {imsi[3:5]} {imsi[5:]}".strip()

    header = [
        "┌─ eSIM Activation " + "─" * 44 + "┐",
        "│" + " " * 62 + "│",
        f"│  ICCID:    {format_iccid(iccid):<47} │",
        f"│  IMSI:     {imsi_fmt:<47} │",
        f"│  MSISDN:   {format_msisdn(msisdn):<47} │",
        "│" + " " * 62 + "│",
    ]
    body = []
    annot = "Scan with phone camera to install eSIM"
    for i, q in enumerate(qr_lines):
        note = annot if i == 1 else ""
        body.append(f"│  {q.ljust(qr_width)}  {note:<{max(0, 58 - qr_width)}} │")
    footer = [
        "│" + " " * 62 + "│",
        f"│  Or enter manually:{' ' * 42} │",
        f"│  {lpa[:58]:<58} │",
        "│" + " " * 62 + "│",
        "└" + "─" * 62 + "┘",
    ]
    return "\n".join(header + body + footer)
