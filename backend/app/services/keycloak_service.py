import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from app.core.config import settings


class KeycloakService:
    def __init__(self):
        self.keycloak_url = settings.keycloak_url
        # Für Server-to-Server Calls innerhalb Docker (z.B. http://keycloak:8080)
        self._internal_url = settings.keycloak_internal_url or settings.keycloak_url
        self.realm = settings.keycloak_realm
        self.client_id = settings.keycloak_client_id
        self.client_secret = settings.keycloak_client_secret
        self.admin_user = settings.keycloak_admin_user
        self.admin_password = settings.keycloak_admin_password
        self._admin_token: Optional[str] = None
        self._admin_token_expires: Optional[datetime] = None

    @property
    def realm_url(self) -> str:
        """Browser-facing realm URL."""
        return f"{self.keycloak_url}/realms/{self.realm}"

    @property
    def _internal_realm_url(self) -> str:
        """Server-to-server realm URL (Docker-intern)."""
        return f"{self._internal_url}/realms/{self.realm}"

    @property
    def token_url(self) -> str:
        return f"{self._internal_realm_url}/protocol/openid-connect/token"

    @property
    def userinfo_url(self) -> str:
        return f"{self._internal_realm_url}/protocol/openid-connect/userinfo"

    @property
    def register_url(self) -> str:
        return f"{self.realm_url}/protocol/openid-connect/registrations"

    @property
    def logout_url(self) -> str:
        return f"{self._internal_realm_url}/protocol/openid-connect/logout"

    @property
    def jwks_url(self) -> str:
        return f"{self._internal_realm_url}/protocol/openid-connect/certs"

    @property
    def well_known_url(self) -> str:
        return f"{self._internal_realm_url}/.well-known/openid-configuration"

    def get_login_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
        }
        return f"{self.realm_url}/protocol/openid-connect/auth?{urlencode(params)}"

    def get_register_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "registration": "1",
        }
        return f"{self.realm_url}/protocol/openid-connect/registrations?{urlencode(params)}"

    def get_social_login_url(self, provider: str, redirect_uri: str, state: str) -> str:
        """Generate auth URL with kc_idp_hint to skip Keycloak login and go directly to the social provider."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "kc_idp_hint": provider,
        }
        return f"{self.realm_url}/protocol/openid-connect/auth?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> Optional[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            if response.status_code == 200:
                return response.json()
            return None

    async def refresh_token(self, refresh_token: str) -> Optional[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                },
            )
            if response.status_code == 200:
                return response.json()
            return None

    async def get_userinfo(self, access_token: str) -> Optional[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code == 200:
                return response.json()
            return None

    async def logout(self, refresh_token: str) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.logout_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                },
            )
            return response.status_code == 204

    async def get_jwks(self) -> Optional[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(self.jwks_url)
            if response.status_code == 200:
                return response.json()
            return None

    async def get_openid_config(self) -> Optional[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(self.well_known_url)
            if response.status_code == 200:
                return response.json()
            return None

    async def _get_admin_token(self) -> Optional[str]:
        now = datetime.now(timezone.utc)
        if self._admin_token and self._admin_token_expires and now < self._admin_token_expires:
            return self._admin_token
        if not self.admin_user or not self.admin_password:
            return None

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self._internal_url}/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": self.admin_user,
                    "password": self.admin_password,
                },
            )
            if response.status_code == 200:
                data = response.json()
                self._admin_token = data.get("access_token")
                expires_in = data.get("expires_in", 60)
                self._admin_token_expires = now + timedelta(seconds=expires_in - 10)
                return self._admin_token
            return None

    async def create_user(
        self,
        email: str,
        username: str,
        password: str,
        first_name: str = "",
        last_name: str = "",
    ) -> Optional[str]:
        admin_token = await self._get_admin_token()
        if not admin_token:
            return None

        user_data = {
            "email": email,
            "username": username,
            "enabled": True,
            "emailVerified": False,
            "credentials": [
                {
                    "type": "password",
                    "value": password,
                    "temporary": False,
                }
            ],
        }
        if first_name or last_name:
            user_data["firstName"] = first_name
            user_data["lastName"] = last_name

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self._internal_url}/admin/realms/{self.realm}/users",
                json=user_data,
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 201:
                location = response.headers.get("Location", "")
                return location.split("/")[-1] if location else None
            return None

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        admin_token = await self._get_admin_token()
        if not admin_token:
            return None

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self._internal_url}/admin/realms/{self.realm}/users",
                params={"email": email, "exact": True},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            if response.status_code == 200:
                users = response.json()
                return users[0] if users else None
            return None

    async def send_verification_email(self, user_id: str) -> bool:
        admin_token = await self._get_admin_token()
        if not admin_token:
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.put(
                f"{self._internal_url}/admin/realms/{self.realm}/users/{user_id}/send-verify-email",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            return response.status_code == 204

    async def send_password_reset(self, user_id: str) -> bool:
        admin_token = await self._get_admin_token()
        if not admin_token:
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.put(
                f"{self._internal_url}/admin/realms/{self.realm}/users/{user_id}/execute-actions-email",
                json=["UPDATE_PASSWORD"],
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "Content-Type": "application/json",
                },
            )
            return response.status_code == 204


keycloak_service = KeycloakService()
