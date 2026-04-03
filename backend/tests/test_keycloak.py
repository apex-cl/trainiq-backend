import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from main import app
from app.core.config import settings
from app.models.user import User


@pytest.fixture
def mock_keycloak_service():
    with patch("app.api.routes.auth_keycloak.keycloak_service") as mock:
        mock.exchange_code = AsyncMock(
            return_value={
                "access_token": "kc_access_token",
                "refresh_token": "kc_refresh_token",
                "id_token": "kc_id_token",
                "expires_in": 300,
            }
        )
        mock.get_userinfo = AsyncMock(
            return_value={
                "sub": "kc-user-123",
                "email": "test@example.com",
                "name": "Test User",
                "email_verified": True,
                "preferred_username": "testuser",
            }
        )
        mock.logout = AsyncMock(return_value=True)
        yield mock


@pytest.fixture
def mock_jwt_service():
    with patch("app.api.routes.auth_keycloak.jwt_service") as mock:
        mock.create_access_token = MagicMock(return_value="app_jwt_token")
        yield mock


@pytest.fixture
def mock_db_session():
    with patch("app.api.routes.auth_keycloak.get_db") as mock:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=user_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock.return_value = mock_session
        yield mock_session


class TestKeycloakConfig:
    def test_keycloak_config_defaults(self):
        assert settings.keycloak_enabled is True
        assert settings.keycloak_url == "http://localhost:8080"
        assert settings.keycloak_realm == "trainiq"
        assert settings.keycloak_client_id == "trainiq-frontend"

    def test_keycloak_config_can_be_enabled(self):
        with patch.dict("os.environ", {"KEYCLOAK_ENABLED": "true"}):
            from app.core.config import Settings

            settings = Settings()
            assert settings.keycloak_enabled is True


class TestKeycloakRoutes:
    @pytest.mark.asyncio
    async def test_login_redirect_when_keycloak_disabled(self):
        with patch("app.api.routes.auth_keycloak.settings") as mock_settings:
            mock_settings.keycloak_enabled = False
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/auth/keycloak/login")
                assert response.status_code == 400
                assert "not enabled" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_redirect_when_keycloak_disabled(self):
        with patch("app.api.routes.auth_keycloak.settings") as mock_settings:
            mock_settings.keycloak_enabled = False
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/auth/keycloak/register")
                assert response.status_code == 400
                assert "not enabled" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_callback_creates_user_if_not_exists(
        self, mock_keycloak_service, mock_jwt_service, client
    ):
        response = await client.post(
            "/auth/keycloak/callback",
            json={"code": "test_code", "redirect_uri": "http://localhost/callback"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        assert data["user"]["email"] == "test@example.com"


class TestKeycloakSecurity:
    @pytest.mark.asyncio
    async def test_callback_requires_valid_code(self):
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.keycloak_enabled = True

            with patch("app.api.routes.auth_keycloak.keycloak_service") as mock_kc:
                mock_kc.exchange_code = AsyncMock(return_value=None)

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/auth/keycloak/callback",
                        json={
                            "code": "invalid_code",
                            "redirect_uri": "http://localhost/callback",
                        },
                    )
                    assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_requires_valid_userinfo(self):
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.keycloak_enabled = True

            with patch("app.api.routes.auth_keycloak.keycloak_service") as mock_kc:
                mock_kc.exchange_code = AsyncMock(
                    return_value={"access_token": "token"}
                )
                mock_kc.get_userinfo = AsyncMock(return_value=None)

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/auth/keycloak/callback",
                        json={
                            "code": "test_code",
                            "redirect_uri": "http://localhost/callback",
                        },
                    )
                    assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_refresh_requires_valid_token(self):
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.keycloak_enabled = True

            with patch("app.api.routes.auth_keycloak.keycloak_service") as mock_kc:
                mock_kc.refresh_token = AsyncMock(return_value=None)

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/auth/keycloak/refresh",
                        json={"refresh_token": "invalid_token"},
                    )
                    assert response.status_code == 400


class TestKeycloakJWKS:
    @pytest.mark.asyncio
    async def test_jwks_endpoint_when_disabled(self):
        with patch("app.api.routes.auth_keycloak.settings") as mock_settings:
            mock_settings.keycloak_enabled = False
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/auth/keycloak/keys")
                assert response.status_code == 400

    @pytest.mark.asyncio
    @patch("app.core.config.settings")
    async def test_jwks_endpoint_returns_keys(self, mock_settings):
        mock_settings.keycloak_enabled = True

        with patch("app.api.routes.auth_keycloak.keycloak_service") as mock_kc:
            mock_kc.get_jwks = AsyncMock(return_value={"keys": []})

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get("/auth/keycloak/keys")
                assert response.status_code == 200


class TestKeycloakUserinfo:
    @pytest.mark.asyncio
    async def test_userinfo_requires_auth(self, client):
        from app.api.dependencies import get_current_user
        from main import app as _app

        mock_user = MagicMock(spec=User)
        mock_user.keycloak_id = "kc-123"
        mock_user.email = "test@example.com"
        mock_user.name = "Test User"
        mock_user.email_verified = True

        async def _override():
            return mock_user

        _app.dependency_overrides[get_current_user] = _override
        try:
            response = await client.get(
                "/auth/keycloak/userinfo",
                headers={"Authorization": "Bearer test_token"},
            )
            assert response.status_code == 200
        finally:
            _app.dependency_overrides.pop(get_current_user, None)


class TestKeycloakIntegration:
    def test_keycloak_service_url_construction(self):
        from app.services.keycloak_service import KeycloakService

        service = KeycloakService()

        # Keycloak 17+ removed the /auth prefix
        assert service.realm_url == "http://localhost:8080/realms/trainiq"
        assert (
            service.token_url
            == "http://localhost:8080/realms/trainiq/protocol/openid-connect/token"
        )
        assert (
            service.userinfo_url
            == "http://localhost:8080/realms/trainiq/protocol/openid-connect/userinfo"
        )
        assert (
            service.jwks_url
            == "http://localhost:8080/realms/trainiq/protocol/openid-connect/certs"
        )

    def test_keycloak_login_url_generation(self):
        from app.services.keycloak_service import KeycloakService

        service = KeycloakService()

        url = service.get_login_url("http://localhost/callback", "test_state")

        assert (
            "http://localhost:8080/realms/trainiq/protocol/openid-connect/auth"
            in url
        )
        assert "client_id=trainiq-frontend" in url
        assert "response_type=code" in url
        assert "scope=openid+profile+email" in url
        assert "state=test_state" in url

    def test_keycloak_register_url_generation(self):
        from app.services.keycloak_service import KeycloakService

        service = KeycloakService()

        url = service.get_register_url("http://localhost/callback", "test_state")

        assert "registration=1" in url


class TestUserModelKeycloakField:
    def test_user_model_has_keycloak_id(self):
        user = User(
            email="test@example.com",
            name="Test User",
            password_hash="hash",
            keycloak_id="kc-12345",
        )

        assert hasattr(user, "keycloak_id")
        assert user.keycloak_id == "kc-12345"

    def test_user_model_keycloak_id_nullable(self):
        user = User(email="test@example.com", name="Test User", password_hash="hash")

        assert user.keycloak_id is None


class TestSocialLogin:
    @pytest.mark.asyncio
    async def test_social_login_disabled_keycloak(self):
        with patch("app.api.routes.auth_keycloak.settings") as mock_settings:
            mock_settings.keycloak_enabled = False
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/auth/keycloak/social/google")
                assert response.status_code == 400
                assert "not enabled" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_social_login_unknown_provider_rejected(self):
        with patch("app.api.routes.auth_keycloak.settings") as mock_settings:
            mock_settings.keycloak_enabled = True
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/auth/keycloak/social/facebook")
                assert response.status_code == 400
                assert "Anbieter" in response.json()["detail"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ["google", "apple", "github"])
    async def test_social_login_returns_auth_url(self, provider):
        with patch("app.api.routes.auth_keycloak.settings") as mock_settings:
            mock_settings.keycloak_enabled = True
            mock_settings.frontend_url = "http://localhost:3000"

            from app.services.keycloak_service import KeycloakService
            real_service = KeycloakService()

            with patch("app.api.routes.auth_keycloak.keycloak_service") as mock_kc:
                mock_kc.get_social_login_url = real_service.get_social_login_url

                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get(f"/auth/keycloak/social/{provider}")
                    assert response.status_code == 200
                    data = response.json()
                    assert "auth_url" in data
                    assert "state" in data
                    assert f"kc_idp_hint={provider}" in data["auth_url"]
                    assert "openid-connect/auth" in data["auth_url"]

    def test_social_login_url_contains_kc_idp_hint(self):
        from app.services.keycloak_service import KeycloakService

        service = KeycloakService()
        url = service.get_social_login_url("google", "http://localhost/callback", "state123")

        assert "kc_idp_hint=google" in url
        assert "openid-connect/auth" in url
        assert "state=state123" in url
        assert "response_type=code" in url

