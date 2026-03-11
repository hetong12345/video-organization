from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import numpy as np
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


@router.get("/{cluster_id}/similar")
def get_similar_clusters(
    cluster_id: int,
    threshold: float = 0.75,
    db: Session = Depends(get_db)
):
    """查找与指定聚类相似的其他聚类"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    if cluster.representative_embedding is None:
        raise HTTPException(status_code=400, detail="Cluster has no embedding")
    
    target_emb = cluster.representative_embedding
    
    # 查询所有其他聚类（排除同一个视频的）
    other_clusters = db.query(Cluster).filter(
        Cluster.id != cluster_id,
        Cluster.video_id != cluster.video_id,
        Cluster.representative_embedding != None
    ).all()
    
    similar_clusters = []
    for c in other_clusters:
        cluster_emb = c.representative_embedding
        
        # 计算余弦相似度
        similarity = np.dot(target_emb, cluster_emb) / (
            np.linalg.norm(target_emb) * np.linalg.norm(cluster_emb)
        )
        
        if similarity >= threshold:
            similar_clusters.append({
                "cluster_id": c.id,
                "video_id": c.video_id,
                "name": c.name,
                "actor_name": c.actor_name,
                "similarity": float(similarity),
                "face_count": c.face_count
            })
    
    # 按相似度排序
    similar_clusters.sort(key=lambda x: x["similarity"], reverse=True)
    
    return {
        "target_cluster": {
            "id": cluster.id,
            "video_id": cluster.video_id,
            "name": cluster.name
        },
        "similar_clusters": similar_clusters[:20]
    }


@router.post("/merge")
def merge_clusters(
    source_cluster_ids: List[int] = Query(...),
    target_cluster_id: int = Query(...),
    db: Session = Depends(get_db)
):
    """合并多个聚类到目标聚类"""
    print(f"[MERGE] Starting merge: source_ids={source_cluster_ids}, target_id={target_cluster_id}")
    
    target = db.query(Cluster).filter(Cluster.id == target_cluster_id).first()
    if not target:
        print(f"[MERGE] Target cluster {target_cluster_id} not found")
        raise HTTPException(status_code=404, detail="Target cluster not found")
    
    print(f"[MERGE] Target cluster found: video_id={target.video_id}, name={target.name}, face_count={target.face_count}")
    
    merged_count = 0
    for source_id in source_cluster_ids:
        if source_id == target_cluster_id:
            print(f"[MERGE] Skipping source_id={source_id} (same as target)")
            continue
        
        source = db.query(Cluster).filter(Cluster.id == source_id).first()
        if not source:
            print(f"[MERGE] Source cluster {source_id} not found, skipping")
            continue
        
        print(f"[MERGE] Merging cluster {source_id} (face_count={source.face_count}) into {target_cluster_id}")
        
        # 将所有人脸转移到目标聚类
        faces = db.query(Face).filter(Face.cluster_id == source_id).all()
        print(f"[MERGE] Found {len(faces)} faces to transfer")
        
        for face in faces:
            face.cluster_id = target_cluster_id
        
        # 删除源聚类
        db.delete(source)
        merged_count += 1
        print(f"[MERGE] Deleted source cluster {source_id}, merged_count={merged_count}")
    
    # 重新计算目标聚类的平均 embedding
    faces = db.query(Face).filter(Face.cluster_id == target_cluster_id).all()
    print(f"[MERGE] Total faces in target cluster: {len(faces)}")
    
    embeddings = [face.embedding for face in faces if face.embedding is not None]
    if embeddings:
        import numpy as np
        target.representative_embedding = np.mean(embeddings, axis=0)
        target.face_count = len(faces)
        print(f"[MERGE] Updated embedding and face_count={target.face_count}")
    
    db.commit()
    print(f"[MERGE] Commit successful. merged_count={merged_count}, total_faces={target.face_count}")
    
    return {
        "success": True,
        "merged_count": merged_count,
        "total_faces": target.face_count
    }


@router.get("/{cluster_id}/faces")
def get_cluster_faces(
    cluster_id: int,
    db: Session = Depends(get_db)
):
    """获取聚类的所有人脸"""
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # 获取该聚类的所有人脸
    faces = db.query(Face).filter(Face.cluster_id == cluster_id).all()
    
    result = []
    for face in faces:
        frame = db.query(Frame).filter(Frame.id == face.frame_id).first()
        result.append({
            "id": face.id,
            "frame_id": face.frame_id,
            "frame_index": frame.frame_index if frame else 0,
            "video_id": face.video_id,
            "bbox_x": face.bbox_x,
            "bbox_y": face.bbox_y,
            "bbox_w": face.bbox_w,
            "bbox_h": face.bbox_h,
            "confidence": face.confidence,
            "actor_name": face.actor_name
        })
    
    return {"faces": result}
