import os
import sys
import time
import uuid
import threading
import argparse
import requests
import numpy as np
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import cv2

# 提前导入 torch 和量化配置
try:
    import torch
    from transformers import BitsAndBytesConfig
    GPU_AVAILABLE = torch.cuda.is_available()
    if GPU_AVAILABLE:
        print(f"GPU available: {torch.cuda.get_device_name(0)}")
    else:
        print("GPU not available, will use CPU")
except ImportError as e:
    print(f"Failed to import torch: {e}")
    GPU_AVAILABLE = False
    BitsAndBytesConfig = None

# 提前导入 insightface
try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
    print("InsightFace imported successfully")
except ImportError as e:
    print(f"Failed to import InsightFace: {e}")
    INSIGHTFACE_AVAILABLE = False
    FaceAnalysis = None

try:
    import torch
    from insightface.app import FaceAnalysis
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    import hdbscan
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False


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


class FeatureExtractor:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.model = None
        self.device = "cuda" if GPU_AVAILABLE and torch.cuda.is_available() else "cpu"
        
    def load_model(self):
        if self.model is None:
            print(f"Loading feature extraction model on {self.device}...")
            self.model = FaceAnalysis(
                name=self.config.feature_model_path,
                providers=['CUDAExecutionProvider' if self.device == "cuda" else 'CPUExecutionProvider']
            )
            self.model.prepare(ctx_id=0 if self.device == "cuda" else -1, det_size=(640, 640))
            print("Feature model loaded.")
    
    def extract(self, image_data: bytes) -> Optional[np.ndarray]:
        self.load_model()
        
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return None
        
        faces = self.model.get(img)
        
        if len(faces) == 0:
            return None
        
        embedding = faces[0].embedding
        return embedding / np.linalg.norm(embedding)


class ClusterProcessor:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.min_samples = int(os.getenv("CLUSTER_MIN_SAMPLES", "5"))
    
    def cluster(self, embeddings: List[np.ndarray]) -> List[int]:
        if len(embeddings) < self.min_samples:
            return list(range(len(embeddings)))
        
        embeddings_matrix = np.array(embeddings)
        
        clusterer = hdbscan.HDBSCAN(
            min_samples=self.min_samples,
            min_cluster_size=self.min_samples,
            metric='euclidean',
            cluster_selection_method='eom'
        )
        
        labels = clusterer.fit_predict(embeddings_matrix)
        
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
        self.device = "cuda" if GPU_AVAILABLE and torch.cuda.is_available() else "cpu"
    
    def load_model(self):
        if self.model is None:
            print(f"Loading LLM model on {self.device}...")
            
            if self.device == "cuda" and GPU_AVAILABLE and BitsAndBytesConfig:
                # GPU 模式：使用 4bit 量化
                print("Using 4-bit quantization for GPU")
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4"
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
                # CPU 模式：不量化，直接加载
                print("Warning: Running LLM on CPU will be very slow!")
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
            print("LLM model loaded.")
    
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
        self.running = False
        
        self.feature_extractor = FeatureExtractor(self.config)
        self.cluster_processor = ClusterProcessor(self.config)
        self.tag_generator = TagGenerator(self.config)
        
        self.executor = ThreadPoolExecutor(max_workers=self.config.max_concurrent)
        self.active_tasks = {}
    
    def start(self):
        print(f"Worker {self.config.worker_id} starting...")
        print(f"NAS URL: {self.config.nas_url}")
        print(f"Max concurrent tasks: {self.config.max_concurrent}")
        print(f"Enabled task types: {self.config.enabled_tasks}")
        
        self.running = True
        
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat_thread.start()
        
        self._task_loop()
    
    def stop(self):
        self.running = False
        self.executor.shutdown(wait=True)
    
    def _heartbeat_loop(self):
        while self.running:
            try:
                self._send_heartbeat()
            except Exception as e:
                print(f"Heartbeat failed: {e}")
            time.sleep(self.config.heartbeat_interval)
    
    def _send_heartbeat(self, status: str = "idle", task_id: Optional[int] = None):
        response = self.session.post(
            f"{self.config.nas_url}/api/workers/heartbeat",
            json={
                "worker_id": self.config.worker_id,
                "status": status,
                "current_task_id": task_id
            }
        )
        response.raise_for_status()
    
    def _task_loop(self):
        print(f"Task loop started for worker {self.config.worker_id}")
        while self.running:
            try:
                if len(self.active_tasks) < self.config.max_concurrent:
                    print(f"Pulling tasks... (active: {len(self.active_tasks)}, max: {self.config.max_concurrent})")
                    tasks = self._pull_tasks()
                    print(f"Pulled {len(tasks)} tasks")
                    for task in tasks:
                        print(f"Submitting task {task['id']} (type: {task['task_type']}) to executor")
                        future = self.executor.submit(self._process_task, task)
                        self.active_tasks[task["id"]] = future
                
                completed = [tid for tid, f in self.active_tasks.items() if f.done()]
                for tid in completed:
                    print(f"Task {tid} completed")
                    del self.active_tasks[tid]
                
            except Exception as e:
                print(f"Task loop error: {e}")
                import traceback
                traceback.print_exc()
            
            time.sleep(self.config.poll_interval)
    
    def _pull_tasks(self) -> List[Dict]:
        task_types = [t.strip() for t in self.config.enabled_tasks if t.strip()]
        
        print(f"Pulling tasks with task_types: {task_types}")
        
        response = self.session.post(
            f"{self.config.nas_url}/api/tasks/pull",
            json={
                "worker_id": self.config.worker_id,
                "task_types": task_types,
                "max_tasks": self.config.max_concurrent - len(self.active_tasks)
            }
        )
        response.raise_for_status()
        data = response.json()
        print(f"Pull tasks response: {data}")
        return data.get("tasks", [])
    
    def _process_task(self, task: Dict):
        task_id = task["id"]
        task_type = task["task_type"]
        video_id = task.get("video_id", "unknown")
        
        print(f"\n{'='*60}")
        print(f"Processing task {task_id} (type: {task_type}) for video {video_id}")
        print(f"{'='*60}")
        
        # 发送开始通知
        try:
            self.session.post(
                f"{self.config.nas_url}/api/tasks/{task_id}/start",
                json={"worker_id": self.config.worker_id}
            )
        except Exception as e:
            print(f"Failed to send start notification: {e}")
        
        try:
            self._send_heartbeat("busy", task_id)
            
            if task_type == "feature":
                self._process_feature_task(task)
            elif task_type == "cluster":
                self._process_cluster_task(task)
            elif task_type == "tag":
                self._process_tag_task(task)
            else:
                print(f"Unknown task type: {task_type}")
            
            # 发送完成通知
            try:
                self.session.post(
                    f"{self.config.nas_url}/api/tasks/{task_id}/complete",
                    json={"worker_id": self.config.worker_id}
                )
            except Exception as e:
                print(f"Failed to send complete notification: {e}")
            
            print(f"✓ Task {task_id} completed successfully\n")
            
        except Exception as e:
            print(f"✗ Task {task_id} failed: {e}")
            import traceback
            traceback.print_exc()
            self._report_failure(task_id, str(e))
        
        self._send_heartbeat("idle")
    
    def _process_feature_task(self, task: Dict):
        print(f"Processing feature task {task['id']}")
        
        # 情况 1: 任务已经有 face_id，直接处理
        if "face_id" in task:
            self._process_existing_face(task)
        # 情况 2: 任务只有 frame_id，需要先检测人脸
        elif "frame_id" in task:
            self._detect_faces_in_frame(task)
        else:
            raise ValueError(f"Task {task['id']} missing both face_id and frame_id: {task}")
    
    def _process_existing_face(self, task: Dict):
        """处理已有人脸记录的特征提取"""
        face_id = task["face_id"]
        
        print(f"Processing existing face {face_id}")
        
        frame_response = self.session.get(
            f"{self.config.nas_url}/api/faces/{face_id}"
        )
        if frame_response.status_code != 200:
            raise ValueError(f"Failed to get face {face_id}: {frame_response.text}")
        
        frame_data = frame_response.json()
        frame_id = frame_data["frame_id"]
        
        image_response = self.session.get(
            f"{self.config.nas_url}/api/frames/{frame_id}/image"
        )
        image_data = image_response.content
        
        embedding = self.feature_extractor.extract(image_data)
        
        if embedding is None:
            raise ValueError("Failed to extract embedding")
        
        response = self.session.post(
            f"{self.config.nas_url}/api/tasks/feature/submit",
            json={
                "task_id": task["id"],
                "face_id": face_id,
                "embedding": embedding.tolist()
            }
        )
        
        if response.status_code != 200:
            raise ValueError(f"Failed to save embedding: {response.text}")
        
        print(f"Feature task {task['id']} completed for face {face_id}")
    
    def _detect_faces_in_frame(self, task: Dict):
        """在帧中检测人脸并创建记录"""
        frame_id = task["frame_id"]
        video_id = task.get("video_id")
        
        print(f"Detecting faces in frame {frame_id}")
        
        # 检查 insightface 是否可用
        if not INSIGHTFACE_AVAILABLE:
            raise RuntimeError("InsightFace is not installed. Cannot detect faces.")
        
        # 获取帧图片
        image_response = self.session.get(
            f"{self.config.nas_url}/api/frames/{frame_id}/image"
        )
        if image_response.status_code != 200:
            raise ValueError(f"Failed to get frame {frame_id}: {image_response.text}")
        
        image_data = image_response.content
        image_array = np.frombuffer(image_data, np.uint8)
        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        
        if frame is None:
            raise ValueError(f"Failed to decode frame {frame_id}")
        
        # 检测人脸
        if not hasattr(self, 'face_app') or self.face_app is None:
            self.face_app = FaceAnalysis(providers=['CPUExecutionProvider'])
            self.face_app.prepare(ctx_id=0, det_size=(640, 640))
        
        faces = self.face_app.get(frame)
        
        if len(faces) == 0:
            print(f"No faces detected in frame {frame_id}")
            # 标记任务为完成（没有人脸）
            self.session.post(
                f"{self.config.nas_url}/api/tasks/{task['id']}/complete",
                json={"result": {"faces_detected": 0}}
            )
            return
        
        print(f"Detected {len(faces)} faces in frame {frame_id}")
        
        # 为每个人脸创建记录
        for idx, face in enumerate(faces):
            face_data = {
                "video_id": video_id,
                "frame_id": frame_id,
                "bounding_box": face.bbox.tolist(),
                "confidence": float(face.det_score),
                "embedding": face.embedding.tolist() if hasattr(face, 'embedding') else None
            }
            
            print(f"Creating face record: {face_data}")
            print(f"POST to: {self.config.nas_url}/api/faces")
            
            response = self.session.post(f"{self.config.nas_url}/api/faces", json=face_data)
            
            print(f"Response status: {response.status_code}")
            print(f"Response body: {response.text}")
            
            if response.status_code == 200:
                face_id = response.json()["id"]
                print(f"✓ Created face record {face_id} for frame {frame_id}")
            else:
                print(f"✗ Failed to create face record: {response.status_code} - {response.text}")
        
        # 标记任务为完成
        self.session.post(
            f"{self.config.nas_url}/api/tasks/{task['id']}/complete",
            json={"result": {"faces_detected": len(faces)}}
        )
    
    def _process_cluster_task(self, task: Dict):
        embeddings = []
        face_ids = []
        
        page = 0
        batch_size = 100
        
        while True:
            response = self.session.get(
                f"{self.config.nas_url}/api/faces",
                params={"has_embedding": True, "skip": page * batch_size, "limit": batch_size}
            )
            
            if response.status_code != 200:
                break
            
            faces = response.json().get("faces", [])
            if not faces:
                break
            
            for face in faces:
                if face.get("embedding") and not face.get("cluster_id"):
                    emb_response = self.session.get(
                        f"{self.config.nas_url}/api/faces/{face['id']}/embedding"
                    )
                    if emb_response.status_code == 200:
                        embeddings.append(np.array(emb_response.json()["embedding"]))
                        face_ids.append(face["id"])
            
            if len(faces) < batch_size:
                break
            page += 1
        
        if not embeddings:
            print("No embeddings to cluster")
            return
        
        labels = self.cluster_processor.cluster(embeddings)
        
        cluster_results = [
            {"face_id": face_ids[i], "cluster_id": labels[i]}
            for i in range(len(face_ids))
        ]
        
        response = self.session.post(
            f"{self.config.nas_url}/api/tasks/cluster/submit",
            json={
                "task_id": task["id"],
                "cluster_results": cluster_results
            }
        )
        response.raise_for_status()
        print(f"Cluster task {task['id']} completed with {len(cluster_results)} faces")
    
    def _process_tag_task(self, task: Dict):
        video_id = task["video_id"]
        
        frames_response = self.session.get(
            f"{self.config.nas_url}/api/videos/{video_id}/frames"
        )
        frames = frames_response.json()
        
        if not frames:
            raise ValueError("No frames found for video")
        
        rep_frame = next((f for f in frames if f.get("is_representative")), frames[0])
        
        image_response = self.session.get(
            f"{self.config.nas_url}/api/frames/{rep_frame['id']}/image"
        )
        image_data = image_response.content
        
        tags = self.tag_generator.generate_tags(image_data)
        
        if not tags:
            tags = ["未知场景"]
        
        response = self.session.post(
            f"{self.config.nas_url}/api/tasks/tag/submit",
            json={
                "task_id": task["id"],
                "video_id": video_id,
                "tags": tags
            }
        )
        response.raise_for_status()
        print(f"Tag task {task['id']} completed with tags: {tags}")
    
    def _report_failure(self, task_id: int, error_message: str):
        try:
            self.session.post(
                f"{self.config.nas_url}/api/tasks/{task_id}/fail",
                params={"error_message": error_message}
            )
            print(f"Reported task {task_id} failure: {error_message}")
        except Exception as e:
            print(f"Failed to report task failure: {e}")


if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Video Processing Worker")
    
    parser.add_argument("--nas-url", type=str, help="NAS server URL (e.g., http://192.168.88.10:8000)")
    parser.add_argument("--worker-id", type=str, help="Worker ID (e.g., worker-gpu-1)")
    parser.add_argument("--max-concurrent", type=int, help="Maximum concurrent tasks")
    parser.add_argument("--heartbeat-interval", type=int, help="Heartbeat interval in seconds")
    parser.add_argument("--poll-interval", type=int, help="Task poll interval in seconds")
    parser.add_argument("--feature-model", type=str, help="Feature extraction model path")
    parser.add_argument("--llm-model", type=str, help="LLM model path")
    parser.add_argument("--enabled-tasks", type=str, help="Enabled task types (comma-separated)")
    
    args = parser.parse_args()
    
    # 打印配置信息
    config = WorkerConfig(args)
    print(f"=== Worker Configuration ===")
    print(f"NAS URL: {config.nas_url}")
    print(f"Worker ID: {config.worker_id}")
    print(f"Max Concurrent: {config.max_concurrent}")
    print(f"Heartbeat Interval: {config.heartbeat_interval}s")
    print(f"Poll Interval: {config.poll_interval}s")
    print(f"Feature Model: {config.feature_model_path}")
    print(f"LLM Model: {config.llm_model_path}")
    print(f"Enabled Tasks: {config.enabled_tasks}")
    print(f"============================")
    
    worker = Worker(config)
    try:
        worker.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        worker.stop()
