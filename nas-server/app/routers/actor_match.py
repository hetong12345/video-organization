from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app.database import get_db
from app.models import Actor, Cluster, Face
from pydantic import BaseModel
import numpy as np

router = APIRouter(prefix="/api/actors", tags=["actors"])


@router.get("/find-similar")
def find_similar_actors(
    cluster_id: int,
    threshold: float = Query(0.8, ge=0, le=1, description="相似度阈值（0-1）"),
    db: Session = Depends(get_db)
):
    """查找与指定聚类相似的其他聚类（跨视频）"""
    # 获取目标聚类的代表性特征
    target_cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not target_cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    if target_cluster.representative_embedding is None:
        raise HTTPException(status_code=400, detail="Cluster has no embedding")
    
    target_emb = target_cluster.representative_embedding
    
    # 查询所有其他聚类（排除同一个视频的）
    other_clusters = db.query(Cluster).filter(
        Cluster.id != cluster_id,
        Cluster.video_id != target_cluster.video_id,
        Cluster.representative_embedding != None
    ).all()
    
    similar_actors = []
    for cluster in other_clusters:
        cluster_emb = cluster.representative_embedding
        
        # 计算余弦相似度
        similarity = np.dot(target_emb, cluster_emb) / (
            np.linalg.norm(target_emb) * np.linalg.norm(cluster_emb)
        )
        
        if similarity >= threshold:
            similar_actors.append({
                "cluster_id": cluster.id,
                "video_id": cluster.video_id,
                "name": cluster.name,
                "actor_name": cluster.actor_name,
                "similarity": float(similarity),
                "face_count": cluster.face_count
            })
    
    # 按相似度排序
    similar_actors.sort(key=lambda x: x["similarity"], reverse=True)
    
    return {
        "target_cluster": {
            "id": target_cluster.id,
            "video_id": target_cluster.video_id,
            "name": target_cluster.name
        },
        "similar_actors": similar_actors[:20]  # 最多返回 20 个
    }


@router.post("/merge-clusters")
def merge_clusters(
    source_cluster_ids: List[int],
    target_cluster_id: int,
    db: Session = Depends(get_db)
):
    """合并多个聚类到目标聚类"""
    target = db.query(Cluster).filter(Cluster.id == target_cluster_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target cluster not found")
    
    merged_count = 0
    for source_id in source_cluster_ids:
        if source_id == target_cluster_id:
            continue
        
        source = db.query(Cluster).filter(Cluster.id == source_id).first()
        if not source:
            continue
        
        # 将所有人脸转移到目标聚类
        faces = db.query(Face).filter(Face.cluster_id == source_id).all()
        for face in faces:
            face.cluster_id = target_cluster_id
        
        # 删除源聚类
        db.delete(source)
        merged_count += 1
    
    # 重新计算目标聚类的平均 embedding
    faces = db.query(Face).filter(Face.cluster_id == target_cluster_id).all()
    embeddings = [face.embedding for face in faces if face.embedding is not None]
    if embeddings:
        import numpy as np
        target.representative_embedding = np.mean(embeddings, axis=0)
        target.face_count = len(faces)
    
    db.commit()
    
    return {
        "success": True,
        "merged_count": merged_count,
        "total_faces": target.face_count
    }
