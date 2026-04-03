import warnings

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    jwt_secret: str = "dev-secret-not-for-production"
    jwt_expire_minutes: int = 10080

    frontend_url: str = "http://localhost"
    # Komma-getrennte Liste weiterer CORS-Origins (z.B. https://www.trainiq.com)
    additional_cors_origins: str = ""

    # SMTP E-Mail
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    from_email: str = "noreply@trainiq.app"
    from_name: str = "TrainIQ"

    # Dev-Modus: kein API-Key nötig, feste Demo-User-ID
    dev_mode: bool = False
    demo_user_id: str = "00000000-0000-0000-0000-000000000001"

    # Gast-Session Limits
    guest_max_messages: int = 5
    guest_max_photos: int = 2
    guest_session_hours: int = 24

    # Web Push Notifications (VAPID)
    vapid_private_key: str = ""
    vapid_public_key: str = ""

    # LLM — OpenAI-kompatibel (OpenRouter, Ollama, ...)
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "stepfun/step-3.5-flash:free"
    # Vision (optional) — für Foto-Analyse (multimodales Modell nötig)
    llm_vision_model: str = ""

    # Embeddings — separater Provider (z.B. NVIDIA NIM)
    # leer lassen = gleicher Provider wie LLM wird genutzt
    llm_embedding_model: str = ""
    embedding_base_url: str = "https://integrate.api.nvidia.com/v1"
    embedding_api_key: str = ""  # leer = llm_api_key wird verwendet

    # Backward-Compat: NVIDIA_API_KEY → llm_api_key
    nvidia_api_key: str = ""

    @property
    def active_llm_api_key(self) -> str:
        return self.llm_api_key or self.nvidia_api_key

    @property
    def active_embedding_api_key(self) -> str:
        """API-Key für Embeddings — fällt auf LLM-Key zurück, falls nicht gesetzt."""
        return self.embedding_api_key or self.active_llm_api_key

    @property
    def active_embedding_base_url(self) -> str:
        """Base-URL für Embeddings — fällt auf LLM-URL zurück, falls nicht gesetzt."""
        return self.embedding_base_url or self.llm_base_url

    # Sentry Error Tracking
    sentry_dsn: str = ""

    # Stripe Billing
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""

    # Garmin Connect
    garmin_client_id: str = ""
    garmin_client_secret: str = ""

    # Strava API — universeller Hub für alle Uhren (einmalige Registrierung)
    # Registrierung: https://www.strava.com/settings/api
    # Deckt ab: Polar, Wahoo, Suunto, COROS, Zepp/Amazfit, Fitbit,
    #           Samsung Health, WHOOP, Google Fit (Wear OS), Apple Watch
    strava_client_id: str = ""
    strava_client_secret: str = ""
    strava_redirect_uri: str = "http://localhost/api/watch/strava/callback"

    # Keycloak OIDC Configuration
    keycloak_url: str = "http://localhost:8080"
    keycloak_internal_url: str = ""  # Docker-intern (z.B. http://keycloak:8080), leer = keycloak_url
    keycloak_realm: str = "trainiq"
    keycloak_client_id: str = "trainiq-frontend"
    keycloak_client_secret: str = ""
    keycloak_enabled: bool = True

    # Keycloak Admin API (für User-Management)
    keycloak_admin_user: str = "admin"
    keycloak_admin_password: str = ""


settings = Settings()

if not settings.dev_mode:
    if settings.jwt_secret == "dev-secret-not-for-production":
        raise ValueError(
            "SICHERHEITSRISIKO: JWT_SECRET darf in Production nicht der Standard-Dev-Wert sein! "
            "Setze JWT_SECRET in deiner .env auf einen sicheren zufälligen String (mindestens 32 Zeichen)."
        )
    if len(settings.jwt_secret) < 32:
        raise ValueError(
            f"SICHERHEITSRISIKO: JWT_SECRET ist zu kurz ({len(settings.jwt_secret)} Zeichen). "
            "Mindestens 32 Zeichen erforderlich."
        )
    if settings.keycloak_admin_password in ("", "admin"):
        import warnings
        warnings.warn(
            "SICHERHEITSWARNUNG: KEYCLOAK_ADMIN_PASSWORD ist schwach oder leer. "
            "Setze ein sicheres Passwort in .env.",
            stacklevel=1,
        )
