from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


class PdfDocumentError(ValueError):
    pass


def extract_pdf_text(
    data: bytes,
    *,
    max_text_characters: int = 500_000,
) -> tuple[str, str]:
    """Extract bounded text from a valid text-layer PDF without OCR."""
    if not data.startswith(b"%PDF-"):
        raise PdfDocumentError("Invalid PDF signature")
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise PdfDocumentError("Encrypted PDF is not readable")
        parts = [page.extract_text() or "" for page in reader.pages]
        metadata = reader.metadata
        title = str(getattr(metadata, "title", "") or "").strip()
    except PdfDocumentError:
        raise
    except Exception as exc:
        raise PdfDocumentError("PDF text extraction failed") from exc
    text = "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    if not text:
        raise PdfDocumentError("PDF has no extractable text")
    return title, text[:max(1, max_text_characters)]
