import React, { useEffect, useRef } from 'react';

export const SilverOrb = ({ state, onClick, size = 260, label = 'Talk to the tutor' }) => {
  // state: 'idle' | 'listening' | 'thinking' | 'speaking'
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let animationFrameId;
    let time = 0;

    const render = () => {
      time += 0.03;
      ctx.clearRect(0, 0, size, size);

      const cx = size / 2;
      const cy = size / 2;
      const baseRadius = size * 0.32;

      // Dynamic amplitude based on state
      let noiseAmp = 0;
      let pulseScale = 1;
      let ringCount = 3;

      if (state === 'listening') {
        noiseAmp = Math.sin(time * 6) * 8 + 6;
        pulseScale = 1 + Math.sin(time * 4) * 0.08;
      } else if (state === 'speaking') {
        noiseAmp = Math.sin(time * 8) * 10 + Math.cos(time * 5) * 6;
        pulseScale = 1 + Math.sin(time * 6) * 0.12;
      } else if (state === 'thinking') {
        noiseAmp = Math.sin(time * 12) * 4;
        pulseScale = 1 + Math.cos(time * 3) * 0.04;
      } else {
        // Idle
        noiseAmp = Math.sin(time * 1.5) * 2;
        pulseScale = 1 + Math.sin(time * 1.5) * 0.02;
      }

      const r = baseRadius * pulseScale;

      // 1. Outer Ambient Glow / Caustics
      const glowGrad = ctx.createRadialGradient(cx, cy, r * 0.5, cx, cy, r * 1.8);
      if (state === 'listening') {
        glowGrad.addColorStop(0, 'rgba(45, 212, 191, 0.35)');
        glowGrad.addColorStop(0.6, 'rgba(20, 184, 166, 0.15)');
        glowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
      } else if (state === 'speaking') {
        glowGrad.addColorStop(0, 'rgba(251, 191, 36, 0.35)');
        glowGrad.addColorStop(0.6, 'rgba(245, 158, 11, 0.15)');
        glowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
      } else if (state === 'thinking') {
        glowGrad.addColorStop(0, 'rgba(168, 85, 247, 0.35)');
        glowGrad.addColorStop(0.6, 'rgba(147, 51, 234, 0.15)');
        glowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
      } else {
        glowGrad.addColorStop(0, 'rgba(226, 232, 240, 0.2)');
        glowGrad.addColorStop(0.7, 'rgba(148, 163, 184, 0.05)');
        glowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
      }
      ctx.fillStyle = glowGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, r * 1.8, 0, Math.PI * 2);
      ctx.fill();

      // 2. Rippling Soundwaves when active
      if (state === 'listening' || state === 'speaking') {
        for (let i = 0; i < ringCount; i++) {
          const ringProgress = (time * 0.8 + i / ringCount) % 1;
          const ringR = r + ringProgress * (size * 0.2);
          const ringAlpha = (1 - ringProgress) * 0.4;

          ctx.beginPath();
          ctx.arc(cx, cy, ringR, 0, Math.PI * 2);
          ctx.strokeStyle = state === 'listening'
            ? `rgba(45, 212, 191, ${ringAlpha})`
            : `rgba(251, 191, 36, ${ringAlpha})`;
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }

      // 3. Fluid Deformed Metallic Sphere Outline
      ctx.beginPath();
      const points = 64;
      for (let i = 0; i <= points; i++) {
        const theta = (i / points) * Math.PI * 2;
        // Organic liquid noise
        const n1 = Math.sin(theta * 4 + time * 3) * noiseAmp;
        const n2 = Math.cos(theta * 3 - time * 2) * (noiseAmp * 0.5);
        const radiusWithNoise = r + n1 + n2;

        const x = cx + Math.cos(theta) * radiusWithNoise;
        const y = cy + Math.sin(theta) * radiusWithNoise;

        if (i === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.closePath();

      // 4. Chrome / Metallic Liquid Gradient Fill
      const grad = ctx.createRadialGradient(
        cx - r * 0.35, cy - r * 0.35, r * 0.05,
        cx, cy, r * 1.1
      );

      if (state === 'listening') {
        grad.addColorStop(0, '#ffffff');
        grad.addColorStop(0.2, '#e2e8f0');
        grad.addColorStop(0.5, '#2dd4bf');
        grad.addColorStop(0.8, '#0f766e');
        grad.addColorStop(1, '#042f2e');
      } else if (state === 'speaking') {
        grad.addColorStop(0, '#ffffff');
        grad.addColorStop(0.2, '#fef3c7');
        grad.addColorStop(0.5, '#f59e0b');
        grad.addColorStop(0.8, '#b45309');
        grad.addColorStop(1, '#451a03');
      } else if (state === 'thinking') {
        grad.addColorStop(0, '#ffffff');
        grad.addColorStop(0.2, '#f3e8ff');
        grad.addColorStop(0.5, '#c084fc');
        grad.addColorStop(0.8, '#7e22ce');
        grad.addColorStop(1, '#3b0764');
      } else {
        // Pure Liquid Silver
        grad.addColorStop(0, '#ffffff');
        grad.addColorStop(0.15, '#f8fafc');
        grad.addColorStop(0.35, '#cbd5e1');
        grad.addColorStop(0.65, '#64748b');
        grad.addColorStop(0.85, '#334155');
        grad.addColorStop(1, '#0f172a');
      }

      ctx.fillStyle = grad;
      ctx.fill();

      // 5. Specular Highlights & Metallic Reflections (Gleam)
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(
        cx - r * 0.32,
        cy - r * 0.32,
        r * 0.38,
        r * 0.22,
        Math.PI / 4,
        0,
        Math.PI * 2
      );
      const specGrad = ctx.createLinearGradient(
        cx - r * 0.5, cy - r * 0.5,
        cx - r * 0.1, cy - r * 0.1
      );
      specGrad.addColorStop(0, 'rgba(255, 255, 255, 0.95)');
      specGrad.addColorStop(0.5, 'rgba(255, 255, 255, 0.4)');
      specGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = specGrad;
      ctx.fill();
      ctx.restore();

      // Bottom rim light
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(
        cx + r * 0.25,
        cy + r * 0.35,
        r * 0.35,
        r * 0.15,
        -Math.PI / 4,
        0,
        Math.PI * 2
      );
      const rimGrad = ctx.createLinearGradient(
        cx, cy + r * 0.2,
        cx + r * 0.3, cy + r * 0.45
      );
      rimGrad.addColorStop(0, 'rgba(255, 255, 255, 0)');
      rimGrad.addColorStop(1, 'rgba(255, 255, 255, 0.35)');
      ctx.fillStyle = rimGrad;
      ctx.fill();
      ctx.restore();

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [state, size]);

  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      aria-label={label}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onClick?.();
        }
      }}
      className="relative flex items-center justify-center cursor-pointer select-none group transition-transform duration-300 hover:scale-105 active:scale-95 rounded-full focus:outline-none focus-visible:ring-4 focus-visible:ring-cyan-400/60"
      style={{ width: size, height: size }}
    >
      <canvas
        ref={canvasRef}
        width={size}
        height={size}
        className="drop-shadow-[0_20px_40px_rgba(0,0,0,0.8)]"
      />
    </div>
  );
};
