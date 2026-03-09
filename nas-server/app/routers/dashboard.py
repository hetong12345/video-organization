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
    total_videos = db.query(func.count(Video.id)).scalar() or 0
    
    pending_videos = db.query(func.count(Video.id)).filter(
        Video.status == VideoStatus.PENDING
    ).scalar() or 0
    
    processing_videos = db.query(func.count(Video.id)).filter(
        Video.status == VideoStatus.PROCESSING
    ).scalar() or 0
    
    featured_videos = db.query(func.count(Video.id)).filter(
        Video.status == VideoStatus.FEATURED
    ).scalar() or 0
    
    clustered_videos = db.query(func.count(Video.id)).filter(
        Video.status == VideoStatus.CLUSTERED
    ).scalar() or 0
    
    tagged_videos = db.query(func.count(Video.id)).filter(
        Video.status == VideoStatus.TAGGED
    ).scalar() or 0
    
    ready_videos = db.query(func.count(Video.id)).filter(
        Video.status == VideoStatus.READY
    ).scalar() or 0
    
    completed_videos = db.query(func.count(Video.id)).filter(
        Video.status == VideoStatus.COMPLETED
    ).scalar() or 0
    
    pending_tasks = db.query(func.count(Task.id)).filter(
        Task.status == TaskStatus.PENDING
    ).scalar() or 0
    
    running_tasks = db.query(func.count(Task.id)).filter(
        Task.status.in_([TaskStatus.ASSIGNED, TaskStatus.RUNNING])
    ).scalar() or 0
    
    five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
    online_workers = db.query(func.count(Worker.id)).filter(
        Worker.last_heartbeat >= five_minutes_ago
    ).scalar() or 0
    
    return DashboardStats(
        total_videos=total_videos,
        pending_videos=pending_videos,
        processing_videos=featured_videos + clustered_videos + tagged_videos,
        ready_videos=ready_videos,
        completed_videos=completed_videos,
        total_tasks=db.query(func.count(Task.id)).scalar() or 0,
        pending_tasks=pending_tasks,
        running_tasks=running_tasks,
        online_workers=online_workers
    )
