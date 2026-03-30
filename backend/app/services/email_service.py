"""
E-Mail Service

Versendet E-Mails via SMTP (aiosmtplib).
Unterstützt: Welcome, Passwort-Reset, Wöchentlicher Report.
"""

import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from loguru import logger
from jinja2 import Environment, BaseLoader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings


# ─── E-Mail Templates ──────────────────────────────────────────────────────────


WELCOME_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="text-align: center; padding: 30px 0;">
        <h1 style="color: #1a1a2e; font-size: 28px;">Willkommen bei TrainIQ</h1>
    </div>
    <div style="background: #f8f9fa; border-radius: 12px; padding: 24px;">
        <p style="font-size: 16px; color: #333;">Hallo {{ name }},</p>
        <p style="font-size: 16px; color: #333;">
            Willkommen bei TrainIQ! Dein smarter Trainingscoach mit KI-Unterstützung ist bereit.
        </p>
        <ul style="font-size: 15px; color: #555; line-height: 1.8;">
            <li>KI-Coach für personalisierte Trainingsberatung</li>
            <li>Automatische Trainingsplan-Generierung</li>
            <li>Strava-Synchronisation</li>
            <li>Gesundheitsmetriken & Recovery-Score</li>
        </ul>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{ frontend_url }}" style="background: #4361ee; color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: 600;">
                Jetzt starten
            </a>
        </div>
    </div>
    <p style="text-align: center; color: #999; font-size: 13px; margin-top: 24px;">
        TrainIQ — Dein smarter Trainingscoach
    </p>
</body>
</html>
"""

RESET_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="text-align: center; padding: 30px 0;">
        <h1 style="color: #1a1a2e;">Passwort zurücksetzen</h1>
    </div>
    <div style="background: #f8f9fa; border-radius: 12px; padding: 24px;">
        <p style="font-size: 16px; color: #333;">Hallo {{ name }},</p>
        <p style="font-size: 16px; color: #333;">
            Du hast ein Zurücksetzen deines Passworts angefordert. Klicke auf den Button, um ein neues Passwort zu setzen.
        </p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{ reset_url }}" style="background: #4361ee; color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: 600;">
                Passwort zurücksetzen
            </a>
        </div>
        <p style="font-size: 14px; color: #999;">
            Der Link ist 60 Minuten gültig. Falls du kein Zurücksetzen angefordert hast, ignoriere diese E-Mail.
        </p>
    </div>
</body>
</html>
"""

WEEKLY_REPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="text-align: center; padding: 30px 0;">
        <h1 style="color: #1a1a2e;">Dein Wochenbericht</h1>
        <p style="color: #666;">{{ week_start }}</p>
    </div>
    <div style="background: #f8f9fa; border-radius: 12px; padding: 24px;">
        <p style="font-size: 16px; color: #333;">Hallo {{ name }},</p>
        <p style="font-size: 16px; color: #333;">Hier ist dein Wochenbericht:</p>

        <div style="display: flex; justify-content: space-around; margin: 24px 0; text-align: center;">
            <div style="flex: 1; padding: 16px;">
                <div style="font-size: 32px; font-weight: bold; color: #4361ee;">{{ completed_workouts }}/{{ total_workouts }}</div>
                <div style="font-size: 14px; color: #666;">Training</div>
            </div>
            <div style="flex: 1; padding: 16px;">
                <div style="font-size: 32px; font-weight: bold; color: #2ec4b6;">{{ total_training_min }}</div>
                <div style="font-size: 14px; color: #666;">Minuten</div>
            </div>
            <div style="flex: 1; padding: 16px;">
                <div style="font-size: 32px; font-weight: bold; color: #ff6b6b;">{{ avg_hrv }}</div>
                <div style="font-size: 14px; color: #666;">HRV Ø</div>
            </div>
        </div>

        <div style="text-align: center; margin: 30px 0;">
            <a href="{{ frontend_url }}/dashboard" style="background: #4361ee; color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: 600;">
                Zum Dashboard
            </a>
        </div>
    </div>
    <p style="text-align: center; color: #999; font-size: 13px; margin-top: 24px;">
        TrainIQ — Dein smarter Trainingscoach
    </p>
</body>
</html>
"""

VERIFY_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="text-align: center; padding: 30px 0;">
        <h1 style="color: #1a1a2e;">E-Mail verifizieren</h1>
    </div>
    <div style="background: #f8f9fa; border-radius: 12px; padding: 24px;">
        <p style="font-size: 16px; color: #333;">Hallo {{ name }},</p>
        <p style="font-size: 16px; color: #333;">
            Bitte verifiziere deine E-Mail-Adresse, um dein TrainIQ-Konto zu aktivieren.
        </p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{ verify_url }}" style="background: #4361ee; color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: 600;">
                E-Mail verifizieren
            </a>
        </div>
        <p style="font-size: 14px; color: #999;">
            Der Link ist 24 Stunden gültig. Falls du diese E-Mail nicht angefordert hast, ignoriere sie.
        </p>
    </div>
    <p style="text-align: center; color: #999; font-size: 13px; margin-top: 24px;">
        TrainIQ — Dein smarter Trainingscoach
    </p>
</body>
</html>
"""

jinja_env = Environment(loader=BaseLoader())


class EmailService:
    """Versendet E-Mails via SMTP."""

    def __init__(self):
        self.smtp_host = getattr(settings, "smtp_host", "localhost")
        self.smtp_port = getattr(settings, "smtp_port", 587)
        self.smtp_user = getattr(settings, "smtp_user", "")
        self.smtp_password = getattr(settings, "smtp_password", "")
        self.smtp_use_tls = getattr(settings, "smtp_use_tls", True)
        self.from_email = getattr(settings, "from_email", "noreply@trainiq.app")
        self.from_name = getattr(settings, "from_name", "TrainIQ")

    async def _send(self, to_email: str, subject: str, html_body: str):
        """Versendet eine E-Mail."""
        msg = EmailMessage()
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content("Diese E-Mail erfordert einen HTML-fähigen E-Mail-Client.")
        msg.add_alternative(html_body, subtype="html")

        try:
            import aiosmtplib

            # Port 465 → implicit TLS (use_tls); Port 587 → STARTTLS (start_tls)
            use_implicit_tls = self.smtp_use_tls and self.smtp_port == 465
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user or None,
                password=self.smtp_password or None,
                use_tls=use_implicit_tls,
                start_tls=self.smtp_use_tls and not use_implicit_tls,
            )
            logger.info(f"Email sent | to={to_email} | subject={subject}")
        except Exception as e:
            logger.error(f"Email sending failed | to={to_email} | error={e}")
            raise

    async def send_welcome(self, to_email: str, name: str):
        """Versendet eine Welcome-E-Mail nach Registrierung."""
        template = jinja_env.from_string(WELCOME_TEMPLATE)
        html = template.render(name=name, frontend_url=settings.frontend_url)
        await self._send(to_email, "Willkommen bei TrainIQ!", html)

    async def send_password_reset(
        self, to_email: str, name: str, db: AsyncSession
    ) -> str:
        """
        Generiert einen Reset-Token und versendet die Reset-E-Mail.
        Gibt den Token zurück.
        """
        from app.models.ai_memory import PasswordResetToken

        token = secrets.token_urlsafe(48)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        reset_token = PasswordResetToken(
            user_id=None,  # Wird über Token zugeordnet
            token=token,
            expires_at=expires_at,
        )

        # User-ID holen
        from app.models.user import User

        result = await db.execute(select(User).where(User.email == to_email))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError("User not found")

        reset_token.user_id = user.id
        db.add(reset_token)
        await db.flush()

        reset_url = f"{settings.frontend_url}/reset-password?token={token}"
        template = jinja_env.from_string(RESET_TEMPLATE)
        html = template.render(name=name, reset_url=reset_url)
        await self._send(to_email, "Passwort zurücksetzen — TrainIQ", html)
        await db.commit()

        return token

    async def verify_reset_token(self, token: str, db: AsyncSession) -> str | None:
        """Verifiziert einen Reset-Token. Gibt die User-ID zurück oder None."""
        from app.models.ai_memory import PasswordResetToken
        import uuid

        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.used == False,
                PasswordResetToken.expires_at > datetime.now(timezone.utc),
            )
        )
        reset_token = result.scalar_one_or_none()
        if reset_token:
            return str(reset_token.user_id)
        return None

    async def use_reset_token(
        self, token: str, new_password_hash: str, db: AsyncSession
    ) -> bool:
        """Verwendet einen Reset-Token und setzt das neue Passwort."""
        from app.models.ai_memory import PasswordResetToken

        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.used == False,
                PasswordResetToken.expires_at > datetime.now(timezone.utc),
            )
        )
        reset_token = result.scalar_one_or_none()
        if not reset_token:
            return False

        # Passwort aktualisieren
        from app.models.user import User

        user_result = await db.execute(
            select(User).where(User.id == reset_token.user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return False

        user.password_hash = new_password_hash
        reset_token.used = True
        await db.commit()
        return True

    async def send_weekly_report(self, to_email: str, name: str, stats: dict):
        """Versendet den wöchentlichen Report."""
        template = jinja_env.from_string(WEEKLY_REPORT_TEMPLATE)
        html = template.render(
            name=name,
            week_start=stats.get("week_start", ""),
            completed_workouts=stats.get("completed_workouts", 0),
            total_workouts=stats.get("total_workouts", 0),
            total_training_min=stats.get("total_training_min", 0),
            avg_hrv=stats.get("avg_hrv", 0),
            frontend_url=settings.frontend_url,
        )
        await self._send(to_email, f"Dein Wochenbericht — TrainIQ", html)

    async def send_verification(self, to_email: str, name: str, token: str):
        """Versendet die E-Mail-Verifizierungs-E-Mail."""
        verify_url = f"{settings.frontend_url}/verify-email/{token}"
        template = jinja_env.from_string(VERIFY_EMAIL_TEMPLATE)
        html = template.render(name=name, verify_url=verify_url)
        await self._send(to_email, "E-Mail verifizieren — TrainIQ", html)
