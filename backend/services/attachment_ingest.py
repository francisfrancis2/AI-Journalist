"""User-uploaded source extraction for story ideation and scripting."""

from __future__ import annotations

import html
import io
import re
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from fastapi import UploadFile

from backend.models.research import RawSource, SourceCredibility, SourceType


MAX_ATTACHMENT_COUNT = 5
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARS = 18_000
MAX_TOTAL_ATTACHMENT_CHARS = 60_000

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".jpeg", ".jpg", ".xls", ".xlsx"}
_XML_SPREADSHEET_NS = "{urn:schemas-microsoft-com:office:spreadsheet}"
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class AttachmentExtractionError(ValueError):
    """Raised when an uploaded attachment is invalid or too large."""


def _clean_text(value: str) -> str:
    cleaned = html.unescape(value or "")
    cleaned = cleaned.replace("\x00", " ")
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _truncate_text(value: str, limit: int = MAX_EXTRACTED_CHARS) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[Attachment text truncated.]"


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "attachment").name.strip()
    return name or "attachment"


def _extract_docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        document_names = [
            name
            for name in archive.namelist()
            if name == "word/document.xml"
            or name.startswith("word/header")
            or name.startswith("word/footer")
        ]
        chunks: list[str] = []
        for name in document_names:
            root = ElementTree.fromstring(archive.read(name))
            for node in root.iter():
                if node.tag == f"{_WORD_NS}t" and node.text:
                    chunks.append(node.text)
                elif node.tag in {f"{_WORD_NS}br", f"{_WORD_NS}p"}:
                    chunks.append("\n")
        return _clean_text(" ".join(chunks))


def _extract_xlsx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f".//{_SPREADSHEET_NS}si"):
                parts = [
                    text_node.text or ""
                    for text_node in item.findall(f".//{_SPREADSHEET_NS}t")
                ]
                shared_strings.append(_clean_text("".join(parts)))

        lines: list[str] = []
        sheet_names = sorted(
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        for sheet_index, sheet_name in enumerate(sheet_names[:8], start=1):
            root = ElementTree.fromstring(archive.read(sheet_name))
            lines.append(f"Sheet {sheet_index}:")
            for row in root.findall(f".//{_SPREADSHEET_NS}row")[:120]:
                cells: list[str] = []
                for cell in row.findall(f"{_SPREADSHEET_NS}c")[:40]:
                    value_node = cell.find(f"{_SPREADSHEET_NS}v")
                    if value_node is None or value_node.text is None:
                        continue
                    value = value_node.text
                    if cell.attrib.get("t") == "s":
                        try:
                            value = shared_strings[int(value)]
                        except (IndexError, ValueError):
                            pass
                    cells.append(_clean_text(value))
                if cells:
                    lines.append(" | ".join(cells))
        return _clean_text("\n".join(lines))


def _extract_xml_spreadsheet_text(data: bytes) -> str:
    root = ElementTree.fromstring(data)
    lines: list[str] = []
    for worksheet in root.findall(f".//{_XML_SPREADSHEET_NS}Worksheet"):
        name = worksheet.attrib.get(f"{_XML_SPREADSHEET_NS}Name") or "Worksheet"
        lines.append(f"Sheet: {name}")
        for row in worksheet.findall(f".//{_XML_SPREADSHEET_NS}Row")[:160]:
            cells = [
                _clean_text(data_node.text or "")
                for data_node in row.findall(f".//{_XML_SPREADSHEET_NS}Data")
                if (data_node.text or "").strip()
            ][:40]
            if cells:
                lines.append(" | ".join(cells))
    return _clean_text("\n".join(lines))


def _extract_xls_text(data: bytes) -> str:
    prefix = data[:300].lstrip().lower()
    if prefix.startswith(b"<?xml") or b"<workbook" in prefix:
        return _extract_xml_spreadsheet_text(data)

    try:
        import xlrd  # type: ignore[import]
    except ImportError:
        return ""

    workbook = xlrd.open_workbook(file_contents=data)
    lines: list[str] = []
    for sheet in workbook.sheets()[:8]:
        lines.append(f"Sheet: {sheet.name}")
        for row_idx in range(min(sheet.nrows, 160)):
            cells = [
                _clean_text(str(sheet.cell_value(row_idx, col_idx)))
                for col_idx in range(min(sheet.ncols, 40))
            ]
            cells = [cell for cell in cells if cell]
            if cells:
                lines.append(" | ".join(cells))
    return _clean_text("\n".join(lines))


def _extract_pdf_text_fallback(data: bytes) -> str:
    raw = data.decode("latin-1", errors="ignore")
    candidates = re.findall(r"\(([^()]{2,500})\)\s*Tj", raw)
    candidates.extend(
        re.findall(r"\(([^()]{2,500})\)", raw[:250_000])
    )
    text = " ".join(
        candidate.encode("latin-1", errors="ignore").decode("unicode_escape", errors="ignore")
        for candidate in candidates
    )
    return _clean_text(text)


def _extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import]

        reader = PdfReader(io.BytesIO(data))
        return _clean_text("\n".join(page.extract_text() or "" for page in reader.pages[:80]))
    except Exception:
        return _extract_pdf_text_fallback(data)


def _extract_jpeg_metadata(data: bytes) -> str:
    try:
        from PIL import Image  # type: ignore[import]

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            metadata = [f"JPEG image dimensions: {width} x {height} pixels."]
            exif = getattr(image, "getexif", lambda: {})()
            if exif:
                metadata.append(f"EXIF fields detected: {len(exif)}.")
            return " ".join(metadata)
    except Exception:
        return "JPEG image uploaded. No local OCR or image metadata extraction was available."


def _extract_text_for_extension(data: bytes, extension: str) -> tuple[str, str]:
    if extension == ".pdf":
        return _extract_pdf_text(data), "PDF text extraction"
    if extension == ".docx":
        return _extract_docx_text(data), "DOCX document text extraction"
    if extension == ".xlsx":
        return _extract_xlsx_text(data), "XLSX worksheet extraction"
    if extension == ".xls":
        return _extract_xls_text(data), "XLS worksheet extraction"
    if extension in {".jpeg", ".jpg"}:
        return _extract_jpeg_metadata(data), "JPEG metadata extraction"
    return "", "Unsupported attachment type"


def _attachment_source(
    *,
    filename: str,
    content_type: str | None,
    size_bytes: int,
    extracted_text: str,
    extraction_note: str,
) -> RawSource:
    content = (
        f"User-uploaded attachment: {filename}\n"
        f"Extraction: {extraction_note}\n"
        f"File size: {size_bytes} bytes\n\n"
        f"{extracted_text or 'No extractable text was found in this attachment. Treat it as a user-provided reference file, not a verified external source.'}"
    )
    return RawSource(
        source_type=SourceType.USER_ATTACHMENT,
        title=f"Uploaded attachment: {filename}",
        content=_truncate_text(content),
        credibility=SourceCredibility.MEDIUM,
        relevance_score=0.95,
        metadata={
            "provider": "user_attachment",
            "filename": filename,
            "content_type": content_type or "application/octet-stream",
            "size_bytes": size_bytes,
            "extraction_note": extraction_note,
            "user_provided": True,
        },
    )


async def extract_attachment_sources(files: Iterable[UploadFile] | None) -> list[RawSource]:
    """Validate and convert uploaded files into high-relevance research sources."""
    uploads = [file for file in (files or []) if file and _safe_filename(file.filename)]
    if len(uploads) > MAX_ATTACHMENT_COUNT:
        raise AttachmentExtractionError(f"Attach at most {MAX_ATTACHMENT_COUNT} files.")

    sources: list[RawSource] = []
    total_chars = 0
    for upload in uploads:
        filename = _safe_filename(upload.filename)
        extension = Path(filename).suffix.lower()
        if extension not in _ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(_ALLOWED_EXTENSIONS))
            raise AttachmentExtractionError(f"{filename} is not supported. Accepted types: {allowed}.")

        data = await upload.read()
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise AttachmentExtractionError(f"{filename} is larger than 10 MB.")
        if not data:
            raise AttachmentExtractionError(f"{filename} is empty.")

        try:
            extracted_text, extraction_note = _extract_text_for_extension(data, extension)
        except Exception as exc:
            raise AttachmentExtractionError(f"Could not extract text from {filename}.") from exc
        remaining_chars = max(0, MAX_TOTAL_ATTACHMENT_CHARS - total_chars)
        extracted_text = _truncate_text(extracted_text, remaining_chars) if remaining_chars else ""
        total_chars += len(extracted_text)
        sources.append(
            _attachment_source(
                filename=filename,
                content_type=upload.content_type,
                size_bytes=len(data),
                extracted_text=extracted_text,
                extraction_note=extraction_note,
            )
        )

    return sources


def raw_sources_from_json(items: list | None) -> list[RawSource]:
    """Hydrate persisted attachment JSON into RawSource instances."""
    sources: list[RawSource] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            sources.append(RawSource(**item))
        except Exception:
            continue
    return sources


def format_attachment_sources_for_prompt(sources: Iterable[RawSource], limit: int = 6) -> str:
    """Compact source block for prompts that need uploaded attachment context."""
    lines: list[str] = []
    for index, source in enumerate(list(sources)[:limit], start=1):
        filename = source.metadata.get("filename") or source.title
        preview = _truncate_text(source.content, 1200)
        lines.append(
            "\n".join(
                [
                    f"{index}. {filename}",
                    f"   Source ID: {source.source_id}",
                    f"   Type: user-uploaded attachment",
                    f"   Preview: {preview or 'No preview available.'}",
                ]
            )
        )
    if not lines:
        return ""
    return (
        "=== USER-UPLOADED ATTACHMENTS ===\n"
        "These files were supplied by the user as source material. Use their facts when relevant to the selected angle, hook, chapters, or script, and do not force them in when they do not support the story direction.\n"
        + "\n".join(lines)
    )
