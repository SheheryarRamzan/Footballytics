import { useStore } from "./store";

export const LANGUAGES: { code: string; label: string; rtl?: boolean }[] = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "ar", label: "العربية", rtl: true },
  { code: "ur", label: "اردو", rtl: true },
  { code: "fr", label: "Français" },
  { code: "pt", label: "Português" },
  { code: "hi", label: "हिन्दी" },
];

type Dict = Record<string, string>;
const STRINGS: Record<string, Dict> = {
  en: {
    matchday: "Matchday", your_matchday: "Your Matchday", match_centre: "Match Centre", studio: "Studio",
    fan: "Fan", analyst: "Analyst", kids: "Kids", audio: "Audio", live: "LIVE", why: "Why am I seeing this?",
    more: "More like this", less: "Less like this", watch: "Watch", squad: "Your squad", points: "pts",
    ask: "Ask the pundit", brief: "Brief me", verified: "Verified", corrected: "Corrected by Verifier",
    feed: "Your feed", start: "Start my matchday",
  },
  es: {
    matchday: "Jornada", your_matchday: "Tu Jornada", match_centre: "Centro del partido", studio: "Estudio",
    fan: "Fan", analyst: "Analista", kids: "Niños", audio: "Audio", live: "EN VIVO", why: "¿Por qué veo esto?",
    more: "Más como esto", less: "Menos como esto", watch: "Ver", squad: "Tu equipo", points: "pts",
    ask: "Pregunta al experto", brief: "Resúmeme", verified: "Verificado", corrected: "Corregido",
    feed: "Tu feed", start: "Empezar mi jornada",
  },
  ar: {
    matchday: "الجولة", your_matchday: "جولتك", match_centre: "مركز المباراة", studio: "الاستوديو",
    fan: "مشجع", analyst: "محلل", kids: "أطفال", audio: "صوت", live: "مباشر", why: "لماذا أرى هذا؟",
    more: "المزيد مثل هذا", less: "أقل من هذا", watch: "شاهد", squad: "فريقك", points: "نقاط",
    ask: "اسأل المحلل", brief: "ملخص لي", verified: "تم التحقق", corrected: "صُحّح",
    feed: "موجزك", start: "ابدأ جولتي",
  },
  ur: {
    matchday: "میچ ڈے", your_matchday: "آپ کا میچ ڈے", match_centre: "میچ سینٹر", studio: "اسٹوڈیو",
    fan: "فین", analyst: "تجزیہ کار", kids: "بچے", audio: "آڈیو", live: "براہ راست", why: "یہ مجھے کیوں دکھایا گیا؟",
    more: "ایسا مزید", less: "ایسا کم", watch: "دیکھیں", squad: "آپ کی ٹیم", points: "پوائنٹس",
    ask: "ماہر سے پوچھیں", brief: "خلاصہ دیں", verified: "تصدیق شدہ", corrected: "درست کیا گیا",
    feed: "آپ کی فیڈ", start: "میرا میچ ڈے شروع کریں",
  },
  fr: {
    matchday: "Journée", your_matchday: "Votre journée", match_centre: "Centre du match", studio: "Studio",
    fan: "Fan", analyst: "Analyste", kids: "Enfants", audio: "Audio", live: "EN DIRECT", why: "Pourquoi je vois ça ?",
    more: "Plus comme ça", less: "Moins comme ça", watch: "Regarder", squad: "Votre équipe", points: "pts",
    ask: "Demandez au consultant", brief: "Résumé", verified: "Vérifié", corrected: "Corrigé",
    feed: "Votre fil", start: "Lancer ma journée",
  },
  pt: {
    matchday: "Rodada", your_matchday: "Sua Rodada", match_centre: "Central da partida", studio: "Estúdio",
    fan: "Torcedor", analyst: "Analista", kids: "Crianças", audio: "Áudio", live: "AO VIVO", why: "Por que vejo isto?",
    more: "Mais assim", less: "Menos assim", watch: "Assistir", squad: "Seu time", points: "pts",
    ask: "Pergunte ao comentarista", brief: "Resumo", verified: "Verificado", corrected: "Corrigido",
    feed: "Seu feed", start: "Começar minha rodada",
  },
  hi: {
    matchday: "मैचडे", your_matchday: "आपका मैचडे", match_centre: "मैच सेंटर", studio: "स्टूडियो",
    fan: "फ़ैन", analyst: "विश्लेषक", kids: "बच्चे", audio: "ऑडियो", live: "लाइव", why: "यह मुझे क्यों दिख रहा है?",
    more: "ऐसा और", less: "ऐसा कम", watch: "देखें", squad: "आपकी टीम", points: "अंक",
    ask: "पंडित से पूछें", brief: "सारांश", verified: "सत्यापित", corrected: "सुधारा गया",
    feed: "आपकी फ़ीड", start: "मेरा मैचडे शुरू करें",
  },
};

export function useT(): (key: string) => string {
  const lang = useStore((s) => s.fan?.language ?? "en");
  const d = STRINGS[lang] ?? STRINGS.en;
  return (key: string) => d[key] ?? STRINGS.en[key] ?? key;
}

export const isRtl = (lang: string) => !!LANGUAGES.find((l) => l.code === lang)?.rtl;
