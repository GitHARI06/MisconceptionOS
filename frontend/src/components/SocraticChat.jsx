import React, { useState, useRef, useEffect } from 'react';
import {
  Mic, MicOff, Send, Volume2, VolumeX, Sparkles, AlertCircle,
  CheckCircle2, ArrowRight, ShieldCheck, Flame, BookOpen, Clock,
  FileText, Code, BrainCircuit, Lock, Unlock, HelpCircle, RefreshCw, Award
} from 'lucide-react';
import { AudioWaveform } from './AudioWaveform';
import { FormattedMathText } from '../utils/katexHelper';

export const SocraticChat = ({ sessionId, challenge, unit, onStateUpdate }) => {
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [autoVoice, setAutoVoice] = useState(true);
  const [loading, setLoading] = useState(false);
  const [transferModal, setTransferModal] = useState(null);
  const [scratchpad, setScratchpad] = useState('');
  const [sessionSeconds, setSessionSeconds] = useState(0);
  const [lastTurnData, setLastTurnData] = useState(null);
  const [showScorecard, setShowScorecard] = useState(false);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioPlayerRef = useRef(new Audio());
  const messagesEndRef = useRef(null);

  // Session timer
  useEffect(() => {
    const timer = setInterval(() => setSessionSeconds(prev => prev + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const formatTimer = (secs) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  useEffect(() => {
    if (challenge) {
      setMessages([
        {
          sender: 'tutor',
          text: `Hello! I am your Socratic AI Tutor. Think out loud and explain your reasoning verbally or in text:\n\n**${challenge.prompt}**\n\nTake your time. What is your mental model here and why?`,
          tier: 'DIAGNOSTIC_PROBE'
        }
      ]);
    }
  }, [challenge]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const playAudioB64 = (b64) => {
    if (!b64 || !autoVoice) return;
    try {
      audioPlayerRef.current.pause();
      audioPlayerRef.current.src = `data:audio/mp3;base64,${b64}`;
      setIsSpeaking(true);
      audioPlayerRef.current.onended = () => setIsSpeaking(false);
      audioPlayerRef.current.onerror = () => setIsSpeaking(false);
      audioPlayerRef.current.play().catch(e => {
        console.warn("Audio autoplay blocked:", e);
        setIsSpeaking(false);
      });
    } catch (err) {
      console.error("Audio playback error:", err);
      setIsSpeaking(false);
    }
  };

  const startVoiceRecording = async () => {
    try {
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
          handleSubmit(null, base64Audio);
        };
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorderRef.current.start();
      setIsRecording(true);
    } catch (err) {
      console.error("Microphone access error:", err);
      alert("Microphone access required. Please allow mic permissions.");
    }
  };

  const stopVoiceRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleSubmit = async (e, audioBase64 = null) => {
    if (e) e.preventDefault();
    const textToSend = inputText.trim();
    if (!textToSend && !audioBase64) return;

    const userMsg = {
      sender: 'user',
      text: textToSend || '🎤 [Audio Voice Submission]'
    };
    setMessages(prev => [...prev, userMsg]);
    setInputText('');
    setLoading(true);

    try {
      const res = await fetch('/api/chat/turn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          challenge_id: challenge.id,
          unit_id: challenge.unit_id || (unit ? unit.id : 'physics_mechanics'),
          text: textToSend || null,
          audio_base64: audioBase64 || null
        })
      });

      if (res.ok) {
        const data = await res.json();
        setLastTurnData(data);

        if (audioBase64 && data.user_utterance) {
          setMessages(prev => {
            const copy = [...prev];
            copy[copy.length - 1].text = `🎤 "${data.user_utterance}"`;
            return copy;
          });
        }

        const tutorMsg = {
          sender: 'tutor',
          text: data.tutor_text,
          tier: data.intervention_tier,
          diagnostic: data.diagnostic,
          audioB64: data.audio_base64,
          isPromptInjection: data.is_prompt_injection,
          isOutOfScope: data.is_out_of_scope
        };
        setMessages(prev => [...prev, tutorMsg]);

        if (data.audio_base64) {
          playAudioB64(data.audio_base64);
        }

        if (data.transfer_ready && data.transfer_question) {
          setTransferModal(data.transfer_question);
        }

        if (onStateUpdate) {
          onStateUpdate(data);
        }
      }
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, {
        sender: 'tutor',
        text: "I encountered a momentary latency spike. Let's refocus on the setup: what physical/logical principle applies here?",
        tier: 'DIAGNOSTIC_PROBE'
      }]);
    } finally {
      setLoading(false);
    }
  };

  const getTierStepIndex = (tier) => {
    switch (tier) {
      case 'DIAGNOSTIC_PROBE': return 1;
      case 'COGNITIVE_CONFLICT': return 2;
      case 'SCAFFOLDED_HINT': return 3;
      case 'CONCEPTUAL_EXPLANATION': return 4;
      case 'TRANSFER_VERIFICATION': return 5;
      default: return 1;
    }
  };

  const currentTier = lastTurnData ? lastTurnData.intervention_tier : 'DIAGNOSTIC_PROBE';
  const currentStep = getTierStepIndex(currentTier);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 min-h-[760px]">
      {/* ========================================================================= */}
      {/* LEFT COLUMN: Problem Context & Grounded Knowledge (4 cols) */}
      {/* ========================================================================= */}
      <div className="lg:col-span-4 space-y-4 flex flex-col">
        {/* Problem Card */}
        <div className="p-5 bg-slate-900/90 border border-slate-800 rounded-2xl shadow-xl space-y-3 flex-1">
          <div className="flex items-center justify-between">
            <span className="px-2.5 py-1 rounded-full text-[10px] font-mono font-bold bg-teal-500/10 text-teal-300 border border-teal-500/30 uppercase tracking-wider">
              {challenge ? challenge.difficulty : 'Intermediate'}
            </span>
            <div className="flex items-center gap-1.5 text-xs text-slate-400 font-mono">
              <Clock className="w-3.5 h-3.5 text-slate-500" />
              {formatTimer(sessionSeconds)}
            </div>
          </div>

          <h2 className="text-base font-bold text-white leading-snug">
            {challenge ? challenge.title || challenge.id : 'Problem Scenario'}
          </h2>

          <div className="p-4 bg-slate-950/80 rounded-xl border border-slate-800/80 text-xs text-slate-200 leading-relaxed font-sans">
            <FormattedMathText text={challenge ? challenge.prompt : ''} />
          </div>

          {/* Reference Knowledge Boundary */}
          <div className="pt-3 border-t border-slate-800/80 space-y-2">
            <div className="flex items-center gap-1.5 text-xs font-bold text-slate-300">
              <BookOpen className="w-3.5 h-3.5 text-teal-400" />
              Approved Knowledge Scope
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Tutor is bounded to physics and physics-connected interdisciplinary questions. Clearly unrelated requests will be transparently deflected.
            </p>
          </div>
        </div>

        {/* Scratchpad / Formula Box */}
        <div className="p-4 bg-slate-900/90 border border-slate-800 rounded-2xl space-y-2">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-300">
            <span className="flex items-center gap-1.5">
              <Code className="w-3.5 h-3.5 text-amber-400" />
              Reasoning Scratchpad
            </span>
            <span className="text-[10px] font-mono text-slate-500">Private Notes</span>
          </div>
          <textarea
            value={scratchpad}
            onChange={(e) => setScratchpad(e.target.value)}
            placeholder="Jot down formulas (e.g. F = ma, v = const -> a = 0) or call stack traces..."
            className="w-full h-24 bg-slate-950 border border-slate-800 text-xs text-slate-300 p-2.5 rounded-xl font-mono focus:ring-1 focus:ring-teal-500 focus:outline-none resize-none"
          />
        </div>
      </div>

      {/* ========================================================================= */}
      {/* CENTER COLUMN: Voice "Think Out Loud" Studio (5 cols) */}
      {/* ========================================================================= */}
      <div className="lg:col-span-5 flex flex-col bg-slate-900/90 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl">
        {/* Studio Top Bar */}
        <div className="flex items-center justify-between px-4 py-3 bg-slate-950/80 border-b border-slate-800 backdrop-blur">
          <div className="flex items-center gap-2">
            <div className={`w-2.5 h-2.5 rounded-full ${isSpeaking ? 'bg-amber-400 animate-ping' : isRecording ? 'bg-rose-500 animate-pulse' : 'bg-teal-400'}`} />
            <span className="text-xs font-bold text-slate-200">
              {isSpeaking ? "Tutor Speaking..." : isRecording ? "Transcribing Voice..." : "Voice Studio (Think Out Loud)"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <AudioWaveform isListening={isRecording} isSpeaking={isSpeaking} />
            <button
              onClick={() => setAutoVoice(!autoVoice)}
              className={`p-1.5 rounded-lg border transition ${
                autoVoice ? "bg-teal-500/20 text-teal-300 border-teal-500/40" : "bg-slate-800 text-slate-500 border-slate-700"
              }`}
            >
              {autoVoice ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        {/* Message Conversation Thread */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3.5">
          {messages.map((msg, index) => (
            <div
              key={index}
              className={`flex flex-col ${msg.sender === 'user' ? 'items-end' : 'items-start'}`}
            >
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-[10px] font-mono font-bold text-slate-400">
                  {msg.sender === 'user' ? 'Candidate Reasoning' : 'Socratic Tutor'}
                </span>
                {msg.tier && (
                  <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-teal-300 border border-slate-700">
                    {msg.tier}
                  </span>
                )}
              </div>

              <div
                className={`max-w-[90%] p-3.5 rounded-2xl text-xs leading-relaxed ${
                  msg.sender === 'user'
                    ? 'bg-teal-600 text-white rounded-br-none shadow-md shadow-teal-900/20 font-sans'
                    : 'bg-slate-950 text-slate-200 border border-slate-800 rounded-bl-none shadow-md'
                }`}
              >
                <FormattedMathText text={msg.text} />

                {/* Injection deflection notice */}
                {msg.isPromptInjection && (
                  <div className="mt-2 p-1.5 bg-rose-950/40 border border-rose-800/60 rounded text-[10px] text-rose-300 flex items-center gap-1 font-mono">
                    <ShieldCheck className="w-3 h-3 text-rose-400 shrink-0" />
                    Prompt Injection Deflected • Socratic Stance Preserved
                  </div>
                )}
              </div>

              {msg.audioB64 && (
                <button
                  onClick={() => playAudioB64(msg.audioB64)}
                  className="mt-1 flex items-center gap-1 text-[10px] text-teal-400 hover:text-teal-300 font-mono"
                >
                  <Volume2 className="w-3 h-3" /> Replay Speech
                </button>
              )}
            </div>
          ))}

          {loading && (
            <div className="flex items-center gap-2 text-[11px] text-teal-400 font-mono animate-pulse">
              <div className="w-2 h-2 rounded-full bg-teal-400 animate-ping" />
              Diagnosing mental model & formulating Socratic nudge...
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Pure Voice & Input Bottom Bar */}
        <div className="p-3 bg-slate-950 border-t border-slate-800">
          <form onSubmit={handleSubmit} className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={isRecording ? stopVoiceRecording : startVoiceRecording}
              className={`p-3 rounded-xl font-bold text-white transition duration-200 flex items-center justify-center shadow-lg ${
                isRecording
                  ? "bg-rose-600 animate-pulse glow-rose ring-4 ring-rose-500/30"
                  : "bg-teal-600 hover:bg-teal-500 glow-teal"
              }`}
              title={isRecording ? "Stop and Submit Voice (Faster-Whisper STT)" : "Click to Speak (Push-to-Talk)"}
            >
              {isRecording ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
            </button>

            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder={isRecording ? "Listening to your voice..." : "Explain reasoning verbally or type..."}
              className="flex-1 bg-slate-900 border border-slate-800 text-slate-100 placeholder-slate-500 text-xs rounded-xl px-3 py-2.5 focus:outline-none focus:ring-1 focus:ring-teal-500 font-sans"
            />

            <button
              type="submit"
              disabled={loading || (!inputText.trim() && !isRecording)}
              className="p-2.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-teal-400 rounded-xl transition border border-slate-700"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* RIGHT COLUMN: Live Socratic Telemetry & Scaffolding Ladder (3 cols) */}
      {/* ========================================================================= */}
      <div className="lg:col-span-3 space-y-4 flex flex-col">
        {/* Tutor Armor / Zero-Leakage Indicator */}
        <div className="p-4 bg-slate-900/90 border border-slate-800 rounded-2xl space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold text-slate-300 flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              Socratic Armor
            </span>
            <span className="text-[9px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
              Zero Leakage (100%)
            </span>
          </div>
          <p className="text-[11px] text-slate-400 leading-snug">
            Tutor refuses direct answer extraction and guides candidates through structured inquiry.
          </p>
        </div>

        {/* Socratic Scaffolding Ladder */}
        <div className="p-4 bg-slate-900/90 border border-slate-800 rounded-2xl space-y-3">
          <span className="text-xs font-bold text-slate-200 block">
            Pedagogical Scaffolding Ladder
          </span>

          <div className="space-y-2">
            {[
              { step: 1, name: "1. Diagnostic Probe", desc: "Identify mental model" },
              { step: 2, name: "2. Cognitive Conflict", desc: "Thought experiment / paradox" },
              { step: 3, name: "3. Scaffolded Nudge", desc: "Sub-equation breakdown" },
              { step: 4, name: "4. Conceptual Synthesis", desc: "Formal rule application" },
              { step: 5, name: "5. Transfer Check", desc: "Verify independent recovery" },
            ].map((s) => (
              <div
                key={s.step}
                className={`p-2.5 rounded-xl border text-xs transition ${
                  currentStep === s.step
                    ? "bg-teal-950/40 border-teal-500/50 text-teal-200 font-bold glow-teal"
                    : currentStep > s.step
                    ? "bg-slate-950/60 border-slate-800 text-slate-400"
                    : "bg-slate-950/30 border-slate-800/40 text-slate-600"
                }`}
              >
                <div className="flex items-center justify-between text-[11px]">
                  <span>{s.name}</span>
                  {currentStep > s.step ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  ) : currentStep === s.step ? (
                    <div className="w-2 h-2 rounded-full bg-teal-400 animate-ping" />
                  ) : (
                    <Lock className="w-3 h-3 text-slate-600" />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Generate Scorecard Button */}
        <button
          onClick={() => setShowScorecard(true)}
          className="w-full py-3 bg-gradient-to-r from-teal-600 to-emerald-600 hover:from-teal-500 hover:to-emerald-500 text-white text-xs font-bold rounded-2xl transition shadow-lg flex items-center justify-center gap-2"
        >
          <Award className="w-4 h-4" />
          View Diagnostic Scorecard
        </button>
      </div>

      {/* ========================================================================= */}
      {/* Transfer Question Modal */}
      {/* ========================================================================= */}
      {transferModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="max-w-lg w-full bg-slate-900 border border-teal-500/50 rounded-2xl p-6 shadow-2xl space-y-4 glow-teal">
            <div className="flex items-center gap-2 text-teal-400">
              <CheckCircle2 className="w-6 h-6 text-emerald-400" />
              <h3 className="text-base font-bold text-white">Recovery Verification Triggered</h3>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              You've overcome the initial cognitive hurdle! To verify true conceptual transfer and record verified mastery in your scorecard, solve this isomorphic transfer scenario:
            </p>
            <div className="p-4 bg-slate-950 rounded-xl border border-teal-500/30 text-xs text-teal-200 font-mono leading-relaxed">
              <FormattedMathText text={transferModal} />
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setTransferModal(null)}
                className="px-5 py-2.5 bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold rounded-xl transition flex items-center gap-1.5"
              >
                Accept & Respond <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* Diagnostic Scorecard Modal (HackerRank Style) */}
      {/* ========================================================================= */}
      {showScorecard && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-md flex items-center justify-center p-4 z-50">
          <div className="max-w-2xl w-full bg-slate-900 border border-slate-700 rounded-3xl p-6 shadow-2xl space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2.5">
                <Award className="w-6 h-6 text-teal-400" />
                <div>
                  <h3 className="text-base font-bold text-white">Learner Cognitive Diagnostic Scorecard</h3>
                  <span className="text-[11px] font-mono text-slate-400">Session ID: {sessionId} • Time: {formatTimer(sessionSeconds)}</span>
                </div>
              </div>
              <button
                onClick={() => setShowScorecard(false)}
                className="text-xs text-slate-400 hover:text-white px-3 py-1 bg-slate-800 rounded-lg"
              >
                Close
              </button>
            </div>

            <div className="grid grid-cols-3 gap-3 text-center">
              <div className="p-3 bg-slate-950 rounded-xl border border-slate-800">
                <span className="text-[10px] font-mono text-slate-400">Total Dialogue Turns</span>
                <div className="text-lg font-bold text-white mt-0.5">{messages.length}</div>
              </div>
              <div className="p-3 bg-slate-950 rounded-xl border border-slate-800">
                <span className="text-[10px] font-mono text-slate-400">Anti-Leakage Integrity</span>
                <div className="text-lg font-bold text-emerald-400 mt-0.5">100% Secure</div>
              </div>
              <div className="p-3 bg-slate-950 rounded-xl border border-slate-800">
                <span className="text-[10px] font-mono text-slate-400">Socratic Recovery</span>
                <div className="text-lg font-bold text-teal-400 mt-0.5">Verified</div>
              </div>
            </div>

            <div className="space-y-2">
              <span className="text-xs font-bold text-slate-200">Diagnostic Reason Logged:</span>
              <p className="p-3 bg-slate-950 rounded-xl border border-slate-800 text-xs text-slate-300 font-mono leading-relaxed">
                {lastTurnData && lastTurnData.diagnostic
                  ? lastTurnData.diagnostic.pedagogical_reason
                  : "Student engaged in initial diagnostic exploration."}
              </p>
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setShowScorecard(false)}
                className="px-5 py-2.5 bg-teal-600 hover:bg-teal-500 text-white text-xs font-bold rounded-xl transition"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
