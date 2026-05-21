"use client";

import { useEffect, useState } from "react";
import { mediaCacheManager, CacheItem } from "@/lib/mediaCache";
import { mediaHistoryManager, HistoryItem } from "@/lib/mediaHistory";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { VideoPlayer } from "@/components/media/VideoPlayer";

export default function MediaManagementPage() {
  const [cacheItems, setCacheItems] = useState<CacheItem[]>([]);
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [cacheStats, setCacheStats] = useState({
    totalSize: 0,
    itemCount: 0,
    byType: {} as Record<string, number>,
  });
  const [historyStats, setHistoryStats] = useState({
    totalItems: 0,
    totalPlayCount: 0,
    byType: {} as Record<string, number>,
    cachedItems: 0,
  });
  const [selectedMedia, setSelectedMedia] = useState<CacheItem | null>(null);
  const [selectedHistory, setSelectedHistory] = useState<HistoryItem | null>(null);
  const [activeTab, setActiveTab] = useState<"cache" | "history">("cache");
  
  const networkStatus = useNetworkStatus();

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      await mediaCacheManager.init();
      await mediaHistoryManager.init();
      
      const [offlineMedia, cacheData, historyData, historyDataStats] = await Promise.all([
        mediaCacheManager.getOfflineAvailableMedia(),
        mediaCacheManager.getCacheStats(),
        mediaHistoryManager.getRecentHistory(20),
        mediaHistoryManager.getHistoryStats(),
      ]);
      
      setCacheItems(offlineMedia);
      setCacheStats(cacheData);
      setHistoryItems(historyData);
      setHistoryStats(historyDataStats);
    } catch (error) {
      console.error("Failed to load media data:", error);
    }
  };

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
  };

  const formatDate = (timestamp: number): string => {
    return new Date(timestamp).toLocaleString("zh-CN");
  };

  const formatTime = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
    }
    return `${minutes}:${secs.toString().padStart(2, "0")}`;
  };

  const handleClearCache = async () => {
    if (!confirm("确定要清除所有缓存吗？")) return;
    
    try {
      await mediaCacheManager.clearAllCache();
      await loadData();
    } catch (error) {
      console.error("Failed to clear cache:", error);
      alert("清除缓存失败");
    }
  };

  const handleClearExpiredCache = async () => {
    try {
      const count = await mediaCacheManager.clearExpiredCache();
      alert(`已清除 ${count} 个过期缓存项`);
      await loadData();
    } catch (error) {
      console.error("Failed to clear expired cache:", error);
      alert("清除过期缓存失败");
    }
  };

  const handleDeleteCacheItem = async (id: string) => {
    if (!confirm("确定要删除此缓存项吗？")) return;
    
    try {
      await mediaCacheManager.deleteCachedMedia(id);
      await loadData();
    } catch (error) {
      console.error("Failed to delete cache item:", error);
      alert("删除缓存项失败");
    }
  };

  const handleClearHistory = async () => {
    if (!confirm("确定要清除所有播放历史吗？")) return;
    
    try {
      await mediaHistoryManager.clearHistory();
      await loadData();
    } catch (error) {
      console.error("Failed to clear history:", error);
      alert("清除历史失败");
    }
  };

  const handleDeleteHistoryItem = async (url: string, type: "video" | "audio") => {
    try {
      await mediaHistoryManager.removeFromHistory(url, type);
      await loadData();
    } catch (error) {
      console.error("Failed to delete history item:", error);
      alert("删除历史项失败");
    }
  };

  const handlePlayMedia = (item: CacheItem) => {
    setSelectedMedia(item);
    setSelectedHistory(null);
  };

  const handlePlayHistory = (item: HistoryItem) => {
    setSelectedHistory(item);
    setSelectedMedia(null);
  };

  const handleClosePlayer = () => {
    setSelectedMedia(null);
    setSelectedHistory(null);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        {/* 标题 */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">音视频管理</h1>
          <p className="text-slate-400">管理本地缓存和播放历史</p>
        </div>

        {/* 网络状态 */}
        <div className="mb-6 p-4 bg-slate-900 rounded-lg">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className={`w-3 h-3 rounded-full ${networkStatus.isOnline ? "bg-green-500" : "bg-red-500"}`} />
              <span>{networkStatus.isOnline ? "在线" : "离线"}</span>
            </div>
            {networkStatus.isOnline && (
              <>
                <div className="text-slate-400">|</div>
                <div className="text-sm text-slate-400">
                  网络类型: {networkStatus.effectiveType}
                </div>
                <div className="text-sm text-slate-400">
                  速度: {networkStatus.downlink} Mbps
                </div>
                <div className="text-sm text-slate-400">
                  延迟: {networkStatus.rtt} ms
                </div>
                {networkStatus.isSlowConnection && (
                  <div className="text-sm text-amber-400">
                    ⚠️ 弱网环境
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* 播放器 */}
        {(selectedMedia || selectedHistory) && (
          <div className="mb-8 p-6 bg-slate-900 rounded-lg">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold">
                {selectedMedia ? "播放缓存媒体" : "播放历史媒体"}
              </h2>
              <button
                onClick={handleClosePlayer}
                className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg transition"
              >
                关闭
              </button>
            </div>
            
            {selectedMedia && (
              <VideoPlayer
                src={selectedMedia.url}
                type={selectedMedia.type}
                title={selectedMedia.url.split("/").pop()}
                enableCache={false}
                enableHistory={true}
              />
            )}
            
            {selectedHistory && (
              <VideoPlayer
                src={selectedHistory.url}
                type={selectedHistory.type}
                title={selectedHistory.title}
                enableCache={true}
                enableHistory={true}
              />
            )}
          </div>
        )}

        {/* 标签页 */}
        <div className="mb-6">
          <div className="flex gap-2">
            <button
              onClick={() => setActiveTab("cache")}
              className={`px-4 py-2 rounded-lg transition ${
                activeTab === "cache"
                  ? "bg-violet-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:bg-slate-700"
              }`}
            >
              本地缓存
            </button>
            <button
              onClick={() => setActiveTab("history")}
              className={`px-4 py-2 rounded-lg transition ${
                activeTab === "history"
                  ? "bg-violet-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:bg-slate-700"
              }`}
            >
              播放历史
            </button>
          </div>
        </div>

        {/* 缓存管理 */}
        {activeTab === "cache" && (
          <div className="space-y-6">
            {/* 缓存统计 */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-4 bg-slate-900 rounded-lg">
                <div className="text-sm text-slate-400 mb-1">缓存大小</div>
                <div className="text-2xl font-bold">{formatBytes(cacheStats.totalSize)}</div>
              </div>
              <div className="p-4 bg-slate-900 rounded-lg">
                <div className="text-sm text-slate-400 mb-1">缓存项数量</div>
                <div className="text-2xl font-bold">{cacheStats.itemCount}</div>
              </div>
              <div className="p-4 bg-slate-900 rounded-lg">
                <div className="text-sm text-slate-400 mb-1">类型分布</div>
                <div className="text-sm">
                  视频: {cacheStats.byType.video || 0} | 
                  音频: {cacheStats.byType.audio || 0}
                </div>
              </div>
            </div>

            {/* 缓存操作 */}
            <div className="flex gap-2">
              <button
                onClick={handleClearExpiredCache}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-500 rounded-lg transition"
              >
                清除过期缓存
              </button>
              <button
                onClick={handleClearCache}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded-lg transition"
              >
                清除所有缓存
              </button>
            </div>

            {/* 缓存列表 */}
            <div className="bg-slate-900 rounded-lg overflow-hidden">
              <div className="p-4 border-b border-slate-800">
                <h3 className="font-semibold">缓存列表</h3>
              </div>
              
              {cacheItems.length === 0 ? (
                <div className="p-8 text-center text-slate-400">
                  暂无缓存内容
                </div>
              ) : (
                <div className="divide-y divide-slate-800">
                  {cacheItems.map((item) => (
                    <div key={item.id} className="p-4 flex items-center justify-between hover:bg-slate-800 transition">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`px-2 py-1 text-xs rounded ${
                            item.type === "video" ? "bg-blue-600" : "bg-green-600"
                          }`}>
                            {item.type === "video" ? "视频" : "音频"}
                          </span>
                          <span className="text-sm text-slate-400">
                            {formatBytes(item.metadata.size)}
                          </span>
                        </div>
                        <div className="text-sm text-slate-300 truncate mb-1">
                          {item.url}
                        </div>
                        <div className="text-xs text-slate-500">
                          缓存时间: {formatDate(item.metadata.createdAt)} | 
                          过期时间: {formatDate(item.metadata.expiresAt)}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handlePlayMedia(item)}
                          className="px-3 py-1 bg-violet-600 hover:bg-violet-500 rounded text-sm transition"
                        >
                          播放
                        </button>
                        <button
                          onClick={() => handleDeleteCacheItem(item.id)}
                          className="px-3 py-1 bg-red-600 hover:bg-red-500 rounded text-sm transition"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* 历史管理 */}
        {activeTab === "history" && (
          <div className="space-y-6">
            {/* 历史统计 */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="p-4 bg-slate-900 rounded-lg">
                <div className="text-sm text-slate-400 mb-1">历史记录数</div>
                <div className="text-2xl font-bold">{historyStats.totalItems}</div>
              </div>
              <div className="p-4 bg-slate-900 rounded-lg">
                <div className="text-sm text-slate-400 mb-1">总播放次数</div>
                <div className="text-2xl font-bold">{historyStats.totalPlayCount}</div>
              </div>
              <div className="p-4 bg-slate-900 rounded-lg">
                <div className="text-sm text-slate-400 mb-1">已缓存项</div>
                <div className="text-2xl font-bold">{historyStats.cachedItems}</div>
              </div>
              <div className="p-4 bg-slate-900 rounded-lg">
                <div className="text-sm text-slate-400 mb-1">类型分布</div>
                <div className="text-sm">
                  视频: {historyStats.byType.video || 0} | 
                  音频: {historyStats.byType.audio || 0}
                </div>
              </div>
            </div>

            {/* 历史操作 */}
            <div className="flex gap-2">
              <button
                onClick={handleClearHistory}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded-lg transition"
              >
                清除所有历史
              </button>
            </div>

            {/* 历史列表 */}
            <div className="bg-slate-900 rounded-lg overflow-hidden">
              <div className="p-4 border-b border-slate-800">
                <h3 className="font-semibold">最近播放</h3>
              </div>
              
              {historyItems.length === 0 ? (
                <div className="p-8 text-center text-slate-400">
                  暂无播放历史
                </div>
              ) : (
                <div className="divide-y divide-slate-800">
                  {historyItems.map((item) => (
                    <div key={item.id} className="p-4 flex items-center justify-between hover:bg-slate-800 transition">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`px-2 py-1 text-xs rounded ${
                            item.type === "video" ? "bg-blue-600" : "bg-green-600"
                          }`}>
                            {item.type === "video" ? "视频" : "音频"}
                          </span>
                          {item.metadata.cached && (
                            <span className="px-2 py-1 text-xs rounded bg-green-600">
                              已缓存
                            </span>
                          )}
                          <span className="text-xs text-slate-400">
                            播放 {item.playCount} 次
                          </span>
                        </div>
                        <div className="text-sm text-slate-300 mb-1">
                          {item.title || item.url}
                        </div>
                        <div className="text-xs text-slate-500">
                          上次播放: {formatDate(item.playedAt)} | 
                          进度: {formatTime(item.lastPosition)} / {formatTime(item.duration)}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handlePlayHistory(item)}
                          className="px-3 py-1 bg-violet-600 hover:bg-violet-500 rounded text-sm transition"
                        >
                          {item.lastPosition > 0 ? "继续" : "播放"}
                        </button>
                        <button
                          onClick={() => handleDeleteHistoryItem(item.url, item.type)}
                          className="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded text-sm transition"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}