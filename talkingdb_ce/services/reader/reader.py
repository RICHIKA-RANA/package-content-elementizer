from .docx.docx_reader import DocxReader
from .pdf.pdf_reader import PdfReader
from talkingdb.models.document.document import DocumentModel


class ReaderFactory:
    """
    Factory class to pick the right reader based on file type.
    """

    @staticmethod
    def get_reader(file_type: str):
        readers = {
            "docx": DocxReader(),
            "pdf": PdfReader(),
        }
        return readers.get(file_type.lower())


def parse_document(io_buffer, file_type: str, file_name: str) -> DocumentModel:
    reader = ReaderFactory.get_reader(file_type)
    if not reader:
        raise ValueError(f"Unsupported file type: {file_type}")
    return reader.read_document(io_buffer, file_name)
