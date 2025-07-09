from enum import Enum

class AllowedToolName(str, Enum):
    MONGO_AGGREGATE = "mongo_aggregate"
    VECTOR_SEARCH = "vector_search"
    ENQUEUE_TRANSCRIPTION_JOB = "enqueue_transcription_job"
    ENQUEUE_MINI_RAG = "enqueue_mini_rag"
    GET_MINI_RAG_SUMMARY = "get_mini_rag_summary"
    WRITE_CALL_INSIGHTS = "write_call_insights"
    VECTOR_CUSTOMER_SIMILARITY_SEARCH = "vector_customer_similarity_search"
