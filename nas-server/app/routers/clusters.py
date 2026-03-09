from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.database import get_db
from app.models import Cluster, Face, Actor, VideoActor, Video, VideoStatus
from app.schemas import ClusterResponse, ClusterNameRequest

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


@router.get("", response_model=List[ClusterResponse])
def list_clusters(db: Session = Depends(get_db)):
    clusters = db.query(Cluster).order_by(Cluster.face_count.desc()).all()
    
    result = []
    for cluster in clusters:
        rep_face = db.query(Face).filter(Face.id == cluster.representative_face_id).first()
        rep_face_url = f"/api/faces/{rep_face.id}/image" if rep_face else None
        
        result.append(ClusterResponse(
            id=cluster.id,
            actor_name=cluster.actor_name,
            face_count=cluster.face_count,
            representative_face_id=cluster.representative_face_id,
            representative_face_url=rep_face_url
        ))
    
    return result


@router.get("/{cluster_id}/faces")
def get_cluster_faces(cluster_id: int, limit: int = 20, db: Session = Depends(get_db)):
    faces = db.query(Face).filter(Face.cluster_id == cluster_id).limit(limit).all()
    return [{"id": f.id, "frame_id": f.frame_id, "image_url": f"/api/faces/{f.id}/image"} for f in faces]


@router.post("/name")
def name_cluster(request: ClusterNameRequest, db: Session = Depends(get_db)):
    cluster = db.query(Cluster).filter(Cluster.id == request.cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    actor = db.query(Actor).filter(Actor.name == request.actor_name).first()
    if not actor:
        actor = Actor(name=request.actor_name, cluster_id=cluster.id)
        db.add(actor)
        db.flush()
    else:
        actor.cluster_id = cluster.id
    
    cluster.actor_name = request.actor_name
    
    faces = db.query(Face).filter(Face.cluster_id == cluster.id).all()
    for face in faces:
        face.actor_name = request.actor_name
        
        frame = db.query(Frame).filter(Frame.id == face.frame_id).first()
        if frame:
            video_actor = db.query(VideoActor).filter(
                VideoActor.video_id == frame.video_id,
                VideoActor.actor_id == actor.id
            ).first()
            if not video_actor:
                db.add(VideoActor(video_id=frame.video_id, actor_id=actor.id))
    
    db.commit()
    
    _update_video_status(db)
    
    return {"success": True, "cluster_id": cluster.id, "actor_name": request.actor_name}


def _update_video_status(db: Session):
    videos = db.query(Video).filter(Video.status == VideoStatus.CLUSTERED).all()
    for video in videos:
        actors = db.query(VideoActor).filter(VideoActor.video_id == video.id).count()
        if actors > 0:
            from app.routers.tasks import _check_video_ready
            _check_video_ready(video, db)
    db.commit()
