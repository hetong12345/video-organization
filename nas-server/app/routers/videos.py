from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
import os
import shutil
from app.database import get_db
from app.models import Video, Frame, Face, VideoTag, Tag, VideoActor, Actor, VideoStatus
from app.schemas import (
    VideoCreate, VideoResponse, VideoListResponse, FrameResponse,
    FaceResponse, AdoptRequest
)
from app.config import settings

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("", response_model=List[VideoListResponse])
def list_videos(
    status: Optional[VideoStatus] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    query = db.query(Video)
    if status:
        query = query.filter(Video.status == status)
    
    videos = query.order_by(Video.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for video in videos:
        actors = db.query(Actor.name).join(VideoActor).filter(
            VideoActor.video_id == video.id
        ).all()
        actor_names = [a[0] for a in actors]
        
        tags = db.query(Tag.name).join(VideoTag).filter(
            VideoTag.video_id == video.id
        ).all()
        tag_names = [t[0] for t in tags]
        
        rep_frame = db.query(Frame).filter(
            Frame.video_id == video.id,
            Frame.is_representative == True
        ).first()
        thumbnail_url = f"/api/frames/{rep_frame.id}/image" if rep_frame else None
        
        result.append(VideoListResponse(
            id=video.id,
            filename=video.filename,
            status=video.status,
            recommended_name=video.recommended_name,
            thumbnail_url=thumbnail_url,
            actors=actor_names,
            tags=tag_names
        ))
    
    return result


@router.get("/{video_id}", response_model=VideoResponse)
def get_video(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.post("", response_model=VideoResponse)
def create_video(video: VideoCreate, db: Session = Depends(get_db)):
    db_video = Video(**video.model_dump())
    db.add(db_video)
    db.commit()
    db.refresh(db_video)
    return db_video


@router.get("/{video_id}/frames", response_model=List[FrameResponse])
def get_video_frames(video_id: int, db: Session = Depends(get_db)):
    frames = db.query(Frame).filter(Frame.video_id == video_id).all()
    return frames


@router.get("/{video_id}/faces", response_model=List[FaceResponse])
def get_video_faces(video_id: int, db: Session = Depends(get_db)):
    faces = db.query(Face).join(Frame).filter(Frame.video_id == video_id).all()
    return faces


@router.post("/adopt")
def adopt_videos(request: AdoptRequest, db: Session = Depends(get_db)):
    results = []
    for video_id in request.video_ids:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            results.append({"video_id": video_id, "success": False, "error": "Not found"})
            continue
        
        if video.status != VideoStatus.READY:
            results.append({"video_id": video_id, "success": False, "error": "Not ready"})
            continue
        
        custom_name = request.custom_names.get(str(video_id)) if request.custom_names else None
        new_name = custom_name or video.recommended_name
        
        if not new_name:
            results.append({"video_id": video_id, "success": False, "error": "No name"})
            continue
        
        actors = db.query(Actor.name).join(VideoActor).filter(
            VideoActor.video_id == video.id
        ).first()
        actor_name = actors[0] if actors else "Unknown"
        
        target_dir = os.path.join(settings.PROCESSED_VIDEO_DIR, actor_name)
        os.makedirs(target_dir, exist_ok=True)
        
        target_path = os.path.join(target_dir, new_name)
        
        try:
            shutil.move(video.filepath, target_path)
            video.target_path = target_path
            video.status = VideoStatus.COMPLETED
            db.commit()
            results.append({"video_id": video_id, "success": True, "target_path": target_path})
        except Exception as e:
            results.append({"video_id": video_id, "success": False, "error": str(e)})
    
    return {"results": results}


@router.delete("/{video_id}")
def delete_video(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    db.delete(video)
    db.commit()
    return {"success": True}
