from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models import Cluster, Face, Video
from app.schemas import ClusterResponse

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


@router.get("", response_model=List[dict])
def list_clusters(
    video_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """获取所有聚类，可按视频筛选"""
    query = db.query(Cluster)
    
    if video_id:
        query = query.filter(Cluster.video_id == video_id)
    
    clusters = query.all()
    
    result = []
    for cluster in clusters:
        # 获取该聚类的所有人脸
        faces = db.query(Face).filter(Face.cluster_id == cluster.id).all()
        
        # 获取预览人脸（前 10 张）
        preview_faces = []
        for face in faces[:10]:
            frame = db.query(Face).filter(Face.id == face.id).first()
            preview_faces.append({
                "id": face.id,
                "frame_id": face.frame_id,
                "video_id": face.video_id
            })
        
        result.append({
            "id": cluster.id,
            "name": cluster.name,
            "video_id": cluster.video_id,
            "face_count": len(faces),
            "preview_faces": preview_faces,
            "editing": False
        })
    
    return result


@router.post("/{cluster_id}/name")
def set_cluster_name(cluster_id: int, request: dict, db: Session = Depends(get_db)):
    """设置聚类名称（角色名）"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    cluster.name = request.get("name", "")
    db.commit()
    
    return {"success": True, "name": cluster.name}


@router.get("/{cluster_id}/faces")
def get_cluster_faces(cluster_id: int, db: Session = Depends(get_db)):
    """获取聚类的所有人脸"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    faces = db.query(Face).filter(Face.cluster_id == cluster_id).all()
    
    result = []
    for face in faces:
        result.append({
            "id": face.id,
            "frame_id": face.frame_id,
            "video_id": face.video_id,
            "bounding_box": face.bounding_box,
            "confidence": face.confidence
        })
    
    return {"cluster_id": cluster_id, "name": cluster.name, "faces": result}
