"""Offline document extraction. OCR evidence is descriptive only, never numeric."""
import csv
from dataclasses import asdict, dataclass
import io
import math
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import time

from bs4 import BeautifulSoup
import pymupdf


class ExtractionError(ValueError):
    def __init__(self, reason, *, quarantined=True):
        super().__init__(reason)
        self.reason, self.quarantined = reason, quarantined


@dataclass(frozen=True)
class ExtractedPage:
    page: int
    text: str
    extraction_kind: str = "native"
    numeric_eligible: bool = True
    section: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    pages: tuple[ExtractedPage, ...]
    metadata: dict

    @property
    def text(self):
        return "\n\n".join(p.text for p in self.pages)

    def page_metadata(self):
        return [asdict(p) for p in self.pages]


def table_text(rows, headers=None):
    """Keep a header with every row; never guess a missing numeric-table header."""
    rows = [[str(cell or "").strip() for cell in row] for row in rows]
    if not rows:
        return ""
    headers = [str(cell or "").strip() for cell in (headers or rows[0])]
    numeric = any(re.search(r"\d", cell) for row in rows for cell in row)
    valid = (len(headers) == len(rows[0]) and all(headers)
             and all(re.search(r"[^\W\d_]", cell, re.UNICODE) for cell in headers))
    if numeric and not valid:
        raise ExtractionError("TABLE_HEADER_MISSING")
    if not valid:
        return "\n".join(" | ".join(row) for row in rows)
    body = rows[1:] if rows[0] == headers else rows
    if any(len(row) != len(headers) for row in body):
        raise ExtractionError("TABLE_HEADER_MISSING")
    return "\n".join(" | ".join(f"{header}: {cell}" for header, cell in zip(headers, row)) for row in body)


class Extractor:
    def __init__(self, settings, *, runner=subprocess.run, monotonic=time.monotonic):
        self.settings, self.runner, self.monotonic = settings, runner, monotonic

    @property
    def profile(self):
        return {"extraction_version": "utc-b2-1", "ocr_languages": "vie+eng",
                "ocr_confidence": 90, "ocr_min_characters": 30,
                "max_pages": self.settings.max_document_pages}

    def extract(self, data: bytes, media_type: str, *, metadata=None, deadline=None):
        deadline = min(deadline if deadline is not None else float("inf"),
                       self.monotonic() + self.settings.ingestion_item_timeout_seconds)
        context = {key: (metadata or {}).get(key) for key in ("year", "campus", "major_code", "method")}
        media_type = media_type.split(";", 1)[0].lower().strip()
        self._remaining(deadline)
        if media_type == "text/html":
            soup = BeautifulSoup(data, "html.parser")
            heading = soup.title or soup.h1
            if heading and re.fullmatch(r"\s*(?:404(?:\s+not found)?|403(?:\s+forbidden)?|not found|access denied|service unavailable|internal server error)\s*",
                                         heading.get_text(" ", strip=True), re.I):
                raise ExtractionError("HTML_ERROR_PAGE", quarantined=False)
            for tag in soup.select("script,style,nav,header,footer,aside,form,noscript,[hidden],[aria-hidden=true]"):
                tag.decompose()
            root = soup.select_one("article,main,[role=main],.field--name-body,.field-name-body") or soup.body or soup
            for table in root.find_all("table"):
                rows = [[cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"], recursive=False)]
                        for row in table.find_all("tr")]
                rows = [row for row in rows if row]
                headers = [cell.get_text(" ", strip=True) for cell in table.select("tr:first-child th")]
                # HTML explicitly identifies headers; td-only numeric tables are unsafe.
                if not headers and any(re.search(r"\d", cell) for row in rows for cell in row):
                    raise ExtractionError("TABLE_HEADER_MISSING")
                table.replace_with(soup.new_string(table_text(rows, headers)))
            result = ExtractionResult((ExtractedPage(1, root.get_text("\n", strip=True)),), context)
        elif media_type == "text/plain":
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise ExtractionError("INVALID_UTF8", quarantined=False) from None
            if any(ord(c) < 32 and c not in "\n\r\t\f" for c in text):
                raise ExtractionError("INVALID_UTF8", quarantined=False)
            result = ExtractionResult((ExtractedPage(1, text),), context)
        elif media_type == "application/pdf":
            result = self._pdf(data, context, deadline)
        elif media_type in {"image/png", "image/jpeg"}:
            try:
                with pymupdf.open(stream=data, filetype="png" if media_type == "image/png" else "jpeg") as image:
                    if image.page_count != 1:
                        raise ExtractionError("INVALID_IMAGE", quarantined=False)
            except ExtractionError:
                raise
            except Exception:
                raise ExtractionError("INVALID_IMAGE", quarantined=False) from None
            result = ExtractionResult((self._ocr(data, 1, deadline),), context)
        else:
            raise ExtractionError("UNSUPPORTED_MEDIA", quarantined=False)
        self._remaining(deadline)
        if not result.text.strip():
            raise ExtractionError("EMPTY_TEXT")
        return result

    def _remaining(self, deadline):
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            raise ExtractionError("ITEM_TIMEOUT")
        return remaining

    def _pdf(self, data, metadata, deadline):
        try:
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                if doc.needs_pass or not doc.page_count:
                    raise ExtractionError("INVALID_PDF", quarantined=False)
                if doc.page_count > self.settings.max_document_pages:
                    raise ExtractionError("PAGE_LIMIT")
                pages = []
                for number, page in enumerate(doc, 1):
                    self._remaining(deadline)
                    text = page.get_text("text", sort=True).strip()
                    if len("".join(text.split())) < 30:
                        pages.append(self._ocr(page.get_pixmap(dpi=200).tobytes("png"), number, deadline))
                        continue
                    tables = []
                    for table in page.find_tables().tables:
                        tables.append(table_text(table.extract(), table.header.names))
                    if tables:
                        # Remove loose cells; only retain rows with their associated headers.
                        boxes = [table.bbox for table in page.find_tables().tables]
                        text = "\n".join(block[4].strip() for block in page.get_text("blocks", sort=True)
                                         if not any(pymupdf.Rect(block[:4]).intersects(pymupdf.Rect(box)) for box in boxes))
                        text += "\n" + "\n".join(tables)
                    pages.append(ExtractedPage(number, text))
                return ExtractionResult(tuple(pages), metadata)
        except ExtractionError:
            raise
        except Exception:
            raise ExtractionError("INVALID_PDF", quarantined=False) from None

    def _ocr(self, data, page, deadline):
        with TemporaryDirectory(prefix="utc-ocr-") as folder:
            path = Path(folder) / "page.png"
            path.write_bytes(data)
            env = os.environ.copy()
            if self.settings.tessdata_prefix:
                env["TESSDATA_PREFIX"] = str(self.settings.tessdata_prefix)
            try:
                output = self.runner([self.settings.tesseract_cmd, str(path), "stdout", "-l", "vie+eng", "tsv"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                    timeout=min(self.settings.ocr_page_timeout_seconds, self._remaining(deadline)),
                    shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except FileNotFoundError:
                raise ExtractionError("OCR_UNAVAILABLE") from None
            except subprocess.TimeoutExpired:
                raise ExtractionError("OCR_TIMEOUT") from None
            except OSError:
                raise ExtractionError("OCR_FAILED") from None
            self._remaining(deadline)
            if output.returncode:
                raise ExtractionError("OCR_UNAVAILABLE")
            words, confidences = [], []
            try:
                for row in csv.DictReader(io.StringIO(output.stdout), delimiter="\t"):
                    if row["level"] != "5" or not row["text"].strip():
                        continue
                    confidence = float(row["conf"])
                    if not math.isfinite(confidence) or not 0 <= confidence <= 100:
                        raise ValueError
                    words.append(row["text"].strip())
                    confidences.append(confidence)
            except (KeyError, ValueError, TypeError, csv.Error):
                raise ExtractionError("OCR_LOW_QUALITY") from None
            text = " ".join(words)
            if (len("".join(text.split())) < 30 or not confidences
                    or sum(confidences) / len(confidences) < 90):
                raise ExtractionError("OCR_LOW_QUALITY")
            return ExtractedPage(page, text, "ocr", False)
