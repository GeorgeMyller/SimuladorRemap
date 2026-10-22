/** Controles de som: "Ativar som" (1.º gesto), mudo (`M`) e volume 0–100 % (RF-19; D-23). */
import type { AudioState } from "./audio/AudioEngine";
import { MSG } from "./messages";

export interface AudioControlsProps {
  state: AudioState;
  muted: boolean;
  /** 0..1 */
  volume: number;
  onEnable: () => void;
  onToggleMute: () => void;
  onVolume: (volume: number) => void;
}

export function AudioControls({ state, muted, volume, onEnable, onToggleMute, onVolume }: AudioControlsProps) {
  if (state === "unavailable" || state === "closed") {
    return <span className="text-xs text-zinc-400">Áudio indisponível (alertas em texto ativos)</span>;
  }
  return (
    <div className="flex items-center gap-2 text-sm" role="group" aria-label="Som do motor">
      {state === "suspended" ? (
        <button
          type="button"
          onClick={onEnable}
          className="rounded border border-zinc-500 px-2 py-0.5 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400"
        >
          {MSG.enableSound}
        </button>
      ) : (
        <button
          type="button"
          onClick={onToggleMute}
          aria-pressed={muted}
          aria-keyshortcuts="M"
          className="rounded border border-zinc-500 px-2 py-0.5 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400"
        >
          {muted ? "Som desligado" : "Som ligado"}
        </button>
      )}
      <label className="flex items-center gap-1">
        <span className="sr-only">Volume</span>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={Math.round(volume * 100)}
          onChange={(e) => onVolume(Number(e.target.value) / 100)}
          aria-label="Volume"
          aria-valuetext={`${Math.round(volume * 100)} %`}
          className="w-24 accent-amber-400"
        />
        <span className="w-9 text-right font-mono text-xs">{Math.round(volume * 100)} %</span>
      </label>
    </div>
  );
}
