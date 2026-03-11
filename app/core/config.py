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
    )


class Settings(BaseModel):
    app_name: str
    jwt_secret: str
    jwt_algorithm: str
    db_url: str


settings = load_settings()
