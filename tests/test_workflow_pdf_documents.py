from __future__ import annotations

import unittest

from faculty_workflow.pdf_documents import PdfDocumentError, extract_pdf_text


def make_text_pdf(text: str, *, title: str = "Faculty Profile") -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        f"<< /Title ({title}) >>".encode("latin-1"),
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode("ascii"))
        result.extend(body)
        result.extend(b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(result)


class PdfDocumentTests(unittest.TestCase):
    def test_extracts_literal_email_and_metadata_title(self) -> None:
        title, text = extract_pdf_text(
            make_text_pdf("Ada Lovelace Professor ada@example.edu", title="Ada Profile")
        )

        self.assertEqual(title, "Ada Profile")
        self.assertIn("Ada Lovelace Professor ada@example.edu", text)

    def test_bounds_extracted_text(self) -> None:
        _, text = extract_pdf_text(make_text_pdf("A" * 200), max_text_characters=50)

        self.assertEqual(len(text), 50)

    def test_invalid_and_empty_text_pdfs_fail_closed(self) -> None:
        with self.assertRaises(PdfDocumentError):
            extract_pdf_text(b"not a pdf")
        with self.assertRaises(PdfDocumentError):
            extract_pdf_text(make_text_pdf("   "))


if __name__ == "__main__":
    unittest.main()
