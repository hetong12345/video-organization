from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.models import Task, Video, Frame, Face, Cluster, Tag, VideoTag, Actor, VideoActor, TaskType, TaskStatus, VideoStatus
from app.schemas import (
    TaskCreate, TaskResponse, TaskPullRequest,
    FeatureSubmitRequest, ClusterSubmitRequest, TagSubmitRequest
)
from app.config import settings
from datetime import datetime

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=List[TaskResponse])
def list_tasks(
    status: TaskStatus = None,
    task_type: TaskType = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    query = db.query(Task)
    if status:
        query = query.filter(Task.status == status)
    if task_type:
        query = query.filter(Task.task_type == task_type)
    
    return query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


@router.post("", response_model=TaskResponse)
def create_task(task: TaskCreate, db: Session = Depends(get_db)):
    db_task = Task(**task.model_dump())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


@router.post("/pull")
def pull_tasks(request: TaskPullRequest, db: Session = Depends(get_db)):
    tasks = []
    for task_type_str in request.task_types:
        # Convert string to TaskType enum if needed
        if isinstance(task_type_str, str):
            try:
                task_type = TaskType(task_type_str)
            except ValueError:
                continue
        else:
            task_type = task_type_str
        
        available_tasks = db.query(Task).filter(
            Task.task_type == task_type,
            Task.status == TaskStatus.PENDING,
            Task.retry_count < settings.MAX_RETRY_COUNT
        ).limit(request.max_tasks).with_for_update(skip_locked=True).all()
        
        for task in available_tasks:
            task.status = TaskStatus.ASSIGNED
            task.worker_id = request.worker_id
            task.started_at = datetime.utcnow()
            
            task_data = {
                "id": task.id,
                "task_type": task.task_type.value,
                "video_id": task.video_id,
            }
            # Only include optional fields if they exist
            if task.frame_id:
                task_data["frame_id"] = task.frame_id
            if task.face_id:
                task_data["face_id"] = task.face_id
            if task.cluster_id:
                task_data["cluster_id"] = task.cluster_id
                
            tasks.append(task_data)
        
        db.commit()
    
    return {"tasks": tasks}


@router.post("/feature/submit")
def submit_feature(request: FeatureSubmitRequest, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == request.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    face = db.query(Face).filter(Face.id == request.face_id).first()
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")
    
    face.embedding = request.embedding
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    
    video = db.query(Video).filter(Video.id == task.video_id).first()
    if video:
        unprocessed_faces = db.query(Face).join(Frame).filter(
            Frame.video_id == video.id,
            Face.embedding == None
        ).count()
        
        if unprocessed_faces == 0:
            video.status = VideoStatus.FEATURED
    
    db.commit()
    return {"success": True}


@router.post("/cluster/submit")
def submit_cluster(request: ClusterSubmitRequest, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == request.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    for result in request.cluster_results:
        face = db.query(Face).filter(Face.id == result["face_id"]).first()
        if face:
            face.cluster_id = result["cluster_id"]
            
            cluster = db.query(Cluster).filter(Cluster.id == result["cluster_id"]).first()
            if not cluster:
                cluster = Cluster(id=result["cluster_id"], face_count=0)
                db.add(cluster)
            cluster.face_count += 1
    
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    
    videos = db.query(Video).filter(Video.status == VideoStatus.FEATURED).all()
    for video in videos:
        unclustered = db.query(Face).join(Frame).filter(
            Frame.video_id == video.id,
            Face.cluster_id == None
        ).count()
        if unclustered == 0:
            video.status = VideoStatus.CLUSTERED
    
    db.commit()
    return {"success": True}


@router.post("/tag/submit")
def submit_tag(request: TagSubmitRequest, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == request.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    video = db.query(Video).filter(Video.id == request.video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    for tag_name in request.tags:
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.add(tag)
            db.flush()
        
        existing = db.query(VideoTag).filter(
            VideoTag.video_id == video.id,
            VideoTag.tag_id == tag.id
        ).first()
        if not existing:
            video_tag = VideoTag(video_id=video.id, tag_id=tag.id)
            db.add(video_tag)
    
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    video.status = VideoStatus.TAGGED
    
    _check_video_ready(video, db)
    
    db.commit()
    return {"success": True}


def _check_video_ready(video: Video, db: Session):
    actors = db.query(VideoActor).filter(VideoActor.video_id == video.id).count()
    tags = db.query(VideoTag).filter(VideoTag.video_id == video.id).count()
    
    if actors > 0 and tags > 0:
        actor_names = db.query(Actor.name).join(VideoActor).filter(
            VideoActor.video_id == video.id
        ).all()
        tag_names = db.query(Tag.name).join(VideoTag).filter(
            VideoTag.video_id == video.id
        ).all()
        
        actor_str = "_".join([a[0] for a in actor_names])
        tag_str = "_".join([t[0] for t in tag_names[:2]])
        
        name, ext = video.filename.rsplit(".", 1) if "." in video.filename else (video.filename, "mp4")
        video.recommended_name = f"[{actor_str}]_{tag_str}_{name}.{ext}"
        video.status = VideoStatus.READY


@router.post("/{task_id}/fail")
def fail_task(task_id: int, error_message: str = "", db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task.status = TaskStatus.FAILED
    task.error_message = error_message
    task.retry_count += 1
    
    if task.retry_count < settings.MAX_RETRY_COUNT:
        task.status = TaskStatus.PENDING
    
    db.commit()
    return {"success": True}


@router.post("/{task_id}/retry")
def retry_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task.status = TaskStatus.PENDING
    task.worker_id = None
    task.error_message = None
    db.commit()
    return {"success": True}
