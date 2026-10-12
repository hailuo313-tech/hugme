"use client";

type OperatorRingControlsProps = {
  soundEnabled: boolean;
  onToggleSound: () => void;
  needsUnlock: boolean;
  onUnlockSound: () => void;
  onTestRing: () => void;
  description?: string;
};

export default function OperatorRingControls({
  soundEnabled,
  onToggleSound,
  needsUnlock,
  onUnlockSound,
  onTestRing,
  description,
}: OperatorRingControlsProps) {
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-100">待人工铃声提醒</div>
          {description ? (
            <p className="mt-1 text-xs text-slate-400">{description}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onToggleSound}
            className={`rounded-md border px-3 py-1.5 text-xs ${
              soundEnabled
                ? "border-amber-600 bg-amber-950 text-amber-100"
                : "border-slate-700 bg-slate-950 text-slate-400"
            }`}
          >
            {soundEnabled ? "铃声提醒：开" : "铃声提醒：关"}
          </button>
          <button
            type="button"
            onClick={onTestRing}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
          >
            测试铃声
          </button>
        </div>
      </div>
      {needsUnlock ? (
        <p className="mt-2 text-xs text-amber-300">
          浏览器需先点击页面任意位置后才能播放铃声。
          <button type="button" className="ml-2 underline" onClick={onUnlockSound}>
            启用声音
          </button>
        </p>
      ) : null}
    </div>
  );
}
