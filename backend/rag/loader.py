from pathlib import Path

from docx import Document
from pypdf import PdfReader


def load_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    text = ""

    for page in reader.pages:
        content = page.extract_text()
        if content:
            text += content + "\n"

    return text


def load_docx(file_path: str) -> str:
    document = Document(file_path)
    parts: list[str] = []

    for paragraph in document.paragraphs:
        content = paragraph.text.strip()
        if content:
            parts.append(content)

    for table in document.tables:
        for row in table.rows:
            cells = [
                cell.text.strip()
                for cell in row.cells
                if cell.text.strip()
            ]
            if cells:
                parts.append(" | ".join(cells))

    return "\n".join(parts)


def load_document(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()

    if suffix == ".pdf":
        return load_pdf(file_path)

    if suffix == ".docx":
        return load_docx(file_path)

    raise ValueError(f"不支持的文件类型: {suffix}")
