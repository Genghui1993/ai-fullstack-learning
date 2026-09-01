from rag.loader import load_pdf
from rag.splitter import split_text


text = load_pdf(
    "test.pdf"
)


chunks = split_text(text)


print(
    len(chunks)
)


print(
    chunks[0]
)