from rag.loader import load_pdf
from rag.splitter import split_text
from rag.embedding import embed_texts
from rag.vector_store import add_documents, search



text = load_pdf(
    "test.pdf"
)



chunks = split_text(
    text
)



print("chunk数量:")
print(len(chunks))



vectors = embed_texts(
    chunks
)



add_documents(
    chunks,
    vectors
)



question = "怎么申请年假？"



question_vector = embed_texts(
    [
        question
    ]
)[0]



result = search(
    question_vector
)


print(result)