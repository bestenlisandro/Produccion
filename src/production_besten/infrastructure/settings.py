from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: SecretStr
    app_env: str = "production"

    def sqlalchemy_database_url(self) -> str:
        return self.database_url.get_secret_value()
