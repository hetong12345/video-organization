from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class VideoStatusEnum(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    FEATURED = "featured"
    CLUSTERED = "clustered"
    TAGGED = "tagged"
    READY = "ready"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskTypeEnum(str, Enum):
    FEATURE = "feature"
    CLUSTER = "cluster"
    TAG = "tag"


class TaskStatusEnum(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoCreate(BaseModel):
    filename: str
    filepath: str
    duration: Optional[float] = None
    file_size: Optional[int] = None


class VideoResponse(BaseModel):
    id: int
    filename: str
    filepath: str
    duration: Optional[float]
    file_size: Optional[int]
    status: VideoStatusEnum
    recommended_name: Optional[str]
    target_path: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class VideoListResponse(BaseModel):
    id: int
    filename: str
    status: VideoStatusEnum
    recommended_name: Optional[str]
    thumbnail_url: Optional[str] = None
    actors: List[str] = []
    tags: List[str] = []

    class Config:
        from_attributes = True


class FrameResponse(BaseModel):
    id: int
    video_id: int
    frame_path: str
    frame_index: Optional[int]
    timestamp: Optional[float]
    is_representative: bool

    class Config:
        from_attributes = True


class FaceResponse(BaseModel):
    id: int
    frame_id: int
    gender: Optional[str]
    age: Optional[int]
    quality_score: Optional[float]
    cluster_id: Optional[int]
    actor_name: Optional[str]

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    task_type: TaskTypeEnum
    video_id: Optional[int] = None
    frame_id: Optional[int] = None
    face_id: Optional[int] = None


class TaskResponse(BaseModel):
    id: int
    task_type: TaskTypeEnum
    status: TaskStatusEnum
    video_id: Optional[int]
    frame_id: Optional[int]
    face_id: Optional[int]
    worker_id: Optional[str]
    error_message: Optional[str]
    retry_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class TaskPullRequest(BaseModel):
    worker_id: str
    task_types: List[TaskTypeEnum]
    max_tasks: int = 1


class FeatureSubmitRequest(BaseModel):
    task_id: int
    face_id: int
    embedding: List[float]


class ClusterSubmitRequest(BaseModel):
    task_id: int
    cluster_results: List[dict]


class TagSubmitRequest(BaseModel):
    task_id: int
    video_id: int
    tags: List[str]


class ClusterNameRequest(BaseModel):
    cluster_id: int
    actor_name: str


class AdoptRequest(BaseModel):
    video_ids: List[int]
    custom_names: Optional[dict] = None


class WorkerHeartbeat(BaseModel):
    worker_id: str
    status: str = "idle"
    current_task_id: Optional[int] = None


class DashboardStats(BaseModel):
    total_videos: int
    pending_videos: int
    processing_videos: int
    ready_videos: int
    completed_videos: int
    total_tasks: int
    pending_tasks: int
    running_tasks: int
    online_workers: int


class ClusterResponse(BaseModel):
    id: int
    actor_name: Optional[str]
    face_count: int
    representative_face_id: Optional[int]
    representative_face_url: Optional[str] = None

    class Config:
        from_attributes = True
