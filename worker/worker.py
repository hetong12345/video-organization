import os
import sys
import time
import uuid
import threading
import argparse
import requests
import logging
import numpy as np
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import cv2

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 提前导入 torch 和量化配置
try:
    import torch
    from transformers import BitsAndBytesConfig
    GPU_AVAILABLE = torch.cuda.is_available()
    if GPU_AVAILABLE:
        logger.info(f"GPU available: {torch.cuda.get_device_name(0)}")
    else:
        logger.info("GPU not available, will use CPU")
except ImportError as e:
    logger.warning(f"Failed to import torch: {e}")
    GPU_AVAILABLE = False
    BitsAndBytesConfig = None

# 提前导入 insightface
try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
    logger.info("InsightFace imported successfully")
except ImportError as e:
    logger.warning(f"Failed to import InsightFace: {e}")
    INSIGHTFACE_AVAILABLE = False
    FaceAnalysis = None

try:
    import hdbscan
    HDBSCAN_AVAILABLE = True
except ImportError:
    HDBSCAN_AVAILABLE = False


class WorkerConfig:
    def __init__(self, args=None):
        # 优先使用命令行参数，其次环境变量，最后默认值
        self.nas_url = args.nas_url if args and args.nas_url else os.getenv("NAS_URL", "http://localhost:8000")
        
        # Worker ID
        if args and args.worker_id:
            self.worker_id = args.worker_id
        elif os.getenv("WORKER_ID"):
            self.worker_id = os.getenv("WORKER_ID")
        else:
            import socket
            hostname = socket.gethostname()
            self.worker_id = f"worker-{hostname}-gpu"
        
        self.max_concurrent = args.max_concurrent if args and args.max_concurrent else int(os.getenv("MAX_CONCURRENT", "2"))
        self.heartbeat_interval = args.heartbeat_interval if args and args.heartbeat_interval else int(os.getenv("HEARTBEAT_INTERVAL", "30"))
        self.poll_interval = args.poll_interval if args and args.poll_interval else int(os.getenv("POLL_INTERVAL", "5"))
        
        self.feature_model_path = args.feature_model if args and args.feature_model else os.getenv("FEATURE_MODEL_PATH", "buffalo_l")
        self.llm_model_path = args.llm_model if args and args.llm_model else os.getenv("LLM_MODEL_PATH", "Qwen/Qwen2.5-7B-Instruct")
        
        enabled_tasks = args.enabled_tasks if args and args.enabled_tasks else os.getenv("ENABLED_TASKS", "feature,cluster,tag")
        self.enabled_tasks = [t.strip() for t in enabled_tasks.split(",")]
        
        # 验证配置
        if not self.nas_url.startswith("http"):
            raise ValueError(f"Invalid NAS_URL: {self.nas_url}")
        
        logger.info(f"Worker config initialized:")
        logger.info(f"  Worker ID: {self.worker_id}")
        logger.info(f"  NAS URL: {self.nas_url}")
        logger.info(f"  Max concurrent tasks: {self.max_concurrent}")
        logger.info(f"  Enabled tasks: {', '.join(self.enabled_tasks)}")


class FeatureExtractor:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.model = None
        self.device = "cuda" if GPU_AVAILABLE and torch.cuda.is_available() else "cpu"
        
    def load_model(self):
        if self.model is None:
            logger.info(f"Loading feature extraction model on {self.device}...")
            self.model = FaceAnalysis(
                name=self.config.feature_model_path,
                providers=['CUDAExecutionProvider' if self.device == "cuda" else 'CPUExecutionProvider']
            )
            self.model.prepare(ctx_id=0 if self.device == "cuda" else -1, det_size=(640, 640))
            logger.info("Feature model loaded.")
    
    def extract(self, image_data: bytes) -> Optional[np.ndarray]:
        self.load_model()
        
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return None
        
        faces = self.model.get(img)
        
        if len(faces) == 0:
            return None
        
        return faces[0].embedding if hasattr(faces[0], 'embedding') else None


class ClusterProcessor:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.min_samples = 2
    
    def cluster(self, embeddings: List[np.ndarray]) -> List[int]:
        n_samples = len(embeddings)
        
        if n_samples < 2:
            return [0] if n_samples > 0 else []
        
        if n_samples < 5:
            return list(range(n_samples))
        
        embeddings_matrix = np.array(embeddings)
        
        # 动态调整参数
        min_samples = min(3, max(2, n_samples // 3))
        min_cluster_size = min(2, max(2, n_samples // 4))
        
        logger.info(f"Clustering {n_samples} faces (min_samples={min_samples}, min_cluster_size={min_cluster_size})")
        
        clusterer = hdbscan.HDBSCAN(
            min_samples=min_samples,
            min_cluster_size=min_cluster_size,
            metric='euclidean',
            cluster_selection_method='eom'
        )
        
        labels = clusterer.fit_predict(embeddings_matrix)
        
        noise_count = sum(1 for l in labels if l == -1)
        logger.info(f"HDBSCAN result: {len(set(labels))} clusters, {noise_count} noise points")
        
        # 如果全是噪声点，使用 K-Means
        if noise_count == len(labels):
            logger.warning("All points are noise, falling back to K-Means")
            from sklearn.cluster import KMeans
            
            if n_samples <= 10:
                k = 1
            elif n_samples <= 20:
                k = 2
            else:
                k = min(5, n_samples // 4)
            
            logger.info(f"K-Means with k={k} for {n_samples} faces")
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = kmeans.fit_predict(embeddings_matrix)
        
        # 重新映射标签
        unique_labels = set(labels)
        label_mapping = {}
        new_label = 0
        for label in sorted(unique_labels):
            if label == -1:
                label_mapping[label] = -1
            else:
                label_mapping[label] = new_label
                new_label += 1
        
        return [label_mapping[l] for l in labels]


class TagGenerator:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.model = None
        self.tokenizer = None
        self.device = "cuda" if GPU_AVAILABLE else "cpu"
    
    def load_model(self):
        if self.model is None:
            logger.info("Loading LLM model...")
            from transformers import AutoModelForCausalLM, AutoTokenizer
            
            if GPU_AVAILABLE:
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True
                )
                
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.config.llm_model_path,
                    trust_remote_code=True
                )
                
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.config.llm_model_path,
                    quantization_config=quantization_config,
                    device_map="auto",
                    trust_remote_code=True
                )
            else:
                logger.warning("Running LLM on CPU will be very slow!")
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.config.llm_model_path,
                    trust_remote_code=True
                )
                
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.config.llm_model_path,
                    device_map="cpu",
                    trust_remote_code=True,
                    torch_dtype=torch.float32
                )
            logger.info("LLM model loaded.")
    
    def generate_tags(self, image_data: bytes) -> List[str]:
        self.load_model()
        
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return []
        
        prompt = """分析这张图片，提取场景和服装相关的标签。
请用简短的中文词语描述，例如：卧室、浴室、护士服、校服、泳装等。
只输出标签，用空格分隔，不要其他内容。

标签:"""
        
        messages = [{"role": "user", "content": prompt}]
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=50,
                temperature=0.7,
                top_p=0.9,
                do_sample=True
            )
        
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        tags = response.split("标签:")[-1].strip().split()
        
        return [t for t in tags if len(t) <= 10][:5]


class Worker:
    def __init__(self, config: Optional[WorkerConfig] = None):
        self.config = config or WorkerConfig()
        self.session = requests.Session()
        self.session.timeout = 30  # 设置超时时间
        self.running = False
        
        self.feature_extractor = FeatureExtractor(self.config)
        self.cluster_processor = ClusterProcessor(self.config)
        self.tag_generator = TagGenerator(self.config)
        
        self.executor = ThreadPoolExecutor(max_workers=self.config.max_concurrent)
        self.active_tasks = {}
        self.tasks_processed = 0
        self.last_heartbeat_time = 0
    
    def start(self):
        logger.info("=" * 60)
        logger.info(f"Worker {self.config.worker_id} starting...")
        logger.info("=" * 60)
        
        self.running = True
        
        # 启动心跳线程
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat_thread.start()
        
        # 主任务循环
        self._task_loop()
    
    def stop(self):
        logger.info("Worker stopping...")
        self.running = False
        self.executor.shutdown(wait=True)
        logger.info("Worker stopped")
    
    def _heartbeat_loop(self):
        """心跳循环线程"""
        while self.running:
            try:
                self._send_heartbeat()
                self.last_heartbeat_time = time.time()
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
            time.sleep(self.config.heartbeat_interval)
    
    def _send_heartbeat(self, status: str = "idle", task_id: Optional[int] = None):
        """发送心跳"""
        try:
            response = self.session.post(
                f"{self.config.nas_url}/api/workers/heartbeat",
                json={
                    "worker_id": self.config.worker_id,
                    "status": status,
                    "current_task_id": task_id
                },
                timeout=10
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send heartbeat: {e}")
            raise
    
    def _task_loop(self):
        """主任务循环"""
        logger.info("Task loop started")
        
        while self.running:
            try:
                # 检查是否有空闲槽位
                if len(self.active_tasks) < self.config.max_concurrent:
                    available_slots = self.config.max_concurrent - len(self.active_tasks)
                    logger.debug(f"Pulling tasks (available slots: {available_slots})")
                    
                    tasks = self._pull_tasks(available_slots)
                    
                    if tasks:
                        logger.info(f"Pulled {len(tasks)} tasks: {[t['id'] for t in tasks]}")
                        
                        for task in tasks:
                            logger.info(f"Processing task {task['id']} (type: {task['task_type']})")
                            future = self.executor.submit(self._process_task, task)
                            self.active_tasks[task["id"]] = future
                    else:
                        logger.debug("No tasks available")
                
                # 清理已完成的任务
                completed_tasks = [tid for tid, f in self.active_tasks.items() if f.done()]
                for tid in completed_tasks:
                    try:
                        self.active_tasks[tid].result()  # 获取结果，检查异常
                        self.tasks_processed += 1
                        logger.info(f"Task {tid} completed successfully (total: {self.tasks_processed})")
                    except Exception as e:
                        logger.error(f"Task {tid} failed: {e}")
                    finally:
                        del self.active_tasks[tid]
                
            except Exception as e:
                logger.error(f"Task loop error: {e}", exc_info=True)
            
            time.sleep(self.config.poll_interval)
        
        logger.info("Task loop exited")
    
    def _pull_tasks(self, max_tasks: int) -> List[Dict]:
        """拉取任务"""
        try:
            task_types = [t.strip() for t in self.config.enabled_tasks if t.strip()]
            
            response = self.session.post(
                f"{self.config.nas_url}/api/tasks/pull",
                json={
                    "worker_id": self.config.worker_id,
                    "task_types": task_types,
                    "max_tasks": max_tasks
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            return data.get("tasks", [])
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to pull tasks: {e}")
            return []
    
    def _process_task(self, task: Dict):
        """处理单个任务"""
        task_id = task["id"]
        task_type = task["task_type"]
        
        try:
            # 通知 NAS 任务开始
            self._notify_task_start(task_id)
            
            # 根据任务类型处理
            if task_type == "feature":
                self._process_feature_task(task)
            elif task_type == "cluster":
                self._process_cluster_task(task)
            elif task_type == "tag":
                self._process_tag_task(task)
            else:
                logger.warning(f"Unknown task type: {task_type}")
                self._notify_task_failed(task_id, f"Unknown task type: {task_type}")
                return
            
            logger.info(f"Task {task_id} completed successfully")
        
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            self._notify_task_failed(task_id, str(e))
    
    def _notify_task_start(self, task_id: int):
        """通知 NAS 任务开始"""
        try:
            self.session.post(
                f"{self.config.nas_url}/api/tasks/{task_id}/start",
                json={"worker_id": self.config.worker_id},
                timeout=10
            )
        except Exception as e:
            logger.warning(f"Failed to notify task start: {e}")
    
    def _notify_task_failed(self, task_id: int, error_message: str):
        """通知 NAS 任务失败"""
        try:
            self.session.post(
                f"{self.config.nas_url}/api/tasks/{task_id}/fail",
                json={"error_message": error_message},
                timeout=10
            )
        except Exception as e:
            logger.error(f"Failed to notify task failure: {e}")
    
    def _process_feature_task(self, task: Dict):
        """处理特征提取任务"""
        task_id = task["id"]
        frame_id = task.get("frame_id")
        video_id = task.get("video_id")
        
        logger.info(f"Processing feature task {task_id} for frame {frame_id}")
        
        if not INSIGHTFACE_AVAILABLE:
            raise RuntimeError("InsightFace is not available")
        
        # 获取帧图片
        response = self.session.get(
            f"{self.config.nas_url}/api/frames/{frame_id}/image",
            timeout=30
        )
        if response.status_code != 200:
            raise ValueError(f"Failed to get frame {frame_id}: {response.text}")
        
        image_data = response.content
        faces = self.feature_extractor.extract(image_data)
        
        if faces is None:
            logger.info(f"No faces detected in frame {frame_id}")
            self._notify_task_complete(task_id, {"faces_detected": 0})
            return
        
        logger.info(f"Detected {len(faces)} faces in frame {frame_id}")
        
        # 为每个人脸创建记录
        created_count = 0
        for idx, face in enumerate(faces):
            try:
                face_data = {
                    "video_id": video_id,
                    "frame_id": frame_id,
                    "bounding_box": face.bbox.tolist(),
                    "confidence": float(face.det_score),
                    "embedding": face.embedding.tolist() if hasattr(face, 'embedding') else None
                }
                
                response = self.session.post(
                    f"{self.config.nas_url}/api/faces",
                    json=face_data,
                    timeout=10
                )
                
                if response.status_code == 200:
                    face_id = response.json()["id"]
                    logger.debug(f"Created face record {face_id}")
                    created_count += 1
                else:
                    logger.error(f"Failed to create face record: {response.status_code} - {response.text}")
            
            except Exception as e:
                logger.error(f"Error creating face record: {e}")
        
        self._notify_task_complete(task_id, {"faces_detected": len(faces), "faces_created": created_count})
    
    def _process_cluster_task(self, task: Dict):
        """处理聚类任务"""
        task_id = task["id"]
        video_id = task.get("video_id")
        
        logger.info(f"Processing cluster task {task_id} for video {video_id}")
        
        embeddings = []
        face_ids = []
        
        page = 0
        batch_size = 100
        
        while True:
            try:
                response = self.session.get(
                    f"{self.config.nas_url}/api/faces",
                    params={
                        "has_embedding": True,
                        "skip": page * batch_size,
                        "limit": batch_size
                    },
                    timeout=30
                )
                
                if response.status_code != 200:
                    logger.error(f"Failed to fetch faces page {page}: {response.status_code}")
                    break
                
                faces = response.json().get("faces", [])
                if not faces:
                    break
                
                logger.debug(f"Page {page}: Got {len(faces)} faces")
                
                for face in faces:
                    if face.get("embedding") and not face.get("cluster_id"):
                        try:
                            embeddings.append(np.array(face["embedding"]))
                            face_ids.append(face["id"])
                        except Exception as e:
                            logger.error(f"Error processing embedding for face {face['id']}: {e}")
                
                if len(faces) < batch_size:
                    break
                page += 1
            
            except Exception as e:
                logger.error(f"Error fetching faces: {e}")
                break
        
        logger.info(f"Fetched {len(embeddings)} embeddings for clustering")
        
        if not embeddings:
            logger.warning("No embeddings to cluster")
            self._notify_task_complete(task_id, {"cluster_results": []})
            return
        
        # 执行聚类
        labels = self.cluster_processor.cluster(embeddings)
        
        cluster_results = [
            {"face_id": face_ids[i], "cluster_id": labels[i]}
            for i in range(len(face_ids))
        ]
        
        # 提交聚类结果
        try:
            response = self.session.post(
                f"{self.config.nas_url}/api/tasks/cluster/submit",
                json={
                    "task_id": task_id,
                    "cluster_results": cluster_results
                },
                timeout=30
            )
            response.raise_for_status()
            logger.info(f"Cluster task {task_id} completed with {len(cluster_results)} faces clustered")
            self._notify_task_complete(task_id, {"faces_clustered": len(cluster_results)})
        
        except Exception as e:
            logger.error(f"Failed to submit cluster results: {e}")
            raise
    
    def _process_tag_task(self, task: Dict):
        """处理打标任务"""
        task_id = task["id"]
        video_id = task.get("video_id")
        
        logger.info(f"Processing tag task {task_id} for video {video_id}")
        
        # 获取视频帧
        response = self.session.get(
            f"{self.config.nas_url}/api/videos/{video_id}/frames",
            timeout=30
        )
        if response.status_code != 200:
            raise ValueError(f"Failed to get frames for video {video_id}: {response.text}")
        
        frames = response.json()
        if not frames:
            raise ValueError("No frames found for video")
        
        # 获取代表性帧
        rep_frame = next((f for f in frames if f.get("is_representative")), frames[0])
        logger.info(f"Using representative frame {rep_frame['id']}")
        
        # 获取帧图片
        response = self.session.get(
            f"{self.config.nas_url}/api/frames/{rep_frame['id']}/image",
            timeout=30
        )
        if response.status_code != 200:
            raise ValueError(f"Failed to get frame image: {response.text}")
        
        image_data = response.content
        
        # 生成标签
        tags = self.tag_generator.generate_tags(image_data)
        
        if not tags:
            tags = ["未知场景"]
        
        logger.info(f"Generated tags: {', '.join(tags)}")
        
        # 提交标签结果
        response = self.session.post(
            f"{self.config.nas_url}/api/tasks/tag/submit",
            json={
                "task_id": task_id,
                "video_id": video_id,
                "tags": tags
            },
            timeout=30
        )
        response.raise_for_status()
        
        logger.info(f"Tag task {task_id} completed with tags: {', '.join(tags)}")
        self._notify_task_complete(task_id, {"tags": tags})
    
    def _notify_task_complete(self, task_id: int, result: Dict):
        """通知 NAS 任务完成"""
        try:
            self.session.post(
                f"{self.config.nas_url}/api/tasks/{task_id}/complete",
                json={"result": result},
                timeout=10
            )
        except Exception as e:
            logger.error(f"Failed to notify task completion: {e}")


def parse_args():
    parser = argparse.ArgumentParser(description="Video Organization Worker")
    parser.add_argument("--nas-url", type=str, help="NAS server URL")
    parser.add_argument("--worker-id", type=str, help="Worker ID")
    parser.add_argument("--max-concurrent", type=int, help="Max concurrent tasks")
    parser.add_argument("--heartbeat-interval", type=int, help="Heartbeat interval (seconds)")
    parser.add_argument("--poll-interval", type=int, help="Poll interval (seconds)")
    parser.add_argument("--feature-model", type=str, help="Feature extraction model path")
    parser.add_argument("--llm-model", type=str, help="LLM model path")
    parser.add_argument("--enabled-tasks", type=str, help="Enabled task types (comma-separated)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    
    try:
        config = WorkerConfig(args)
        worker = Worker(config)
        worker.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Worker failed to start: {e}", exc_info=True)
        sys.exit(1)
