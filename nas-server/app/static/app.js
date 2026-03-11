// API 客户端
const api = axios.create({
  baseURL: '/api',
  timeout: 30000
});

// Vue 应用
const { createApp, ref, reactive, computed, watch, onMounted } = Vue;
const { ElMessageBox, ElMessage } = ElementPlus;

createApp({
  setup() {
    // 页面状态
    const page = ref('dashboard');
    const loading = ref(false);
    
    // 对话框状态
    const showDialog = ref(false);
    const showDirSelector = ref(false);
    const showFaceDialog = ref(false);
    const showSimilarDialog = ref(false);
    const reExtracting = ref(false);
    
    // 数据
    const stats = reactive({
      total_videos: 0, pending_videos: 0, processing_videos: 0,
      ready_videos: 0, completed_videos: 0,
      pending_tasks: 0, running_tasks: 0, online_workers: 0
    });
    const systemDirs = ref([]);
    const dirs = ref([]);
    const videos = ref([]);
    const tasks = ref([]);
    const workers = ref([]);
    const reviewList = ref([]);
    const frames = ref([]);
    const clusters = ref([]);
    const currentVideo = ref(null);
    const currentCluster = ref(null);
    const videoTasks = ref([]);
    const frameFaces = ref([]);
    const similarClusters = ref([]);
    const clusterFaces = ref([]);
    
    // 选择状态
    const selectedDirs = ref([]);
    const selectedVideos = ref([]);
    const selectedReviews = ref([]);
    const filter = ref('');
    const reviewNames = reactive({});
    const clusterVideoFilter = ref('');
    const videoSearch = ref('');
    const sortBy = ref('');
    
    // 计算属性
    const filteredVideos = computed(() => {
      let result = videos.value;
      if (videoSearch.value) {
        const search = videoSearch.value.toLowerCase();
        result = result.filter(v => v.filename.toLowerCase().includes(search));
      }
      if (filter.value) {
        result = result.filter(v => v.status === filter.value);
      }
      if (sortBy.value) {
        result = [...result].sort((a, b) => {
          switch (sortBy.value) {
            case 'created_desc': return new Date(b.created_at) - new Date(a.created_at);
            case 'created_asc': return new Date(a.created_at) - new Date(b.created_at);
            case 'name_asc': return a.filename.localeCompare(b.filename);
            case 'name_desc': return b.filename.localeCompare(a.filename);
            case 'duration_desc': return (b.duration || 0) - (a.duration || 0);
            case 'duration_asc': return (a.duration || 0) - (b.duration || 0);
            default: return 0;
          }
        });
      }
      return result;
    });
    
    const groupedClusters = computed(() => {
      const groups = {};
      clusters.value.forEach(c => {
        if (!groups[c.video_id]) {
          groups[c.video_id] = {
            video_id: c.video_id,
            filename: videos.value.find(v => v.id === c.video_id)?.filename || '',
            clusters: []
          };
        }
        groups[c.video_id].clusters.push(c);
      });
      return Object.values(groups);
    });
    
    const groupedTasks = computed(() => {
      return [...tasks.value].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    });
    
    const totalFaces = computed(() => frames.value.reduce((sum, f) => sum + (f.face_count || 0), 0));
    
    // 方法
    const statusText = (status) => {
      const map = { pending: '待处理', processing: '抽帧中', featured: '特征提取', clustered: '聚类中', tagged: '打标中', ready: '待采纳', completed: '已完成' };
      return map[status] || status;
    };
    
    const taskTypeText = (type) => {
      const map = { feature: '特征提取', cluster: '人脸聚类', tag: '场景打标', extract: '抽帧' };
      return map[type] || type;
    };
    
    const taskStatusText = (status) => {
      const map = { pending: '待分配', running: '进行中', completed: '已完成', failed: '失败' };
      return map[status] || status;
    };
    
    const formatTime = (time) => {
      if (!time) return '-';
      const d = new Date(time);
      const now = new Date();
      const diff = (now - d) / 1000;
      if (diff < 60) return '刚刚';
      if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
      if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
      return d.toLocaleDateString();
    };
    
    const calcDuration = (seconds) => {
      if (!seconds) return '-';
      const m = Math.floor(seconds / 60);
      const s = Math.floor(seconds % 60);
      return `${m}:${s.toString().padStart(2, '0')}`;
    };
    
    const refreshAll = async () => {
      await loadStats();
      ElMessage.success('刷新成功');
    };
    
    const loadStats = async () => {
      try {
        const res = await api.get('/dashboard/stats');
        Object.assign(stats, res.data);
      } catch (e) {}
    };
    
    const loadVideos = async () => {
      try {
        const res = await api.get('/videos');
        videos.value = res.data;
      } catch (e) {}
    };
    
    const refreshVideos = async () => {
      await loadVideos();
      ElMessage.success('刷新成功');
    };
    
    const toggleVideo = (id) => {
      const idx = selectedVideos.value.indexOf(id);
      if (idx > -1) selectedVideos.value.splice(idx, 1);
      else selectedVideos.value.push(id);
    };
    
    const sortVideos = () => {};
    
    const openVideo = async (video) => {
      currentVideo.value = video;
      try {
        const [framesRes, tasksRes] = await Promise.all([
          api.get(`/videos/${video.id}/frames`),
          api.get(`/videos/${video.id}/tasks`)
        ]);
        frames.value = framesRes.data;
        videoTasks.value = tasksRes.data;
        showDialog.value = true;
      } catch (e) {
        ElMessage.error('加载失败');
      }
    };
    
    const startProcess = async (video_id) => {
      try {
        await api.post(`/videos/start-process`, { video_ids: [video_id] });
        ElMessage.success('已开始处理');
        loadVideos();
        loadStats();
      } catch (e) {
        ElMessage.error('处理失败');
      }
    };
    
    const reExtract = async (video_id) => {
      if (!confirm('确定要重新抽帧吗？这将删除现有的帧和人脸数据。')) return;
      reExtracting.value = true;
      try {
        await api.post(`/videos/${video_id}/re-extract`);
        ElMessage.success('已重新开始抽帧');
        loadVideos();
      } catch (e) {
        ElMessage.error('操作失败');
      } finally {
        reExtracting.value = false;
      }
    };
    
    const loadClusters = async () => {
      try {
        let url = '/clusters';
        if (clusterVideoFilter.value) {
          url += `?video_id=${clusterVideoFilter.value}`;
        }
        const res = await api.get(url);
        clusters.value = res.data;
      } catch (e) {
        console.error('loadClusters error:', e);
      }
    };
    
    const findSimilarClusters = async (cluster) => {
      try {
        currentCluster.value = cluster;
        similarClusters.value = [];
        showSimilarDialog.value = true;
        
        const res = await api.get(`/clusters/${cluster.id}/similar?threshold=0.75`);
        similarClusters.value = res.data.similar_clusters || [];
        
        if (similarClusters.value.length === 0) {
          ElMessage.info('未找到相似的聚类');
        }
      } catch (e) {
        ElMessage.error('查找失败：' + e.message);
      }
    };
    
    const mergeClusters = async (sourceId, targetId) => {
      console.log('[mergeClusters] Called with:', { sourceId, targetId });
      
      try {
        // 使用 Element Plus 的确认对话框
        await ElMessageBox.confirm(
          '确定要将这个聚类合并到当前聚类吗？合并后无法撤销。',
          '确认合并',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            type: 'warning'
          }
        );
        
        console.log('[mergeClusters] User confirmed, sending API request...');
        
        // 显示加载提示
        ElMessage.info('正在合并...');
        
        const response = await api.post(`/clusters/merge?source_cluster_ids=${sourceId}&target_cluster_id=${targetId}`);
        
        console.log('[mergeClusters] API response:', response.data);
        
        ElMessage.success('合并成功');
        showSimilarDialog.value = false;
        loadClusters();
      } catch (e) {
        console.error('[mergeClusters] Error:', e);
        if (e === 'cancel') {
          // 用户取消操作，不显示错误
          console.log('[mergeClusters] User cancelled');
          return;
        }
        ElMessage.error('合并失败：' + (e.message || '未知错误'));
      }
    };
    
    const showNameDialog = async (clusterId, currentName) => {
      try {
        const { value } = await ElMessageBox.prompt(
          '请输入聚类名称（演员名）:',
          '命名聚类',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            inputPattern: /.+/,
            inputErrorMessage: '名称不能为空',
            inputValue: currentName || ''
          }
        );
        await saveClusterName(clusterId, value);
      } catch (e) {
        if (e === 'cancel') {
          // 用户取消操作，不显示错误
          return;
        }
      }
    };
    
    const saveClusterName = async (clusterId, name) => {
      try {
        await api.post(`/clusters/${clusterId}/name`, { name });
        ElMessage.success('命名成功');
        loadClusters();
      } catch (e) {
        ElMessage.error('命名失败');
      }
    };
    
    const loadReview = async () => {
      try {
        const res = await api.get('/videos?status=ready');
        reviewList.value = res.data;
        reviewList.value.forEach(v => { if (!reviewNames[v.id]) reviewNames[v.id] = v.recommended_name || ''; });
      } catch (e) {}
    };
    
    const toggleReviewSelection = (video_id) => {
      const idx = selectedReviews.value.indexOf(video_id);
      if (idx > -1) selectedReviews.value.splice(idx, 1);
      else selectedReviews.value.push(video_id);
    };
    
    const batchAdopt = async () => {
      if (selectedReviews.value.length === 0) {
        ElMessage.warning('请选择要采纳的视频');
        return;
      }
      
      const loading = ElMessage.loading('正在批量采纳...', { duration: 0 });
      let success = 0;
      let failed = 0;
      
      const videoIds = [];
      const customNames = {};
      
      for (const videoId of selectedReviews.value) {
        const name = reviewNames[videoId] || '';
        videoIds.push(videoId);
        if (name) {
          customNames[videoId] = name;
        }
      }
      
      try {
        await api.post('/videos/adopt', {
          video_ids: videoIds,
          custom_names: customNames
        });
        success = videoIds.length;
      } catch (e) {
        failed = videoIds.length;
      }
      
      loading.close();
      ElMessage.success(`采纳成功 ${success} 个，失败 ${failed} 个`);
      selectedReviews.value = [];
      loadReview();
    };
    
    const adopt = async (id) => {
      try {
        await api.post('/videos/adopt', {
          video_ids: [id],
          custom_names: reviewNames[id] ? { [id]: reviewNames[id] } : null
        });
        ElMessage.success('采纳成功');
        loadReview();
        loadStats();
      } catch (e) { ElMessage.error('采纳失败'); }
    };
    
    const loadTasks = async () => {
      try { tasks.value = (await api.get('/tasks')).data; } catch (e) {}
    };
    
    const retryTask = async (task_id) => {
      try {
        await api.post(`/tasks/${task_id}/retry`);
        ElMessage.success('已重试');
        loadTasks();
      } catch (e) { ElMessage.error('重试失败'); }
    };
    
    const loadWorkers = async () => {
      try { workers.value = (await api.get('/workers')).data; } catch (e) {}
    };
    
    const loadSystemDirs = async () => {
      try { systemDirs.value = (await api.get('/videos/system-directories')).data; } catch (e) {}
    };
    
    const toggleDir = (path) => {
      const idx = selectedDirs.value.indexOf(path);
      if (idx > -1) selectedDirs.value.splice(idx, 1);
      else selectedDirs.value.push(path);
    };
    
    const confirmDirSelection = async () => {
      try {
        await api.post('/videos/scan', { directories: selectedDirs.value });
        ElMessage.success('添加成功');
        showDirSelector.value = false;
        selectedDirs.value = [];
        loadDirs();
        loadStats();
      } catch (e) { ElMessage.error('添加失败'); }
    };
    
    const loadDirs = async () => {
      try { dirs.value = (await api.get('/videos/directories')).data; } catch (e) {}
    };
    
    const scanDirs = async () => {
      try {
        await api.post('/videos/scan', { directories: dirs.value.map(d => d.path) });
        ElMessage.success('已开始扫描');
        loadStats();
      } catch (e) { ElMessage.error('扫描失败'); }
    };
    
    const viewFrameFaces = async (frame) => {
      try {
        const res = await api.get(`/frames/${frame.id}/faces`);
        frameFaces.value = res.data.faces || [];
        showFaceDialog.value = true;
      } catch (e) { ElMessage.error('加载失败'); }
    };
    
    const viewClusterDetail = async (cluster) => {
      try {
        currentCluster.value = cluster;
        clusterFaces.value = [];
        showFaceDialog.value = true;
        
        // 获取该聚类的所有人脸
        const res = await api.get(`/clusters/${cluster.id}/faces`);
        clusterFaces.value = res.data.faces || [];
      } catch (e) {
        console.error('viewClusterDetail error:', e);
        ElMessage.error('加载聚类详情失败');
      }
    };
    
    const viewFrameDetail = (face) => {
      // 可以进一步实现查看单张人脸详情的功能
      console.log('View frame detail:', face);
    };
    
    // 页面切换监听
    watch(page, (p) => {
      if (p === 'dashboard') loadStats();
      if (p === 'videos') { loadSystemDirs(); loadDirs(); loadVideos(); }
      if (p === 'clusters') { loadVideos(); loadClusters(); }
      if (p === 'review') loadReview();
      if (p === 'tasks') loadTasks();
      if (p === 'workers') loadWorkers();
    });
    
    // 自动刷新
    onMounted(() => {
      loadStats();
      setInterval(loadStats, 30000);
    });
    
    return {
      page, loading, showDialog, showDirSelector, showFaceDialog, showSimilarDialog, reExtracting,
      stats, systemDirs, dirs, videos, tasks, workers, reviewList, frames, clusters, clusterFaces,
      currentVideo, currentCluster, videoTasks, frameFaces, similarClusters,
      selectedDirs, selectedVideos, selectedReviews, filter, reviewNames,
      clusterVideoFilter, videoSearch, sortBy, filteredVideos, groupedClusters, groupedTasks, totalFaces,
      statusText, taskTypeText, taskStatusText, formatTime, calcDuration,
      refreshAll, loadStats, loadVideos, refreshVideos, toggleVideo, sortVideos, openVideo,
      startProcess, reExtract, loadClusters, findSimilarClusters, mergeClusters, showNameDialog, saveClusterName,
      loadReview, toggleReviewSelection, batchAdopt, adopt, loadTasks, retryTask, loadWorkers,
      loadSystemDirs, toggleDir, confirmDirSelection, scanDirs, viewFrameFaces, viewClusterDetail, viewFrameDetail
    };
  }
}).use(ElementPlus).mount('#app');
