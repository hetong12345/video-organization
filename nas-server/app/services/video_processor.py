import os
import subprocess
import json
from typing import List, Optional, Tuple
import cv2
from app.config import settings
from app.database import SessionLocal
from app.models import Video, Frame, Task, VideoStatus, TaskType, TaskStatus


class VideoScanner:
    SUPPORTED_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'}
    
    def __init__(self, raw_dir: str = None):
        self.raw_dir = raw_dir or settings.RAW_VIDEO_DIR
    
    def scan_directory(self) -> List[dict]:
        new_videos = []
        db = SessionLocal()
        
        try:
            for root, dirs, files in os.walk(self.raw_dir):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext not in self.SUPPORTED_EXTENSIONS:
                        continue
                    
                    filepath = os.path.join(root, file)
                    
                    existing = db.query(Video).filter(Video.filepath == filepath).first()
                    if existing:
                        continue
                    
                    duration, file_size = self._get_video_info(filepath)
                    
                    video = Video(
                        filename=file,
                        filepath=filepath,
                        duration=duration,
                        file_size=file_size,
                        status=VideoStatus.PENDING
                    )
                    db.add(video)
                    db.commit()
                    db.refresh(video)
                    
                    new_videos.append({
                        "id": video.id,
                        "filename": file,
                        "filepath": filepath
                    })
        finally:
            db.close()
        
        return new_videos
    
    def _get_video_info(self, filepath: str) -> Tuple[Optional[float], Optional[int]]:
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', filepath
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            data = json.loads(result.stdout)
            
            duration = float(data.get('format', {}).get('duration', 0))
            file_size = int(data.get('format', {}).get('size', 0))
            
            return duration, file_size
        except Exception as e:
            print(f"Error getting video info: {e}")
            return None, None


class FrameExtractor:
    def __init__(self):
        self.cache_dir = settings.FRAME_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def extract_frames(self, video_id: int) -> List[dict]:
        db = SessionLocal()
        extracted_frames = []
        
        try:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                return []
            
            video.status = VideoStatus.PROCESSING
            db.commit()
            
            video_cache_dir = os.path.join(self.cache_dir, str(video_id))
            os.makedirs(video_cache_dir, exist_ok=True)
            
            scene_changes = self._detect_scene_changes(video.filepath)
            
            cap = cv2.VideoCapture(video.filepath)
            fps = cap.get(cv2.CAP_PROP_FPS)
            
            frame_index = 0
            for scene_frame in scene_changes[:10]:
                cap.set(cv2.CAP_PROP_POS_FRAMES, scene_frame)
                ret, frame = cap.read()
                
                if not ret:
                    continue
                
                frame_path = os.path.join(video_cache_dir, f"frame_{frame_index}.jpg")
                cv2.imwrite(frame_path, frame)
                
                frame_record = Frame(
                    video_id=video_id,
                    frame_path=frame_path,
                    frame_index=scene_frame,
                    timestamp=scene_frame / fps if fps > 0 else None,
                    is_representative=(frame_index == 0)
                )
                db.add(frame_record)
                db.flush()
                
                task = Task(
                    task_type=TaskType.FEATURE,
                    status=TaskStatus.PENDING,
                    video_id=video_id,
                    frame_id=frame_record.id
                )
                db.add(task)
                
                extracted_frames.append({
                    "frame_id": frame_record.id,
                    "path": frame_path
                })
                frame_index += 1
            
            cap.release()
            
            if extracted_frames:
                tag_task = Task(
                    task_type=TaskType.TAG,
                    status=TaskStatus.PENDING,
                    video_id=video_id
                )
                db.add(tag_task)
                db.commit()
            
        except Exception as e:
            print(f"Error extracting frames: {e}")
            db.rollback()
        finally:
            db.close()
        
        return extracted_frames
    
    def _detect_scene_changes(self, filepath: str) -> List[int]:
        try:
            cmd = [
                'ffmpeg', '-i', filepath, '-filter_complex',
                f"select='gt(scene,0.3)',showinfo",
                '-f', 'null', '-'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, stderr=subprocess.STDOUT)
            
            scene_frames = [0]
            for line in result.stdout.split('\n'):
                if 'pts_time' in line:
                    try:
                        time_str = line.split('pts_time:')[1].split()[0]
                        time = float(time_str)
                        cap = cv2.VideoCapture(filepath)
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        cap.release()
                        frame_num = int(time * fps) if fps > 0 else 0
                        scene_frames.append(frame_num)
                    except:
                        pass
            
            return sorted(list(set(scene_frames)))
        except Exception as e:
            print(f"Error detecting scene changes: {e}")
            return list(range(0, 100, 10))
