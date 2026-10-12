/** Browser ringtone for operator pending-review alerts (Web Audio API). */

const RING_TONE_HZ = [440, 480] as const;
const RING_WARBLE_HZ = 25;
const BURST_SECONDS = 0.34;
const BURST_GAP_MS = 200;
const CYCLE_PAUSE_MS = 2800;

export class OperatorRingPlayer {
  private audioContext: AudioContext | null = null;
  private loopTimer: number | null = null;
  private ringTimers: number[] = [];
  private ringing = false;
  private unlocked = false;
  private activeNodes: AudioScheduledSourceNode[] = [];

  private ensureContext(): AudioContext | null {
    if (typeof window === "undefined") return null;
    if (!this.audioContext) {
      const Ctx =
        window.AudioContext ||
        (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctx) return null;
      this.audioContext = new Ctx();
    }
    return this.audioContext;
  }

  async unlock(): Promise<void> {
    const ctx = this.ensureContext();
    if (!ctx) return;
    if (ctx.state === "suspended") {
      await ctx.resume();
    }
    this.unlocked = true;
  }

  get isUnlocked(): boolean {
    return this.unlocked;
  }

  private trackNode(node: AudioScheduledSourceNode): void {
    this.activeNodes.push(node);
    node.onended = () => {
      this.activeNodes = this.activeNodes.filter((item) => item !== node);
    };
  }

  private clearActiveNodes(): void {
    for (const node of this.activeNodes) {
      try {
        node.stop();
      } catch {
        /* already stopped */
      }
    }
    this.activeNodes = [];
  }

  private clearRingTimers(): void {
    for (const timer of this.ringTimers) {
      window.clearTimeout(timer);
    }
    this.ringTimers = [];
  }

  private playTelephoneBurst(durationSeconds = BURST_SECONDS): void {
    const ctx = this.audioContext;
    if (!ctx || !this.unlocked || ctx.state !== "running") return;

    const now = ctx.currentTime;
    const end = now + durationSeconds;

    const compressor = ctx.createDynamicsCompressor();
    compressor.threshold.setValueAtTime(-3, now);
    compressor.knee.setValueAtTime(4, now);
    compressor.ratio.setValueAtTime(10, now);
    compressor.attack.setValueAtTime(0.001, now);
    compressor.release.setValueAtTime(0.08, now);
    compressor.connect(ctx.destination);

    const master = ctx.createGain();
    master.gain.setValueAtTime(1.45, now);
    master.connect(compressor);

    const output = ctx.createGain();
    output.gain.setValueAtTime(0.78, now);
    output.connect(master);

    const warble = ctx.createOscillator();
    const warbleDepth = ctx.createGain();
    warble.type = "sine";
    warble.frequency.setValueAtTime(RING_WARBLE_HZ, now);
    warbleDepth.gain.setValueAtTime(0.52, now);
    warble.connect(warbleDepth);
    warbleDepth.connect(output.gain);
    warble.start(now);
    warble.stop(end);
    this.trackNode(warble);

    const envelope = ctx.createGain();
    envelope.gain.setValueAtTime(0.001, now);
    envelope.gain.exponentialRampToValueAtTime(1, now + 0.018);
    envelope.gain.setValueAtTime(1, now + durationSeconds * 0.72);
    envelope.gain.exponentialRampToValueAtTime(0.001, end);
    envelope.connect(output);

    for (const frequency of RING_TONE_HZ) {
      const tone = ctx.createOscillator();
      const toneGain = ctx.createGain();
      tone.type = "sine";
      tone.frequency.setValueAtTime(frequency, now);
      toneGain.gain.setValueAtTime(0.92, now);
      tone.connect(toneGain);
      toneGain.connect(envelope);

      const harmonic = ctx.createOscillator();
      const harmonicGain = ctx.createGain();
      harmonic.type = "triangle";
      harmonic.frequency.setValueAtTime(frequency * 2, now);
      harmonicGain.gain.setValueAtTime(0.18, now);
      harmonic.connect(harmonicGain);
      harmonicGain.connect(envelope);

      tone.start(now);
      tone.stop(end);
      harmonic.start(now);
      harmonic.stop(end);
      this.trackNode(tone);
      this.trackNode(harmonic);
    }
  }

  private playDoubleRing(): void {
    const firstBurstDelay = 0;
    const secondBurstDelay = Math.round(BURST_SECONDS * 1000 + BURST_GAP_MS);

    this.ringTimers.push(
      window.setTimeout(() => {
        if (!this.ringing) return;
        this.playTelephoneBurst(BURST_SECONDS);
      }, firstBurstDelay),
    );
    this.ringTimers.push(
      window.setTimeout(() => {
        if (!this.ringing) return;
        this.playTelephoneBurst(BURST_SECONDS);
      }, secondBurstDelay),
    );
  }

  start(): void {
    if (this.ringing) return;
    this.ringing = true;

    const cycleMs =
      Math.round(BURST_SECONDS * 1000) +
      BURST_GAP_MS +
      Math.round(BURST_SECONDS * 1000) +
      CYCLE_PAUSE_MS;

    const cycle = () => {
      if (!this.ringing) return;
      this.clearRingTimers();
      this.playDoubleRing();
      this.loopTimer = window.setTimeout(cycle, cycleMs);
    };

    cycle();
  }

  stop(): void {
    this.ringing = false;
    if (this.loopTimer !== null) {
      window.clearTimeout(this.loopTimer);
      this.loopTimer = null;
    }
    this.clearRingTimers();
    this.clearActiveNodes();
  }

  destroy(): void {
    this.stop();
    void this.audioContext?.close();
    this.audioContext = null;
    this.unlocked = false;
  }
}
