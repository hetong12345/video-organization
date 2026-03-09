from app.services.video_processor import VideoScanner, FrameExtractor
from app.database import SessionLocal
from app.models import Video, Task, Face, VideoStatus, TaskType, TaskStatus
from app.config import settings
from pgvector.sqlalchemy import Vector
from sqlalchemy import func
import numpy as np


class TaskManager:
    def __init__(self):
        self.scanner = VideoScanner()
        self.extractor = FrameExtractor()
    
    def scan_and_process(self):
        new_videos = self.scanner.scan_directory()
        
        db = SessionLocal()
        try:
            for video_info in new_videos:
                self.extractor.extract_frames(video_info['id'])
        finally:
            db.close()
    
    def create_cluster_task(self):
        db = SessionLocal()
        try:
            unclustered_count = db.query(Face).filter(
                Face.embedding != None,
                Face.cluster_id == None
            ).count()
            
            if unclustered_count >= settings.CLUSTER_MIN_SAMPLES:
                existing_pending = db.query(Task).filter(
                    Task.task_type == TaskType.CLUSTER,
                    Task.status == TaskStatus.PENDING
                ).first()
                
                if not existing_pending:
                    task = Task(
                        task_type=TaskType.CLUSTER,
                        status=TaskStatus.PENDING
                    )
                    db.add(task)
                    db.commit()
        finally:
            db.close()
    
    def process_pending_videos(self):
        db = SessionLocal()
        try:
            pending_videos = db.query(Video).filter(
                Video.status == VideoStatus.PENDING
            ).limit(5).all()
            
            for video in pending_videos:
                self.extractor.extract_frames(video.id)
        finally:
            db.close()


task_manager = TaskManager()
