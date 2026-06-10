from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/communityai"
    secret_key: str = "changeme-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    anthropic_api_key: str
    similarity_threshold: float = 0.65
    min_messages_for_profile: int = 6
    recluster_every_n_users: int = 10
    admin_secret: str = "change-this-admin-secret"
    brave_api_key: str = ""
    eventbrite_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
