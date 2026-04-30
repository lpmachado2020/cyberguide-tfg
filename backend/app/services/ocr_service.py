"""Image OCR helpers for CyberGuide.

Purpose:
- Extract readable text from user-uploaded screenshots and images using local OCR.

Inputs:
- Raw image bytes uploaded by the user.

Outputs:
- Plain text plus lightweight OCR metadata for traceability.

Used by:
- `backend/app/main.py`
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidocr_onnxruntime import RapidOCR


@dataclass
class OCRExtraction:
    """Structured OCR result used by the image query flow."""

    text: str
    segment_count: int


class OCRService:
    """Local OCR wrapper built on top of RapidOCR."""

    def __init__(self) -> None:
        self.engine = RapidOCR()

    def extract_text(self, image_bytes: bytes) -> OCRExtraction:
        """Run OCR over raw image bytes and return normalized text."""
        result, _ = self.engine(image_bytes)
        if not result:
            return OCRExtraction(text="", segment_count=0)

        fragments: list[str] = []
        for item in result:
            if len(item) < 2:
                continue
            text = str(item[1]).strip()
            if text:
                fragments.append(text)

        normalized_text = "\n".join(fragments).strip()
        return OCRExtraction(
            text=normalized_text,
            segment_count=len(fragments),
        )
