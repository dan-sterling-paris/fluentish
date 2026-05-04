import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Google Sheets
    google_service_account_json: str = ""
    spreadsheet_id: str = ""
    sheet_name: str = "Sheet1"
    sheet_name_col: int = 1
    sheet_phone_col: int = 2
    sheet_status_col: int = 3
    ingested_marker: str = "Ingested"

    # ClickSend
    clicksend_username: str = ""
    clicksend_api_key: str = ""
    clicksend_from: str = "FluentISH"
    clicksend_webhook_secret: str = ""

    # SMS Templates — use {name} as the only interpolation token
    template_1: str = "Hi {name}, thanks for your interest in French lessons! Are you looking for in-person or online classes?"
    template_2: str = "Hi {name}, just checking in — have you had a chance to think about your French learning goals?"
    template_3: str = "Hi {name}, I have some availability this week if you'd like to book a free 15-minute discovery call!"

    # App
    database_url: str = "sqlite+aiosqlite:///./crm.db"
    port: int = 8001

    def validate_service_account(self) -> None:
        if self.google_service_account_json and not Path(self.google_service_account_json).exists():
            raise ValueError(
                f"GOOGLE_SERVICE_ACCOUNT_JSON path does not exist: {self.google_service_account_json}"
            )


settings = Settings()
