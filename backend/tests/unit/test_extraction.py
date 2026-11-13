"""GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC. Offline native/OCR fixtures."""
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest

from app.services.extraction import Extractor, ExtractionError

ASSETS = Path(__file__).parents[1] / "fixtures/utc"


@pytest.fixture
def native_pdf():
    with pymupdf.open() as doc:
        for text in ("SYNTHETIC admissions description for testing only.", "SYNTHETIC second page description for testing only."):
            doc.new_page().insert_text((50, 50), text)
        return doc.tobytes()


def tsv(confidence=95, text="SYNTHETIC description for testing only never official facts"):
    return "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tconf\ttext\n" + "\n".join(
        f"5\t1\t1\t1\t1\t{i}\t{confidence}\t{word}" for i, word in enumerate(text.split(), 1))


def test_html_txt_and_native_pages(settings, native_pdf):
    extractor = Extractor(settings)
    html = b"<html><title>NOT YEAR 2026</title><nav>REMOVE</nav><main><h1>SYNTHETIC</h1><p>Body description</p></main><script>REMOVE</script></html>"
    result = extractor.extract(html, "text/html")
    assert "REMOVE" not in result.text and "Body description" in result.text
    assert result.metadata["year"] is None
    txt = extractor.extract("GIẢ LẬP\r\nNội dung UTF-8".encode(), "text/plain")
    assert txt.pages[0].page == 1 and "Nội dung" in txt.text
    native = extractor.extract(native_pdf, "application/pdf")
    assert [p.page for p in native.pages] == [1, 2]
    assert all(p.extraction_kind == "native" for p in native.pages)
    with pytest.raises(ExtractionError, match="INVALID_UTF8"):
        extractor.extract(b"\xff\xfe", "text/plain")
    with pytest.raises(ExtractionError, match="HTML_ERROR_PAGE"):
        extractor.extract(b"<html><title>404 Not Found</title><body>page missing</body></html>", "text/html")


def test_ocr_gate_and_command(settings):
    with pymupdf.open() as doc:
        doc.new_page()
        image = doc[0].get_pixmap().tobytes("png")
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=tsv(), stderr=""))
    result = Extractor(settings, runner=runner).extract(image, "image/png")
    assert result.pages[0].extraction_kind == "ocr" and not result.pages[0].numeric_eligible
    args, kwargs = runner.call_args
    assert args[0][2:] == ["stdout", "-l", "vie+eng", "tsv"]
    assert 0 < kwargs["timeout"] <= 60 and kwargs.get("shell", False) is False
    for output in (tsv(89), tsv(95, "too short"), tsv(float("nan"))):
        runner.return_value.stdout = output
        with pytest.raises(ExtractionError, match="OCR_LOW_QUALITY") as error:
            Extractor(settings, runner=runner).extract(image, "image/png")
        assert error.value.quarantined
    runner.side_effect = FileNotFoundError()
    with pytest.raises(ExtractionError, match="OCR_UNAVAILABLE"):
        Extractor(settings, runner=runner).extract(image, "image/png")
    runner.side_effect = subprocess.TimeoutExpired("tesseract", 60)
    with pytest.raises(ExtractionError, match="OCR_TIMEOUT"):
        Extractor(settings, runner=runner).extract(image, "image/png")


def test_pdf_limits_corruption_and_table_headers(settings):
    extractor = Extractor(settings)
    with pytest.raises(ExtractionError, match="INVALID_PDF"):
        extractor.extract(b"%PDF-corrupt", "application/pdf")
    with pymupdf.open() as doc:
        for _ in range(201): doc.new_page()
        data = doc.tobytes()
    with pytest.raises(ExtractionError, match="PAGE_LIMIT"):
        extractor.extract(data, "application/pdf")
    with pytest.raises(ExtractionError, match="TABLE_HEADER_MISSING"):
        extractor.extract(b"<main><table><tr><td>DEMO</td><td>25</td></tr></table></main>", "text/html")
    result = extractor.extract(b"<main><table><tr><th>Program</th><th>Score (points)</th></tr><tr><td>DEMO</td><td>25</td></tr></table></main>", "text/html")
    assert "Score (points)" in result.pages[0].text and "25" in result.text


def test_pdf_table_fixtures_and_scan_fallback(settings):
    extractor = Extractor(settings)
    result = extractor.extract((ASSETS / "table.pdf").read_bytes(), "application/pdf")
    assert "Score (points): 25" in result.text and "Program: DEMO-A" in result.text
    assert result.pages[0].numeric_eligible
    with pytest.raises(ExtractionError, match="TABLE_HEADER_MISSING"):
        extractor.extract((ASSETS / "table-no-header.pdf").read_bytes(), "application/pdf")
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=tsv(90), stderr=""))
    scan = Extractor(settings, runner=runner).extract((ASSETS / "scan.pdf").read_bytes(), "application/pdf")
    assert scan.pages[0].extraction_kind == "ocr" and not scan.pages[0].numeric_eligible
    assert runner.call_count == 1


def test_item_budget_and_mixed_pdf_quarantines_whole_item(settings):
    clock = SimpleNamespace(value=0.)
    def runner(*_a, **kwargs):
        assert kwargs["timeout"] <= 1
        clock.value += 2
        return SimpleNamespace(returncode=0, stdout=tsv(), stderr="")
    extractor = Extractor(settings, runner=runner, monotonic=lambda: clock.value)
    with pytest.raises(ExtractionError, match="ITEM_TIMEOUT"):
        extractor.extract((ASSETS / "image.png").read_bytes(), "image/png", deadline=1)
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 50), "SYNTHETIC valid native description for this mixed document")
        doc.new_page()
        data = doc.tobytes()
    extractor = Extractor(settings, runner=Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="missing vie data")))
    with pytest.raises(ExtractionError, match="OCR_UNAVAILABLE") as error:
        extractor.extract(data, "application/pdf")
    assert error.value.quarantined


@pytest.mark.parametrize("characters,confidence,accepted", [(29,95,False),(30,90,True),(30,89.99,False)])
def test_exact_ocr_quality_boundaries(settings, characters, confidence, accepted):
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=tsv(confidence, "x" * characters), stderr=""))
    extractor = Extractor(settings, runner=runner)
    if accepted:
        result = extractor.extract((ASSETS / "image.png").read_bytes(), "image/png")
        assert not result.pages[0].numeric_eligible
    else:
        with pytest.raises(ExtractionError, match="OCR_LOW_QUALITY"):
            extractor.extract((ASSETS / "image.png").read_bytes(), "image/png")
