from qdrant_client import QdrantClient
from semantic_search.embedding_utils import get_embedding

client = QdrantClient(host="qdrant", port=6333)

async def vector_call_handler(args: dict):
    query = args["query"]
    top_k = args.get("top_k", 10)
    threshold = args.get("threshold", 0.35)
    embedding_type = args.get("embedding_type", "call_level")

    # Embed sorgusu
    vector = get_embedding(query, embedding_type=embedding_type)
    if not vector:
        return {"name": "vector_call", "output": {"message": "⚠️ Embedding üretilemedi"}}

    try:
        search_result = client.search(
            collection_name="semantic_transcripts",
            query_vector=vector,
            limit=top_k,
            score_threshold=threshold
        )
        if not search_result:
            return {"name": "vector_call", "output": {"message": "🔍 Eşleşen kayıt bulunamadı"}}

        return {
            "name": "vector_call",
            "output": [r.dict() for r in search_result]
        }

    except Exception as e:
        return {"name": "vector_call", "output": {"message": f"❌ Qdrant arama hatası: {e}"}}
