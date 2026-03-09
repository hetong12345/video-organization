from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/video_org"
    RAW_VIDEO_DIR: str = "/media/raw"
    PROCESSED_VIDEO_DIR: str = "/media/processed"
    CACHE_DIR: str = "/cache"
    FRAME_CACHE_DIR: str = "/cache/frames"
    
    MIN_FACE_RATIO: float = 0.1
    MAX_RETRY_COUNT: int = 3
    WORKER_TIMEOUT: int = 300
    
    FEATURE_BATCH_SIZE: int = 100
    CLUSTER_MIN_SAMPLES: int = 5
    
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
