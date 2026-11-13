"""Explicit local Tesseract smoke; never part of the default offline pytest suite.

Run from backend: uv run --locked --offline python tests/smoke/check_ocr.py
Uses configured Tesseract and generated synthetic Vietnamese images/PDF only.
"""
import argparse
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pymupdf

from app.api.routes.health import probe_ocr
from app.core.config import get_settings
from app.services.extraction import Extractor, ExtractionError


def synthetic_documents(font):
    """Generate local fixtures, never admissions facts or downloaded documents."""
    with pymupdf.open() as doc:
        page = doc.new_page(width=720, height=260)
        page.insert_font(fontname="fixture", fontfile=str(font))
        page.insert_text((35, 60), "GIẢ LẬP - KHÔNG PHẢI THÔNG TIN UTC", fontname="fixture", fontsize=20)
        page.insert_text((35, 105), "Tài liệu này dùng để kiểm thử nhận dạng tiếng Việt.", fontname="fixture", fontsize=20)
        page.insert_text((35, 150), "SYNTHETIC document for local OCR testing only.", fontname="fixture", fontsize=20)
        native = doc.tobytes()
        image = page.get_pixmap(dpi=200).tobytes("png")
    with pymupdf.open() as doc:
        page = doc.new_page(width=720, height=260)
        page.insert_image(page.rect, stream=image)
        scan = doc.tobytes()
    with pymupdf.open() as doc:
        page = doc.new_page(width=720, height=260)
        blank = page.get_pixmap(dpi=100).tobytes("png")
    return native, image, scan, blank


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/arial.ttf"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    report = {"synthetic_only": True, "ocr_available": probe_ocr(settings), "cases": []}
    if not report["ocr_available"]:
        raise SystemExit("Tesseract with both vie and eng is required; check local OCR configuration.")
    if not args.font.is_file():
        raise SystemExit("Provide a Vietnamese-capable TrueType font with --font.")
    version = subprocess.run([settings.tesseract_cmd, "--version"], capture_output=True, text=True,
                             timeout=5, check=True)
    report["version"] = version.stdout.splitlines()[0]
    calls = []

    def measured_runner(*positional, **kwargs):
        # Delegate to the actual process, preserving the extractor's real timeout/env.
        result = subprocess.run(*positional, **kwargs)
        confidences = [float(row["conf"]) for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t")
                       if row.get("level") == "5" and row.get("text", "").strip() and float(row["conf"]) >= 0]
        calls.append({"mean_confidence": sum(confidences) / len(confidences) if confidences else None})
        return result

    extractor = Extractor(settings, runner=measured_runner)
    native, image, scan, blank = synthetic_documents(args.font)
    for name, data, media, expected_kind in [
        ("vietnamese_native_pdf", native, "application/pdf", "native"),
        ("vietnamese_png", image, "image/png", "ocr"),
        ("vietnamese_scan_pdf", scan, "application/pdf", "ocr"),
    ]:
        started, before = time.monotonic(), len(calls)
        result = extractor.extract(data, media)
        page = result.pages[0]
        assert len(result.pages) == 1 and page.page == 1
        assert page.extraction_kind == expected_kind
        assert "tiếng việt" in unicodedata.normalize("NFC", result.text).casefold()
        assert page.numeric_eligible == (expected_kind == "native")
        assert len(calls) - before == (1 if expected_kind == "ocr" else 0)
        report["cases"].append({"name": name, "status": "pass", "extraction_kind": page.extraction_kind,
            "numeric_eligible": page.numeric_eligible, "characters": len("".join(result.text.split())),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "mean_confidence": calls[-1]["mean_confidence"] if expected_kind == "ocr" else None})
    try:
        extractor.extract(blank, "image/png")
    except ExtractionError as error:
        assert error.quarantined and error.reason == "OCR_LOW_QUALITY"
        report["cases"].append({"name": "blank_png", "status": "pass", "reason": error.reason, "quarantined": True})
    else:
        raise AssertionError("Blank image must be quarantined")
    report["status"] = "pass"
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
