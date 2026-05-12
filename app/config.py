from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://docqa:docqa@localhost:5432/docqa"
    REDIS_URL: str = "redis://localhost:6379/0"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    UPLOAD_DIR: str = "data/uploads"
    INDEX_DIR: str = "data/indexes"
    MAX_FILE_SIZE_MB: int = 50
    SECRET_KEY: str = "change-this-in-production"

    class Config:
        env_file = ".env"


settings = Settings()
