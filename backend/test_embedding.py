from rag.loader import load_pdf
from rag.splitter import split_text
from rag.embedding import embed_texts
# from rag.vector_store import search
from rag.vector_store import add_documents, search



# text = load_pdf(
#     "test.pdf"
# )
text = load_pdf(
    "RAG_产品说明书.pdf"
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


question = "这个系统支持什么功能？"



question_vector = embed_texts(
    [
        question
    ]
)[0]



result = search(
    question_vector
)


print(result)

from rag.vector_store import collection

data = collection.get()

print(len(data["documents"]))

for doc in data["documents"]:
    print("----------------")
    print(doc[:100])