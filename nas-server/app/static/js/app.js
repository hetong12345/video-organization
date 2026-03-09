const API_BASE = '';

let selectedVideos = new Set();
let selectedDirectories = new Set();

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadDashboard();
    setInterval(loadDashboard, 30000);
});

function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            
            const page = item.dataset.page;
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(`page-${page}`).classList.add('active');
            
            loadPage(page);
        });
    });
}

function loadPage(page) {
    switch(page) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'videos':
            loadVideos();
            loadDirectories();
            break;
        case 'clusters':
            loadClusters();
            break;
        case 'review':
            loadReviewVideos();
            break;
        case 'tasks':
            loadTasks();
            break;
        case 'workers':
            loadWorkers();
            break;
    }
}

async function loadDashboard() {
    try {
        const response = await fetch(`${API_BASE}/api/dashboard/stats`);
        const data = await response.json();
        
        document.getElementById('stat-total-videos').textContent = data.total_videos;
        document.getElementById('stat-pending-videos').textContent = data.pending_videos;
        document.getElementById('stat-processing-videos').textContent = data.processing_videos;
        document.getElementById('stat-ready-videos').textContent = data.ready_videos;
        document.getElementById('stat-completed-videos').textContent = data.completed_videos;
        document.getElementById('stat-online-workers').textContent = data.online_workers;
    } catch (error) {
        console.error('Failed to load dashboard:', error);
    }
}

async function loadDirectories() {
    const container = document.getElementById('directory-list');
    container.innerHTML = '<div class="loading">加载中...</div>';
    
    try {
        const response = await fetch(`${API_BASE}/api/videos/directories`);
        const data = await response.json();
        
        if (!data.directories || data.directories.length === 0) {
            container.innerHTML = '<div class="loading">未发现视频目录，请在 /media 目录下放置视频</div>';
            return;
        }
        
        container.innerHTML = data.directories.map(d => `
            <div class="directory-item">
                <input type="checkbox" id="dir-${d.path}" value="${d.path}" onchange="toggleDirectory('${d.path}')">
                <label for="dir-${d.path}">${d.path} (${d.video_count}个视频)</label>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `<div class="error">加载失败: ${error.message}</div>`;
    }
}

function toggleDirectory(path) {
    if (selectedDirectories.has(path)) {
        selectedDirectories.delete(path);
    } else {
        selectedDirectories.add(path);
    }
}

async function scanSelectedDirectories() {
    if (selectedDirectories.size === 0) {
        alert('请先选择要扫描的目录');
        return;
    }
    
    const dirs = Array.from(selectedDirectories);
    
    try {
        const response = await fetch(`${API_BASE}/api/videos/scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ directories: dirs })
        });
        
        const data = await response.json();
        alert(`扫描完成！\n${data.results.map(r => `${r.directory}: ${r.videos}个视频`).join('\n')}`);
        loadVideos();
    } catch (error) {
        alert('扫描失败: ' + error.message);
    }
}

async function loadVideos() {
    const status = document.getElementById('video-status-filter').value;
    const container = document.getElementById('video-list');
    container.innerHTML = '<div class="loading">加载中...</div>';
    
    try {
        const url = status ? `${API_BASE}/api/videos?status=${status}` : `${API_BASE}/api/videos`;
        const response = await fetch(url);
        const videos = await response.json();
        
        if (videos.length === 0) {
            container.innerHTML = '<div class="loading">暂无视频，请先扫描目录</div>';
            return;
        }
        
        container.innerHTML = videos.map(video => `
            <div class="video-card" onclick="showVideoDetail(${video.id})">
                ${video.thumbnail_url ? `<img src="${video.thumbnail_url}" alt="缩略图">` : '<div style="height:160px;background:#ecf0f1;display:flex;align-items:center;justify-content:center;">无缩略图</div>'}
                <div class="video-card-content">
                    <div class="video-card-title">${video.filename}</div>
                    <span class="video-card-status ${video.status}">${getStatusText(video.status)}</span>
                </div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `<div class="error">加载失败: ${error.message}</div>`;
    }
}

async function showVideoDetail(videoId) {
    try {
        const [videoRes, framesRes] = await Promise.all([
            fetch(`${API_BASE}/api/videos/${videoId}`),
            fetch(`${API_BASE}/api/videos/${videoId}/frames`)
        ]);
        
        const video = await videoRes.json();
        const frames = await framesRes.json();
        
        const modalBody = document.getElementById('modal-body');
        modalBody.innerHTML = `
            <h2>${video.filename}</h2>
            <p><strong>状态:</strong> ${getStatusText(video.status)}</p>
            <p><strong>时长:</strong> ${video.duration ? video.duration.toFixed(1) + '秒' : '未知'}</p>
            <p><strong>推荐命名:</strong> ${video.recommended_name || '未生成'}</p>
            <h3 style="margin-top:20px;">抽帧图片 (${frames.length})</h3>
            <div class="video-grid" style="margin-top:12px;">
                ${frames.map(f => `
                    <div class="video-card">
                        <img src="/api/frames/${f.id}/image" alt="帧">
                        <div class="video-card-content">
                            <div>时间: ${f.timestamp ? f.timestamp.toFixed(1) + 's' : '-'}</div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
        
        openModal();
    } catch (error) {
        alert('加载视频详情失败: ' + error.message);
    }
}

async function loadClusters() {
    const container = document.getElementById('cluster-list');
    container.innerHTML = '<div class="loading">加载中...</div>';
    
    try {
        const response = await fetch(`${API_BASE}/api/clusters`);
        const clusters = await response.json();
        
        if (clusters.length === 0) {
            container.innerHTML = '<div class="loading">暂无聚类数据</div>';
            return;
        }
        
        container.innerHTML = clusters.map(cluster => `
            <div class="cluster-card">
                ${cluster.representative_face_url ? `<img src="${cluster.representative_face_url}" alt="代表脸">` : '<div style="height:160px;background:#ecf0f1;display:flex;align-items:center;justify-content:center;">无图片</div>'}
                <div class="cluster-card-content">
                    <div><strong>聚类 #${cluster.id}</strong></div>
                    <div style="color:#7f8c8d;font-size:12px;">人脸数: ${cluster.face_count}</div>
                    <input type="text" id="cluster-name-${cluster.id}" placeholder="输入演员姓名" value="${cluster.actor_name || ''}">
                    <button onclick="nameCluster(${cluster.id})">保存命名</button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `<div class="error">加载失败: ${error.message}</div>`;
    }
}

async function nameCluster(clusterId) {
    const name = document.getElementById(`cluster-name-${clusterId}`).value.trim();
    if (!name) {
        alert('请输入演员姓名');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/clusters/name`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cluster_id: clusterId, actor_name: name })
        });
        
        const result = await response.json();
        if (result.success) {
            alert('命名成功！');
            loadClusters();
            loadDashboard();
        } else {
            alert('命名失败');
        }
    } catch (error) {
        alert('命名失败: ' + error.message);
    }
}

async function loadReviewVideos() {
    const container = document.getElementById('review-list');
    container.innerHTML = '<div class="loading">加载中...</div>';
    selectedVideos.clear();
    
    try {
        const response = await fetch(`${API_BASE}/api/videos?status=ready`);
        const videos = await response.json();
        
        if (videos.length === 0) {
            container.innerHTML = '<div class="loading">暂无待审核视频</div>';
            return;
        }
        
        container.innerHTML = videos.map(video => `
            <div class="review-card" data-video-id="${video.id}">
                ${video.thumbnail_url ? `<img src="${video.thumbnail_url}" alt="缩略图">` : '<div style="height:160px;background:#ecf0f1;display:flex;align-items:center;justify-content:center;">无缩略图</div>'}
                <div class="review-card-content">
                    <div class="checkbox-wrapper">
                        <input type="checkbox" id="select-${video.id}" onchange="toggleSelect(${video.id})">
                        <label for="select-${video.id}">选择</label>
                    </div>
                    <div class="video-card-title">${video.filename}</div>
                    <input type="text" id="rename-${video.id}" value="${video.recommended_name || ''}" placeholder="推荐命名">
                    <div class="review-card-actions">
                        <button class="btn-adopt" onclick="adoptVideo(${video.id})">采纳</button>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `<div class="error">加载失败: ${error.message}</div>`;
    }
}

function toggleSelect(videoId) {
    if (selectedVideos.has(videoId)) {
        selectedVideos.delete(videoId);
    } else {
        selectedVideos.add(videoId);
    }
}

async function adoptVideo(videoId) {
    const customName = document.getElementById(`rename-${videoId}`).value;
    
    try {
        const response = await fetch(`${API_BASE}/api/videos/adopt`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_ids: [videoId],
                custom_names: customName ? { [videoId]: customName } : null
            })
        });
        
        const result = await response.json();
        if (result.results[0].success) {
            alert('采纳成功！');
            loadReviewVideos();
            loadDashboard();
        } else {
            alert('采纳失败: ' + result.results[0].error);
        }
    } catch (error) {
        alert('采纳失败: ' + error.message);
    }
}

async function adoptSelected() {
    if (selectedVideos.size === 0) {
        alert('请先选择视频');
        return;
    }
    
    const customNames = {};
    selectedVideos.forEach(id => {
        const input = document.getElementById(`rename-${id}`);
        if (input && input.value) {
            customNames[id] = input.value;
        }
    });
    
    try {
        const response = await fetch(`${API_BASE}/api/videos/adopt`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_ids: Array.from(selectedVideos),
                custom_names: Object.keys(customNames).length > 0 ? customNames : null
            })
        });
        
        const result = await response.json();
        const successCount = result.results.filter(r => r.success).length;
        alert(`成功采纳 ${successCount}/${result.results.length} 个视频`);
        loadReviewVideos();
        loadDashboard();
    } catch (error) {
        alert('批量采纳失败: ' + error.message);
    }
}

async function loadTasks() {
    const type = document.getElementById('task-type-filter').value;
    const status = document.getElementById('task-status-filter').value;
    const tbody = document.getElementById('task-tbody');
    
    let url = `${API_BASE}/api/tasks?`;
    if (type) url += `task_type=${type}&`;
    if (status) url += `status=${status}&`;
    
    try {
        const response = await fetch(url);
        const tasks = await response.json();
        
        tbody.innerHTML = tasks.map(task => `
            <tr>
                <td>${task.id}</td>
                <td>${getTaskTypeText(task.task_type)}</td>
                <td><span class="video-card-status ${task.status}">${getTaskStatusText(task.status)}</span></td>
                <td>${task.worker_id || '-'}</td>
                <td>${new Date(task.created_at).toLocaleString()}</td>
                <td>
                    ${task.status === 'failed' ? `<button onclick="retryTask(${task.id})">重试</button>` : ''}
                </td>
            </tr>
        `).join('');
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="6" class="error">加载失败: ${error.message}</td></tr>`;
    }
}

async function retryTask(taskId) {
    try {
        await fetch(`${API_BASE}/api/tasks/${taskId}/retry`, { method: 'POST' });
        loadTasks();
    } catch (error) {
        alert('重试失败: ' + error.message);
    }
}

async function loadWorkers() {
    const container = document.getElementById('worker-list');
    container.innerHTML = '<div class="loading">加载中...</div>';
    
    try {
        const response = await fetch(`${API_BASE}/api/workers`);
        const workers = await response.json();
        
        if (workers.length === 0) {
            container.innerHTML = '<div class="loading">暂无Worker</div>';
            return;
        }
        
        container.innerHTML = workers.map(worker => `
            <div class="worker-card">
                <div class="worker-status">
                    <span class="status-dot ${worker.is_online ? 'online' : ''}"></span>
                    <strong>${worker.id}</strong>
                    <span style="color:#7f8c8d;">${worker.is_online ? '在线' : '离线'}</span>
                </div>
                <div style="color:#7f8c8d;font-size:14px;">
                    <div>状态: ${worker.status}</div>
                    <div>最后心跳: ${new Date(worker.last_heartbeat).toLocaleString()}</div>
                    ${worker.current_task ? `<div>当前任务: #${worker.current_task.id} (${worker.current_task.type})</div>` : ''}
                </div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `<div class="error">加载失败: ${error.message}</div>`;
    }
}

function getStatusText(status) {
    const statusMap = {
        'pending': '待处理',
        'processing': '处理中',
        'ready': '待采纳',
        'completed': '已完成',
        'failed': '失败'
    };
    return statusMap[status] || status;
}

function getTaskTypeText(type) {
    const typeMap = {
        'feature': '特征提取',
        'cluster': '聚类',
        'tag': '打标'
    };
    return typeMap[type] || type;
}

function getTaskStatusText(status) {
    const statusMap = {
        'pending': '待分配',
        'assigned': '已分配',
        'running': '运行中',
        'completed': '已完成',
        'failed': '失败'
    };
    return statusMap[status] || status;
}

function openModal() {
    document.getElementById('modal').classList.add('active');
}

function closeModal() {
    document.getElementById('modal').classList.remove('active');
}

document.getElementById('modal').addEventListener('click', (e) => {
    if (e.target.id === 'modal') {
        closeModal();
    }
});
