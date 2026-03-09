import os
import subprocess
import json
from typing import List, Optional, Tuple
import cv2
import numpy as np
from insightface.app import FaceAnalysis
from app.config import settings
from app.database import SessionLocal
from app.models import Video, Frame, Face, Task, VideoStatus, TaskType, TaskStatus


class VideoScanner:
    SUPPORTED_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'}
    
    def __init__(self):
        self.raw_dir = settings.RAW_VIDEO_DIR
    
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
        self.min_face_ratio = settings.MIN_FACE_RATIO
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.face_analyzer = FaceAnalysis(
            name='buffalo_l',
            providers=['CPUExecutionProvider']
        )
        self.face_analyzer.prepare(ctx_id=-1, det_size=(640, 640))
    
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
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            frame_data = []
            frame_index = 0
            
            for scene_frame in scene_changes:
                if scene_frame >= total_frames:
                    continue
                
                cap.set(cv2.CAP_PROP_POS_FRAMES, scene_frame)
                ret, frame = cap.read()
                
                if not ret:
                    continue
                
                faces = self._detect_faces(frame)
                
                for face_data in faces:
                    frame_path = os.path.join(video_cache_dir, f"frame_{frame_index}.jpg")
                    cv2.imwrite(frame_path, frame)
                    
                    frame_record = Frame(
                        video_id=video_id,
                        frame_path=frame_path,
                        frame_index=scene_frame,
                        timestamp=scene_frame / fps if fps > 0 else None,
                        is_representative=False
                    )
                    db.add(frame_record)
                    db.flush()
                    
                    face_record = Face(
                        frame_id=frame_record.id,
                        bbox_x=face_data['bbox'][0],
                        bbox_y=face_data['bbox'][1],
                        bbox_w=face_data['bbox'][2],
                        bbox_h=face_data['bbox'][3],
                        gender=face_data['gender'],
                        age=face_data['age'],
                        quality_score=face_data['quality']
                    )
                    db.add(face_record)
                    db.flush()
                    
                    task = Task(
                        task_type=TaskType.FEATURE,
                        status=TaskStatus.PENDING,
                        video_id=video_id,
                        frame_id=frame_record.id,
                        face_id=face_record.id
                    )
                    db.add(task)
                    
                    frame_data.append({
                        "frame_id": frame_record.id,
                        "face_id": face_record.id,
                        "quality": face_data['quality']
                    })
                    
                    frame_index += 1
            
            cap.release()
            
            if frame_data:
                best_frame = max(frame_data, key=lambda x: x['quality'])
                best_frame_record = db.query(Frame).filter(
                    Frame.id == best_frame['frame_id']
                ).first()
                if best_frame_record:
                    best_frame_record.is_representative = True
            
            db.commit()
            
            if frame_data:
                tag_task = Task(
                    task_type=TaskType.TAG,
                    status=TaskStatus.PENDING,
                    video_id=video_id
                )
                db.add(tag_task)
                db.commit()
            
            extracted_frames = frame_data
            
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
            return [0]
    
    def _detect_faces(self, frame: np.ndarray) -> List[dict]:
        faces = self.face_analyzer.get(frame)
        valid_faces = []
        
        frame_h, frame_w = frame.shape[:2]
        frame_area = frame_h * frame_w
        
        for face in faces:
            bbox = face.bbox.astype(int)
            x, y, w, h = bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]
            
            face_area = w * h
            face_ratio = face_area / frame_area
            
            if face_ratio < self.min_face_ratio:
                continue
            
            gender = face.sex
            if gender != 'F':
                continue
            
            if hasattr(face, 'pose') and face.pose is not None:
                yaw = abs(face.pose[1])
                if yaw > 30:
                    continue
            
            quality = self._calculate_face_quality(face, frame)
            
            valid_faces.append({
                'bbox': [x, y, w, h],
                'gender': gender,
                'age': face.age if hasattr(face, 'age') else None,
                'quality': quality
            })
        
        return valid_faces
    
    def _calculate_face_quality(self, face, frame: np.ndarray) -> float:
        quality = 0.0
        
        if hasattr(face, 'det_score'):
            quality += float(face.det_score) * 0.5
        
        bbox = face.bbox.astype(int)
        x1, y1, x2, y2 = max(0, bbox[0]), max(0, bbox[1]), min(frame.shape[1], bbox[2]), min(frame.shape[0], bbox[3])
        face_region = frame[y1:y2, x1:x2]
        
        if face_region.size > 0:
            gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
            quality += cv2.Laplacian(gray, cv2.CV_64F).var() / 1000 * 0.3
        
        face_area = (x2 - x1) * (y2 - y1)
        frame_area = frame.shape[0] * frame.shape[1]
        quality += (face_area / frame_area) * 0.2
        
        return min(quality, 1.0)
