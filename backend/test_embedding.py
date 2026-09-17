from rag.loader import load_pdf
from rag.splitter import split_text
from rag.embedding import embed_texts
# from rag.vector_store import search
from rag.vector_store import add_documents, search
from datetime import datetime, timezone
import uuid



# text = load_pdf(
#     "test.pdf"
# )
text = load_pdf(
    "data/test.pdf"
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
    vectors,
    filename="test.pdf",
    file_id=str(uuid.uuid4()),
    uploaded_at=datetime.now(timezone.utc).isoformat(),
    user_id="test-user",
    knowledge_base_id="test-knowledge-base",
)


question = "这个系统支持什么功能？"



question_vector = embed_texts(
    [
        question
    ]
)[0]



result = search(
    question_vector,
    user_id="test-user",
    knowledge_base_id="test-knowledge-base",
)


print(result)

from rag.vector_store import collection

data = collection.get()

print(len(data["documents"]))

for doc in data["documents"]:
    print("----------------")
    print(doc[:100])
