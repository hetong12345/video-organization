# 视频 AI 整理系统 - 架构设计文档

## 项目概述

基于 AI 的视频自动整理系统，通过人脸识别、聚类和场景分析，自动为视频文件生成结构化命名和标签。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         前端页面 (Vue 3)                         │
│  - 视频管理  - 人脸聚类  - 命名审核  - 任务监控  - Worker 状态    │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     NAS 服务器 (FastAPI + PostgreSQL)            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  视频扫描   │  │  抽帧服务   │  │  任务管理   │             │
│  │  VideoScanner│  │FrameExtractor│  │  Task Router │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  人脸管理   │  │  聚类管理   │  │  仪表盘     │             │
│  │  Face Router │  │Cluster Router│  │Dashboard    │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│                                                                 │
│  ┌──────────────────────────────────────────────────┐          │
│  │              PostgreSQL + pgvector               │          │
│  │  Videos | Frames | Faces | Clusters | Tasks     │          │
│  └──────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Worker (本地 Python 进程)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ 特征提取    │  │ 人脸聚类    │  │ 场景打标    │             │
│  │InsightFace  │  │  HDBSCAN    │  │  LLM (Qwen) │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. NAS 服务器 (nas-server/)

**职责**：
- 视频文件扫描和元数据管理
- 视频抽帧（不检测人脸）
- 任务调度和状态管理
- 数据持久化（PostgreSQL）
- 前端页面托管

**关键服务**：

#### VideoScanner
- 扫描指定目录，识别视频文件
- 提取视频元数据（时长、分辨率等）
- 创建 Video 记录

#### FrameExtractor
- 根据视频时长智能抽帧（1 帧/分钟，最少 3 帧，最多 10 帧）
- 创建 Frame 记录
- 创建 FEATURE 类型任务（只有 frame_id，等待 Worker 处理）

**API 路由**：
- `/api/videos` - 视频管理
- `/api/frames` - 帧管理
- `/api/faces` - 人脸管理
- `/api/tasks` - 任务管理
- `/api/clusters` - 聚类管理
- `/api/dashboard/stats` - 统计信息

### 2. Worker (worker/)

**职责**：
- 从 NAS 服务器拉取任务
- 执行人脸检测、特征提取、聚类、打标等 AI 任务
- 将结果回传给 NAS 服务器

**任务类型**：

#### FEATURE - 特征提取
1. 接收任务（包含 frame_id）
2. 从 NAS 获取帧图片
3. 使用 InsightFace 检测人脸
4. 为每个人脸创建 Face 记录（包含 bounding_box、embedding）
5. 标记任务完成

**流程**：
```
Task(frame_id=23) 
  → 获取帧图片
  → InsightFace 检测 → 1 张人脸
  → POST /api/faces {video_id, frame_id, bbox, embedding}
  → Face 记录创建成功
  → POST /api/tasks/23/complete
```

#### CLUSTER - 人脸聚类
1. 获取所有已提取特征的人脸（有 embedding，无 cluster_id）
2. 使用 HDBSCAN 算法聚类
3. 创建 Cluster 记录
4. 更新 Face 记录的 cluster_id
5. 标记任务完成

**算法**：
- HDBSCAN (min_cluster_size=3, min_samples=1)
- 基于 512 维人脸 embedding 向量

#### TAG - 场景打标
1. 获取视频的代表帧
2. 使用 LLM（Qwen2.5-7B）分析场景
3. 生成标签（如"办公室"、"户外"、"对话场景"）
4. 创建 Tag 记录并关联视频
5. 标记任务完成

**配置**：
- GPU 模式：4bit 量化，device_map="auto"
- CPU 模式：float32，device_map="cpu"（慢）

### 3. 前端 (nas-server/app/static/)

**技术栈**：Vue 3 + Element Plus

**页面**：

#### 仪表盘
- 统计信息（视频数、任务数、Worker 状态）
- 实时刷新（30 秒）

#### 视频管理
- 目录树浏览
- 视频列表（状态、时长、推荐命名）
- 抽帧预览（显示每帧的人脸数量）
- 人脸详情弹窗

#### 人脸聚类
- 聚类列表（按视频筛选）
- 预览人脸（每个聚类前 10 张）
- 角色命名（保存到 Cluster.name）

#### 命名审核
- 待审核视频列表
- AI 生成的推荐命名
- 一键采纳/修改

#### 任务监控
- 任务列表（类型、状态、耗时）
- 失败任务重试
- Worker 分配情况

#### Worker 状态
- 在线 Worker 列表
- 心跳监控
- 当前任务

## 数据库设计

### 核心表

**videos**
```sql
id, filepath, filename, duration, resolution, 
status (SCANNED|PROCESSING|FEATURED|CLUSTERED|TAGGED|READY|ADOPTED),
recommended_name, created_at
```

**frames**
```sql
id, video_id (FK), frame_path, frame_index, 
timestamp, is_representative, created_at
```

**faces**
```sql
id, video_id (FK), frame_id (FK), 
bbox_x, bbox_y, bbox_w, bbox_h, confidence,
embedding (VECTOR(512)), cluster_id (FK), 
actor_name, created_at
```

**clusters**
```sql
id, video_id (FK), name, representative_face_id (FK),
face_count, created_at, updated_at
```

**tasks**
```sql
id, task_type (FEATURE|CLUSTER|TAG), 
status (PENDING|ASSIGNED|RUNNING|COMPLETED|FAILED),
video_id (FK), frame_id (FK), face_id (FK),
worker_id, retry_count, error_message,
created_at, started_at, completed_at
```

**tags / video_tags**
```sql
tags: id, name, category, created_at
video_tags: id, video_id (FK), tag_id (FK), confidence
```

**workers**
```sql
id, worker_id (unique), status, last_heartbeat,
current_task_id, created_at
```

## 任务流程

### 完整处理流程

```
1. 扫描视频
   └─> VideoScanner.scan_directory()
       └─> 创建 Video (status=SCANNED)

2. 开始处理（用户点击"处理"）
   └─> FrameExtractor.extract_frames(video_id, force=True)
       ├─> 删除旧数据 (Face → Frame → Task)
       ├─> 抽取 10 帧
       ├─> 创建 Frame 记录
       ├─> 创建 FEATURE 任务 (10 个)
       └─> Video.status = PROCESSING

3. Worker 拉取任务（每 5 秒）
   └─> POST /api/tasks/pull
       ├─> 查询 PENDING 任务
       ├─> 更新为 ASSIGNED
       └─> 返回任务列表

4. Worker 执行 FEATURE 任务
   ├─> 获取帧图片
   ├─> InsightFace 检测人脸
   ├─> POST /api/faces 创建 Face 记录
   └─> POST /api/tasks/{id}/complete

5. NAS 处理特征完成
   └─> /api/tasks/feature/submit
       ├─> 保存 embedding
       ├─> 检查是否所有 FACE 都完成
       └─> 是 → 创建 CLUSTER 任务
           └─> Video.status = FEATURED

6. Worker 执行 CLUSTER 任务
   ├─> GET /api/faces?has_embedding=true
   ├─> HDBSCAN 聚类
   ├─> 创建 Cluster 记录
   ├─> 更新 Face.cluster_id
   └─> POST /api/tasks/cluster/submit

7. Worker 执行 TAG 任务
   ├─> 获取代表帧
   ├─> LLM 分析场景
   └─> 创建 Tag 记录

8. 所有任务完成
   └─> Video.status = READY
       └─> 等待用户审核命名
```

### 任务状态机

```
PENDING → ASSIGNED → RUNNING → COMPLETED
   │                      │
   │                      └──→ FAILED
   │                           │
   └───────────────────────────┘ (重试)
```

## 关键设计决策

### 1. 抽帧与人脸检测分离

**原因**：
- NAS 服务器可能没有 GPU 或 AI 依赖
- Worker 可以分布式部署，利用不同机器的 GPU 资源
- 架构更清晰，职责分离

**实现**：
- NAS 只负责抽帧，创建 FEATURE 任务（只有 frame_id）
- Worker 接收任务后检测人脸，创建 Face 记录

### 2. 任务拉取模式（Pull-based）

**原因**：
- Worker 主动拉取，NAS 不需要维护任务队列
- Worker 可以控制并发数
- 更容易实现负载均衡

**实现**：
- Worker 每 5 秒轮询 `/api/tasks/pull`
- 每次最多拉取 `max_concurrent - active_tasks` 个任务
- 使用 `FOR UPDATE SKIP LOCKED` 避免任务重复分配

### 3. 聚类任务延迟创建

**原因**：
- 必须等所有特征提取完成后才能聚类
- 避免轮询检查，使用事件驱动

**实现**：
- 每个 FEATURE 任务完成时检查剩余未处理人脸数
- 当数量为 0 时，自动创建 CLUSTER 任务

### 4. GPU/CPU 自适应

**原因**：
- Worker 可能部署在有/无 GPU 的机器上
- 需要自动适配

**实现**：
```python
if torch.cuda.is_available():
    # GPU: 4bit 量化
    quantization_config = BitsAndBytesConfig(...)
    model = AutoModelForCausalLM.from_pretrained(..., quantization_config=...)
else:
    # CPU: float32
    model = AutoModelForCausalLM.from_pretrained(..., torch_dtype=torch.float32)
```

## 部署架构

### 开发环境
```
本地运行：
- NAS 服务器：Docker 容器（PostgreSQL + FastAPI）
- Worker：本地 Python 进程（使用本地 GPU）
```

### 生产环境（Unraid）
```
Docker 容器：
- video-org-app: NAS 服务器 + PostgreSQL
- video-org-worker (可选): Worker 容器（如有 GPU 直通）

本地运行：
- Worker：Unraid 宿主机 Python 进程（直接使用 GPU）
```

### 配置项

**环境变量**：
```bash
# NAS 服务器
DATABASE_URL=postgresql://postgres:postgres@db:5432/video_org
RAW_VIDEO_DIR=/media/raw
FRAME_CACHE_DIR=/cache/frames

# Worker
NAS_URL=http://192.168.88.10:8000
WORKER_ID=worker-gpu-1
MAX_CONCURRENT=2
ENABLED_TASKS=feature,cluster,tag
FEATURE_MODEL_PATH=buffalo_l
LLM_MODEL_PATH=Qwen/Qwen2.5-7B-Instruct
```

## 性能优化

### 1. 批量处理
- 特征提取：批量获取人脸 embedding
- 聚类：一次性加载所有人脸向量

### 2. 缓存策略
- 帧图片缓存在 `/cache/frames/{video_id}/`
- 避免重复解码视频

### 3. 数据库索引
- `faces.frame_id` - 快速查询某帧的人脸
- `faces.cluster_id` - 快速查询聚类的人脸
- `tasks.status` - 快速查询待处理任务
- `tasks.video_id` - 快速查询视频的任务

### 4. 并发控制
- Worker 并发数限制（默认 2）
- 任务超时检测（300 秒）
- 心跳机制（30 秒）

## 扩展性

### 水平扩展 Worker
- 部署多个 Worker 实例
- 通过 `worker_id` 区分
- 任务自动负载均衡

### 新增任务类型
1. 在 `TaskType` 枚举中添加
2. 实现 `Worker._process_xxx_task()`
3. 添加对应的 submit 接口

### 更换 AI 模型
- 人脸检测：替换 InsightFace 为其他模型
- 聚类：替换 HDBSCAN 为其他算法
- 打标：更换 LLM 模型

## 故障恢复

### 任务失败重试
- 自动重试最多 3 次
- 手动点击"重试"按钮
- 失败任务记录错误信息

### Worker 离线处理
- 心跳超时（300 秒）标记为离线
- 任务重新分配给其他 Worker
- 避免任务丢失

### 数据库一致性
- 外键约束保证数据完整性
- 事务保证原子性
- 删除顺序：Face → Frame → Task

## 监控与日志

### Worker 日志
```
Processing task 23 (type: feature) for video 1
Detecting faces in frame 21
Detected 1 faces in frame 21
Creating face record: {...}
✓ Created face record 45 for frame 21
✓ Task 23 completed successfully
```

### NAS 日志
```
Created cluster task for video 1
Task 23 completed
Video 1 status updated to CLUSTERED
```

### 前端监控
- 任务状态实时展示
- Worker 在线状态
- 处理进度条

## 安全考虑

### 认证授权
- 当前：无认证（内网使用）
- 未来：JWT Token / API Key

### 数据隔离
- 不同视频的数据通过 video_id 隔离
- Worker 只能访问分配的任务

### 资源限制
- Worker 并发数限制
- 任务超时自动终止
- 磁盘空间监控

## 未来规划

1. **多 Worker 支持** - 分布式任务处理
2. **GPU 直通** - Docker 容器直接使用 GPU
3. **进度实时推送** - WebSocket 推送任务进度
4. **更多 AI 功能** - 动作识别、语音转文字
5. **移动端适配** - 响应式设计
6. **用户系统** - 多用户支持
