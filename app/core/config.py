import os

from dotenv import load_dotenv
from pydantic import BaseModel


def load_settings() -> "Settings":
    load_dotenv()
    return Settings(
        app_name=os.getenv("APP_NAME", "采购配送管理接口"),
        jwt_secret=os.getenv("JWT_SECRET", "change-me"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        db_url=os.getenv(
            "DATABASE_URL", "mysql+pymysql://user:pass@localhost:3306/pd"
        ),
        coze_stream_url=os.getenv("Coze_url") or os.getenv("COZE_URL"),
        coze_project_id=os.getenv("project_id") or os.getenv("COZE_PROJECT_ID"),
        coze_session_id=os.getenv("session_id") or os.getenv("COZE_SESSION_ID"),
        coze_bearer_token=os.getenv("YOUR_TOKEN") or os.getenv("COZE_BEARER_TOKEN"),
    )


class Settings(BaseModel):
    app_name: str
    jwt_secret: str
    jwt_algorithm: str
    db_url: str
    coze_stream_url: str | None = None
    coze_project_id: str | None = None
    coze_session_id: str | None = None
    coze_bearer_token: str | None = None


settings = load_settings()
