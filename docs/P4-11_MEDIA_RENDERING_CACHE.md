# P4-11: App 音视频渲染与本地缓存

## 任务概述

实现 App 端音视频播放器组件，支持本地缓存机制，确保在弱网环境下可以播放历史内容。

## 实现内容

### 1. 音视频播放器组件 (`admin/components/media/VideoPlayer.tsx`)

**核心功能：**
- 支持视频和音频播放
- 自定义控制栏（进度条、音量、播放速度）
- 播放状态监控（播放中、缓冲、错误）
- 集成本地缓存机制
- 集成播放历史记录
- 网络状态感知
- 弱网环境适配

**主要特性：**
- 自动缓存已播放的媒体内容
- 弱网环境下预加载媒体
- 支持从上次播放位置继续
- 实时显示缓存状态和网络状态
- 支持禁用缓存和历史记录

### 2. 本地缓存管理器 (`admin/lib/mediaCache.ts`)

**技术实现：**
- 使用 IndexedDB 存储媒体文件
- 支持视频和音频缓存
- 自动过期清理（默认 7 天）
- 缓存大小限制（默认 500MB）
- LRU 淘汰策略

**核心接口：**
```typescript
class MediaCacheManager {
  // 缓存媒体文件
  cacheMedia(url, type, data, options?): Promise<string>
  
  // 获取缓存
  getCachedMedia(url, type): Promise<Blob | null>
  
  // 删除缓存
  deleteCachedMedia(id): Promise<void>
  
  // 清理过期缓存
  clearExpiredCache(): Promise<number>
  
  // 获取缓存统计
  getCacheStats(): Promise<CacheStats>
  
  // 预加载媒体
  preloadMedia(url, type): Promise<void>
  
  // 获取离线可用媒体
  getOfflineAvailableMedia(): Promise<CacheItem[]>
}
```

### 3. 网络状态监控 (`admin/hooks/useNetworkStatus.ts`)

**监控指标：**
- 在线/离线状态
- 网络类型（2g/3g/4g/wifi）
- 下行速度
- 往返延迟（RTT）
- 节省数据模式
- 弱网检测

**弱网判断标准：**
- effectiveType 为 "slow-2g" 或 "2g"
- downlink < 0.5 Mbps
- rtt > 300ms

### 4. 播放历史管理器 (`admin/lib/mediaHistory.ts`)

**功能特性：**
- 记录播放历史（最多 50 条）
- 保存播放位置
- 统计播放次数
- 支持按类型、缓存状态过滤
- 最近播放和最多播放排序

**核心接口：**
```typescript
class MediaHistoryManager {
  // 添加到历史
  addToHistory(url, type, options?): Promise<void>
  
  // 更新播放位置
  updatePlaybackPosition(url, type, position): Promise<void>
  
  // 获取历史
  getHistory(filters?): Promise<HistoryItem[]>
  
  // 获取离线可用历史
  getOfflineAvailableHistory(): Promise<HistoryItem[]>
  
  // 清除历史
  clearHistory(): Promise<void>
  
  // 获取统计
  getHistoryStats(): Promise<HistoryStats>
}
```

### 5. 音视频管理界面 (`admin/app/media/page.tsx`)

**界面功能：**
- 查看本地缓存列表
- 查看播放历史
- 缓存统计信息
- 历史统计信息
- 清除缓存（过期/全部）
- 清除历史记录
- 直接播放缓存内容
- 继续播放历史内容

**页面布局：**
- 网络状态显示
- 播放器区域
- 标签页切换（缓存/历史）
- 统计卡片
- 操作按钮
- 列表展示

## 使用示例

### 基础使用

```tsx
import { VideoPlayer } from "@/components/media/VideoPlayer";

function MyComponent() {
  return (
    <VideoPlayer
      src="https://example.com/video.mp4"
      type="video"
      title="示例视频"
      enableCache={true}
      enableHistory={true}
    />
  );
}
```

### 高级配置

```tsx
<VideoPlayer
  src="https://example.com/audio.mp3"
  type="audio"
  title="示例音频"
  poster="https://example.com/poster.jpg"
  autoPlay={false}
  controls={true}
  loop={false}
  muted={false}
  enableCache={true}
  enableHistory={true}
  preloadStrategy="auto"
  onEnded={() => console.log("播放结束")}
  onError={(error) => console.error("播放错误", error)}
  onProgress={(currentTime, duration) => console.log(`进度: ${currentTime}/${duration}`)}
/>
```

## 技术架构

### 数据流

```
用户播放媒体
    ↓
检查网络状态
    ↓
检查本地缓存
    ↓
┌─────────┴─────────┐
│                   │
有缓存            无缓存
│                   │
使用缓存         从网络加载
│                   │
播放              缓存到本地
│                   │
记录历史          记录历史
```

### 存储架构

```
IndexedDB (ERISMediaCache)
├── media store
│   ├── id (key)
│   ├── url
│   ├── type
│   ├── data (Blob)
│   └── metadata
│       ├── size
│       ├── mimeType
│       ├── createdAt
│       ├── lastAccessedAt
│       └── expiresAt

LocalStorage (eris_media_history)
├── HistoryItem[]
│   ├── id
│   ├── url
│   ├── type
│   ├── title
│   ├── playedAt
│   ├── duration
│   ├── lastPosition
│   ├── playCount
│   └── metadata
```

## 性能优化

1. **缓存策略**
   - 首次播放后自动缓存
   - 弱网环境主动预加载
   - LRU 淘汰策略
   - 定期清理过期缓存

2. **网络优化**
   - 离线优先策略
   - 弱网降级处理
   - 断点续播支持

3. **存储优化**
   - 缓存大小限制
   - 自动压缩清理
   - 按需加载

## 浏览器兼容性

- IndexedDB: 所有现代浏览器
- Network Information API: Chrome 61+, Firefox 31+
- 降级处理: 不支持的网络特性不影响基本功能

## 配置参数

### 缓存配置

```typescript
// 在 mediaCache.ts 中修改
private maxCacheSize = 500 * 1024 * 1024; // 500MB
private defaultExpiration = 7 * 24 * 60 * 60 * 1000; // 7天
```

### 历史配置

```typescript
// 在 mediaHistory.ts 中修改
private maxHistoryItems = 50; // 最多 50 条历史
```

## 未来扩展

1. **后台下载**
   - 支持后台预下载
   - 下载队列管理
   - 断点续传

2. **智能缓存**
   - 基于用户行为的缓存预测
   - 热门内容预加载
   - 个性化推荐

3. **质量自适应**
   - 根据网络状况自动切换清晰度
   - 多码率支持
   - 自适应码率流（HLS/DASH）

4. **社交功能**
   - 分享播放历史
   - 评论与弹幕
   - 协作播放列表

## 注意事项

1. **存储空间**
   - 用户设备存储空间有限
   - 需要合理设置缓存大小
   - 提供手动清理功能

2. **隐私保护**
   - 播放历史包含用户行为数据
   - 需要提供清除历史功能
   - 遵守隐私保护法规

3. **版权保护**
   - 缓存内容可能有版权限制
   - 需要设置合理的过期时间
   - 避免永久缓存版权内容

## 相关文件

- `admin/components/media/VideoPlayer.tsx` - 播放器组件
- `admin/lib/mediaCache.ts` - 缓存管理器
- `admin/lib/mediaHistory.ts` - 历史管理器
- `admin/hooks/useNetworkStatus.ts` - 网络状态钩子
- `admin/app/media/page.tsx` - 管理界面

## 测试建议

1. **功能测试**
   - 基本播放功能
   - 缓存功能
   - 历史记录功能
   - 网络状态切换

2. **性能测试**
   - 大文件缓存
   - 长时间播放
   - 频繁切换

3. **兼容性测试**
   - 不同浏览器
   - 不同网络环境
   - 不同设备

4. **边界测试**
   - 存储空间不足
   - 网络异常
   - 并发操作

## 完成状态

- [x] 音视频播放器组件
- [x] 本地缓存机制
- [x] 网络状态监控
- [x] 播放历史管理
- [x] 音视频管理界面
- [x] 文档更新