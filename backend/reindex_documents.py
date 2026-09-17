from pathlib import Path

from rag.embedding import embed_texts
from rag.loader import load_document_sections
from rag.splitter import split_sections
from rag.vector_store import (
    add_documents,
    delete_document,
    list_documents,
)


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"


def reindex_document(document):
    file_id = document["id"]
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    if not matches:
        raise FileNotFoundError(f"找不到原始文件：{file_id}")

    sections = load_document_sections(str(matches[0]))
    chunks = split_sections(sections)
    texts = [chunk["text"] for chunk in chunks]
    embeddings = embed_texts(texts)

    # 所有新向量准备完毕后再替换旧索引，降低中途失败的数据风险。
    delete_document(file_id)
    add_documents(
        texts,
        embeddings,
        filename=document["filename"],
        file_id=file_id,
        uploaded_at=document["uploaded_at"],
        chunk_metadatas=chunks,
        user_id=document.get("user_id"),
        knowledge_base_id=document.get("knowledge_base_id"),
    )
    return len(chunks)


def main():
    documents = list_documents()
    if not documents:
        print("知识库中没有需要重建索引的文档")
        return

    for document in documents:
        count = reindex_document(document)
        print(f"已重建：{document['filename']}（{count} 个结构化片段）")


if __name__ == "__main__":
    main()
