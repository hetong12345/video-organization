from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from datetime import datetime, timedelta
from app.database import get_db
from app.models import Worker, Task, TaskStatus
from app.schemas import WorkerHeartbeat

router = APIRouter(prefix="/api/workers", tags=["workers"])


@router.post("/heartbeat")
def heartbeat(request: WorkerHeartbeat, db: Session = Depends(get_db)):
    worker = db.query(Worker).filter(Worker.id == request.worker_id).first()
    
    if worker:
        worker.last_heartbeat = datetime.utcnow()
        worker.status = request.status
        worker.current_task_id = request.current_task_id
    else:
        worker = Worker(
            id=request.worker_id,
            status=request.status,
            current_task_id=request.current_task_id
        )
        db.add(worker)
    
    db.commit()
    return {"success": True}


@router.get("")
def list_workers(db: Session = Depends(get_db)):
    workers = db.query(Worker).all()
    
    result = []
    for worker in workers:
        # Handle timezone-aware datetime
        last_heartbeat = worker.last_heartbeat
        if last_heartbeat.tzinfo is not None:
            # Convert to naive UTC datetime
            from datetime import timezone
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            last_heartbeat_naive = last_heartbeat.replace(tzinfo=None)
            is_online = (now_utc - last_heartbeat_naive).total_seconds() < 300
        else:
            is_online = (datetime.utcnow() - last_heartbeat).total_seconds() < 300
        
        current_task = None
        if worker.current_task_id:
            task = db.query(Task).filter(Task.id == worker.current_task_id).first()
            if task:
                current_task = {
                    "id": task.id,
                    "type": task.task_type.value,
                    "status": task.status.value
                }
        
        result.append({
            "id": worker.id,
            "status": worker.status,
            "is_online": is_online,
            "last_heartbeat": worker.last_heartbeat.isoformat(),
            "current_task": current_task
        })
    
    return result


@router.get("/online")
def get_online_workers(db: Session = Depends(get_db)):
    five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
    workers = db.query(Worker).filter(Worker.last_heartbeat >= five_minutes_ago).all()
    
    return [{
        "id": w.id,
        "status": w.status,
        "current_task_id": w.current_task_id
    } for w in workers]
