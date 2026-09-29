import React from 'react';

export const AudioWaveform = ({ isListening, isSpeaking }) => {
  return (
    <div className="flex items-center justify-center space-x-1.5 h-10 px-4 py-2 bg-slate-900/80 rounded-full border border-slate-800">
      <span className="text-xs font-mono mr-2 text-slate-400 uppercase tracking-wider">
        {isListening ? "Listening..." : isSpeaking ? "Tutor Speaking..." : "Voice Ready"}
      </span>
      {[...Array(9)].map((_, i) => (
        <span
          key={i}
          className={`w-1 rounded-full transition-all duration-150 ${
            isListening
              ? "bg-teal-400 animate-pulse"
              : isSpeaking
              ? "bg-amber-400 animate-bounce"
              : "bg-slate-700 h-2"
          }`}
          style={{
            height: isListening
              ? `${Math.sin(i + Date.now() / 200) * 12 + 16}px`
              : isSpeaking
              ? `${Math.cos(i + Date.now() / 150) * 14 + 18}px`
              : '8px',
            animationDelay: `${i * 100}ms`
          }}
        />
      ))}
    </div>
  );
};
