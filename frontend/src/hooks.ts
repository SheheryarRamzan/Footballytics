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

/**
 * Audio-description mode: voice the audio rendition of new verified items on the stage (or any
 * very important moment). Uses the server's multilingual voice (gpt-4o-mini-tts) and falls back to
 * the browser's speech synthesis. Items that existed before the mode was switched on are skipped.
 */
export function useAudioDescription() {
  const fan = useStore((s) => s.fan);
  const items = useStore((s) => s.items);
  const spoken = useRef(new Set<string>());
  const queue = useRef<BroadcastItem[]>([]);
  const playing = useRef(false);
  const enabled = fan?.mode === "audio";

  // When the mode is switched on, everything already received counts as heard.
  useEffect(() => {
    if (enabled) for (const id of Object.keys(useStore.getState().items)) spoken.current.add(id);
    else {
      queue.current = [];
      window.speechSynthesis?.cancel();
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled || !fan) return;
    const { stage } = useStore.getState();
    for (const it of Object.values(items)) {
      if (spoken.current.has(it.moment_id)) continue;
      spoken.current.add(it.moment_id);
      if (it.status !== "template" && (it.match_id === stage || it.importance >= 90)) queue.current.push(it);
    }
    queue.current = queue.current.slice(-3); // never fall far behind live play

    const next = async () => {
      if (playing.current || !queue.current.length) return;
      playing.current = true;
      const it = queue.current.shift()!;
      const lang = it.renditions[fan.language] ? fan.language : "en";
      const text = it.renditions[lang]?.audio;
      const done = () => {
        playing.current = false;
        next();
      };
      try {
        const res = await fetch(`/api/tts?moment_id=${encodeURIComponent(it.moment_id)}&lang=${lang}`);
        if (!res.ok) throw new Error(String(res.status));
        const audio = new Audio(URL.createObjectURL(await res.blob()));
        audio.onended = done;
        audio.onerror = done;
        await audio.play();
      } catch {
        if (!text || !("speechSynthesis" in window)) return done();
        const u = new SpeechSynthesisUtterance(text);
        u.lang = VOICE_LANG[lang] ?? "en-GB";
        u.onend = done;
        u.onerror = done;
        window.speechSynthesis.speak(u);
      }
    };
    next();
  }, [items, fan, enabled]);
}
