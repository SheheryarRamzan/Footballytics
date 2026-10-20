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
    feed: "Your feed", start: "Start my matchday", cutting: "Cutting to",
  },
  es: {
    matchday: "Jornada", your_matchday: "Tu Jornada", match_centre: "Centro del partido", studio: "Estudio",
    fan: "Fan", analyst: "Analista", kids: "Niños", audio: "Audio", live: "EN VIVO", why: "¿Por qué veo esto?",
    more: "Más como esto", less: "Menos como esto", watch: "Ver", squad: "Tu equipo", points: "pts",
    ask: "Pregunta al experto", brief: "Resúmeme", verified: "Verificado", corrected: "Corregido",
    feed: "Tu feed", start: "Empezar mi jornada", cutting: "Cambiamos a",
  },
  ar: {
    matchday: "الجولة", your_matchday: "جولتك", match_centre: "مركز المباراة", studio: "الاستوديو",
    fan: "مشجع", analyst: "محلل", kids: "أطفال", audio: "صوت", live: "مباشر", why: "لماذا أرى هذا؟",
    more: "المزيد مثل هذا", less: "أقل من هذا", watch: "شاهد", squad: "فريقك", points: "نقاط",
    ask: "اسأل المحلل", brief: "ملخص لي", verified: "تم التحقق", corrected: "صُحّح",
    feed: "موجزك", start: "ابدأ جولتي", cutting: "ننتقل إلى",
  },
  ur: {
    matchday: "میچ ڈے", your_matchday: "آپ کا میچ ڈے", match_centre: "میچ سینٹر", studio: "اسٹوڈیو",
    fan: "فین", analyst: "تجزیہ کار", kids: "بچے", audio: "آڈیو", live: "براہ راست", why: "یہ مجھے کیوں دکھایا گیا؟",
    more: "ایسا مزید", less: "ایسا کم", watch: "دیکھیں", squad: "آپ کی ٹیم", points: "پوائنٹس",
    ask: "ماہر سے پوچھیں", brief: "خلاصہ دیں", verified: "تصدیق شدہ", corrected: "درست کیا گیا",
    feed: "آپ کی فیڈ", start: "میرا میچ ڈے شروع کریں", cutting: "اب چلتے ہیں",
  },
  fr: {
    matchday: "Journée", your_matchday: "Votre journée", match_centre: "Centre du match", studio: "Studio",
    fan: "Fan", analyst: "Analyste", kids: "Enfants", audio: "Audio", live: "EN DIRECT", why: "Pourquoi je vois ça ?",
    more: "Plus comme ça", less: "Moins comme ça", watch: "Regarder", squad: "Votre équipe", points: "pts",
    ask: "Demandez au consultant", brief: "Résumé", verified: "Vérifié", corrected: "Corrigé",
    feed: "Votre fil", start: "Lancer ma journée", cutting: "On passe à",
  },
  pt: {
    matchday: "Rodada", your_matchday: "Sua Rodada", match_centre: "Central da partida", studio: "Estúdio",
    fan: "Torcedor", analyst: "Analista", kids: "Crianças", audio: "Áudio", live: "AO VIVO", why: "Por que vejo isto?",
    more: "Mais assim", less: "Menos assim", watch: "Assistir", squad: "Seu time", points: "pts",
    ask: "Pergunte ao comentarista", brief: "Resumo", verified: "Verificado", corrected: "Corrigido",
    feed: "Seu feed", start: "Começar minha rodada", cutting: "Indo para",
  },
  hi: {
    matchday: "मैचडे", your_matchday: "आपका मैचडे", match_centre: "मैच सेंटर", studio: "स्टूडियो",
    fan: "फ़ैन", analyst: "विश्लेषक", kids: "बच्चे", audio: "ऑडियो", live: "लाइव", why: "यह मुझे क्यों दिख रहा है?",
    more: "ऐसा और", less: "ऐसा कम", watch: "देखें", squad: "आपकी टीम", points: "अंक",
    ask: "पंडित से पूछें", brief: "सारांश", verified: "सत्यापित", corrected: "सुधारा गया",
    feed: "आपकी फ़ीड", start: "मेरा मैचडे शुरू करें", cutting: "अब चलते हैं",
  },
};

export const tr = (key: string, lang: string) => STRINGS[lang]?.[key] ?? STRINGS.en[key] ?? key;

export function useT(): (key: string) => string {
  const lang = useStore((s) => s.fan?.language ?? "en");
  return (key: string) => tr(key, lang);
}

// Moment labels, so instant (pre-agent) graphics are in the viewer's language too.
const KINDS = [
  "goal", "wonder_strike", "big_chance", "great_save", "penalty_awarded", "red_card", "yellow_card", "momentum_swing",
  "control_shift", "pressing_shift", "tempo_shift", "line_breaking_pass", "sprint_tag", "shot_speed", "high_turnover",
  "milestone", "substitution", "half_time", "full_time",
];
const KIND_LABELS: Record<string, string[]> = {
  en: ["GOAL", "WONDER GOAL", "BIG CHANCE", "GREAT SAVE", "PENALTY", "RED CARD", "YELLOW CARD", "MOMENTUM",
    "CONTROL vs CHAOS", "PRESSING", "TEMPO", "LINE-BREAKER", "TOP SPEED", "SHOT SPEED", "HIGH TURNOVER", "MILESTONE",
    "SUBSTITUTION", "HALF TIME", "FULL TIME"],
  es: ["GOL", "GOLAZO", "OCASIÓN CLARA", "PARADÓN", "PENALTI", "TARJETA ROJA", "TARJETA AMARILLA", "IMPULSO",
    "CONTROL vs CAOS", "PRESIÓN", "RITMO", "PASE ENTRE LÍNEAS", "VELOCIDAD PUNTA", "POTENCIA DE TIRO",
    "RECUPERACIÓN ALTA", "HITO", "CAMBIO", "DESCANSO", "FINAL"],
  ar: ["هدف", "هدف رائع", "فرصة كبيرة", "تصدٍّ رائع", "ركلة جزاء", "بطاقة حمراء", "بطاقة صفراء", "زخم",
    "سيطرة أم فوضى", "ضغط", "إيقاع", "تمريرة تكسر الخطوط", "أعلى سرعة", "قوة التسديدة", "استعادة متقدمة", "إنجاز",
    "تبديل", "نهاية الشوط الأول", "نهاية المباراة"],
  ur: ["گول", "شاندار گول", "بڑا موقع", "شاندار بچاؤ", "پنالٹی", "ریڈ کارڈ", "ییلو کارڈ", "کھیل کا رخ",
    "کنٹرول یا افراتفری", "دباؤ", "کھیل کی رفتار", "لائنیں توڑنے والا پاس", "تیز ترین رفتار", "شاٹ کی رفتار",
    "آگے گیند چھین لی", "سنگ میل", "کھلاڑی کی تبدیلی", "ہاف ٹائم", "فل ٹائم"],
  fr: ["BUT", "BUT SPLENDIDE", "GROSSE OCCASION", "ARRÊT DÉCISIF", "PENALTY", "CARTON ROUGE", "CARTON JAUNE",
    "DYNAMIQUE", "CONTRÔLE vs CHAOS", "PRESSING", "RYTHME", "PASSE QUI CASSE LES LIGNES", "VITESSE DE POINTE",
    "PUISSANCE DE FRAPPE", "RÉCUPÉRATION HAUTE", "CAP FRANCHI", "REMPLACEMENT", "MI-TEMPS", "FIN DU MATCH"],
  pt: ["GOL", "GOLAÇO", "GRANDE CHANCE", "GRANDE DEFESA", "PÊNALTI", "CARTÃO VERMELHO", "CARTÃO AMARELO", "EMBALO",
    "CONTROLE vs CAOS", "PRESSÃO", "RITMO", "PASSE QUE QUEBRA LINHAS", "VELOCIDADE MÁXIMA", "POTÊNCIA DO CHUTE",
    "RECUPERAÇÃO ALTA", "MARCO", "SUBSTITUIÇÃO", "INTERVALO", "FIM DE JOGO"],
  hi: ["गोल", "शानदार गोल", "बड़ा मौका", "शानदार बचाव", "पेनल्टी", "रेड कार्ड", "येलो कार्ड", "मोमेंटम",
    "नियंत्रण बनाम अफरातफरी", "प्रेसिंग", "खेल की गति", "लाइन तोड़ने वाला पास", "टॉप स्पीड", "शॉट की रफ़्तार",
    "आगे गेंद छीनी", "उपलब्धि", "खिलाड़ी बदला", "हाफ़ टाइम", "फ़ुल टाइम"],
};

export function kindLabel(kind: string, lang: string): string {
  const i = KINDS.indexOf(kind);
  if (i < 0) return kind.replace(/_/g, " ").toUpperCase();
  return (KIND_LABELS[lang] ?? KIND_LABELS.en)[i];
}

/** The numbers behind a moment; they read the same in every language. */
export function factParts(f?: Record<string, any>, kind = ""): string[] {
  if (!f) return [];
  const num = (v: any, d = 0) => Number(v).toFixed(d);
  const parts: string[] = [];
  if (f.on_name) parts.push(`▲ ${f.on_name} ▼ ${f.off_name ?? ""}`.trim());
  if (f.score && ["goal", "wonder_strike", "half_time", "full_time"].includes(kind)) parts.push(String(f.score));
  if (f.xg != null) parts.push(`xG ${num(f.xg, 2)}`);
  if (f.speed_kmh != null) parts.push(`${num(f.speed_kmh, 1)} km/h`);
  if (f.shot_speed_kmh) parts.push(`${num(f.shot_speed_kmh)} km/h`);
  if (f.difficulty != null) parts.push(`${num(f.difficulty, 1)}/10`);
  const metres = f.length_m ?? f.distance_m;
  if (metres != null) parts.push(`${num(metres)} m`);
  if (f.threat_share != null) parts.push(`${num(f.threat_share * 100)}%`);
  if (f.ppda_now != null) parts.push(`PPDA ${num(f.ppda_now, 1)}`);
  return parts.slice(0, 3);
}

const FSI = String.fromCodePoint(0x2068); // first-strong isolate
const PDI = String.fromCodePoint(0x2069); // pop directional isolate
const NBSP = String.fromCodePoint(0xa0); // keep "28 m" on one line

/** Join segments with each one bidi-isolated, so names and numbers keep their order inside RTL text. */
export const joinIsolated = (parts: (string | undefined | null)[]) =>
  parts.filter(Boolean).map((p) => `${FSI}${p!.replace(/ /g, NBSP)}${PDI}`).join(" · ");

export const factLine = (f?: Record<string, any>, kind = "") => joinIsolated(factParts(f, kind));

/** What a non-English viewer sees until the agents' rendition in their language arrives. */
export function instantLine(kind: string, playerId: string | null | undefined, facts: Record<string, any> | undefined,
  lang: string): string {
  const who = playerId ? useStore.getState().players[playerId]?.name : undefined;
  return joinIsolated([kindLabel(kind, lang), who, ...factParts(facts, kind)]);
}

/** The Director's personal line: English from the server, language-neutral otherwise. */
export function decisionLine(d: { line: string; kind?: string | null; data?: Record<string, any> }, lang: string): string {
  if (lang === "en" || !d.kind) return d.line;
  return instantLine(d.kind, d.data?.player_id, d.data?.facts, lang);
}

export const isRtl = (lang: string) => !!LANGUAGES.find((l) => l.code === lang)?.rtl;
