export const WS_RECONNECT_INITIAL_DELAY_MS = 1000;
export const WS_RECONNECT_MAX_DELAY_MS = 8000;
export const WS_RECONNECT_RECOVERY_SLA_MS = 10000;

export function nextReconnectDelayMs(attempt: number): number {
  const safeAttempt = Math.max(0, Math.floor(attempt));
  return Math.min(
    WS_RECONNECT_INITIAL_DELAY_MS * 2 ** safeAttempt,
    WS_RECONNECT_MAX_DELAY_MS,
  );
}

