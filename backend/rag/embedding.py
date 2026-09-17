from sentence_transformers import SentenceTransformer


model = SentenceTransformer(
    "BAAI/bge-small-zh"
)


def embed_texts(texts:list[str]):

    vectors = model.encode(
        texts,
        normalize_embeddings=True,
    )

    return vectors.tolist()
