from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import os
from app.database import get_db
from app.models import Video, Frame, Face, Task, VideoStatus, TaskType, TaskStatus
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


@router.get("/system-directories")
def list_system_directories(base_path: str = "/media"):
    """列出系统目录结构，用于选择扫描目录"""
    result = []
    
    if not os.path.exists(base_path):
        return {"directories": result}
    
    try:
        for item in os.listdir(base_path):
            full_path = os.path.join(base_path, item)
            if os.path.isdir(full_path):
                try:
                    video_count = sum(1 for f in os.listdir(full_path) 
                                    if os.path.splitext(f)[1].lower() in {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'})
                    result.append({
                        "path": full_path,
                        "name": item,
                        "video_count": video_count,
                        "has_subdirs": any(os.path.isdir(os.path.join(full_path, s)) for s in os.listdir(full_path))
                    })
                except:
                    result.append({
                        "path": full_path,
                        "name": item,
                        "video_count": 0,
                        "has_subdirs": False
                    })
    except Exception as e:
        print(f"Error listing directories: {e}")
    
    return {"directories": sorted(result, key=lambda x: x['name'])}


@router.post("/scan")
def scan_videos(data: dict, db: Session = Depends(get_db)):
    from app.services.video_processor import VideoScanner
    
    directories = data.get("directories", [])
    
    if not directories:
        return {"results": [], "error": "No directories provided"}
    
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
def start_process(data: dict, db: Session = Depends(get_db)):
    from app.services.video_processor import FrameExtractor
    
    video_ids = data.get("video_ids", [])
    force = data.get("force", False)
    
    if not video_ids:
        return {"results": [], "error": "No video_ids provided"}
    
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


@router.post("/adopt")
def adopt_videos(data: dict, db: Session = Depends(get_db)):
    video_ids = data.get("video_ids", [])
    custom_names = data.get("custom_names")
    
    if not video_ids:
        return {"results": [], "error": "No video_ids provided"}
    
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


@router.get("/{video_id}", response_model=VideoResponse)
def get_video(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.get("/{video_id}/frames", response_model=List[FrameResponse])
def get_video_frames(video_id: int, db: Session = Depends(get_db)):
    frames = db.query(Frame).filter(Frame.video_id == video_id).all()
    
    # 统计每帧的人脸数量
    result = []
    for frame in frames:
        face_count = db.query(Face).filter(Face.frame_id == frame.id).count()
        frame_dict = {
            "id": frame.id,
            "video_id": frame.video_id,
            "frame_path": frame.frame_path,
            "frame_index": frame.frame_index,
            "timestamp": frame.timestamp,
            "is_representative": frame.is_representative,
            "face_count": face_count
        }
        result.append(frame_dict)
    
    return result


@router.get("/{video_id}/tasks")
def get_video_tasks(video_id: int, db: Session = Depends(get_db)):
    """获取视频的所有任务"""
    tasks = db.query(Task).filter(Task.video_id == video_id).all()
    return [
        {
            "id": t.id,
            "task_type": t.task_type.value,
            "status": t.status.value,
            "video_id": t.video_id,
            "worker_id": t.worker_id,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None
        }
        for t in tasks
    ]


@router.post("/{video_id}/re-extract")
def re_extract_frames(video_id: int, db: Session = Depends(get_db)):
    from app.services.video_processor import FrameExtractor
    
    extractor = FrameExtractor()
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    frames = extractor.extract_frames(video_id, force=True)
    
    return {"success": True, "frames_extracted": len(frames)}
