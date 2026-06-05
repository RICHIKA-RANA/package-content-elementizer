import sys


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: _convert_main <pdf_path> <docx_path>\n")
        return 2

    pdf_path, docx_path = argv

    try:
        from pdf2docx import Converter
    except Exception as exc:
        sys.stderr.write(f"ImportError: {exc}\n")
        return 3

    try:
        cv = Converter(pdf_path)
        try:
            cv.convert(docx_path, start=0, end=None)
        finally:
            cv.close()
    except BaseException as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
