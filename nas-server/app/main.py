from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import settings
from app.database import engine, Base, get_db, init_pgvector
from app.routers import dashboard, videos, tasks, clusters, frames, faces, workers, actors, actor_match
from app.scheduler import setup_scheduler, shutdown_scheduler
import os
import time
from sqlalchemy import text

# 等待数据库就绪并创建表
def init_database():
    max_retries = 30
    for i in range(max_retries):
        try:
            # 尝试连接数据库
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("Database connection successful")
            
            # 启用 pgvector 扩展
            init_pgvector()
            
            # 创建所有表
            Base.metadata.create_all(bind=engine)
            print("Database tables created successfully")
            return
        except Exception as e:
            print(f"Waiting for database... ({i+1}/{max_retries}): {e}")
            time.sleep(2)
    raise Exception("Failed to connect to database after multiple attempts")

init_database()

app = FastAPI(
    title="Video Organization System",
    description="AI-powered video organization system",
    version="1.0.0"
)

app.include_router(dashboard.router)
app.include_router(videos.router)
app.include_router(tasks.router)
app.include_router(clusters.router)
app.include_router(frames.router)
app.include_router(faces.router)
app.include_router(workers.router)
app.include_router(actors.router)
app.include_router(actor_match.router)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.on_event("startup")
async def startup_event():
    setup_scheduler()


@app.on_event("shutdown")
async def shutdown_event():
    shutdown_scheduler()


@app.get("/")
async def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Video Organization API", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
