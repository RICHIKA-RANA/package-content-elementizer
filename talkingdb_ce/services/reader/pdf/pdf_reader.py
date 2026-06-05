import io
import os
import subprocess
import sys
import tempfile
from collections import Counter
from typing import List, Optional, Tuple

from talkingdb.logger.console import logger
from talkingdb.models.document.document import DocumentModel
from talkingdb.models.document.elements.primitive.paragraph import (
    ParagraphModel,
    ParagraphStyleModel,
)

from ..docx.docx_reader import DocxReader


CONVERT_TIMEOUT_SECONDS = int(os.getenv("CE_PDF_CONVERT_TIMEOUT_SECONDS", "600"))

MIN_EXTRACTABLE_TEXT_CHARS = int(os.getenv("CE_PDF_MIN_TEXT_CHARS", "16"))

MAX_HEADING_LEVEL = 6

HEADING_MAX_CHARS = 200
BOLD_HEADING_MAX_CHARS = 120

_CONVERT_MODULE = "talkingdb_ce.services.reader.pdf._convert_main"


def _round_size(size: Optional[float]) -> Optional[int]:
    """Round a font size to the nearest point for tier clustering."""
    return round(size) if size else None


class PdfReader:
    """Reads a PDF by converting it to DOCX and reusing :class:`DocxReader`."""

    def __init__(self) -> None:
        self.docx_reader = DocxReader()

    # --------------------------------------------------------------- public API
    def read_document(self, io_buffer, file_name) -> DocumentModel:
        docx_bytes = self._to_docx_bytes(io_buffer)

        model = self.docx_reader.read_document(io.BytesIO(docx_bytes), file_name)

        self._reject_if_textless(model, file_name)
        self._remap_headings(model)
        model.build_hierarchy()
        return model

    # ----------------------------------------------------------------- convert
    def _to_docx_bytes(self, io_buffer) -> bytes:
        io_buffer.seek(0)
        pdf_data = io_buffer.read()

        pdf_path: Optional[str] = None
        docx_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="tdb-pdf-", suffix=".pdf", delete=False
            ) as tmp_pdf:
                tmp_pdf.write(pdf_data)
                pdf_path = tmp_pdf.name

            with tempfile.NamedTemporaryFile(
                prefix="tdb-pdf-", suffix=".docx", delete=False
            ) as tmp_docx:
                docx_path = tmp_docx.name

            self._convert(pdf_path, docx_path)

            with open(docx_path, "rb") as fh:
                return fh.read()
        finally:
            for path in (pdf_path, docx_path):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        logger.warning(f"failed to remove temp file: {path}")

    def _convert(self, pdf_path: str, docx_path: str) -> None:
        """Run pdf2docx in a killable child process with a wall-clock cap."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", _CONVERT_MODULE, pdf_path, docx_path],
                capture_output=True,
                text=True,
                timeout=CONVERT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise ValueError(
                f"PDF conversion exceeded {CONVERT_TIMEOUT_SECONDS}s and was aborted"
            )

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            detail = detail or f"converter exited with code {result.returncode}"
            raise ValueError(f"PDF could not be converted ({detail})")

    # ------------------------------------------------------------- text guard
    def _reject_if_textless(self, model: DocumentModel, file_name) -> None:
        total = 0
        for elem in model.iter_elements():
            text = elem.to_text() if hasattr(elem, "to_text") else ""
            if text:
                total += len(text.strip())
            if total >= MIN_EXTRACTABLE_TEXT_CHARS:
                return
        raise ValueError(
            f"No extractable text found in PDF '{file_name}' "
            f"(possibly a scanned/image-only document; OCR is not supported)"
        )

    # --------------------------------------------------------- heading remap
    def _remap_headings(self, model: DocumentModel) -> None:
        paragraphs = [
            elem
            for elem in model.iter_elements()
            if isinstance(elem, ParagraphModel)
        ]

        for para in paragraphs:
            if para.style is None:
                para.style = ParagraphStyleModel(name="Normal")

        sized: List[Tuple[ParagraphModel, str, Optional[int], bool]] = []
        size_weight: Counter = Counter()
        for para in paragraphs:
            text = para.to_text().strip()
            if not text:
                continue
            size = self._para_size(para)
            sized.append((para, text, size, self._para_bold(para)))
            if size is not None:
                size_weight[size] += len(text)

        if not size_weight:
            return  # no font metrics to reason about; leave as a flat document

        body_size = size_weight.most_common(1)[0][0]
        tiers = sorted({s for s in size_weight if s > body_size}, reverse=True)
        size_level = {s: min(i + 1, MAX_HEADING_LEVEL) for i, s in enumerate(tiers)}
        bold_level = min(len(tiers) + 1, MAX_HEADING_LEVEL)

        for para, text, size, bold in sized:
            level: Optional[int] = None
            if size in size_level and len(text) <= HEADING_MAX_CHARS:
                level = size_level[size]
            elif (
                bold
                and len(text) <= BOLD_HEADING_MAX_CHARS
                and (size is None or size <= body_size)
            ):
                level = bold_level
            if level:
                para.style.name = f"Heading {level}"

    @staticmethod
    def _para_size(para: ParagraphModel) -> Optional[int]:
        sizes = [
            r.attributes.font_size
            for r in para.runs
            if r.text and r.text.strip() and r.attributes and r.attributes.font_size
        ]
        if sizes:
            return _round_size(max(sizes))
        if para.style and para.style.font_size:
            return _round_size(para.style.font_size)
        return None

    @staticmethod
    def _para_bold(para: ParagraphModel) -> bool:
        runs = [r for r in para.runs if r.text and r.text.strip()]
        if not runs:
            return False
        return all(r.attributes and r.attributes.bold for r in runs)
