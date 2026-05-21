"use client";

import { useRef, useEffect, useState } from "react";
import { mediaCacheManager } from "@/lib/mediaCache";
import { mediaHistoryManager } from "@/lib/mediaHistory";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";

interface VideoPlayerProps {
  src: string;
  type: "video" | "audio";
  poster?: string;
  autoPlay?: boolean;
  controls?: boolean;
  loop?: boolean;
  muted?: boolean;
  className?: string;
  onEnded?: () => void;
  onError?: (error: Error) => void;
  onProgress?: (currentTime: number, duration: number) => void;
  onBufferStart?: () => void;
  onBufferEnd?: () => void;
  enableCache?: boolean; // 是否启用缓存
  preloadStrategy?: "auto" | "metadata" | "none";
  enableHistory?: boolean; // 是否启用历史记录
  title?: string; // 媒体标题（用于历史记录）
}

export function VideoPlayer({
  src,
  type,
  poster,
  autoPlay = false,
  controls = true,
  loop = false,
  muted = false,
  className = "",
  onEnded,
  onError,
  onProgress,
  onBufferStart,
  onBufferEnd,
  enableCache = true,
  preloadStrategy = "metadata",
  enableHistory = true,
  title,
}: VideoPlayerProps) {
  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isBuffering, setIsBuffering] = useState(false);
  const [volume, setVolume] = useState(1);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [currentSrc, setCurrentSrc] = useState<string>(src);
  const [isUsingCache, setIsUsingCache] = useState(false);
  const [cacheStatus, setCacheStatus] = useState<"none" | "loading" | "loaded" | "error">("none");
  const [hasRestoredPosition, setHasRestoredPosition] = useState(false);
  
  const networkStatus = useNetworkStatus();

  const cacheCurrentMedia = async () => {
    try {
      const response = await fetch(src);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.blob();
      await mediaCacheManager.cacheMedia(src, type, data);
      setCacheStatus("loaded");
      console.log(`Media cached: ${type} - ${data.size} bytes`);
    } catch (error) {
      console.error("Failed to cache media:", error);
      setCacheStatus("error");
    }
  };

  // 初始化历史记录管理器
  useEffect(() => {
    const initHistory = async () => {
      if (!enableHistory) return;
      
      try {
        await mediaHistoryManager.init();
        
        // 检查是否有历史记录
        const historyItem = await mediaHistoryManager.getHistoryItem(src, type);
        if (historyItem && historyItem.lastPosition > 0) {
          console.log(`Found history for ${type}, last position: ${historyItem.lastPosition}s`);
          // 将在媒体加载后恢复播放位置
        }
      } catch (error) {
        console.error("History initialization failed:", error);
      }
    };
    
    initHistory();
  }, [src, type, enableHistory]);

  // 初始化缓存管理器并尝试加载缓存
  useEffect(() => {
    const initCache = async () => {
      if (!enableCache) return;
      
      try {
        await mediaCacheManager.init();
        setCacheStatus("loading");
        
        // 检查缓存中是否有该媒体
        const cachedData = await mediaCacheManager.getCachedMedia(src, type);
        
        if (cachedData) {
          const blobUrl = URL.createObjectURL(cachedData);
          setCurrentSrc(blobUrl);
          setIsUsingCache(true);
          setCacheStatus("loaded");
          console.log(`Using cached ${type}: ${cachedData.size} bytes`);
        } else {
          // 缓存中没有，使用原始 URL
          setCurrentSrc(src);
          setIsUsingCache(false);
          setCacheStatus("none");
          
          // 如果是弱网环境，预加载媒体
          if (networkStatus.isSlowConnection && preloadStrategy !== "none") {
            console.log("Slow network detected, preloading media...");
            mediaCacheManager.preloadMedia(src, type);
          }
        }
      } catch (error) {
        console.error("Cache initialization failed:", error);
        setCacheStatus("error");
        setCurrentSrc(src);
        setIsUsingCache(false);
      }
    };
    
    initCache();
  }, [src, type, enableCache, networkStatus.isSlowConnection, preloadStrategy]);

  useEffect(() => {
    const media = mediaRef.current;
    if (!media) return;

    const handleTimeUpdate = async () => {
      setCurrentTime(media.currentTime);
      if (onProgress) {
        onProgress(media.currentTime, media.duration);
      }
      
      // 定期更新历史记录中的播放位置（每 5 秒更新一次）
      if (enableHistory && isPlaying && Math.floor(media.currentTime) % 5 === 0) {
        try {
          await mediaHistoryManager.updatePlaybackPosition(src, type, media.currentTime);
        } catch (error) {
          console.error("Failed to update playback position:", error);
        }
      }
    };

    const handleLoadedMetadata = async () => {
      setDuration(media.duration);
      
      // 恢复播放位置
      if (enableHistory && !hasRestoredPosition) {
        const historyItem = await mediaHistoryManager.getHistoryItem(src, type);
        if (historyItem && historyItem.lastPosition > 0) {
          media.currentTime = historyItem.lastPosition;
          setHasRestoredPosition(true);
          console.log(`Restored position to ${historyItem.lastPosition}s`);
        }
      }
    };

    const handlePlay = async () => {
      setIsPlaying(true);
      
      // 添加到历史记录
      if (enableHistory) {
        try {
          await mediaHistoryManager.addToHistory(src, type, {
            title,
            duration: media.duration,
            lastPosition: media.currentTime,
            cached: isUsingCache,
          });
        } catch (error) {
          console.error("Failed to add to history:", error);
        }
      }
    };

    const handlePause = () => {
      setIsPlaying(false);
    };

    const handleEnded = () => {
      setIsPlaying(false);
      if (onEnded) onEnded();
    };

    const handleWaiting = () => {
      setIsBuffering(true);
      if (onBufferStart) onBufferStart();
    };

    const handleCanPlay = () => {
      setIsBuffering(false);
      if (onBufferEnd) onBufferEnd();
      
      // 如果不是使用缓存且启用缓存，则缓存当前媒体
      if (!isUsingCache && enableCache && cacheStatus !== "loaded") {
        cacheCurrentMedia();
      }
    };

    const handleError = (e: Event) => {
      const error = media.error;
      if (error) {
        const mediaError = new Error(`Media error: ${error.message} (code: ${error.code})`);
        if (onError) onError(mediaError);
      }
    };

    media.addEventListener("timeupdate", handleTimeUpdate);
    media.addEventListener("loadedmetadata", handleLoadedMetadata);
    media.addEventListener("play", handlePlay);
    media.addEventListener("pause", handlePause);
    media.addEventListener("ended", handleEnded);
    media.addEventListener("waiting", handleWaiting);
    media.addEventListener("canplay", handleCanPlay);
    media.addEventListener("error", handleError);

    return () => {
      media.removeEventListener("timeupdate", handleTimeUpdate);
      media.removeEventListener("loadedmetadata", handleLoadedMetadata);
      media.removeEventListener("play", handlePlay);
      media.removeEventListener("pause", handlePause);
      media.removeEventListener("ended", handleEnded);
      media.removeEventListener("waiting", handleWaiting);
      media.removeEventListener("canplay", handleCanPlay);
      media.removeEventListener("error", handleError);
    };
  }, [currentSrc, onEnded, onError, onProgress, onBufferStart, onBufferEnd, isUsingCache, enableCache, cacheStatus, src, type, enableHistory, title, isPlaying, hasRestoredPosition]);

  const togglePlay = () => {
    const media = mediaRef.current;
    if (!media) return;

    if (media.paused) {
      media.play().catch((error) => {
        console.error("Failed to play:", error);
      });
    } else {
      media.pause();
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const media = mediaRef.current;
    if (!media) return;

    const time = parseFloat(e.target.value);
    media.currentTime = time;
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const media = mediaRef.current;
    if (!media) return;

    const newVolume = parseFloat(e.target.value);
    media.volume = newVolume;
    setVolume(newVolume);
  };

  const handlePlaybackRateChange = (newRate: number) => {
    const media = mediaRef.current;
    if (!media) return;

    media.playbackRate = newRate;
    setPlaybackRate(newRate);
  };

  const formatTime = (time: number) => {
    if (isNaN(time)) return "0:00";
    
    const hours = Math.floor(time / 3600);
    const minutes = Math.floor((time % 3600) / 60);
    const seconds = Math.floor(time % 60);
    
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
    }
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  };

  if (type === "audio") {
    return (
      <div className={`media-player audio-player ${className}`}>
        <audio
          ref={mediaRef as React.RefObject<HTMLAudioElement>}
          src={currentSrc}
          autoPlay={autoPlay}
          controls={controls}
          loop={loop}
          muted={muted}
        />
        {enableCache && (
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
            <span>缓存状态:</span>
            <span className={`
              ${cacheStatus === "loaded" ? "text-green-400" : 
                cacheStatus === "loading" ? "text-amber-400" : 
                cacheStatus === "error" ? "text-red-400" : "text-slate-400"}
            `}>
              {cacheStatus === "loaded" ? "已缓存" : 
               cacheStatus === "loading" ? "缓存中..." : 
               cacheStatus === "error" ? "缓存失败" : "未缓存"}
            </span>
            {isUsingCache && <span className="text-green-400">● 使用缓存</span>}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`media-player video-player ${className}`}>
      <video
        ref={mediaRef as React.RefObject<HTMLVideoElement>}
        src={currentSrc}
        poster={poster}
        autoPlay={autoPlay}
        controls={controls}
        loop={loop}
        muted={muted}
        className="w-full rounded-lg bg-black"
      />
      
      {/* 自定义控制栏 */}
      <div className="mt-4 space-y-3">
        {/* 进度条 */}
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-400 w-12">{formatTime(currentTime)}</span>
          <input
            type="range"
            min="0"
            max={duration}
            value={currentTime}
            onChange={handleSeek}
            className="flex-1 h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer"
          />
          <span className="text-sm text-slate-400 w-12">{formatTime(duration)}</span>
        </div>

        {/* 控制按钮 */}
        <div className="flex items-center gap-3">
          <button
            onClick={togglePlay}
            className="bg-violet-600 hover:bg-violet-500 text-white px-4 py-2 rounded-lg transition"
          >
            {isPlaying ? "暂停" : "播放"}
          </button>

          {/* 音量控制 */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-400">音量</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={volume}
              onChange={handleVolumeChange}
              className="w-24 h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer"
            />
          </div>

          {/* 播放速度 */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-400">速度</span>
            <select
              value={playbackRate}
              onChange={(e) => handlePlaybackRateChange(parseFloat(e.target.value))}
              className="bg-slate-800 border border-slate-700 text-white rounded px-2 py-1"
            >
              <option value={0.5}>0.5x</option>
              <option value={0.75}>0.75x</option>
              <option value={1}>1x</option>
              <option value={1.25}>1.25x</option>
              <option value={1.5}>1.5x</option>
              <option value={2}>2x</option>
            </select>
          </div>

          {/* 缓冲状态 */}
          {isBuffering && (
            <div className="flex items-center gap-2 text-sm text-amber-400">
              <span className="animate-pulse">●</span>
              <span>缓冲中...</span>
            </div>
          )}

          {/* 缓存状态 */}
          {enableCache && (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <span>缓存:</span>
              <span className={`
                ${cacheStatus === "loaded" ? "text-green-400" : 
                  cacheStatus === "loading" ? "text-amber-400" : 
                  cacheStatus === "error" ? "text-red-400" : "text-slate-400"}
              `}>
                {cacheStatus === "loaded" ? "已缓存" : 
                 cacheStatus === "loading" ? "缓存中..." : 
                 cacheStatus === "error" ? "缓存失败" : "未缓存"}
              </span>
              {isUsingCache && <span className="text-green-400">● 离线</span>}
              {!networkStatus.isOnline && <span className="text-red-400">● 离线</span>}
              {networkStatus.isSlowConnection && networkStatus.isOnline && <span className="text-amber-400">● 弱网</span>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}