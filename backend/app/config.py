from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str          # Required — set via DATABASE_URL in .env or docker-compose environment
    secret_key: str            # Required — signs JWT tokens; must be a long random string in production
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7-day sessions
    anthropic_api_key: str     # Required — Anthropic API key for all AI features
    similarity_threshold: float = 0.65  # Min cosine similarity to consider two users a community match
    min_messages_for_profile: int = 6   # Onboarding turns before generating a user profile embedding
    recluster_every_n_users: int = 10   # Trigger full k-means re-cluster after every N new members
    admin_secret: str          # Required — self-service admin elevation via /api/auth/make-admin
    brave_api_key: str = ""       # Optional: Brave Search for live event discovery
    eventbrite_api_key: str = ""  # Optional: Eventbrite for event announcements (reserved for future use)

    class Config:
        env_file = ".env"


settings = Settings()
