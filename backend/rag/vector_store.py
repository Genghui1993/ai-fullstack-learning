from pathlib import Path
import uuid
import chromadb
import os


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

client = chromadb.PersistentClient(
    path=str(DATA_DIR / "chroma")
)


collection = client.get_or_create_collection(
    name="documents"
)



def add_documents(
    texts,
    embeddings,
    filename: str,
    file_id: str,
    uploaded_at: str,
    chunk_metadatas=None,
    user_id: str | None = None,
    knowledge_base_id: str | None = None,
):

    ids = [
        str(uuid.uuid4())
        for _ in texts
    ]

    metadatas = []
    for index, _ in enumerate(texts):
        metadata = {
            "filename": filename,
            "file_id": file_id,
            "uploaded_at": uploaded_at,
            "chunk_index": index,
        }
        if user_id:
            metadata["user_id"] = user_id
        if knowledge_base_id:
            metadata["knowledge_base_id"] = knowledge_base_id
        if chunk_metadatas and index < len(chunk_metadatas):
            extra = chunk_metadatas[index]
            if extra.get("page") is not None:
                metadata["page"] = int(extra["page"])
            if extra.get("title"):
                metadata["title"] = str(extra["title"])
        metadatas.append(metadata)

    collection.add(
        documents=texts,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas
    )



def search(
    embedding,
    user_id: str,
    knowledge_base_id: str,
    top_k=5
):
    metadata_rows = collection.get(include=["metadatas"]).get("metadatas") or []
    active_file_ids = sorted(
        {
            metadata.get("file_id")
            for metadata in metadata_rows
            if metadata
            and metadata.get("file_id")
            and metadata.get("user_id") == user_id
            and metadata.get("knowledge_base_id") == knowledge_base_id
        }
    )

    if not active_file_ids:
        return {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

    where = (
        {"file_id": active_file_ids[0]}
        if len(active_file_ids) == 1
        else {"file_id": {"$in": active_file_ids}}
    )

    return collection.query(
        query_embeddings=[
            embedding
        ],
        n_results=min(top_k, len(metadata_rows)),
        where=where,
        include=["documents", "metadatas", "distances"],
    )


def list_documents(
    user_id: str | None = None,
    knowledge_base_id: str | None = None,
):
    data = collection.get(include=["metadatas"])
    documents = {}

    for metadata in data.get("metadatas") or []:
        if not metadata:
            continue

        file_id = metadata.get("file_id")
        if not file_id:
            continue
        if user_id is not None and metadata.get("user_id") != user_id:
            continue
        if knowledge_base_id is not None and metadata.get("knowledge_base_id") != knowledge_base_id:
            continue

        item = documents.setdefault(
            file_id,
            {
                "id": file_id,
                "filename": metadata.get("filename", "未知文件"),
                "uploaded_at": metadata.get("uploaded_at", ""),
                "user_id": metadata.get("user_id"),
                "knowledge_base_id": metadata.get("knowledge_base_id"),
                "chunks": 0,
            },
        )
        item["chunks"] += 1

    return sorted(
        documents.values(),
        key=lambda item: item["uploaded_at"],
        reverse=True,
    )


def delete_document(file_id: str):
    collection.delete(where={"file_id": file_id})


def assign_unscoped_documents(user_id: str, knowledge_base_id: str):
    data = collection.get(include=["metadatas"])
    ids = []
    metadatas = []
    for item_id, metadata in zip(data.get("ids") or [], data.get("metadatas") or []):
        if not metadata or metadata.get("user_id") != user_id:
            continue
        if metadata.get("knowledge_base_id"):
            continue
        ids.append(item_id)
        metadatas.append({**metadata, "knowledge_base_id": knowledge_base_id})
    if ids:
        collection.update(ids=ids, metadatas=metadatas)
    return len(ids)
