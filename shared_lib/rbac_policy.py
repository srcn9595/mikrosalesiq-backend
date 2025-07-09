# shared_lib/config/rbac_policy.py
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared_lib.intents_enum import IntentName
from shared_lib.tool_enum import AllowedToolName

RBAC_POLICIES = {
    "ROLE_SUPER_ADMIN": {
        "allowed_intents": ["*"],
        "allowed_tools": ["*"]
    },
    "ROLE_SALES_ADMIN": {
        "allowed_intents": [
            IntentName.GET_CALL_DATES,
            IntentName.GET_LAST_CALL,
            IntentName.GET_CUSTOMER_OVERVIEW,
            IntentName.GET_OPPORTUNITY_INFO,
            IntentName.GET_CONVERSION_PROBABILITY,
            IntentName.GET_RISK_SCORE,
            IntentName.GET_NEXT_STEPS,
            IntentName.GET_SENTIMENT_ANALYSIS,
            IntentName.GET_AUDIO_ANALYSIS_COMMENTARY,
            IntentName.GET_SALES_SCORES,
            IntentName.GET_SUMMARY_BY_CALL,
            IntentName.GET_PERSONALITY_AND_SECTOR,
        ],
        "allowed_tools": [
            AllowedToolName.MONGO_AGGREGATE,
            AllowedToolName.GET_MINI_RAG_SUMMARY
        ]
    },
    "ROLE_SALES_USER": {
        "allowed_intents": [
            IntentName.GET_CALL_DATES,
            IntentName.GET_LAST_CALL,
            IntentName.GET_TRANSCRIPT_BY_CALL_ID,
            IntentName.GET_CUSTOMER_OVERVIEW,
            IntentName.GET_SUMMARY_BY_CALL,
        ],
        "allowed_tools": [
            AllowedToolName.MONGO_AGGREGATE
        ]
    },
    "ROLE_ANALYST": {
        "allowed_intents": [
            IntentName.GET_CALL_METRICS,
            IntentName.SEMANTIC_SEARCH,
            IntentName.VECTOR_CUSTOMER_SIMILARITY_SEARCH,
            IntentName.GET_OPPORTUNITY_INFO,
            IntentName.GET_CONVERSION_PROBABILITY,
            IntentName.GET_RISK_SCORE,
        ],
        "allowed_tools": [
            AllowedToolName.MONGO_AGGREGATE,
            AllowedToolName.VECTOR_SEARCH
        ]
    }
}