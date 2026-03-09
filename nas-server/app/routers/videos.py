from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import os
from app.database import get_db
from app.models import Video, Frame, Task, VideoStatus, TaskType, TaskStatus
from app.schemas import VideoCreate, VideoResponse, VideoListResponse, FrameResponse
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
        actors = []
        tags = []
        
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
            actors=actors,
            tags=tags
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


@router.post("/scan")
def scan_videos(directories: Optional[List[str]] = None, db: Session = Depends(get_db)):
    from app.services.video_processor import VideoScanner
    
    if directories is None:
        directories = [settings.RAW_VIDEO_DIR]
    
    results = []
    for directory in directories:
        if not os.path.exists(directory):
            results.append({"directory": directory, "error": "Directory not found", "videos": 0})
            continue
        
        scanner = VideoScanner(directory)
        new_videos = scanner.scan_directory()
        
        results.append({"directory": directory, "videos": len(new_videos)})
    
    return {"results": results}


@router.post("/start-process")
def start_process(video_ids: List[int], force: bool = False, db: Session = Depends(get_db)):
    from app.services.video_processor import FrameExtractor
    
    extractor = FrameExtractor()
    results = []
    
    for video_id in video_ids:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            results.append({"video_id": video_id, "success": False, "error": "Video not found"})
            continue
        
        if video.status not in [VideoStatus.PENDING, VideoStatus.READY]:
            if not force:
                results.append({"video_id": video_id, "success": False, "error": f"Video status is {video.status}"})
                continue
        
        extractor.extract_frames(video_id, force=force)
        results.append({"video_id": video_id, "success": True})
    
    return {"results": results}


@router.post("/{video_id}/re-extract")
def re_extract_frames(video_id: int, db: Session = Depends(get_db)):
    from app.services.video_processor import FrameExtractor
    
    extractor = FrameExtractor()
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    frames = extractor.extract_frames(video_id, force=True)
    
    return {"success": True, "frames_extracted": len(frames)}


@router.post("/adopt")
def adopt_videos(
    video_ids: List[int],
    custom_names: Optional[dict] = None,
    db: Session = Depends(get_db)
):
    results = []
    
    for video_id in video_ids:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            results.append({"video_id": video_id, "success": False, "error": "Video not found"})
            continue
        
        if custom_names and video_id in custom_names:
            video.recommended_name = custom_names[video_id]
        
        video.status = VideoStatus.COMPLETED
        db.commit()
        results.append({"video_id": video_id, "success": True})
    
    return {"results": results}


@router.get("/directories")
def list_video_directories():
    dirs = []
    if not os.path.exists('/media'):
        return {"directories": dirs}
    
    for root, subdirs, files in os.walk('/media'):
        for subdir in subdirs:
            full_path = os.path.join(root, subdir)
            try:
                video_count = sum(1 for f in os.listdir(full_path) 
                                if os.path.splitext(f)[1].lower() in {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'})
                if video_count > 0:
                    dirs.append({
                        "path": full_path,
                        "video_count": video_count
                    })
            except:
                pass
    
    return {"directories": dirs}
