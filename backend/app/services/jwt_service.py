from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt, jwk
from jose.utils import base64url_decode, base64url_encode
from typing import Optional, Union
from fastapi import HTTPException, status
from app.core.config import settings


class JWTService:
    def __init__(self):
        self.secret = settings.jwt_secret
        self.algorithm = "HS256"
        self.expire_minutes = settings.jwt_expire_minutes

    def create_access_token(
        self,
        data: dict,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=self.expire_minutes)
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, self.secret, algorithm=self.algorithm)

    def verify_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def decode_token(self, token: str, verify: bool = True) -> Optional[dict]:
        try:
            options = {"verify_exp": verify}
            return jwt.decode(
                token,
                self.secret,
                algorithms=[self.algorithm],
                options=options,
            )
        except JWTError:
            return None


jwt_service = JWTService()
