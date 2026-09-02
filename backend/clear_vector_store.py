from rag.vector_store import client

try:
    client.delete_collection(name="documents")
    print("旧知识库已清空")
except Exception as e:
    print(f"清理失败: {e}")