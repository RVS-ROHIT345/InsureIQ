"""
InsureIQ — Application Settings
Loads all configuration from environment variables via python-dotenv.
No secrets ever live in this file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).parent.parent / ".env")


class Settings:
    """Centralized app config. All values come from environment variables."""

    # --- Gemini API ---
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    # gemini-2.5-flash: 1M token context handles full insurance docs; fast + cheap.
    # (gemini-1.5-pro was retired by Google — returns 404. Switch to "gemini-2.5-pro"
    #  for higher-quality reasoning at higher latency/cost.)
    # Overridable via the GEMINI_MODEL env var.
    GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    # --- Application ---
    APP_ENV: str = os.environ.get("APP_ENV", "development")
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

    # --- File upload constraints ---
    MAX_FILE_SIZE_MB: int = int(os.environ.get("MAX_FILE_SIZE_MB", "50"))
    MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024
    ALLOWED_EXTENSIONS: set = {"pdf", "docx"}

    # --- MCP server ---
    MCP_SERVER_HOST: str = os.environ.get("MCP_SERVER_HOST", "0.0.0.0")
    MCP_SERVER_PORT: int = int(os.environ.get("MCP_SERVER_PORT", "8001"))

    # --- FastAPI ---
    API_HOST: str = os.environ.get("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.environ.get("API_PORT", "8000"))

    # --- CORS ---
    # Comma-separated list of allowed browser origins. Defaults to "*" for
    # development; set an explicit allow-list in production (e.g. the deployed
    # frontend origin) to lock down cross-origin access.
    CORS_ALLOWED_ORIGINS: list = [
        origin.strip()
        for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",")
        if origin.strip()
    ]

    # --- Document type detection keywords ---
    # Used by Ingestion Agent to classify uploaded insurance documents
    DOC_TYPE_KEYWORDS: dict = {
        "health": [
            "health insurance", "mediclaim", "hospitalization", "medical expenses",
            "pre-existing disease", "cashless treatment", "network hospital",
            "room rent", "critical illness", "surgical benefit"
        ],
        "life": [
            "life insurance", "sum assured", "death benefit", "maturity benefit",
            "premium paying term", "endowment", "term plan", "whole life",
            "ulip", "unit linked", "surrender value", "paid-up value"
        ],
        "car": [
            "motor insurance", "vehicle insurance", "own damage", "third party",
            "idv", "insured declared value", "no claim bonus", "comprehensive cover",
            "collision damage", "roadside assistance"
        ],
        "home": [
            "home insurance", "property insurance", "structure coverage",
            "contents coverage", "flood damage", "fire damage", "burglary",
            "homeowner", "dwelling coverage"
        ],
    }

    def validate(self) -> None:
        """Raise immediately if required config is missing. Called at startup."""
        if not self.GEMINI_API_KEY:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. "
                "Copy .env.example to .env and add your Gemini API key."
            )


# Singleton instance — import this everywhere
settings = Settings()
