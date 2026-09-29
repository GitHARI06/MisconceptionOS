import React, { useState, useRef, useEffect } from 'react';
import { SilverOrb } from './SilverOrb';
import { FormattedMathText } from '../utils/katexHelper';
import { Volume2, VolumeX, Sparkles, ShieldCheck, CheckCircle2, ArrowRight } from 'lucide-react';

export const MinimalVoiceStudio = ({ sessionId, onStateUpdate }) => {
  const [orbState, setOrbState] = useState('idle'); // 'idle' | 'listening' | 'thinking' | 'speaking'
  const [liveTranscript, setLiveTranscript] = useState('');
  const [tutorSpeech, setTutorSpeech] = useState("Good morning, welcome to learning. What shall we learn today?");
  const [lastAudioB64, setLastAudioB64] = useState(null);
  const [autoVoice, setAutoVoice] = useState(true);
  const [transferModal, setTransferModal] = useState(null);
  const [hasStarted, setHasStarted] = useState(false);
  const [bootVoicePending, setBootVoicePending] = useState(false);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioPlayerRef = useRef(new Audio());
  const recognitionRef = useRef(null);
  const spokenTextRef = useRef('');

  useEffect(() => {
    // Initial bootup greeting speech
    const greeting = "Good morning, welcome to learning. What shall we learn today?";
    setTutorSpeech(greeting);

    // Setup Web Speech API for instantaneous streaming transcription
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-US';

      recognition.onresult = (event) => {
        let interimTranscript = '';
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            spokenTextRef.current += event.results[i][0].transcript + ' ';
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }
        setLiveTranscript(spokenTextRef.current + interimTranscript);
      };

      recognition.onerror = (e) => {
        console.warn('Speech recognition notice:', e);
      };

      recognitionRef.current = recognition;
    }
  }, []);

  const speakText = (text, b64Audio = null) => {
    if (!autoVoice) {
      setOrbState('idle');
      return;
    }

    if (b64Audio) {
      try {
        audioPlayerRef.current.pause();
        audioPlayerRef.current.src = `data:audio/mp3;base64,${b64Audio}`;
        setOrbState('speaking');
        audioPlayerRef.current.onended = () => setOrbState('idle');
        audioPlayerRef.current.onerror = () => fallbackBrowserTTS(text);
        audioPlayerRef.current.play().catch(e => {
          console.warn("Autoplay block, fallback to Web Speech TTS:", e);
        setBootVoicePending(true);
          fallbackBrowserTTS(text);
        });
        return;
      } catch (err) {
        console.error(err);
      }
    }

    fallbackBrowserTTS(text);
  };

  const fallbackBrowserTTS = (text) => {
    if (!window.speechSynthesis) {
      setOrbState('idle');
      return;
    }
    window.speechSynthesis.cancel();
    const cleanText = text.replace(/[*#$`\\]/g, '');
    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.onstart = () => setOrbState('speaking');
    utterance.onend = () => setOrbState('idle');
    utterance.onerror = () => setOrbState('idle');
    window.speechSynthesis.speak(utterance);
  };

  // Request the server-generated greeting at boot. This gives the browser a
  // real voice asset to play immediately instead of relying only on the
  // transcript. If autoplay is blocked, the pending audio is retried from the
  // first user gesture in startListening().
  useEffect(() => {
    const greeting = "Good morning, welcome to learning. What shall we learn today?";
    let cancelled = false;

    const playBootGreeting = async () => {
      if (!autoVoice) return;
      try {
        const response = await fetch('/api/audio/synthesize', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: greeting })
        });
        if (!response.ok || cancelled) throw new Error('Greeting audio unavailable');
        const data = await response.json();
        if (!cancelled && data.audio_base64) {
          setLastAudioB64(data.audio_base64);
          speakText(greeting, data.audio_base64);
        } else if (!cancelled) {
          setBootVoicePending(true);
          fallbackBrowserTTS(greeting);
        }
      } catch (error) {
        if (!cancelled) {
          setBootVoicePending(true);
          console.warn('Boot greeting audio unavailable; using browser voice:', error);
          fallbackBrowserTTS(greeting);
        }
      }
    };

    const bootTimer = window.setTimeout(playBootGreeting, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(bootTimer);
    };
  }, [autoVoice]);

  const startListening = async () => {
    try {
      if (!hasStarted) {
        setHasStarted(true);
      }
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      audioPlayerRef.current.pause();

      // A browser gesture unlocks media playback after an autoplay block.
      if (bootVoicePending && lastAudioB64 && autoVoice) {
        setBootVoicePending(false);
        speakText("Good morning, welcome to learning. What shall we learn today?", lastAudioB64);
      } else if (bootVoicePending && autoVoice) {
        setBootVoicePending(false);
        fallbackBrowserTTS("Good morning, welcome to learning. What shall we learn today?");
      }

      spokenTextRef.current = '';
      setLiveTranscript('');

      if (recognitionRef.current) {
        try { recognitionRef.current.start(); } catch (e) {}
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorderRef.current = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorderRef.current.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        const reader = new FileReader();
        reader.readAsDataURL(audioBlob);
        reader.onloadend = () => {
          const base64Audio = reader.result;
          const textFallback = spokenTextRef.current.trim();
          processVoiceTurn(base64Audio, textFallback);
        };
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorderRef.current.start();
      setOrbState('listening');
      setLiveTranscript('Listening to you...');
    } catch (err) {
      console.error("Mic access error:", err);
      alert("Microphone access is required for voice mode.");
      setOrbState('idle');
    }
  };

  const stopListening = () => {
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch (e) {}
    }
    if (mediaRecorderRef.current && orbState === 'listening') {
      mediaRecorderRef.current.stop();
      setOrbState('thinking');
    }
  };

  const handleOrbClick = () => {
    if (orbState === 'idle' || orbState === 'speaking') {
      startListening();
    } else if (orbState === 'listening') {
      stopListening();
    }
  };

  const processVoiceTurn = async (audioBase64, textFallback = '') => {
    try {
      const res = await fetch('/api/chat/turn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          challenge_id: 'freeform_inquiry',
          unit_id: 'physics_mechanics',
          text: textFallback || null,
          audio_base64: audioBase64 || null
        })
      });

      if (res.ok) {
        const data = await res.json();
        const displayUser = data.user_utterance || textFallback || 'Your Query';
        setLiveTranscript(`"${displayUser}"`);
        setTutorSpeech(data.tutor_text);
        setLastAudioB64(data.audio_base64);

        if (data.transfer_ready && data.transfer_question) {
          setTransferModal(data.transfer_question);
        }

        if (onStateUpdate) {
          onStateUpdate(data);
        }

        speakText(data.tutor_text, data.audio_base64);
      } else {
        const fallback = "Let's explore that together: what fundamental principles apply here?";
        setTutorSpeech(fallback);
        speakText(fallback);
      }
    } catch (err) {
      console.warn("Turn processing fallback:", err);
      const fallback = "Let's explore that topic! What core concepts or questions do you have in mind?";
      setTutorSpeech(fallback);
      speakText(fallback);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-140px)] max-w-3xl mx-auto px-4 py-8 text-center select-none space-y-8 animate-in fade-in duration-500">
      {/* Clean Minimal Headline */}
      <div className="space-y-2">
        <h1 className="text-3xl sm:text-4xl font-normal tracking-tight text-slate-100">
          Good morning, welcome to learning.
        </h1>
        <p className="text-xs text-slate-500 font-mono">
          What shall we learn today? Click the silver orb and tell me any physics topic or concept.
        </p>
      </div>

      {/* The Animated Clickable Silver Orb */}
      <div className="flex flex-col items-center justify-center space-y-4">
        <SilverOrb
          state={orbState}
          onClick={handleOrbClick}
          size={290}
        />

        {/* State Label */}
        <span className="text-xs font-mono tracking-widest text-slate-400 uppercase font-medium">
          {orbState === 'listening'
            ? '● Listening (Click to finish speaking)'
            : orbState === 'thinking'
            ? '✦ Formulating Teacher Response...'
            : orbState === 'speaking'
            ? '▶ Socratic Teacher Speaking'
            : 'Click Silver Orb to Speak'}
        </span>
      </div>

      {/* Dynamic Subtitle / Dialogue Area */}
      <div className="w-full max-w-2xl space-y-4">
        {/* User Speech Live Transcription */}
        {liveTranscript && (
          <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-2xl text-xs text-teal-300 font-mono italic max-w-lg mx-auto backdrop-blur-sm animate-in fade-in">
            {liveTranscript}
          </div>
        )}

        {/* Teacher / Tutor Voice Response */}
        {tutorSpeech && (
          <div className="p-6 bg-slate-900/80 border border-slate-800 rounded-3xl text-sm text-slate-100 leading-relaxed shadow-2xl backdrop-blur-md max-w-2xl mx-auto text-left">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-mono uppercase text-teal-400 font-bold tracking-wider">
                Socratic Teacher
              </span>
              <button
                onClick={() => speakText(tutorSpeech, lastAudioB64)}
                className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-teal-300 font-mono transition"
              >
                <Volume2 className="w-3.5 h-3.5" /> Replay Voice
              </button>
            </div>
            <FormattedMathText text={tutorSpeech} />
          </div>
        )}
      </div>

      {/* Transfer Question Modal */}
      {transferModal && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-md flex items-center justify-center p-4 z-50">
          <div className="max-w-lg w-full bg-slate-900 border border-teal-500/40 rounded-3xl p-6 shadow-2xl space-y-4 text-left">
            <div className="flex items-center gap-2 text-teal-400">
              <CheckCircle2 className="w-6 h-6 text-emerald-400" />
              <h3 className="text-base font-bold text-white">Transfer Challenge</h3>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              You've identified the core principle! To verify conceptual transfer, explain your reasoning for this scenario:
            </p>
            <div className="p-4 bg-slate-950 rounded-2xl border border-teal-500/20 text-xs text-teal-200 font-mono leading-relaxed">
              <FormattedMathText text={transferModal} />
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setTransferModal(null)}
                className="px-5 py-2.5 bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold rounded-xl transition flex items-center gap-1.5"
              >
                Accept & Speak <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
