import os
import logging
from typing import Optional, Dict

# OpenAI veya HuggingFace transformers isteğe bağlı import edilir
import numpy as np

# ✔ Logging
log = logging.getLogger("customer_embedding_utils")
logging.basicConfig(level=logging.INFO)

# ✔ Config
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai")  # "openai" | "hf"
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
HF_MODEL_NAME      = os.getenv("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# ✔ OpenAI
if EMBEDDING_PROVIDER == "openai":
    import openai
    openai.api_key = OPENAI_API_KEY

# ✔ HuggingFace
elif EMBEDDING_PROVIDER == "hf":
    from sentence_transformers import SentenceTransformer
    hf_model = SentenceTransformer(HF_MODEL_NAME)

else:
    raise ValueError(f"❌ Geçersiz EMBEDDING_PROVIDER: {EMBEDDING_PROVIDER}")


def get_customer_embedding(text: str) -> Optional[list[float]]:
    """
    Müşteri bazlı merged_transcript'ten vektör üretir.
    """
    try:
        if EMBEDDING_PROVIDER == "openai":
            response = openai.embeddings.create(
                input=text,
                model="text-embedding-3-small"
            )
            return response.data[0].embedding

        elif EMBEDDING_PROVIDER == "hf":
            embedding = hf_model.encode(text, normalize_embeddings=True)
            return embedding.tolist()

    except Exception as e:
        log.exception("❌ Customer embedding alınamadı:")
        return None


def get_embedding_metadata() -> Dict[str, str | int]:
    """
    Kullanılan embedding motoru hakkında metadata verir.
    """
    if EMBEDDING_PROVIDER == "openai":
        return {
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-small",
            "embedding_dim": 1536
        }

    elif EMBEDDING_PROVIDER == "hf":
        dim = hf_model.get_sentence_embedding_dimension()
        return {
            "embedding_provider": "huggingface",
            "embedding_model": HF_MODEL_NAME,
            "embedding_dim": dim
        }

    return {}
