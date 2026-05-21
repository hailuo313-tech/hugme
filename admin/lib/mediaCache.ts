/**
 * P4-11: 本地缓存管理器
 * 
 * 使用 IndexedDB 实现音视频的本地缓存，支持弱网环境下的历史回放。
 */

interface CacheItem {
  id: string;
  url: string;
  type: "video" | "audio";
  data: Blob;
  metadata: {
    size: number;
    mimeType: string;
    createdAt: number;
    lastAccessedAt: number;
    expiresAt: number;
  };
}

class MediaCacheManager {
  private dbName = "ERISMediaCache";
  private storeName = "media";
  private db: IDBDatabase | null = null;
  private readonly maxCacheSize = 500 * 1024 * 1024; // 500MB
  private readonly defaultExpiration = 7 * 24 * 60 * 60 * 1000; // 7天

  async init(): Promise<void> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, 1);

      request.onerror = () => {
        console.error("Failed to open IndexedDB:", request.error);
        reject(request.error);
      };

      request.onsuccess = () => {
        this.db = request.result;
        resolve();
      };

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        
        if (!db.objectStoreNames.contains(this.storeName)) {
          const objectStore = db.createObjectStore(this.storeName, { keyPath: "id" });
          objectStore.createIndex("url", "url", { unique: false });
          objectStore.createIndex("type", "type", { unique: false });
          objectStore.createIndex("expiresAt", "expiresAt", { unique: false });
        }
      };
    });
  }

  async cacheMedia(
    url: string,
    type: "video" | "audio",
    data: Blob,
    options?: {
      expiration?: number; // 过期时间（毫秒）
    }
  ): Promise<string> {
    if (!this.db) {
      await this.init();
    }

    const expiration = options?.expiration || this.defaultExpiration;
    const id = this.generateId(url, type);
    const now = Date.now();
    const metadata = {
      size: data.size,
      mimeType: data.type,
      createdAt: now,
      lastAccessedAt: now,
      expiresAt: now + expiration,
    };

    // 检查缓存大小限制
    await this.checkCacheSize(data.size);

    const cacheItem: CacheItem = {
      id,
      url,
      type,
      data,
      metadata,
    };

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([this.storeName], "readwrite");
      const objectStore = transaction.objectStore(this.storeName);

      const request = objectStore.put(cacheItem);

      request.onerror = () => {
        console.error("Failed to cache media:", request.error);
        reject(request.error);
      };

      request.onsuccess = () => {
        console.log(`Media cached: ${type} - ${metadata.size} bytes`);
        resolve(id);
      };
    });
  }

  async getCachedMedia(url: string, type: "video" | "audio"): Promise<Blob | null> {
    if (!this.db) {
      await this.init();
    }

    const id = this.generateId(url, type);

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([this.storeName], "readonly");
      const objectStore = transaction.objectStore(this.storeName);

      const request = objectStore.get(id);

      request.onerror = () => {
        console.error("Failed to get cached media:", request.error);
        reject(request.error);
      };

      request.onsuccess = () => {
        const cacheItem = request.result as CacheItem | undefined;

        if (!cacheItem) {
          resolve(null);
          return;
        }

        // 检查是否过期
        if (cacheItem.metadata.expiresAt < Date.now()) {
          this.deleteCachedMedia(id);
          resolve(null);
          return;
        }

        // 更新最后访问时间
        cacheItem.metadata.lastAccessedAt = Date.now();
        objectStore.put(cacheItem);

        resolve(cacheItem.data);
      };
    });
  }

  async deleteCachedMedia(id: string): Promise<void> {
    if (!this.db) {
      await this.init();
    }

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([this.storeName], "readwrite");
      const objectStore = transaction.objectStore(this.storeName);

      const request = objectStore.delete(id);

      request.onerror = () => {
        console.error("Failed to delete cached media:", request.error);
        reject(request.error);
      };

      request.onsuccess = () => {
        console.log(`Media cache deleted: ${id}`);
        resolve();
      };
    });
  }

  async clearExpiredCache(): Promise<number> {
    if (!this.db) {
      await this.init();
    }

    const now = Date.now();
    let deletedCount = 0;

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([this.storeName], "readwrite");
      const objectStore = transaction.objectStore(this.storeName);

      const request = objectStore.openCursor();

      request.onerror = () => {
        console.error("Failed to clear expired cache:", request.error);
        reject(request.error);
      };

      request.onsuccess = (event) => {
        const cursor = (event.target as IDBRequest).result;

        if (!cursor) {
          resolve(deletedCount);
          return;
        }

        const cacheItem = cursor.value as CacheItem;

        if (cacheItem.metadata.expiresAt < now) {
          cursor.delete();
          deletedCount++;
          cursor.continue();
        } else {
          cursor.continue();
        }
      };
    });
  }

  async getCacheStats(): Promise<{
    totalSize: number;
    itemCount: number;
    byType: Record<string, number>;
  }> {
    if (!this.db) {
      await this.init();
    }

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([this.storeName], "readonly");
      const objectStore = transaction.objectStore(this.storeName);

      const request = objectStore.getAll();

      request.onerror = () => {
        console.error("Failed to get cache stats:", request.error);
        reject(request.error);
      };

      request.onsuccess = (event) => {
        const cacheItems = (event.target as IDBRequest).result as CacheItem[];
        const totalSize = cacheItems.reduce((sum, item) => sum + item.metadata.size, 0);
        const byType: Record<string, number> = {};

        for (const item of cacheItems) {
          byType[item.type] = (byType[item.type] || 0) + 1;
        }

        resolve({
          totalSize,
          itemCount: cacheItems.length,
          byType,
        });
      };
    });
  }

  async clearAllCache(): Promise<void> {
    if (!this.db) {
      await this.init();
    }

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([this.storeName], "readwrite");
      const objectStore = transaction.objectStore(this.storeName);

      const request = objectStore.clear();

      request.onerror = () => {
        console.error("Failed to clear all cache:", request.error);
        reject(request.error);
      };

      request.onsuccess = () => {
        console.log("All cache cleared");
        resolve();
      };
    });
  }

  private async checkCacheSize(newItemSize: number): Promise<void> {
    const stats = await this.getCacheStats();
    
    if (stats.totalSize + newItemSize > this.maxCacheSize) {
      console.warn("Cache size limit reached, clearing expired items first");
      await this.clearExpiredCache();
      
      const newStats = await this.getCacheStats();
      if (newStats.totalSize + newItemSize > this.maxCacheSize) {
        console.warn("Still over limit, clearing oldest items");
        await this.clearOldestItems(newItemSize);
      }
    }
  }

  private async clearOldestItems(targetSize: number): Promise<void> {
    const itemsToDelete = await this.getOldestItems(targetSize);
    
    for (const item of itemsToDelete) {
      await this.deleteCachedMedia(item.id);
    }
  }

  private async getOldestItems(targetSize: number): Promise<CacheItem[]> {
    const items: CacheItem[] = [];

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([this.storeName], "readonly");
      const objectStore = transaction.objectStore(this.storeName);

      const request = objectStore.openCursor(null, "prev"); // 反向遍历，从最旧的开始

      request.onerror = () => {
        console.error("Failed to get oldest items:", request.error);
        reject(request.error);
      };

      request.onsuccess = (event) => {
        const cursor = (event.target as IDBRequest).result;

        if (!cursor || items.reduce((sum, item) => sum + item.metadata.size, 0) >= targetSize) {
          resolve(items);
          return;
        }

        const cacheItem = cursor.value as CacheItem;
        items.push(cacheItem);
        cursor.continue();
      };
    });
  }

  private generateId(url: string, type: string): string {
    // 使用 URL 和类型生成唯一 ID
    const encoder = new TextEncoder();
    const data = encoder.encode(`${type}:${url}`);
    const hashArray = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)));
    const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    return `${type}_${hashHex.substring(0, 16)}`;
  }

  async preloadMedia(url: string, type: "video" | "audio"): Promise<void> {
    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.blob();
      await this.cacheMedia(url, type, data);
      console.log(`Media preloaded: ${type} - ${data.size} bytes`);
    } catch (error) {
      console.error("Failed to preload media:", error);
    }
  }

  async getOfflineAvailableMedia(): Promise<CacheItem[]> {
    if (!this.db) {
      await this.init();
    }

    const now = Date.now();

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([this.storeName], "readonly");
      const objectStore = transaction.objectStore(this.storeName);

      const request = objectStore.getAll();

      request.onerror = () => {
        console.error("Failed to get offline media:", request.error);
        reject(request.error);
      };

      request.onsuccess = (event) => {
        const cacheItems = (event.target as IDBRequest).result as CacheItem[];
        
        // 过滤出未过期的缓存
        const availableItems = cacheItems.filter(
          item => item.metadata.expiresAt >= now
        );
        
        // 按最后访问时间排序
        availableItems.sort(
          (a, b) => b.metadata.lastAccessedAt - a.metadata.lastAccessedAt
        );
        
        resolve(availableItems);
      };
    });
  }
}

// 导出单例
const mediaCacheManager = new MediaCacheManager();

export { mediaCacheManager, MediaCacheManager };
export type { CacheItem };