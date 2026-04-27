"""
Application configuration using pydantic-settings
"""
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file="../.env",  # Read from project root
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    app_name: str = "PromptoRAG"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "dev-secret-key-change-in-production"

    # Database (MySQL)
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "promptorag"
    db_user: str = "root"
    db_password: str = ""

    @property
    def database_url(self) -> str:
        """Construct MySQL connection URL"""
        return f"mysql+pymysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"

    # Ollama
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3:8b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_api_key: Optional[str] = None

    # OpenAI API
    openai_api_key: Optional[str] = None

    # Google Gemini API
    gemini_api_key: Optional[str] = None

    # OpenRouter API
    openrouter_api_key: Optional[str] = None

    # Answer generation defaults
    answer_provider: str = "ollama"
    answer_model: str = "gemma4:latest"

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_persist_dir: str = "./chroma_data"

    # File Upload
    upload_dir: str = "./uploads"
    max_upload_size: int = 52428800  # 50MB

    # Knowledge Sources (Network Drive)
    # Use mapped drive letter (W:) or UNC path
    knowledge_source_root: str = "W:\\"
    knowledge_source_unc: str = "\\\\diskstation\\W2_프로젝트폴더"

    # CORS
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "null",
    ]


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
