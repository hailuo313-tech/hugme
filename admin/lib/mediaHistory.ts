/**
 * P4-11: 媒体历史回放管理器
 * 
 * 管理媒体播放历史，支持弱网环境下的历史回放功能。
 */

interface HistoryItem {
  id: string;
  url: string;
  type: "video" | "audio";
  title?: string;
  thumbnail?: string;
  playedAt: number;
  duration: number;
  lastPosition: number; // 上次播放到的位置（秒）
  playCount: number;
  metadata: {
    size?: number;
    mimeType?: string;
    cached: boolean;
  };
}

class MediaHistoryManager {
  private historyKey = "eris_media_history";
  private maxHistoryItems = 50;
  private history: HistoryItem[] = [];

  async init(): Promise<void> {
    try {
      const stored = localStorage.getItem(this.historyKey);
      if (stored) {
        this.history = JSON.parse(stored);
        // 按播放时间倒序排列
        this.history.sort((a, b) => b.playedAt - a.playedAt);
      }
    } catch (error) {
      console.error("Failed to load media history:", error);
      this.history = [];
    }
  }

  async addToHistory(
    url: string,
    type: "video" | "audio",
    options?: {
      title?: string;
      thumbnail?: string;
      duration?: number;
      lastPosition?: number;
      size?: number;
      mimeType?: string;
      cached?: boolean;
    }
  ): Promise<void> {
    const id = this.generateId(url, type);
    const now = Date.now();
    
    // 检查是否已存在
    const existingIndex = this.history.findIndex(item => item.id === id);
    
    if (existingIndex !== -1) {
      // 更新现有记录
      const existing = this.history[existingIndex];
      this.history[existingIndex] = {
        ...existing,
        playedAt: now,
        lastPosition: options?.lastPosition || existing.lastPosition,
        playCount: existing.playCount + 1,
        metadata: {
          ...existing.metadata,
          size: options?.size || existing.metadata.size,
          mimeType: options?.mimeType || existing.metadata.mimeType,
          cached: options?.cached ?? existing.metadata.cached,
        },
      };
      
      // 移到最前面
      this.history.splice(existingIndex, 1);
      this.history.unshift(this.history[existingIndex]);
    } else {
      // 添加新记录
      const newItem: HistoryItem = {
        id,
        url,
        type,
        title: options?.title,
        thumbnail: options?.thumbnail,
        playedAt: now,
        duration: options?.duration || 0,
        lastPosition: options?.lastPosition || 0,
        playCount: 1,
        metadata: {
          size: options?.size,
          mimeType: options?.mimeType,
          cached: options?.cached || false,
        },
      };
      
      this.history.unshift(newItem);
      
      // 限制历史记录数量
      if (this.history.length > this.maxHistoryItems) {
        this.history = this.history.slice(0, this.maxHistoryItems);
      }
    }
    
    await this.saveHistory();
  }

  async updatePlaybackPosition(
    url: string,
    type: "video" | "audio",
    position: number
  ): Promise<void> {
    const id = this.generateId(url, type);
    const item = this.history.find(item => item.id === id);
    
    if (item) {
      item.lastPosition = position;
      item.playedAt = Date.now(); // 更新播放时间
      await this.saveHistory();
    }
  }

  async getHistory(
    filters?: {
      type?: "video" | "audio";
      cachedOnly?: boolean;
      limit?: number;
    }
  ): Promise<HistoryItem[]> {
    let filtered = [...this.history];
    
    if (filters?.type) {
      filtered = filtered.filter(item => item.type === filters.type);
    }
    
    if (filters?.cachedOnly) {
      filtered = filtered.filter(item => item.metadata.cached);
    }
    
    if (filters?.limit) {
      filtered = filtered.slice(0, filters.limit);
    }
    
    return filtered;
  }

  async getOfflineAvailableHistory(): Promise<HistoryItem[]> {
    return this.getHistory({ cachedOnly: true });
  }

  async getHistoryItem(url: string, type: "video" | "audio"): Promise<HistoryItem | null> {
    const id = this.generateId(url, type);
    return this.history.find(item => item.id === id) || null;
  }

  async removeFromHistory(url: string, type: "video" | "audio"): Promise<void> {
    const id = this.generateId(url, type);
    this.history = this.history.filter(item => item.id !== id);
    await this.saveHistory();
  }

  async clearHistory(): Promise<void> {
    this.history = [];
    await this.saveHistory();
  }

  async getRecentHistory(limit: number = 10): Promise<HistoryItem[]> {
    return this.history.slice(0, limit);
  }

  async getMostPlayed(limit: number = 10): Promise<HistoryItem[]> {
    const sorted = [...this.history].sort((a, b) => b.playCount - a.playCount);
    return sorted.slice(0, limit);
  }

  private async saveHistory(): Promise<void> {
    try {
      localStorage.setItem(this.historyKey, JSON.stringify(this.history));
    } catch (error) {
      console.error("Failed to save media history:", error);
    }
  }

  private generateId(url: string, type: string): string {
    // 使用简单的 hash 算法生成唯一 ID
    const str = `${type}:${url}`;
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // Convert to 32bit integer
    }
    return `${type}_${Math.abs(hash).toString(16)}`;
  }

  async getHistoryStats(): Promise<{
    totalItems: number;
    totalPlayCount: number;
    byType: Record<string, number>;
    cachedItems: number;
  }> {
    const byType: Record<string, number> = {};
    let totalPlayCount = 0;
    let cachedItems = 0;

    for (const item of this.history) {
      byType[item.type] = (byType[item.type] || 0) + 1;
      totalPlayCount += item.playCount;
      if (item.metadata.cached) {
        cachedItems++;
      }
    }

    return {
      totalItems: this.history.length,
      totalPlayCount,
      byType,
      cachedItems,
    };
  }
}

// 导出单例
const mediaHistoryManager = new MediaHistoryManager();

export { mediaHistoryManager, MediaHistoryManager };
export type { HistoryItem };