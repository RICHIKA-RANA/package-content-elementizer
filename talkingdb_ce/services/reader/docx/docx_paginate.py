import os
import re
import subprocess
import tempfile
from typing import List

from talkingdb.logger.console import logger
from talkingdb.models.document.document import DocumentModel

# Toggle without a redeploy if soffice is missing/misbehaving in an env.
PAGINATE_DOCX_ENABLED = os.getenv(
    "CE_DOCX_PAGINATE", "1") not in ("0", "false", "False")

CONVERT_TIMEOUT_SECONDS = int(
    os.getenv("CE_DOCX_PAGINATE_TIMEOUT_SECONDS", "120"))

_ANCHOR_LEN = 40
_MIN_ANCHOR_LEN = 8


class PaginationError(Exception):
    pass


def paginate_docx(docx_bytes: bytes, model: DocumentModel) -> None:
    """Best-effort: render docx -> pdf, extract per-page text, stamp elem.page.

    Never raises. Any failure (soffice missing, timeout, render error) is
    logged and leaves elements with page=None, exactly as before.
    """
    try:
        pdf_bytes = _render_to_pdf(docx_bytes, CONVERT_TIMEOUT_SECONDS)
        page_texts = _extract_page_texts(pdf_bytes)
        _assign_pages(model, page_texts)
    except Exception as exc:
        logger.warning(f"docx pagination skipped: {exc}")


def _render_to_pdf(docx_bytes: bytes, timeout_seconds: int) -> bytes:
    with tempfile.TemporaryDirectory(prefix="tdb-docx-paginate-") as tmp_dir:
        # Step 1: write the docx to disk and close the handle before soffice touches it
        docx_path = os.path.join(tmp_dir, "input.docx")
        with open(docx_path, "wb") as fh:
            fh.write(docx_bytes)
        # handle is now closed — soffice can read the file cleanly

        # Step 2: unique profile dir per call so concurrent renders don't deadlock
        profile_uri = f"file://{tmp_dir}/lo_profile"

        try:
            result = subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--norestore",
                    f"-env:UserInstallation={profile_uri}",
                    "--convert-to", "pdf",
                    "--outdir", tmp_dir,
                    docx_path,
                ],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise PaginationError(
                f"docx->pdf render exceeded {timeout_seconds}s"
            )
        except FileNotFoundError:
            raise PaginationError("soffice binary not found on PATH")

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise PaginationError(
                f"soffice exited with code {result.returncode}: {detail}"
            )

        # Step 3: read the pdf soffice wrote — separate handle, read mode
        pdf_path = os.path.join(tmp_dir, "input.pdf")
        if not os.path.exists(pdf_path):
            raise PaginationError("soffice did not produce a pdf output")

        with open(pdf_path, "rb") as fh:
            return fh.read()
    # tmp_dir and all its contents are deleted here after the bytes are returned


def _extract_page_texts(pdf_bytes: bytes) -> List[str]:
    import fitz  # PyMuPDF — transitive dep via pdf2docx

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return [page.get_text() for page in doc]
    finally:
        doc.close()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _assign_pages(model: DocumentModel, page_texts: List[str]) -> None:
    """Walk elements in document order, advancing a page cursor forward-only
    by anchor-matching each element's text against the rendered page text.

    Forward-only + cursor-after-match avoids false matches on repeated
    phrases (e.g. running headers). Best effort: if an anchor can't be
    found ahead, the element keeps the current page rather than failing.
    """
    norm_pages = [_normalize(t) for t in page_texts]
    if not norm_pages:
        return

    page_idx = 0
    cursor = 0  # consumed offset within norm_pages[page_idx]

    for elem in model.iter_elements():
        text = elem.to_text() if hasattr(elem, "to_text") else ""
        norm = _normalize(text)

        if not norm:
            elem.page = page_idx + 1
            continue

        anchor = norm[:_ANCHOR_LEN] if len(norm) >= _MIN_ANCHOR_LEN else norm

        matched = False
        search_idx = page_idx
        while search_idx < len(norm_pages):
            haystack = norm_pages[search_idx]
            start = cursor if search_idx == page_idx else 0
            pos = haystack.find(anchor, start)
            if pos != -1:
                page_idx = search_idx
                cursor = pos + len(anchor)
                matched = True
                break
            search_idx += 1

        elem.page = page_idx + 1

        if not matched:
            logger.debug(
                f"docx pagination: no anchor match for element "
                f"{getattr(elem, 'id', None)}; kept page {page_idx + 1}"
            )
