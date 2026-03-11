from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app.database import get_db
from app.models import Actor, Cluster, Face, Video, VideoActor
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/actors", tags=["actors"])


class ActorResponse(BaseModel):
    id: int
    name: str
    cluster_count: int = 0
    video_count: int = 0
    face_count: int = 0
    created_at: datetime
    
    class Config:
        from_attributes = True


class ActorCreate(BaseModel):
    name: str
    cluster_ids: List[int] = []


class ActorUpdate(BaseModel):
    name: Optional[str] = None
    cluster_ids: Optional[List[int]] = None


@router.get("", response_model=List[ActorResponse])
def list_actors(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """获取所有演员列表"""
    actors = db.query(Actor).order_by(Actor.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for actor in actors:
        # 统计该演员的聚类数量
        cluster_count = db.query(Cluster).filter(Cluster.actor_name == actor.name).count()
        
        # 统计该演员的人脸数量
        face_count = db.query(Face).join(Cluster).filter(
            Cluster.actor_name == actor.name
        ).count()
        
        # 统计该演员出现的视频数量
        video_count = db.query(Video).join(Face).join(Cluster).filter(
            Cluster.actor_name == actor.name
        ).distinct().count()
        
        result.append({
            "id": actor.id,
            "name": actor.name,
            "cluster_count": cluster_count,
            "video_count": video_count,
            "face_count": face_count,
            "created_at": actor.created_at
        })
    
    return result


@router.get("/{actor_id}")
def get_actor(actor_id: int, db: Session = Depends(get_db)):
    """获取演员详情"""
    actor = db.query(Actor).filter(Actor.id == actor_id).first()
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")
    
    # 获取该演员的所有聚类
    clusters = db.query(Cluster).filter(Cluster.actor_name == actor.name).all()
    cluster_ids = [c.id for c in clusters]
    
    # 统计人脸数量
    face_count = db.query(Face).filter(Face.cluster_id.in_(cluster_ids)).count()
    
    # 获取出现的视频列表
    videos = db.query(Video).join(Face).filter(Face.cluster_id.in_(cluster_ids)).distinct().all()
    
    return {
        "id": actor.id,
        "name": actor.name,
        "cluster_count": len(clusters),
        "video_count": len(videos),
        "face_count": face_count,
        "created_at": actor.created_at,
        "clusters": [{"id": c.id, "video_id": c.video_id} for c in clusters],
        "videos": [{"id": v.id, "filename": v.filename} for v in videos[:20]]  # 限制返回 20 个
    }


@router.post("")
def create_actor(actor_data: ActorCreate, db: Session = Depends(get_db)):
    """创建新演员"""
    # 检查名称是否已存在
    existing = db.query(Actor).filter(Actor.name == actor_data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Actor name already exists")
    
    actor = Actor(name=actor_data.name)
    db.add(actor)
    db.commit()
    db.refresh(actor)
    
    # 关联聚类
    if actor_data.cluster_ids:
        for cluster_id in actor_data.cluster_ids:
            cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
            if cluster:
                cluster.actor_name = actor.name
        
        db.commit()
    
    return {"id": actor.id, "name": actor.name}


@router.put("/{actor_id}")
def update_actor(actor_id: int, actor_data: ActorUpdate, db: Session = Depends(get_db)):
    """更新演员信息"""
    actor = db.query(Actor).filter(Actor.id == actor_id).first()
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")
    
    if actor_data.name:
        # 检查新名称是否已存在
        existing = db.query(Actor).filter(
            Actor.name == actor_data.name,
            Actor.id != actor_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Actor name already exists")
        
        # 更新名称（同时更新关联的聚类）
        old_name = actor.name
        actor.name = actor_data.name
        
        # 更新所有关联聚类的 actor_name
        clusters = db.query(Cluster).filter(Cluster.actor_name == old_name).all()
        for cluster in clusters:
            cluster.actor_name = actor_data.name
    
    if actor_data.cluster_ids is not None:
        # 先移除旧的关联
        old_clusters = db.query(Cluster).filter(Cluster.actor_name == actor.name).all()
        for cluster in old_clusters:
            if cluster.id not in actor_data.cluster_ids:
                cluster.actor_name = None
        
        # 添加新的关联
        for cluster_id in actor_data.cluster_ids:
            cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
            if cluster:
                cluster.actor_name = actor.name
    
    db.commit()
    
    return {"success": True}


@router.delete("/{actor_id}")
def delete_actor(actor_id: int, db: Session = Depends(get_db)):
    """删除演员（不删除聚类，只解除关联）"""
    actor = db.query(Actor).filter(Actor.id == actor_id).first()
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")
    
    # 解除所有关联聚类的 actor_name
    clusters = db.query(Cluster).filter(Cluster.actor_name == actor.name).all()
    for cluster in clusters:
        cluster.actor_name = None
    
    # 删除演员
    db.delete(actor)
    db.commit()
    
    return {"success": True}


@router.post("/merge")
def merge_actors(source_ids: List[int], target_id: int, db: Session = Depends(get_db)):
    """合并演员（将多个演员合并到一个）"""
    target = db.query(Actor).filter(Actor.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target actor not found")
    
    for source_id in source_ids:
        if source_id == target_id:
            continue
        
        source = db.query(Actor).filter(Actor.id == source_id).first()
        if not source:
            continue
        
        # 将所有关联聚类转移到目标演员
        clusters = db.query(Cluster).filter(Cluster.actor_name == source.name).all()
        for cluster in clusters:
            cluster.actor_name = target.name
        
        # 删除源演员
        db.delete(source)
    
    db.commit()
    
    return {"success": True}


@router.get("/search/query")
def search_actors(q: str, db: Session = Depends(get_db)):
    """搜索演员"""
    actors = db.query(Actor).filter(Actor.name.ilike(f"%{q}%")).limit(20).all()
    return [
        {
            "id": actor.id,
            "name": actor.name,
            "video_count": db.query(Video).join(Face).join(Cluster).filter(
                Cluster.actor_name == actor.name
            ).distinct().count()
        }
        for actor in actors
    ]
