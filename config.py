"""
Central config. Follows the $0-stack rule: if real Stripe keys aren't in
.env yet, the app runs in SIMULATED mode -- checkout sessions and webhook
signatures are generated/verified locally with a fake secret, so the whole
system is buildable and testable before a real (still free, still no-card)
Stripe test-mode account exists. Swap in real keys later and nothing else
in the code has to change -- stripe_service.py checks `settings.stripe_live`
and branches.
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./billing.db"

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Used only in simulated mode, to sign/verify fake webhook payloads
    # locally so the exact-same verification code path is exercised.
    simulated_webhook_secret: str = "whsec_simulated_local_dev_secret"

    @property
    def stripe_live(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)

    @property
    def active_webhook_secret(self) -> str:
        return self.stripe_webhook_secret if self.stripe_live else self.simulated_webhook_secret


settings = Settings()
