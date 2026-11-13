"""Regenerate synthetic offline PDF/PNG assets with the locked PyMuPDF dependency.

Run from backend: .venv/Scripts/python.exe tests/fixtures/build_ingestion.py
GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC. Never place these in runtime/demo storage.
"""
from pathlib import Path
import pymupdf

ROOT = Path(__file__).parent / "utc"


def table_pdf(headers=True):
    doc = pymupdf.open()
    page = doc.new_page(width=500, height=300)
    page.insert_text((30, 30), "SYNTHETIC TABLE - TEST ONLY, NO OFFICIAL UTC FACTS")
    rows = [["Program", "Score (points)"], ["DEMO-A", "25"], ["DEMO-B", "26"]] if headers else [["DEMO-A", "25"], ["DEMO-B", "26"]]
    for row, cells in enumerate(rows):
        for col, text in enumerate(cells):
            page.insert_text((40 + col * 190, 70 + row * 30), text)
    for y in range(50, 51 + len(rows) * 30, 30):
        page.draw_line((30, y), (420, y))
    for x in [30, 220, 420]:
        page.draw_line((x, 50), (x, 50 + len(rows) * 30))
    data = doc.tobytes()
    doc.close()
    return data


if __name__ == "__main__":
    ROOT.mkdir(exist_ok=True)
    with pymupdf.open() as doc:
        for text in ["SYNTHETIC native description for offline testing only.", "SYNTHETIC second page, never official UTC information."]:
            doc.new_page(width=500, height=200).insert_text((30, 50), text)
        (ROOT / "native.pdf").write_bytes(doc.tobytes())
        image = doc[0].get_pixmap().tobytes("png")
        (ROOT / "image.png").write_bytes(image)
    with pymupdf.open() as doc:
        page = doc.new_page(width=500, height=200)
        page.insert_image(page.rect, stream=image)
        (ROOT / "scan.pdf").write_bytes(doc.tobytes())
    (ROOT / "table.pdf").write_bytes(table_pdf())
    (ROOT / "table-no-header.pdf").write_bytes(table_pdf(False))
