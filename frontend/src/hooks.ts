import { useEffect, useRef, useState } from "react";
import { useStore } from "./store";
import type { BroadcastItem } from "./types";

/** Re-render every `ms` milliseconds (for overlays that expire). */
export function useNow(ms = 500): number {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(performance.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

/** Poll an async function every `ms` while `enabled`. */
export function usePoll<T>(fn: () => Promise<T>, ms: number, deps: unknown[], enabled = true): T | null {
  const [value, setValue] = useState<T | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const run = async () => {
      try {
        const v = await fn();
        if (alive) setValue(v);
      } catch {
        /* transient */
      }
    };
    run();
    const id = window.setInterval(run, ms);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, ms]);
  return value;
}

const VOICE_LANG: Record<string, string> = { en: "en-GB", es: "es-ES", ar: "ar-SA", ur: "ur-PK", fr: "fr-FR", pt: "pt-BR", hi: "hi-IN" };

/** Audio-description mode: speak the audio rendition of verified items on the stage (and the fan's squad). */
export function useAudioDescription() {
  const fan = useStore((s) => s.fan);
  const items = useStore((s) => s.items);
  const spoken = useRef(new Set<string>());
  useEffect(() => {
    if (fan?.mode !== "audio" || !("speechSynthesis" in window)) return;
    const { stage } = useStore.getState();
    const fresh = Object.values(items)
      .filter((it: BroadcastItem) => !spoken.current.has(it.moment_id))
      .filter((it) => it.match_id === stage || it.importance >= 90);
    for (const it of fresh.slice(-2)) {
      spoken.current.add(it.moment_id);
      const r = it.renditions[fan.language] ?? it.renditions.en;
      if (!r) continue;
      const u = new SpeechSynthesisUtterance(r.audio);
      u.lang = VOICE_LANG[fan.language] ?? "en-GB";
      u.rate = 1.02;
      window.speechSynthesis.speak(u);
    }
  }, [items, fan]);
}
