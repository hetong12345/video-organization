from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Face, Frame
import os

router = APIRouter(prefix="/api/faces", tags=["faces"])


@router.get("/{face_id}/image")
def get_face_image(face_id: int, db: Session = Depends(get_db)):
    face = db.query(Face).filter(Face.id == face_id).first()
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")
    
    frame = db.query(Frame).filter(Frame.id == face.frame_id).first()
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")
    
    if not os.path.exists(frame.frame_path):
        raise HTTPException(status_code=404, detail="Image file not found")
    
    return FileResponse(frame.frame_path, media_type="image/jpeg")


@router.get("/{face_id}")
def get_face(face_id: int, db: Session = Depends(get_db)):
    face = db.query(Face).filter(Face.id == face_id).first()
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")
    
    return {
        "id": face.id,
        "frame_id": face.frame_id,
        "bbox": [face.bbox_x, face.bbox_y, face.bbox_w, face.bbox_h],
        "gender": face.gender,
        "age": face.age,
        "quality_score": face.quality_score,
        "cluster_id": face.cluster_id,
        "actor_name": face.actor_name
    }


@router.get("/{face_id}/embedding")
def get_face_embedding(face_id: int, db: Session = Depends(get_db)):
    face = db.query(Face).filter(Face.id == face_id).first()
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")
    
    if face.embedding is None:
        raise HTTPException(status_code=404, detail="Embedding not found")
    
    return {
        "face_id": face.id,
        "embedding": face.embedding.tolist() if hasattr(face.embedding, 'tolist') else face.embedding
    }
