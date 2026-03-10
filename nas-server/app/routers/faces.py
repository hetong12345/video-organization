from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models import Face, Frame
import os

router = APIRouter(prefix="/api/faces", tags=["faces"])


@router.post("")
def create_face(face_data: dict, db: Session = Depends(get_db)):
    """创建人脸记录"""
    frame = db.query(Frame).filter(Frame.id == face_data["frame_id"]).first()
    if not frame:
        raise HTTPException(status_code=404, detail="Frame not found")
    
    bbox = face_data.get("bounding_box", [0, 0, 0, 0])
    
    face = Face(
        video_id=face_data["video_id"],
        frame_id=face_data["frame_id"],
        bbox_x=int(bbox[0]),
        bbox_y=int(bbox[1]),
        bbox_w=int(bbox[2]),
        bbox_h=int(bbox[3]),
        confidence=face_data.get("confidence", 1.0),
        embedding=face_data.get("embedding")
    )
    db.add(face)
    db.commit()
    db.refresh(face)
    
    print(f"Created face {face.id} for frame {face.frame_id}")
    return {"id": face.id, "face_id": face.id}


@router.get("")
def list_faces(
    has_embedding: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """获取人脸列表"""
    query = db.query(Face)
    
    if has_embedding is True:
        query = query.filter(Face.embedding != None)
    elif has_embedding is False:
        query = query.filter(Face.embedding == None)
    
    faces = query.offset(skip).limit(limit).all()
    
    return {
        "faces": [
            {
                "id": face.id,
                "video_id": face.video_id,
                "frame_id": face.frame_id,
                "embedding": face.embedding.tolist() if face.embedding else None,
                "cluster_id": face.cluster_id
            }
            for face in faces
        ]
    }


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
