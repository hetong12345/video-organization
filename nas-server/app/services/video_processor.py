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
                        "filepath": filepath,
                        "duration": duration
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
    FRAMES_PER_MINUTE = 1
    MAX_FRAMES = 10
    MIN_FRAMES = 3
    
    def __init__(self):
        self.cache_dir = settings.FRAME_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def extract_frames(self, video_id: int, force: bool = False) -> List[dict]:
        db = SessionLocal()
        extracted_frames = []
        
        try:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                return []
            
            existing_frames = db.query(Frame).filter(Frame.video_id == video_id).count()
            if existing_frames > 0 and not force:
                return []
            
            db.query(Frame).filter(Frame.video_id == video_id).delete()
            db.query(Task).filter(Task.video_id == video_id).delete()
            
            video.status = VideoStatus.PROCESSING
            db.commit()
            
            video_cache_dir = os.path.join(self.cache_dir, str(video_id))
            if os.path.exists(video_cache_dir):
                for f in os.listdir(video_cache_dir):
                    os.remove(os.path.join(video_cache_dir, f))
            os.makedirs(video_cache_dir, exist_ok=True)
            
            duration = video.duration or 0
            target_frame_count = self._calculate_frame_count(duration)
            
            cap = cv2.VideoCapture(video.filepath)
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            
            scene_changes = self._detect_scene_changes_fast(video.filepath, total_frames, fps, target_frame_count)
            
            selected_frames = self._distribute_frames(scene_changes, target_frame_count, total_frames)
            
            cap = cv2.VideoCapture(video.filepath)
            for idx, frame_pos in enumerate(selected_frames):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
                ret, frame = cap.read()
                
                if not ret:
                    continue
                
                frame_path = os.path.join(video_cache_dir, f"frame_{idx:04d}.jpg")
                cv2.imwrite(frame_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                
                frame_record = Frame(
                    video_id=video_id,
                    frame_path=frame_path,
                    frame_index=frame_pos,
                    timestamp=frame_pos / fps if fps > 0 else None,
                    is_representative=(idx == 0)
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
                    "path": frame_path,
                    "timestamp": frame_pos / fps if fps > 0 else None
                })
            
            cap.release()
            
            if extracted_frames:
                tag_task = Task(
                    task_type=TaskType.TAG,
                    status=TaskStatus.PENDING,
                    video_id=video_id
                )
                db.add(tag_task)
                video.status = VideoStatus.PENDING
                db.commit()
            
        except Exception as e:
            print(f"Error extracting frames: {e}")
            db.rollback()
        finally:
            db.close()
        
        return extracted_frames
    
    def _calculate_frame_count(self, duration: float) -> int:
        if not duration or duration <= 0:
            return self.MIN_FRAMES
        
        minutes = duration / 60
        count = int(minutes * self.FRAMES_PER_MINUTE)
        return max(self.MIN_FRAMES, min(count, self.MAX_FRAMES))
    
    def _detect_scene_changes_fast(self, filepath: str, total_frames: int, fps: float, target_count: int) -> List[int]:
        try:
            cmd = [
                'ffmpeg', '-i', filepath, '-filter_complex',
                f"select='gt(scene,0.4)',showinfo",
                '-f', 'null', '-'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, stderr=subprocess.STDOUT, timeout=60)
            
            scene_frames = []
            for line in result.stdout.split('\n'):
                if 'pts_time' in line:
                    try:
                        time_str = line.split('pts_time:')[1].split()[0]
                        time = float(time_str)
                        frame_num = int(time * fps) if fps > 0 else 0
                        if 0 <= frame_num < total_frames:
                            scene_frames.append(frame_num)
                    except:
                        pass
            
            if len(scene_frames) < 2:
                return self._generate_uniform_frames(total_frames, target_count)
            
            return sorted(scene_frames)
        except Exception as e:
            print(f"Error detecting scene changes: {e}")
            return self._generate_uniform_frames(total_frames, target_count)
    
    def _generate_uniform_frames(self, total_frames: int, count: int) -> List[int]:
        if total_frames <= 0 or count <= 0:
            return [0]
        
        step = max(1, total_frames // count)
        frames = list(range(0, total_frames, step))
        return frames[:count]
    
    def _distribute_frames(self, scene_changes: List[int], target_count: int, total_frames: int) -> List[int]:
        if len(scene_changes) <= target_count:
            return scene_changes
        
        selected = []
        selected.append(scene_changes[0])
        
        step = len(scene_changes) // (target_count - 1)
        for i in range(1, target_count - 1):
            idx = min(i * step, len(scene_changes) - 1)
            selected.append(scene_changes[idx])
        
        selected.append(scene_changes[-1])
        
        selected = sorted(list(set(selected)))
        
        if len(selected) > target_count:
            selected = self._reduce_frames(selected, target_count)
        
        return selected
    
    def _reduce_frames(self, frames: List[int], target: int) -> List[int]:
        if len(frames) <= target:
            return frames
        
        indices = []
        for i in range(target):
            idx = int(i * (len(frames) - 1) / (target - 1))
            indices.append(idx)
        
        return [frames[i] for i in indices]
