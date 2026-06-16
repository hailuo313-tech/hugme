"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { OperatorRingPlayer } from "@/lib/operatorRing";

const STORAGE_KEY = "eris_pending_review_sound";

type UsePendingReviewRingOptions = {
  enabled?: boolean;
};

export function usePendingReviewRing(
  pendingIds: string[],
  options?: UsePendingReviewRingOptions,
) {
  const [soundEnabled, setSoundEnabled] = useState(() => {
    if (typeof window === "undefined") return true;
    return window.localStorage.getItem(STORAGE_KEY) !== "0";
  });
  const [needsUnlock, setNeedsUnlock] = useState(false);

  const playerRef = useRef<OperatorRingPlayer | null>(null);
  const knownIdsRef = useRef<Set<string>>(new Set());
  const bootstrappedRef = useRef(false);

  const pendingKey = useMemo(() => pendingIds.join("|"), [pendingIds]);
  const featureEnabled = options?.enabled !== false;

  const refreshUnlockState = useCallback(() => {
    setNeedsUnlock(!playerRef.current?.isUnlocked);
  }, []);

  const unlockSound = useCallback(async () => {
    if (!playerRef.current) {
      playerRef.current = new OperatorRingPlayer();
    }
    await playerRef.current.unlock();
    refreshUnlockState();
  }, [refreshUnlockState]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, soundEnabled ? "1" : "0");
  }, [soundEnabled]);

  useEffect(() => {
    playerRef.current = new OperatorRingPlayer();
    refreshUnlockState();
    return () => {
      playerRef.current?.destroy();
      playerRef.current = null;
    };
  }, [refreshUnlockState]);

  useEffect(() => {
    const unlockOnGesture = () => {
      void unlockSound();
    };
    window.addEventListener("pointerdown", unlockOnGesture);
    window.addEventListener("keydown", unlockOnGesture);
    return () => {
      window.removeEventListener("pointerdown", unlockOnGesture);
      window.removeEventListener("keydown", unlockOnGesture);
    };
  }, [unlockSound]);

  useEffect(() => {
    const player = playerRef.current;
    if (!player || !featureEnabled || !soundEnabled) {
      player?.stop();
      return;
    }

    if (document.visibilityState !== "visible") {
      player.stop();
      return;
    }

    const ids = pendingKey ? pendingKey.split("|") : [];

    if (!bootstrappedRef.current) {
      bootstrappedRef.current = true;
      for (const id of ids) knownIdsRef.current.add(id);
    } else {
      knownIdsRef.current = new Set(ids);
    }

    if (ids.length === 0) {
      player.stop();
      return;
    }

    void unlockSound().then(() => player.start());
  }, [featureEnabled, pendingKey, soundEnabled, unlockSound]);

  useEffect(() => {
    const onVisibilityChange = () => {
      const player = playerRef.current;
      if (!player || !featureEnabled || !soundEnabled) return;

      if (document.visibilityState === "visible") {
        const count = pendingKey ? pendingKey.split("|").length : 0;
        if (count > 0) {
          void unlockSound().then(() => player.start());
        }
      } else {
        player.stop();
      }
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [featureEnabled, pendingKey, soundEnabled, unlockSound]);

  const toggleSound = useCallback((next?: boolean) => {
    setSoundEnabled((prev) => {
      const value = next ?? !prev;
      if (!value) playerRef.current?.stop();
      return value;
    });
  }, []);

  const testRing = useCallback(() => {
    const player = playerRef.current;
    if (!player) return;
    void unlockSound().then(() => {
      player.stop();
      player.start();
    });
  }, [unlockSound]);

  return {
    soundEnabled,
    setSoundEnabled: toggleSound,
    needsUnlock,
    unlockSound,
    testRing,
  };
}
