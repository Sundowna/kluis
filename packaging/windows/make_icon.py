"""Builds packaging/windows/kluis.ico from Kluis's SVG logo (the Linux icon), for Kluis.exe and the installer.

Run with the MSYS2 Python that has GdkPixbuf + librsvg: python packaging/windows/make_icon.py
An .ico is a small directory of images; Windows Vista and later read PNG images inside it.
"""
import os
import struct
import sys

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "..", "..", "kluis", "data", "icons", "dev.kluis.Kluis.svg")
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png(size):
    pb = GdkPixbuf.Pixbuf.new_from_file_at_size(SVG, size, size)
    ok, data = pb.save_to_bufferv("png", [], [])
    assert ok
    return bytes(data)


def main(out):
    images = [(s, png(s)) for s in SIZES]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    with open(out, "wb") as fh:
        fh.write(head + entries + blobs)
    print(f"{out}: {len(images)} sizes")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "kluis.ico"))
