import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: _convert_main <pdf_path> <docx_path> <pages_path>\n")
        return 2

    pdf_path, docx_path, pages_path = argv

    try:
        from docx import Document
        from pdf2docx import Converter
    except Exception as exc:
        sys.stderr.write(f"ImportError: {exc}\n")
        return 3

    page_numbers: list[int] = []

    try:
        cv = Converter(pdf_path)
        try:
            settings = cv.default_settings
            cv.parse(start=0, end=None, **settings)

            parsed_pages = [p for p in cv.pages if p.finalized]
            if not parsed_pages:
                raise ValueError("No parsed pages produced by pdf2docx")

            docx_file = Document()

            for page in parsed_pages:
                try:
                    page.make_docx(docx_file)
                except Exception as exc:
                    if not settings.get("ignore_page_error", True):
                        raise
                    sys.stderr.write(f"WARNING: skipped page {page.id + 1}: {exc}\n")
                    continue

                # pdf2docx starts a new docx section per page (Page.make_docx),
                # so this order matches the section order in the saved docx.
                page_numbers.append(page.id + 1)

            docx_file.save(docx_path)
        finally:
            cv.close()
    except BaseException as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1

    with open(pages_path, "w") as fh:
        json.dump(page_numbers, fh)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))