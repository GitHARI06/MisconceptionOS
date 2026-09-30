// Voice helpers shared by the voice studio: recorder format selection,
// transcript selection, echo detection and a better browser-voice fallback.

export const timeGreeting = (date = new Date()) => {
  const hour = date.getHours();
  if (hour >= 5 && hour < 12) return 'Good morning';
  if (hour >= 12 && hour < 17) return 'Good afternoon';
  if (hour >= 17 && hour < 22) return 'Good evening';
  return 'Hello';
};

// Local fallback if the personal greeting cannot be fetched.
export const GREETING = `${timeGreeting()}! I'm your physics tutor. What would you like to explore today?`;

// Lesson phases in which the learner is working on a problem: the tutor
// gives them more time to think and nudges gently instead of hanging up.
export const THINKING_PHASES = new Set(['SOCRATIC_CHALLENGE', 'SOCRATIC_SCAFFOLDING', 'TRANSFER_CHECK']);

export const NUDGE = "Take your time, there's no rush. If you'd like a hint, just say hint.";

// Short, natural acknowledgements spoken while the tutor is working out a
// reply, so a pause never feels like the line went dead.
const ACKS = {
  question: ['Good question. Let me think.', 'Hmm, let me think about that.'],
  answer: ['Okay, let me look at your reasoning.', 'Interesting. Let me think about that.'],
  other: ['Mm-hm, one moment.', 'Okay, give me a second.'],
};
export const ALL_ACKS = [...ACKS.question, ...ACKS.answer, ...ACKS.other];
let ackCounter = 0;
export const pickAck = (text, phase) => {
  const t = (text || '').trim().toLowerCase();
  const kind = /\?$/.test(t) || /^(what|why|how|when|where|which|who|can|could|is|are|does|do)\b/.test(t)
    ? 'question'
    : THINKING_PHASES.has(phase) ? 'answer' : 'other';
  ackCounter += 1;
  return ACKS[kind][ackCounter % ACKS[kind].length];
};
export const ACK_DELAY_MS = 900;

// Voice-activity detection tuning (milliseconds / RMS amplitude).
export const VAD = {
  calibrateMs: 250,        // measure the room's noise floor first
  minThreshold: 0.012,     // never treat quieter than this as speech
  noiseMultiplier: 2.6,    // speech must be this much louder than the room
  maxNoiseFloor: 0.03,     // cap, in case the learner starts talking instantly
  minSpeechMs: 180,        // ignore clicks and pops
  endSilenceMs: 850,       // this much silence after speech ends the turn
  thinkingEndSilenceMs: 1500, // while solving a problem learners pause to think mid-answer
  noSpeechTimeoutMs: 8000, // nobody spoke: stop listening quietly
  maxUtteranceMs: 30000,   // hard cap on one turn
  bargeInMs: 300,          // sustained speech needed to interrupt the tutor
  bargeInThreshold: 0.045, // interrupting must be clearly louder than echo
};

const RECORDER_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];

export const pickRecorderType = () => {
  if (typeof window === 'undefined' || !window.MediaRecorder) return null;
  if (!MediaRecorder.isTypeSupported) return '';
  return RECORDER_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || '';
};

const PHYSICS_WORDS = [
  'newton', 'inertia', 'force', 'velocity', 'acceleration', 'momentum', 'friction', 'gravity',
  'energy', 'entropy', 'thermodynamics', 'heat', 'temperature', 'pressure', 'wave', 'frequency',
  'refraction', 'reflection', 'voltage', 'current', 'resistance', 'magnetic', 'quantum', 'mass',
  'joule', 'watt', 'ohm', 'kinetic', 'potential', 'net', 'vacuum', 'orbit', 'photon', 'electron',
];

// Pick the recognition alternative that is most likely right, nudging
// towards physics vocabulary. Chrome reports confidence 0 when it does not
// know, so 0 means "unknown", not "wrong".
export const bestAlternative = (result) => {
  let best = null;
  for (let i = 0; i < result.length; i += 1) {
    const alt = result[i];
    const text = (alt.transcript || '').trim();
    if (!text) continue;
    const confidence = typeof alt.confidence === 'number' && alt.confidence > 0 ? alt.confidence : 0.6;
    const lower = text.toLowerCase();
    const vocab = PHYSICS_WORDS.filter((w) => lower.includes(w)).length;
    const score = confidence + Math.min(vocab, 2) * 0.08 - i * 0.01;
    if (!best || score > best.score) best = { text, confidence, score };
  }
  if (!best || best.confidence < 0.2) return null;
  return best;
};

const words = (text) => ((text || '').toLowerCase().match(/[a-z0-9']+/g) || []);

// Fraction of the heard words that also appear in what the tutor is saying.
// A high ratio means the microphone picked up the tutor's own voice.
export const echoRatio = (heard, spoken) => {
  const heardWords = words(heard);
  if (!heardWords.length) return 0;
  const spokenWords = new Set(words(spoken));
  return heardWords.filter((w) => spokenWords.has(w)).length / heardWords.length;
};

const normWord = (w) => {
  const x = w.replace(/'/g, '');
  return ({ okay: 'ok', im: 'i', am: 'i' })[x] || x;
};

// How many leading heard words follow the tutor's sentence in order
// (tolerating an occasional recognition slip). 0 if fewer than 5 match.
const echoRun = (heard, spoken) => {
  let best = 0;
  for (let start = 0; start < spoken.length; start += 1) {
    if (spoken[start] !== heard[0]) continue;
    let i = 0; let j = start; let matched = 0; let budget = 1; let end = 0;
    while (i < heard.length && j < spoken.length) {
      if (heard[i] === spoken[j]) {
        i += 1; j += 1; matched += 1;
        end = i; // echo ends at the last exact match
        if (matched % 5 === 0) budget = 1;
      } else if (budget && i + 1 < heard.length && heard[i + 1] === spoken[j]) {
        i += 1; budget = 0;
      } else if (budget && j + 1 < spoken.length && heard[i] === spoken[j + 1]) {
        j += 1; budget = 0;
      } else if (budget) {
        i += 1; j += 1; budget = 0;
      } else break;
    }
    if (matched >= 5) best = Math.max(best, end);
  }
  return best;
};

// The microphone picked up the tutor: drop a leading run of at least four
// words that follows what the tutor just said *in order*, and keep anything
// the learner added. Answers that merely reuse the tutor's vocabulary are
// kept. Returns '' when nothing but echo was heard.
export const stripEcho = (heard, spoken) => {
  const text = (heard || '').trim();
  const tokens = text.split(/\s+/).filter(Boolean);
  const heardWords = words(text).map(normWord);
  const spokenWords = words(spoken).map(normWord);
  if (heardWords.length < 4 || !spokenWords.length) return text;
  let removed = 0;
  for (;;) {
    const run = heardWords.length - removed >= 5 ? echoRun(heardWords.slice(removed), spokenWords) : 0;
    if (!run) break;
    removed += run;
  }
  if (!removed) return text;
  let count = 0; let cut = 0;
  for (let k = 0; k < tokens.length && count < removed; k += 1) {
    count += words(tokens[k]).length;
    cut = k + 1;
  }
  const rest = tokens.slice(cut).join(' ').trim();
  return words(rest).length >= 2 ? rest : '';
};

export const isFiller = (text) => /^(uh+|um+|hmm+|okay|ok|yes|no|yeah|yep|mm+)[.!?\s]*$/i.test((text || '').trim());

export const blobToDataUrl = (blob) => new Promise((resolve) => {
  const reader = new FileReader();
  reader.onloadend = () => resolve(reader.result);
  reader.onerror = () => resolve(null);
  reader.readAsDataURL(blob);
});

// ---- browser speech-synthesis fallback ------------------------------------

let cachedVoice;
const pickVoice = () => {
  if (cachedVoice !== undefined) return cachedVoice;
  const voices = window.speechSynthesis?.getVoices?.() || [];
  if (!voices.length) return null;
  const english = voices.filter((v) => /^en(-|_|$)/i.test(v.lang));
  const preferred = [/natural/i, /online/i, /google us english/i, /aria|jenny|guy|andrew|samantha/i];
  cachedVoice = null;
  for (const pattern of preferred) {
    const match = english.find((v) => pattern.test(v.name));
    if (match) { cachedVoice = match; break; }
  }
  cachedVoice = cachedVoice || english.find((v) => v.default) || english[0] || null;
  return cachedVoice;
};

export const plainSpeech = (text) => (text || '')
  .replace(/\\\(|\\\)|\\\[|\\\]|\$/g, ' ')
  .replace(/\\[a-zA-Z]+/g, ' ')
  .replace(/[*_`#>{}]/g, '')
  .replace(/\s+/g, ' ')
  .trim();

// Chrome silently stops utterances longer than ~15 s, so speak sentence by
// sentence. Resolves when everything was spoken (or cancelled).
export const browserSpeak = (text, { onStart, isCurrent }) => new Promise((resolve) => {
  const synth = window.speechSynthesis;
  if (!synth || typeof SpeechSynthesisUtterance === 'undefined') { resolve(); return; }
  synth.cancel();
  const sentences = plainSpeech(text).match(/[^.!?]+[.!?]*/g) || [];
  if (!sentences.length) { resolve(); return; }
  onStart?.();
  let index = 0;
  const next = () => {
    if (!isCurrent() || index >= sentences.length) { resolve(); return; }
    const utterance = new SpeechSynthesisUtterance(sentences[index].trim());
    index += 1;
    const voice = pickVoice();
    if (voice) utterance.voice = voice;
    utterance.rate = 1.02;
    utterance.onend = next;
    utterance.onerror = next;
    synth.speak(utterance);
  };
  next();
});
