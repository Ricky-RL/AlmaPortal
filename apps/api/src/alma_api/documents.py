"""Bounded resume format validation."""

from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath

from alma_api.application import ValidatedResume
from alma_api.domain import DomainError, ResumeFormat

MAX_RESUME_BYTES = 10 * 1024 * 1024
MAX_DOCX_ENTRIES = 256
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 100

_OLE_HEADER = bytes.fromhex("D0CF11E0A1B11AE1")
_DOCX_REQUIRED_ENTRIES = frozenset({"[Content_Types].xml", "word/document.xml"})


def validate_resume(content: bytes, original_filename: str) -> ValidatedResume:
    if not content:
        raise DomainError("invalid_resume", "resume cannot be empty")
    if len(content) > MAX_RESUME_BYTES:
        raise DomainError("resume_too_large", "resume must be at most 10 MiB")
    if content.startswith(b"%PDF-"):
        return ValidatedResume(content, original_filename, "application/pdf", ResumeFormat.PDF)
    if content.startswith(_OLE_HEADER):
        return ValidatedResume(content, original_filename, "application/msword", ResumeFormat.DOC)
    if content.startswith(b"PK\x03\x04"):
        _validate_docx(content)
        return ValidatedResume(
            content,
            original_filename,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ResumeFormat.DOCX,
        )
    raise DomainError("unsupported_resume_format", "resume must be a valid PDF, DOC, or DOCX file")


def _validate_docx(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise DomainError("unsafe_docx", "DOCX contains too many entries")
            names = {entry.filename for entry in entries}
            if not _DOCX_REQUIRED_ENTRIES.issubset(names):
                raise DomainError("invalid_docx", "DOCX is missing required document entries")
            total_uncompressed = 0
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise DomainError("unsafe_docx", "DOCX contains an unsafe entry path")
                if entry.flag_bits & 0x1:
                    raise DomainError("unsafe_docx", "encrypted DOCX entries are not accepted")
                total_uncompressed += entry.file_size
                if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise DomainError("unsafe_docx", "DOCX expands beyond the allowed size")
                compressed_size = max(entry.compress_size, 1)
                if entry.file_size > compressed_size * MAX_DOCX_COMPRESSION_RATIO:
                    raise DomainError("unsafe_docx", "DOCX entry has an unsafe compression ratio")
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise DomainError("invalid_docx", "DOCX contains a corrupt entry")
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise DomainError("invalid_docx", "resume is not a valid DOCX archive") from exc
