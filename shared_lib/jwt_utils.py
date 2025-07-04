# shared_lib/jwt_utils.py

from jose import jwt, JWTError
from fastapi import HTTPException
import os

KEYCLOAK_PUBLIC_KEY = os.getenv("KEYCLOAK_PUBLIC_KEY")
KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER")

def verify_token(auth_header: str) -> dict:
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yetkilendirme başarısız.")
    token = auth_header[7:]
    try:
        payload = jwt.decode(
            token,
            KEYCLOAK_PUBLIC_KEY,
            algorithms=["RS256"],
            options={"verify_aud": False},
            issuer=KEYCLOAK_ISSUER
        )
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Geçersiz token: {e}")
