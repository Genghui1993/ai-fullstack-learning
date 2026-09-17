import re


SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；.!?;])")


def _split_long_text(text: str, chunk_size: int, overlap: int):
    if len(text) <= chunk_size:
        return [text]

    sentences = [item.strip() for item in SENTENCE_BOUNDARY.split(text) if item.strip()]
    chunks = []
    current = ""

    for sentence in sentences:
        candidate = f"{current}{sentence}" if current else sentence
        if current and len(candidate) > chunk_size:
            chunks.append(current)
            current = f"{current[-overlap:]}{sentence}"
        else:
            current = candidate

    if current:
        chunks.append(current)

    # 没有标点的超长表格或文本，回退到定长切分。
    if len(chunks) == 1 and len(chunks[0]) > chunk_size:
        chunks = []
        start = 0
        while start < len(text):
            chunks.append(text[start:start + chunk_size])
            start += chunk_size - overlap

    return chunks


def split_sections(sections, chunk_size: int = 500, overlap: int = 80):
    chunks = []

    for section in sections:
        title = section.get("title", "").strip()
        text = section.get("text", "").strip()
        if not text:
            continue

        searchable_text = f"{title}\n{text}" if title else text
        for part in _split_long_text(searchable_text, chunk_size, overlap):
            chunks.append(
                {
                    "text": part,
                    "page": section.get("page"),
                    "title": title,
                }
            )

    return chunks


def split_text(text: str, chunk_size: int = 500, overlap: int = 80):
    sections = [
        {"text": paragraph, "page": None, "title": ""}
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]
    return [item["text"] for item in split_sections(sections, chunk_size, overlap)]
