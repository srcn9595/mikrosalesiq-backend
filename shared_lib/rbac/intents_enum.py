from enum import Enum

class IntentName(str, Enum):
    GET_CALL_DATES = "get_call_dates"
    GET_LAST_CALL = "get_last_call"
    GET_TRANSCRIPT_BY_CALL_ID = "get_transcript_by_call_id"
    GET_TRANSCRIPTS_BY_CUSTOMER_NUM = "get_transcripts_by_customer_num"
    ENQUEUE_TRANSCRIPTION_JOB = "enqueue_transcription_job"
    GET_CALL_ANALYSIS = "get_call_analysis"
    GET_CUSTOMER_OVERVIEW = "get_customer_overview"
    SEMANTIC_SEARCH = "semantic_search"
    VECTOR_CUSTOMER_SIMILARITY_SEARCH = "vector_customer_similarity_search"
    GET_CUSTOMER_PRODUCTS = "get_customer_products"
    META_ABOUT_CREATOR = "meta_about_creator"
    GET_RANDOM_TRANSCRIPTS = "get_random_transcripts"
    GET_OPPORTUNITY_INFO = "get_opportunity_info"
    GET_CONTACT_INFO = "get_contact_info"
    GET_CALL_METRICS = "get_call_metrics"
    GET_CONVERSION_PROBABILITY = "get_conversion_probability"
    GET_RISK_SCORE = "get_risk_score"
    GET_NEXT_STEPS = "get_next_steps"
    GET_AUDIO_ANALYSIS_COMMENTARY = "get_audio_analysis_commentary"
    GET_SENTIMENT_ANALYSIS = "get_sentiment_analysis"
    GET_SALES_SCORES = "get_sales_scores"
    GET_SUMMARY_BY_CALL = "get_summary_by_call"
    GET_PERSONALITY_AND_SECTOR = "get_personality_and_sector"
    GET_META_ABOUT_CREATOR = "meta_about_creator"