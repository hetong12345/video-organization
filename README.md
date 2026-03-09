# 视频AI整理系统

一套完整的视频AI整理系统，包含NAS端核心服务和Worker端GPU处理节点。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                         NAS 端                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ FastAPI App │  │ PostgreSQL  │  │ 视频文件 / 缓存图片  │  │
│  │  (Docker)   │  │ + pgvector  │  │   (卷挂载)          │  │
│  └──────┬──────┘  └──────┬──────┘  └─────────────────────┘  │
│         │                │                                   │
│         └────────────────┘                                   │
│                  │                                           │
└──────────────────┼───────────────────────────────────────────┘
                   │ HTTP API
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼───┐     ┌───▼───┐     ┌───▼───┐
│Worker1│     │Worker2│     │WorkerN│
│(GPU)  │     │(GPU)  │     │(GPU)  │
└───────┘     └───────┘     └───────┘
```

## 功能特性

- **自动视频扫描**: 监控指定目录，自动发现新视频
- **智能抽帧**: 基于场景检测，在镜头切换点附近抽帧
- **人脸检测**: 使用InsightFace检测女性正脸
- **特征提取**: ArcFace提取512维人脸特征向量
- **智能聚类**: HDBSCAN算法自动聚类相似人脸
- **场景打标**: Qwen2.5大模型生成场景/服装标签
- **推荐命名**: 自动生成`[演员]_[标签]_[原名]`格式命名
- **Web管理界面**: 可视化管理视频、聚类、任务

## 快速开始

### NAS端部署

1. **克隆项目**
```bash
cd nas-server
```

2. **配置环境变量**
```bash
cp .env.example .env
# 编辑 .env 文件配置参数
```

3. **创建必要目录**
```bash
mkdir -p media/raw media/processed cache
```

4. **启动服务**
```bash
docker-compose up -d
```

5. **访问Web界面**
```
http://localhost:8000
```

### Worker端部署

#### 方式一：直接运行

1. **安装依赖**
```bash
cd worker
pip install -r requirements.txt
```

2. **配置环境变量**
```bash
export NAS_URL=http://your-nas-ip:8000
export WORKER_ID=worker-1
export MAX_CONCURRENT=2
export ENABLED_TASKS=feature,cluster,tag
```

3. **运行Worker**
```bash
python worker.py
```

#### 方式二：Docker运行

1. **构建镜像**
```bash
cd worker
docker build -t video-org-worker .
```

2. **运行容器**
```bash
docker run -d \
  --gpus all \
  -e NAS_URL=http://your-nas-ip:8000 \
  -e WORKER_ID=worker-1 \
  -e MAX_CONCURRENT=2 \
  video-org-worker
```

## 配置说明

### NAS端环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| DATABASE_URL | postgresql://postgres:postgres@db:5432/video_org | 数据库连接 |
| RAW_VIDEO_DIR | /media/raw | 原始视频目录 |
| PROCESSED_VIDEO_DIR | /media/processed | 处理后视频目录 |
| CACHE_DIR | /cache | 缓存目录 |
| FRAME_CACHE_DIR | /cache/frames | 抽帧图片缓存 |
| MIN_FACE_RATIO | 0.1 | 最小人脸占比阈值 |
| MAX_RETRY_COUNT | 3 | 任务最大重试次数 |
| CLUSTER_MIN_SAMPLES | 5 | 聚类最小样本数 |

### Worker端环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| NAS_URL | http://localhost:8000 | NAS服务地址 |
| WORKER_ID | worker-xxx | Worker唯一标识 |
| MAX_CONCURRENT | 2 | 最大并发任务数 |
| ENABLED_TASKS | feature,cluster,tag | 启用的任务类型 |
| HEARTBEAT_INTERVAL | 30 | 心跳间隔(秒) |
| POLL_INTERVAL | 5 | 任务拉取间隔(秒) |
| LLM_MODEL_PATH | Qwen/Qwen2.5-7B-Instruct | LLM模型路径 |

## API文档

启动服务后访问 `http://localhost:8000/docs` 查看完整API文档。

### 主要API端点

- `GET /api/dashboard/stats` - 获取仪表盘统计
- `GET /api/videos` - 视频列表
- `GET /api/clusters` - 聚类列表
- `POST /api/clusters/name` - 命名聚类
- `POST /api/videos/adopt` - 采纳推荐命名
- `POST /api/tasks/pull` - Worker拉取任务
- `POST /api/tasks/feature/submit` - 提交特征提取结果
- `POST /api/tasks/cluster/submit` - 提交聚类结果
- `POST /api/tasks/tag/submit` - 提交打标结果

## 工作流程

1. **视频入库**: 将视频文件放入 `/media/raw` 目录
2. **自动扫描**: 系统每5分钟扫描新视频
3. **抽帧检测**: 检测场景变化点，提取关键帧
4. **人脸筛选**: 检测女性正脸，过滤低质量人脸
5. **特征提取**: Worker提取人脸特征向量
6. **智能聚类**: 自动聚类相似人脸
7. **场景打标**: LLM生成场景标签
8. **人工命名**: 在Web界面为聚类命名演员
9. **推荐审核**: 审核并采纳推荐命名
10. **文件整理**: 自动移动并重命名文件

## 目录结构

```
video-organization/
├── nas-server/                 # NAS端服务
│   ├── app/
│   │   ├── main.py            # FastAPI主应用
│   │   ├── config.py          # 配置管理
│   │   ├── database.py        # 数据库连接
│   │   ├── models.py          # SQLAlchemy模型
│   │   ├── schemas.py         # Pydantic模型
│   │   ├── scheduler.py       # 定时任务
│   │   ├── routers/           # API路由
│   │   │   ├── dashboard.py
│   │   │   ├── videos.py
│   │   │   ├── tasks.py
│   │   │   ├── clusters.py
│   │   │   ├── frames.py
│   │   │   ├── faces.py
│   │   │   └── workers.py
│   │   ├── services/          # 业务逻辑
│   │   │   ├── video_processor.py
│   │   │   └── task_manager.py
│   │   └── static/            # Web前端
│   │       ├── index.html
│   │       ├── css/style.css
│   │       └── js/app.js
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── init-db.sql
│   ├── requirements.txt
│   └── .env.example
│
└── worker/                    # Worker端
    ├── worker.py              # Worker主程序
    ├── Dockerfile
    └── requirements.txt
```

## 注意事项

1. **内网环境**: 系统设计为纯内网使用，无任何鉴权机制
2. **GPU要求**: Worker端需要NVIDIA GPU，建议RTX 3090或更高
3. **存储空间**: 抽帧图片会占用大量SSD空间，请确保缓存目录有足够空间
4. **网络带宽**: Worker和NAS之间传输图片，建议千兆内网
5. **模型下载**: 首次运行会自动下载模型，需要网络连接

## 故障排查

### Worker连接失败
- 检查NAS_URL配置是否正确
- 确认NAS端服务正常运行
- 检查网络连通性

### 特征提取失败
- 确认GPU驱动正常
- 检查CUDA版本兼容性
- 查看Worker日志

### 聚类无结果
- 确认有足够的特征向量
- 调整CLUSTER_MIN_SAMPLES参数
- 检查HDBSCAN参数

## 许可证

MIT License
