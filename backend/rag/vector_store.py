import chromadb


client = chromadb.PersistentClient(
    path="./chroma"
)


collection = client.get_or_create_collection(
    name="documents"
)



def add_documents(
    texts,
    embeddings
):

    ids = [
        str(i)
        for i in range(len(texts))
    ]


    collection.add(
        documents=texts,
        embeddings=embeddings,
        ids=ids
    )



def search(
    embedding,
    top_k=3
):

    result = collection.query(
        query_embeddings=[
            embedding
        ],
        n_results=top_k
    )


    return result