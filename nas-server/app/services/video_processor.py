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
    
    def _get_video_info(self, filepath: str) -> Tuple[float, float, int]:
        """使用 ffprobe 获取视频信息"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=r_frame_rate,duration,nb_frames',
                '-show_entries', 'format=duration',
                '-of', 'json', filepath
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if not result.stdout:
                return 0.0, 0.0, 0
            
            data = json.loads(result.stdout)
            
            # 获取时长
            duration = 0.0
            if 'format' in data and 'duration' in data['format']:
                duration = float(data['format']['duration'])
            elif 'streams' in data and len(data['streams']) > 0:
                stream = data['streams'][0]
                if 'duration' in stream:
                    duration = float(stream['duration'])
            
            # 获取帧率
            fps = 0.0
            if 'streams' in data and len(data['streams']) > 0:
                stream = data['streams'][0]
                if 'r_frame_rate' in stream:
                    rate = stream['r_frame_rate']
                    if '/' in rate:
                        num, den = rate.split('/')
                        fps = float(num) / float(den)
                    else:
                        fps = float(rate)
            
            # 获取总帧数
            total_frames = 0
            if 'streams' in data and len(data['streams']) > 0:
                stream = data['streams'][0]
                if 'nb_frames' in stream:
                    total_frames = int(stream['nb_frames'])
            
            # 如果总帧数为 0，用时长和帧率计算
            if total_frames == 0 and duration > 0 and fps > 0:
                total_frames = int(duration * fps)
            
            return duration, fps, total_frames
        except Exception as e:
            print(f"Error in _get_video_info: {e}")
            return 0.0, 0.0, 0
    
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
            
            # 先删除关联的 tasks，再删除 frames（外键约束）
            db.query(Task).filter(Task.video_id == video_id).delete()
            db.query(Frame).filter(Frame.video_id == video_id).delete()
            
            video.status = VideoStatus.PROCESSING
            db.commit()
            
            video_cache_dir = os.path.join(self.cache_dir, str(video_id))
            if os.path.exists(video_cache_dir):
                for f in os.listdir(video_cache_dir):
                    os.remove(os.path.join(video_cache_dir, f))
            os.makedirs(video_cache_dir, exist_ok=True)
            
            # 使用 ffprobe 获取准确的视频信息
            duration, fps, total_frames = self._get_video_info(video.filepath)
            
            # 如果 ffprobe 获取失败，尝试用数据库中的时长
            if duration == 0 and video.duration:
                duration = video.duration
            
            target_frame_count = self._calculate_frame_count(duration)
            
            print(f"Video {video_id}: duration={duration:.1f}s, fps={fps}, total_frames={total_frames}, target_frames={target_frame_count}")
            
            # 如果还是获取不到总帧数，用时长估算
            if total_frames == 0 and duration > 0 and fps > 0:
                total_frames = int(duration * fps)
            
            if total_frames == 0:
                print(f"Cannot determine total frames for video {video_id}, trying OpenCV")
                # 尝试用 OpenCV
                cap = cv2.VideoCapture(video.filepath)
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                cap.release()
                print(f"OpenCV: fps={fps}, total_frames={total_frames}")
            
            if total_frames == 0:
                print(f"Failed to get video info for {video_id}")
                video.status = VideoStatus.FAILED
                db.commit()
                return []
            
            # 按时间均匀分布抽帧
            selected_frames = self._generate_time_based_frames(total_frames, fps, duration, target_frame_count)
            
            print(f"Selected {len(selected_frames)} frames at positions: {selected_frames}")
            
            cap = cv2.VideoCapture(video.filepath)
            for idx, frame_pos in enumerate(selected_frames):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
                ret, frame = cap.read()
                
                if not ret:
                    print(f"Failed to read frame at position {frame_pos}")
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
                print(f"Extracted {len(extracted_frames)} frames for video {video_id}")
            else:
                video.status = VideoStatus.FAILED
                db.commit()
                print(f"No frames extracted for video {video_id}")
            
        except Exception as e:
            print(f"Error extracting frames: {e}")
            db.rollback()
            try:
                video.status = VideoStatus.FAILED
                db.commit()
            except:
                pass
        finally:
            db.close()
        
        return extracted_frames
    
    def _calculate_frame_count(self, duration: float) -> int:
        if not duration or duration <= 0:
            return self.MIN_FRAMES
        
        minutes = duration / 60
        count = int(minutes * self.FRAMES_PER_MINUTE)
        return max(self.MIN_FRAMES, min(count, self.MAX_FRAMES))
    
    def _generate_time_based_frames(self, total_frames: int, fps: float, duration: float, count: int) -> List[int]:
        """按时间均匀分布生成帧位置"""
        if total_frames <= 0 or count <= 0:
            return [0]
        
        # 如果视频时长有效，按时间均匀分布
        if duration > 0 and fps > 0:
            # 在视频时长内均匀分布时间点
            time_positions = []
            for i in range(count):
                # 从 5% 到 95% 的时间范围，避免开头和结尾
                ratio = 0.05 + (0.9 * i / max(count - 1, 1))
                time_pos = duration * ratio
                frame_pos = int(time_pos * fps)
                frame_pos = max(0, min(frame_pos, total_frames - 1))
                time_positions.append(frame_pos)
            return sorted(list(set(time_positions)))
        else:
            # 如果时长未知，按帧数均匀分布
            step = total_frames // count
            frames = []
            for i in range(count):
                pos = min(i * step + step // 2, total_frames - 1)
                frames.append(pos)
            return frames
