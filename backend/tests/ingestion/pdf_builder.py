"""Builds small, valid PDFs for the parser tests.

Committing binary fixtures would make these tests hard to read and impossible to
review, so the PDFs are written here in the PDF syntax, cross-reference table
included, which is what lets ``pypdf`` read them exactly as it would read a real file.
"""

from __future__ import annotations


def build_pdf(pages: list[str]) -> bytes:
    """Return a one-page-per-string PDF that draws each string on its page."""
    if not pages:
        raise ValueError("a PDF needs at least one page")

    objects: dict[int, bytes] = {}
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(len(pages)))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii")
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    for index, text in enumerate(pages):
        page_id = 4 + 2 * index
        content_id = page_id + 1
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")
        stream = f"BT /F1 12 Tf 72 720 Td ({_escape(text)}) Tj ET".encode("latin-1")
        objects[content_id] = (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode("ascii") + objects[number] + b"\nendobj\n"

    start_xref = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for number in range(1, size):
        out += b"%010d 00000 n \n" % offsets[number]
    out += (f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{start_xref}\n%%EOF\n").encode(
        "ascii"
    )
    return bytes(out)


def _escape(text: str) -> str:
    """Escape the characters that are special inside a PDF string literal."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
