"""Generate a multi-resolution Windows .ico from Work Memory's programmatic brand badge."""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from work_memory.ui.app_icon import _ICON_SIZES, build_brand_pixmap


def _pixmap_to_ico_frame(size: int) -> tuple[int, int, bytes]:
    """Render ``build_brand_pixmap(size)`` and encode as PNG (256px) or 32-bit DIB (<=128px)."""
    pixmap = build_brand_pixmap(size)
    if size >= 256:
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buf, "PNG")
        return size, size, bytes(buf.data())

    img = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    width = img.width()
    height = img.height()
    # ICO DIBs are stored bottom-up and declare doubled height (XOR + AND masks).
    dib_header = struct.pack(
        "<IIIHHIIIIII",
        40,          # biSize (BITMAPINFOHEADER)
        width,       # biWidth
        height * 2,  # biHeight (includes AND mask)
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression (BI_RGB)
        width * height * 4,
        0,
        0,
        0,
        0,
    )
    xor_rows = bytearray()
    for y in range(height - 1, -1, -1):
        ptr = img.constScanLine(y)
        xor_rows.extend(bytes(ptr[: width * 4]))  # type: ignore[index]

    # 1-bit AND mask padded to 4-byte row stride (0 = use per-pixel alpha channel).
    and_stride = ((width + 31) // 32) * 4
    and_mask = b"\x00" * (and_stride * height)
    return width, height, dib_header + bytes(xor_rows) + and_mask


def build_work_memory_ico(output_path: Path) -> Path:
    """Write a multi-resolution Windows ``.ico`` matching ``build_app_icon()``."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    del app

    frames = [_pixmap_to_ico_frame(sz) for sz in _ICON_SIZES]
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = bytearray()
    payload = bytearray()

    for width, height, data in frames:
        w_byte = 0 if width >= 256 else width
        h_byte = 0 if height >= 256 else height
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                w_byte,
                h_byte,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        payload.extend(data)
        offset += len(data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(header + bytes(entries) + bytes(payload))
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Work Memory .ico asset.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "work_memory.ico",
    )
    args = parser.parse_args()
    out = build_work_memory_ico(args.output)
    print(f"Generated {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
