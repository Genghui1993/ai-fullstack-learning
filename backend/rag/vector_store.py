import uuid
import chromadb


client = chromadb.PersistentClient(
    path="./chroma"
)


collection = client.get_or_create_collection(
    name="documents"
)



def add_documents(
    texts,
    embeddings,
    filename: str | None = None
):

    ids = [
        str(uuid.uuid4())
        for _ in texts
    ]

    metadatas = None
    if filename:
        metadatas = [
            {"filename": filename}
            for _ in texts
        ]

    collection.add(
        documents=texts,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas
    )



def search(
    embedding,
    top_k=3
):

    count = collection.count()

    if count == 0:
        return {
            "documents": [[]]
        }

    result = collection.query(
        query_embeddings=[
            embedding
        ],
        n_results=min(top_k, count)
    )


    return result
