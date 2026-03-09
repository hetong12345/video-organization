from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import Video, Task, Worker, VideoStatus, TaskStatus
from app.schemas import DashboardStats
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db)):
    total_videos = db.query(func.count(Video.id)).scalar()
    pending_videos = db.query(func.count(Video.id)).filter(Video.status == VideoStatus.PENDING).scalar()
    processing_videos = db.query(func.count(Video.id)).filter(
        Video.status.in_([VideoStatus.PROCESSING, VideoStatus.FEATURED, VideoStatus.CLUSTERED])
    ).scalar()
    ready_videos = db.query(func.count(Video.id)).filter(Video.status == VideoStatus.READY).scalar()
    completed_videos = db.query(func.count(Video.id)).filter(Video.status == VideoStatus.COMPLETED).scalar()
    
    total_tasks = db.query(func.count(Task.id)).scalar()
    pending_tasks = db.query(func.count(Task.id)).filter(Task.status == TaskStatus.PENDING).scalar()
    running_tasks = db.query(func.count(Task.id)).filter(
        Task.status.in_([TaskStatus.ASSIGNED, TaskStatus.RUNNING])
    ).scalar()
    
    five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
    online_workers = db.query(func.count(Worker.id)).filter(
        Worker.last_heartbeat >= five_minutes_ago
    ).scalar()
    
    return DashboardStats(
        total_videos=total_videos or 0,
        pending_videos=pending_videos or 0,
        processing_videos=processing_videos or 0,
        ready_videos=ready_videos or 0,
        completed_videos=completed_videos or 0,
        total_tasks=total_tasks or 0,
        pending_tasks=pending_tasks or 0,
        running_tasks=running_tasks or 0,
        online_workers=online_workers or 0
    )
