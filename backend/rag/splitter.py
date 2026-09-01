def split_text(
    text: str,
    chunk_size: int = 200,
    overlap: int = 50
):

    chunks = []

    start = 0


    while start < len(text):

        end = start + chunk_size


        chunk = text[start:end]


        chunks.append(chunk)


        start = end - overlap


    return chunks