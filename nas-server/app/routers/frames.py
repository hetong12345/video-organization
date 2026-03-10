from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Frame, Face
from app.schemas import FrameResponse
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


@router.get("/{frame_id}", response_model=FrameResponse)
def get_frame(frame_id: int, db: Session = Depends(get_db)):
    frame = db.query(Frame).filter(Frame.id == frame_id).first()
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")
    return frame


@router.get("/{frame_id}/faces")
def get_frame_faces(frame_id: int, db: Session = Depends(get_db)):
    """获取某帧的所有人脸"""
    faces = db.query(Face).filter(Face.frame_id == frame_id).all()
    return [
        {
            "id": face.id,
            "frame_id": face.frame_id,
            "video_id": face.video_id,
            "bounding_box": [face.bbox_x, face.bbox_y, face.bbox_w, face.bbox_h],
            "confidence": face.confidence,
            "cluster_id": face.cluster_id,
            "actor_name": face.actor_name
        }
        for face in faces
    ]
