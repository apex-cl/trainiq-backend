import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional
from functools import lru_cache
from jose import JWTError, jwt, jwk
from fastapi import HTTPException, status
from app.core.config import settings


class KeycloakJWTService:
    def __init__(self):
        self._jwks_cache: Optional[dict] = None
        self._jwks_cache_time: Optional[datetime] = None
        self._cache_duration = timedelta(hours=1)

    async def _get_jwks(self) -> dict:
        if self._jwks_cache and self._jwks_cache_time:
            if (
                datetime.now(timezone.utc) - self._jwks_cache_time
                < self._cache_duration
            ):
                return self._jwks_cache

        _internal_url = settings.keycloak_internal_url or settings.keycloak_url
        jwks_url = f"{_internal_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/certs"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            if response.status_code == 200:
                self._jwks_cache = response.json()
                self._jwks_cache_time = datetime.now(timezone.utc)
                return self._jwks_cache
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Keycloak JWKS endpoint not available",
            )

    def _find_key_by_kid(self, jwks: dict, kid: str) -> Optional[dict]:
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None

    async def verify_keycloak_token(self, token: str) -> dict:
        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format",
                headers={"WWW-Authenticate": "Bearer"},
            )

        kid = unverified_header.get("kid")
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing key ID",
                headers={"WWW-Authenticate": "Bearer"},
            )

        jwks = await self._get_jwks()
        key_data = self._find_key_by_kid(jwks, kid)

        if not key_data:
            self._jwks_cache = None
            self._jwks_cache_time = None
            jwks = await self._get_jwks()
            key_data = self._find_key_by_kid(jwks, kid)
            if not key_data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Signing key not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        try:
            public_key = jwk.construct(key_data)
            payload = jwt.decode(
                token,
                public_key,
                algorithms=[key_data.get("alg", "RS256")],
                audience=settings.keycloak_client_id,
                issuer=f"{settings.keycloak_url}/realms/{settings.keycloak_realm}",
            )
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token validation failed",
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def get_user_id_from_token(self, token: str) -> Optional[str]:
        try:
            payload = await self.verify_keycloak_token(token)
            return payload.get("sub")
        except HTTPException:
            return None


keycloak_jwt_service = KeycloakJWTService()
