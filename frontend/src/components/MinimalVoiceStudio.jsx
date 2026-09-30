import React, { useState, useRef, useEffect } from 'react';
import { SilverOrb } from './SilverOrb';
import { FormattedMathText } from '../utils/katexHelper';
import { Volume2, CheckCircle2, ArrowRight, BookOpen, Lightbulb, RotateCcw, Snail, Shuffle, Gauge } from 'lucide-react';
import {
  GREETING, VAD, pickRecorderType, bestAlternative, echoRatio, stripEcho, isFiller, blobToDataUrl, browserSpeak,
  timeGreeting, THINKING_PHASES, NUDGE, ALL_ACKS, pickAck, ACK_DELAY_MS,
} from './voiceEngine';

const MIC_CONSTRAINTS = {
  audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

export const MinimalVoiceStudio = ({ sessionId, resumeTopic = null, onStateUpdate, learnerName = null }) => {
  const [orbState, setOrbState] = useState('idle'); // 'idle' | 'listening' | 'thinking' | 'speaking'
  const [liveTranscript, setLiveTranscript] = useState('');
  const [tutorSpeech, setTutorSpeech] = useState(GREETING);
  const [transferModal, setTransferModal] = useState(null);
  const [sources, setSources] = useState([]);
  const [notice, setNotice] = useState('');
  const [phase, setPhase] = useState('GREETING');
  const [speechRate, setSpeechRate] = useState(0);
  const [greetingName, setGreetingName] = useState(learnerName);

  // Latest props for callbacks created earlier (avoids stale closures).
  const sessionIdRef = useRef(sessionId);
  const resumeTopicRef = useRef(resumeTopic);
  const onStateUpdateRef = useRef(onStateUpdate);
  sessionIdRef.current = sessionId;
  resumeTopicRef.current = resumeTopic;
  onStateUpdateRef.current = onStateUpdate;

  const micStreamRef = useRef(null);
  const recognitionRef = useRef(undefined);      // undefined = not created yet, null = unsupported
  const recognitionWantedRef = useRef(false);
  const recognitionActiveRef = useRef(false);
  const finalizeResolverRef = useRef(null);
  const finalTextRef = useRef('');
  const interimTextRef = useRef('');
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const vadTokenRef = useRef(0);
  const audioContextRef = useRef(null);
  const listeningRef = useRef(false);
  const speakingRef = useRef(false);
  const processingRef = useRef(false);
  const speechIdRef = useRef(0);
  const currentAudioRef = useRef(null);
  const currentSpeechRef = useRef('');
  const lastReplyRef = useRef({ text: GREETING, url: null, b64: null });
  const handsFreeRef = useRef(false);
  const preferServerSttRef = useRef(false);
  const mountedRef = useRef(true);
  const learnerStartedRef = useRef(false);
  const echoGuardUntilRef = useRef(0);
  const echoDropsRef = useRef(0);
  const phaseRef = useRef('GREETING');
  const speechRateRef = useRef(0);
  const nudgeCountRef = useRef(0);
  const ackAudioRef = useRef(null);
  const neuralVoiceOkRef = useRef(true);
  const learnerNameRef = useRef(learnerName);
  learnerNameRef.current = learnerName;

  useEffect(() => {
    if (resumeTopic) {
      setTutorSpeech(`We’re continuing with ${resumeTopic}. Ask your next question or tell me what you would like to revisit.`);
      setLiveTranscript(`Resumed concept: ${resumeTopic}`);
      setSources([]);
    }
  }, [resumeTopic]);

  // ---------------------------------------------------------------- recognition
  const ensureRecognition = () => {
    if (recognitionRef.current !== undefined) return recognitionRef.current;
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      recognitionRef.current = null;
      return null;
    }
    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';
    recognition.maxAlternatives = 3;

    recognition.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) {
          const best = bestAlternative(result);
          if (!best) continue;
          // Late echo of the tutor's last words, delivered after it stopped.
          if (!speakingRef.current && Date.now() < echoGuardUntilRef.current
              && !stripEcho(best.text, currentSpeechRef.current)) continue;
          if (speakingRef.current) handleSpeechDuringTutor(best.text);
          else finalTextRef.current = `${finalTextRef.current} ${best.text}`.trim();
        } else {
          interim += result[0]?.transcript || '';
        }
      }
      interimTextRef.current = interim.trim();
      if (listeningRef.current) {
        const shown = `${finalTextRef.current} ${interimTextRef.current}`.trim();
        setLiveTranscript(shown || 'Listening…');
      }
    };
    recognition.onend = () => {
      recognitionActiveRef.current = false;
      if (finalizeResolverRef.current) {
        const resolve = finalizeResolverRef.current;
        finalizeResolverRef.current = null;
        resolve();
      } else if (recognitionWantedRef.current) {
        window.setTimeout(startRecognition, 80);   // Chrome ends sessions on its own; keep listening
      }
    };
    recognition.onerror = (event) => {
      if (event?.error === 'not-allowed' || event?.error === 'service-not-allowed') {
        recognitionWantedRef.current = false;
        recognitionRef.current = null;
      }
    };
    recognitionRef.current = recognition;
    return recognition;
  };

  const startRecognition = () => {
    const recognition = ensureRecognition();
    if (!recognition) return;
    recognitionWantedRef.current = true;
    if (recognitionActiveRef.current) return;
    try {
      recognition.start();
      recognitionActiveRef.current = true;
    } catch (e) { /* already running */ }
  };

  // Like stop(), but Chrome discards results still in flight. Used when the
  // tutor stops talking, so the transcript of its own voice (which Chrome
  // delivers a moment later) is never mistaken for the learner.
  const abortRecognition = () => {
    recognitionWantedRef.current = false;
    finalTextRef.current = '';
    interimTextRef.current = '';
    if (recognitionRef.current && recognitionActiveRef.current) {
      try { recognitionRef.current.abort(); } catch (e) { /* ignore */ }
    }
  };

  const stopRecognition = () => {
    recognitionWantedRef.current = false;
    if (recognitionRef.current && recognitionActiveRef.current) {
      try { recognitionRef.current.stop(); } catch (e) { /* ignore */ }
    }
  };

  // Chrome delivers the final words a moment after the speaker stops. Wait
  // for them (bounded) so the end of the sentence is not lost.
  const waitForFinalTranscript = (maxMs = 700) => new Promise((resolve) => {
    const recognition = recognitionRef.current;
    if (!recognition || !recognitionActiveRef.current) { resolve(); return; }
    finalizeResolverRef.current = resolve;
    recognitionWantedRef.current = false;
    try { recognition.stop(); } catch (e) { resolve(); }
    window.setTimeout(() => {
      if (finalizeResolverRef.current === resolve) finalizeResolverRef.current = null;
      resolve();
    }, maxMs);
  });

  // ---------------------------------------------------------------- VAD
  const stopVad = () => {
    vadTokenRef.current += 1;
    if (audioContextRef.current) audioContextRef.current.close().catch(() => {});
    audioContextRef.current = null;
  };

  const runVad = async (mode) => {
    stopVad();
    const stream = micStreamRef.current;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!stream || !AudioContextClass) return;
    const token = vadTokenRef.current;
    const context = new AudioContextClass();
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.15;
    context.createMediaStreamSource(stream).connect(analyser);
    await context.resume().catch(() => {});
    if (token !== vadTokenRef.current) { context.close().catch(() => {}); return; }
    audioContextRef.current = context;

    const samples = new Float32Array(analyser.fftSize);
    const started = performance.now();
    let noiseSum = 0;
    let noiseFrames = 0;
    let voiceStart = null;
    let lastVoice = 0;
    let heard = false;

    const tick = () => {
      if (token !== vadTokenRef.current) return;
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
      const rms = Math.sqrt(sum / samples.length);
      const now = performance.now();
      const elapsed = now - started;

      if (mode === 'listen' && elapsed < VAD.calibrateMs) {
        noiseSum += rms;
        noiseFrames += 1;
      } else {
        const floor = Math.min(noiseFrames ? noiseSum / noiseFrames : 0.005, VAD.maxNoiseFloor);
        const threshold = mode === 'speak'
          ? Math.max(VAD.bargeInThreshold, floor * 4)
          : Math.max(VAD.minThreshold, floor * VAD.noiseMultiplier);
        if (rms > threshold) {
          if (voiceStart === null) voiceStart = now;
          lastVoice = now;
          const needed = mode === 'speak' ? VAD.bargeInMs : VAD.minSpeechMs;
          if (now - voiceStart >= needed) {
            if (mode === 'speak') { beginBargeIn(); return; }
            heard = true;
          }
        } else if (voiceStart !== null && !heard && now - lastVoice > 250) {
          voiceStart = null;   // a click or pop, not speech
        }
        // The recogniser hearing words also counts as speech.
        if (mode === 'listen' && (finalTextRef.current || interimTextRef.current)) {
          heard = true;
          if (!lastVoice) lastVoice = now;
        }
        if (mode === 'listen') {
          // While solving a problem, learners pause mid-answer to think.
          const endSilence = THINKING_PHASES.has(phaseRef.current) ? VAD.thinkingEndSilenceMs : VAD.endSilenceMs;
          if (heard && now - lastVoice > endSilence) { finishListening(); return; }
          if (!heard && elapsed > VAD.noSpeechTimeoutMs) {
            if (THINKING_PHASES.has(phaseRef.current) && nudgeCountRef.current === 0) {
              // Like a tutor giving wait-time: one gentle nudge, then keep listening.
              nudgeCountRef.current += 1;
              cancelListening('');
              speak(NUDGE, { url: speakUrl(NUDGE), remember: false });
            } else {
              cancelListening('I didn’t hear anything. Tap the orb when you’re ready to talk.');
            }
            return;
          }
          if (elapsed > VAD.maxUtteranceMs) { finishListening(); return; }
        }
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  // ---------------------------------------------------------------- speaking
  const stopAudio = () => {
    speechIdRef.current += 1;
    if (currentAudioRef.current) {
      currentAudioRef.current.onended = null;
      currentAudioRef.current.onerror = null;
      currentAudioRef.current.pause();
      currentAudioRef.current.removeAttribute('src');
      currentAudioRef.current = null;
    }
    window.speechSynthesis?.cancel();
    speakingRef.current = false;
  };

  const onSpeechStart = (id, viaBrowserVoice = false) => {
    if (id !== speechIdRef.current) return;
    speakingRef.current = true;
    setOrbState('speaking');
    // The browser's own voice is not echo-cancelled, so the microphone would
    // hear the tutor. With it, the learner interrupts by tapping the orb.
    if (micStreamRef.current && !viaBrowserVoice) {
      startRecognition();
      runVad('speak');
    }
  };

  const onSpeechEnd = (id) => {
    if (id !== speechIdRef.current || !mountedRef.current) return;
    speakingRef.current = false;
    currentAudioRef.current = null;
    stopVad();
    abortRecognition();
    echoGuardUntilRef.current = Date.now() + 1500;
    setOrbState('idle');
    // Hands-free: listen again once the tutor has finished.
    if (handsFreeRef.current && micStreamRef.current && !processingRef.current) {
      window.setTimeout(() => {
        if (mountedRef.current && !listeningRef.current && !speakingRef.current && !processingRef.current) startListening();
      }, 150);
    }
  };

  const speakWithBrowser = (text, id) => {
    browserSpeak(text, {
      onStart: () => onSpeechStart(id, true),
      isCurrent: () => id === speechIdRef.current,
    }).then(() => onSpeechEnd(id));
  };

  const speakUrl = (text) => `/api/audio/speak?text=${encodeURIComponent(text)}&rate=${speechRateRef.current}`;

  const stopAck = () => {
    if (ackAudioRef.current) {
      ackAudioRef.current.onended = null;
      ackAudioRef.current.pause();
      ackAudioRef.current = null;
    }
  };

  // "Hmm, let me think about that." while a reply is on its way. Resolves
  // when the acknowledgement has finished (or immediately if none played).
  const playAck = (line) => new Promise((resolve) => {
    if (!neuralVoiceOkRef.current) { resolve(); return; }
    const audio = new Audio(speakUrl(line));
    ackAudioRef.current = audio;
    const done = () => { if (ackAudioRef.current === audio) ackAudioRef.current = null; resolve(); };
    audio.onended = done;
    audio.onerror = done;
    audio.play().catch(done);
  });

  const speak = (text, { url = null, b64 = null, remember = true } = {}) => {
    // Never talk over an open microphone session: close it first so the
    // listening state cannot get stuck.
    if (listeningRef.current) cancelListening('');
    stopAudio();
    const id = speechIdRef.current;
    currentSpeechRef.current = text;
    if (remember) lastReplyRef.current = { text, url, b64 };
    const src = url || (b64 ? `data:audio/mpeg;base64,${b64}` : null);
    if (!src) { speakWithBrowser(text, id); return; }

    // Streaming <audio>: playback starts as soon as the first bytes arrive.
    const audio = new Audio();
    audio.preload = 'auto';
    currentAudioRef.current = audio;
    let started = false;
    audio.onplaying = () => { if (!started) { started = true; onSpeechStart(id); } };
    audio.onended = () => onSpeechEnd(id);
    audio.onerror = () => {
      if (id !== speechIdRef.current) return;
      if (!started) { neuralVoiceOkRef.current = false; speakWithBrowser(text, id); }   // neural voice unavailable
      else onSpeechEnd(id);
    };
    audio.src = src;
    audio.play().catch((error) => {
      if (id !== speechIdRef.current) return;
      if (error?.name === 'NotAllowedError') {
        // Autoplay blocked until the learner interacts with the page.
        setOrbState('idle');
        setNotice('Tap the orb to start talking with your tutor.');
      } else if (!started) {
        speakWithBrowser(text, id);
      }
    });
  };

  const replay = () => {
    const { text, url, b64 } = lastReplyRef.current;
    if (listeningRef.current) cancelListening('');
    speak(text, { url, b64 });
  };

  // ---------------------------------------------------------------- listening
  const getMic = async () => {
    if (micStreamRef.current) return micStreamRef.current;
    const stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
    micStreamRef.current = stream;
    return stream;
  };

  const startListening = async () => {
    if (listeningRef.current || processingRef.current) return;
    learnerStartedRef.current = true;
    stopAudio();
    setNotice('');
    let stream;
    try {
      stream = await getMic();
    } catch (error) {
      setOrbState('idle');
      setNotice('Microphone access is blocked. Allow the microphone for this site in your browser settings, then tap the orb.');
      return;
    }
    if (!mountedRef.current) return;
    finalTextRef.current = '';
    interimTextRef.current = '';
    chunksRef.current = [];

    const type = pickRecorderType();
    let recorder = null;
    if (type !== null) {
      try {
        recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
        recorder.ondataavailable = (event) => { if (event.data.size > 0) chunksRef.current.push(event.data); };
        recorder.start(250);
      } catch (e) {
        recorder = null;
      }
    }
    recorderRef.current = recorder;
    listeningRef.current = true;
    startRecognition();
    setOrbState('listening');
    setLiveTranscript('Listening…');
    runVad('listen');
  };

  const stopRecorder = () => new Promise((resolve) => {
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (!recorder || recorder.state === 'inactive') { resolve(null); return; }
    recorder.onstop = () => resolve(new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' }));
    try { recorder.stop(); } catch (e) { resolve(null); }
  });

  const cancelListening = (message) => {
    if (!listeningRef.current) return;
    listeningRef.current = false;
    stopVad();
    stopRecognition();
    stopRecorder();
    setOrbState('idle');
    setLiveTranscript('');
    if (message) setNotice(message);
  };

  const finishListening = async () => {
    if (!listeningRef.current) return;
    listeningRef.current = false;
    stopVad();
    setOrbState('thinking');
    const [blob] = await Promise.all([stopRecorder(), waitForFinalTranscript(700)]);
    const heard = (finalTextRef.current || interimTextRef.current).trim();
    // Never answer the tutor's own voice picked up by the microphone.
    const text = stripEcho(heard, currentSpeechRef.current);
    if (heard && !text) {
      setOrbState('idle');
      setLiveTranscript('');
      echoDropsRef.current += 1;
      if (echoDropsRef.current <= 2 && handsFreeRef.current) {
        window.setTimeout(() => { if (mountedRef.current && !processingRef.current) startListening(); }, 200);
      } else {
        setNotice('I could only hear my own voice. Try headphones, or tap the orb and speak.');
      }
      return;
    }
    echoDropsRef.current = 0;
    const wantAudio = preferServerSttRef.current || !text;
    const audioB64 = wantAudio && blob && blob.size > 1200 ? await blobToDataUrl(blob) : null;
    if (!text && !audioB64) {
      setOrbState('idle');
      setLiveTranscript('');
      setNotice('I didn’t catch that. Tap the orb and try again.');
      return;
    }
    await sendTurn(text, audioB64);
  };

  // Words heard while the tutor is talking: a real interruption, or the
  // microphone picking up the tutor's own voice?
  const handleSpeechDuringTutor = (text) => {
    const clean = (text || '').trim();
    if (clean.length < 3 || isFiller(clean)) return;
    if (echoRatio(clean, currentSpeechRef.current) >= 0.6) return;
    if (processingRef.current) return;
    stopAudio();
    stopVad();
    stopRecognition();
    sendTurn(clean, null);
  };

  const beginBargeIn = () => {
    if (!speakingRef.current || processingRef.current) return;
    stopAudio();
    stopVad();
    stopRecognition();
    setLiveTranscript('Listening…');
    startListening();
  };

  // Tap alternatives to the classroom requests the tutor understands by voice.
  const quickRequest = (text) => {
    learnerStartedRef.current = true;
    if (processingRef.current) return;
    if (listeningRef.current) cancelListening('');
    stopAudio();
    sendTurn(text, null);
  };

  const handleOrbClick = () => {
    if (orbState === 'listening') finishListening();
    else if (orbState === 'speaking') beginBargeIn();
    else if (orbState === 'idle') startListening();
  };

  // ---------------------------------------------------------------- turns
  const sendTurn = async (text, audioB64) => {
    processingRef.current = true;
    nudgeCountRef.current = 0;
    setOrbState('thinking');
    setNotice('');
    if (text) setLiveTranscript(`"${text}"`);
    let ackPlayback = Promise.resolve();
    const ackTimer = window.setTimeout(() => {
      if (processingRef.current && mountedRef.current) ackPlayback = playAck(pickAck(text, phaseRef.current));
    }, ACK_DELAY_MS);
    try {
      const res = await fetch('/api/chat/turn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          challenge_id: 'freeform_inquiry',
          unit_id: 'physics_mechanics',
          text: text || null,
          audio_base64: audioB64 || null,
          topic: resumeTopicRef.current || null,
          voice_mode: 'stream',
          learner_name: learnerNameRef.current || null,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      window.clearTimeout(ackTimer);
      if (!mountedRef.current) return;
      if (data.echo_detected) {
        // The server recognised the tutor's own voice: just keep listening.
        stopAck();
        processingRef.current = false;
        setOrbState('idle');
        setLiveTranscript('');
        if (handsFreeRef.current) window.setTimeout(() => { if (mountedRef.current) startListening(); }, 200);
        return;
      }
      phaseRef.current = data.lesson_phase;
      setPhase(data.lesson_phase);
      speechRateRef.current = data.speech_rate || 0;
      setSpeechRate(data.speech_rate || 0);
      if (data.learner_name) setGreetingName(data.learner_name);
      setLiveTranscript(data.user_utterance ? `"${data.user_utterance}"` : '');
      setTutorSpeech(data.tutor_text);
      setSources(data.sources || []);
      if (data.transfer_ready && data.transfer_question) setTransferModal(data.transfer_question);
      onStateUpdateRef.current?.(data);
      // Let a started "let me think" finish naturally (never cut mid-word).
      await Promise.race([ackPlayback, new Promise((r) => window.setTimeout(r, 2500))]);
      stopAck();
      processingRef.current = false;
      speak(data.tutor_text, { url: data.tts_url, b64: data.audio_base64 });
    } catch (err) {
      console.warn('Turn processing fallback:', err);
      window.clearTimeout(ackTimer);
      stopAck();
      processingRef.current = false;
      if (!mountedRef.current) return;
      const fallback = 'Sorry, I lost my connection for a moment. Could you say that again?';
      setTutorSpeech(fallback);
      setSources([]);
      speak(fallback);
    }
  };

  // ---------------------------------------------------------------- boot
  useEffect(() => {
    mountedRef.current = true;
    fetch('/api/audio/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((status) => { preferServerSttRef.current = Boolean(status?.prefer_server_stt); })
      .catch(() => {});

    // Greeting: streamed neural voice (cached server-side after first use).
    // Skipped if the learner already tapped the orb and started talking.
    const bootTimer = window.setTimeout(async () => {
      let greeting = { text: GREETING, tts_url: `/api/audio/speak?text=${encodeURIComponent(GREETING)}` };
      try {
        const res = await fetch('/api/tutor/session-start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessionIdRef.current,
            learner_name: learnerNameRef.current || null,
            hour: new Date().getHours(),
            voice_mode: 'stream',
          }),
        });
        if (res.ok) {
          greeting = await res.json();
          speechRateRef.current = greeting.speech_rate || 0;
          setSpeechRate(greeting.speech_rate || 0);
          if (greeting.learner_name) setGreetingName(greeting.learner_name);
        }
      } catch (e) { /* offline: local greeting */ }
      if (!mountedRef.current || learnerStartedRef.current) return;
      phaseRef.current = 'GREETING';
      setPhase('GREETING');
      setTutorSpeech(greeting.text);
      speak(greeting.text, { url: greeting.tts_url });
      // Warm the server's voice cache so "let me think" plays instantly later.
      // One phrase at a time, after the greeting, so it never competes with it.
      window.setTimeout(async () => {
        for (const line of [...ALL_ACKS, NUDGE]) {
          if (!mountedRef.current) return;
          try { await (await fetch(speakUrl(line))).arrayBuffer(); } catch (e) { /* optional */ }
        }
      }, 6000);
    }, 250);

    // Ask for the microphone up front so the lesson can run hands-free.
    if (navigator.mediaDevices?.getUserMedia) {
      getMic()
        .then(() => {
          if (!mountedRef.current) return;
          handsFreeRef.current = true;
          if (speakingRef.current) { startRecognition(); runVad('speak'); }
        })
        .catch(() => { /* the learner can still tap the orb later */ });
    }

    return () => {
      mountedRef.current = false;
      window.clearTimeout(bootTimer);
      listeningRef.current = false;
      stopAck();
      stopAudio();
      stopVad();
      stopRecognition();
      stopRecorder();
      micStreamRef.current?.getTracks().forEach((track) => track.stop());
      micStreamRef.current = null;
    };
  }, []);

  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-140px)] max-w-3xl mx-auto px-4 py-8 text-center select-none space-y-8 animate-in fade-in duration-500">
      {/* Clean Minimal Headline */}
      <div className="space-y-2">
        <h1 className="text-3xl sm:text-4xl font-normal tracking-tight text-slate-100">
          {timeGreeting()}{greetingName ? `, ${greetingName}` : ''}. Let’s learn together.
        </h1>
        <p className="text-xs text-slate-500 font-mono">
          Tap the orb and talk to me like you would to a tutor. Ask for a hint, say “slower”, or “say that again” anytime.
        </p>
      </div>

      {/* The Animated Clickable Silver Orb */}
      <div className="flex flex-col items-center justify-center space-y-4">
        <SilverOrb
          state={orbState}
          onClick={handleOrbClick}
          size={290}
          label={{ listening: 'Stop listening', speaking: 'Interrupt the tutor', thinking: 'Tutor is thinking' }[orbState] || 'Talk to the tutor'}
        />

        {/* State Label */}
        <span className="text-xs font-mono tracking-widest text-slate-400 uppercase font-medium">
          {orbState === 'listening'
            ? '● Listening (auto-stops after silence)'
            : orbState === 'thinking'
            ? '✦ Formulating Teacher Response...'
            : orbState === 'speaking'
            ? '▶ Speaking (speak to interrupt)'
            : 'Click Silver Orb to Speak'}
        </span>
      </div>

      {/* Dynamic Subtitle / Dialogue Area */}
      <div className="w-full max-w-2xl space-y-4">
        {notice && (
          <div role="status" className="p-3 bg-amber-950/30 border border-amber-800/50 rounded-2xl text-xs text-amber-200 max-w-lg mx-auto">
            {notice}
          </div>
        )}

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
                onClick={replay}
                className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-teal-300 font-mono transition"
              >
                <Volume2 className="w-3.5 h-3.5" /> Replay Voice
              </button>
            </div>
            <div data-testid="tutor-speech" aria-live="polite">
              <FormattedMathText text={tutorSpeech} />
            </div>
            {sources.length > 0 && (
              <div data-testid="tutor-sources" className="mt-4 pt-3 border-t border-slate-800 flex flex-wrap items-center gap-2">
                <span className="flex items-center gap-1 text-[10px] font-mono uppercase tracking-wider text-slate-500">
                  <BookOpen className="w-3.5 h-3.5" /> From your library
                </span>
                {sources.map((source) => (
                  <span
                    key={`${source.document_id}-${source.page}`}
                    title={source.snippet}
                    className="rounded-full border border-cyan-800/60 bg-cyan-950/30 px-2.5 py-0.5 text-[11px] text-cyan-200"
                  >
                    {source.title} · p.{source.page}
                  </span>
                ))}
              </div>
            )}
            <div data-testid="tutor-actions" className="mt-4 flex flex-wrap gap-2" aria-label="Quick requests">
              {THINKING_PHASES.has(phase) && (
                <button type="button" disabled={orbState === 'thinking'} onClick={() => quickRequest('Can I get a hint?')} className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-[11px] text-slate-300 transition hover:border-teal-500/60 hover:text-teal-200 disabled:opacity-40 flex items-center gap-1.5">
                  <Lightbulb className="w-3.5 h-3.5" /> Hint
                </button>
              )}
              <button type="button" disabled={orbState === 'thinking'} onClick={replay} className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-[11px] text-slate-300 transition hover:border-teal-500/60 hover:text-teal-200 disabled:opacity-40 flex items-center gap-1.5">
                <RotateCcw className="w-3.5 h-3.5" /> Say it again
              </button>
              {phase !== 'GREETING' && (
                <button type="button" disabled={orbState === 'thinking'} onClick={() => quickRequest('Can you explain it differently?')} className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-[11px] text-slate-300 transition hover:border-teal-500/60 hover:text-teal-200 disabled:opacity-40 flex items-center gap-1.5">
                  <Shuffle className="w-3.5 h-3.5" /> Explain differently
                </button>
              )}
              {speechRate < 0 ? (
                <button type="button" disabled={orbState === 'thinking'} onClick={() => quickRequest('Normal speed please')} className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-[11px] text-slate-300 transition hover:border-teal-500/60 hover:text-teal-200 disabled:opacity-40 flex items-center gap-1.5">
                  <Gauge className="w-3.5 h-3.5" /> Normal speed
                </button>
              ) : (
                <button type="button" disabled={orbState === 'thinking'} onClick={() => quickRequest('Please speak a bit slower')} className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-[11px] text-slate-300 transition hover:border-teal-500/60 hover:text-teal-200 disabled:opacity-40 flex items-center gap-1.5">
                  <Snail className="w-3.5 h-3.5" /> Slower
                </button>
              )}
            </div>
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
