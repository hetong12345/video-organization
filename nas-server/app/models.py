from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.database import Base
import enum


class VideoStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    FEATURED = "featured"
    CLUSTERED = "clustered"
    TAGGED = "tagged"
    READY = "ready"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(enum.Enum):
    FEATURE = "feature"
    CLUSTER = "cluster"
    TAG = "tag"


class TaskStatus(enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(500), nullable=False)
    filepath = Column(String(1000), nullable=False)
    duration = Column(Float)
    file_size = Column(Integer)
    status = Column(Enum(VideoStatus), default=VideoStatus.PENDING)
    recommended_name = Column(String(500))
    target_path = Column(String(1000))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    frames = relationship("Frame", back_populates="video", cascade="all, delete-orphan")
    tags = relationship("VideoTag", back_populates="video", cascade="all, delete-orphan")
    actors = relationship("VideoActor", back_populates="video", cascade="all, delete-orphan")


class Frame(Base):
    __tablename__ = "frames"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    frame_path = Column(String(1000), nullable=False)
    frame_index = Column(Integer)
    timestamp = Column(Float)
    is_representative = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    video = relationship("Video", back_populates="frames")
    faces = relationship("Face", back_populates="frame", cascade="all, delete-orphan")


class Face(Base):
    __tablename__ = "faces"

    id = Column(Integer, primary_key=True, index=True)
    frame_id = Column(Integer, ForeignKey("frames.id"), nullable=False)
    bbox_x = Column(Integer)
    bbox_y = Column(Integer)
    bbox_w = Column(Integer)
    bbox_h = Column(Integer)
    gender = Column(String(10))
    age = Column(Integer)
    quality_score = Column(Float)
    embedding = Column(Vector(512))
    cluster_id = Column(Integer, nullable=True)
    actor_name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    frame = relationship("Frame", back_populates="faces")


class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, index=True)
    actor_name = Column(String(100), nullable=True)
    representative_face_id = Column(Integer, ForeignKey("faces.id"), nullable=True)
    face_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(Enum(TaskType), nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=True)
    frame_id = Column(Integer, ForeignKey("frames.id"), nullable=True)
    face_id = Column(Integer, ForeignKey("faces.id"), nullable=True)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=True)
    worker_id = Column(String(100), nullable=True)
    result_data = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    category = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class VideoTag(Base):
    __tablename__ = "video_tags"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=False)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    video = relationship("Video", back_populates="tags")
    tag = relationship("Tag")


class Actor(Base):
    __tablename__ = "actors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class VideoActor(Base):
    __tablename__ = "video_actors"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    actor_id = Column(Integer, ForeignKey("actors.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    video = relationship("Video", back_populates="actors")
    actor = relationship("Actor")


class Worker(Base):
    __tablename__ = "workers"

    id = Column(String(100), primary_key=True)
    last_heartbeat = Column(DateTime(timezone=True), server_default=func.now())
    current_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    status = Column(String(20), default="idle")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
