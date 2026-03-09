from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Frame, Face
from app.config import settings
import os

router = APIRouter(prefix="/api/frames", tags=["frames"])


@router.get("/{frame_id}/image")
def get_frame_image(frame_id: int, db: Session = Depends(get_db)):
    frame = db.query(Frame).filter(Frame.id == frame_id).first()
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")
    
    if not os.path.exists(frame.frame_path):
        raise HTTPException(status_code=404, detail="Image file not found")
    
    return FileResponse(frame.frame_path, media_type="image/jpeg")


@router.get("/{frame_id}")
def get_frame(frame_id: int, db: Session = Depends(get_db)):
    frame = db.query(Frame).filter(Frame.id == frame_id).first()
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")
    
    return {
        "id": frame.id,
        "video_id": frame.video_id,
        "frame_path": frame.frame_path,
        "frame_index": frame.frame_index,
        "timestamp": frame.timestamp,
        "is_representative": frame.is_representative
    }


@router.get("/{frame_id}/faces")
def get_frame_faces(frame_id: int, db: Session = Depends(get_db)):
    faces = db.query(Face).filter(Face.frame_id == frame_id).all()
    return [{
        "id": f.id,
        "bbox": [f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h],
        "gender": f.gender,
        "age": f.age,
        "quality_score": f.quality_score,
        "cluster_id": f.cluster_id,
        "actor_name": f.actor_name
    } for f in faces]
