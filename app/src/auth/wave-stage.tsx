import { useEffect, useRef } from 'react';

const LAYERS = [
  { amp: 34, freq: 1.4, speed: 0.6, phase: 0, alpha: 0.9, width: 2.5, y: 0.5 },
  { amp: 24, freq: 2.2, speed: -0.45, phase: 1.7, alpha: 0.45, width: 2, y: 0.52 },
  { amp: 46, freq: 1.0, speed: 0.3, phase: 3.1, alpha: 0.25, width: 1.5, y: 0.48 },
  { amp: 16, freq: 3.1, speed: 0.9, phase: 0.6, alpha: 0.3, width: 1.5, y: 0.54 },
];

/** The brand panel's animated sound wave around the logo; typing anywhere on the page makes it swell. */
export function WaveStage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    let w = 0, h = 0, t = 0, energy = 0, frame = 0;

    const onInput = () => { energy = Math.min(1, energy + 0.3); };
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (reduceMotion) draw();
    };
    function draw() {
      const css = getComputedStyle(canvas);
      const from = css.getPropertyValue('--primary').trim();
      const to = css.getPropertyValue('--highlight').trim();
      const stroke = ctx!.createLinearGradient(0, 0, w, 0);
      stroke.addColorStop(0, 'transparent');
      stroke.addColorStop(0.2, from);
      stroke.addColorStop(0.8, to);
      stroke.addColorStop(1, 'transparent');
      ctx!.clearRect(0, 0, w, h);
      for (const L of LAYERS) {
        ctx!.beginPath();
        for (let x = 0; x <= w; x += 4) {
          const u = x / w;
          const breathe = 0.75 + 0.25 * Math.sin(t * 0.7 + L.phase);
          const y = h * L.y + Math.sin(u * Math.PI * 2 * L.freq + t * L.speed + L.phase) * L.amp * (1 + energy * 1.6) * Math.sin(Math.PI * u) * breathe;
          if (x) ctx!.lineTo(x, y);
          else ctx!.moveTo(x, y);
        }
        ctx!.globalAlpha = L.alpha;
        ctx!.lineWidth = L.width;
        ctx!.strokeStyle = stroke;
        ctx!.shadowColor = from;
        ctx!.shadowBlur = 14;
        ctx!.stroke();
      }
      ctx!.globalAlpha = 1;
    }
    const loop = () => {
      t += 0.016;
      energy *= 0.965;
      draw();
      frame = requestAnimationFrame(loop);
    };

    resize();
    window.addEventListener('resize', resize);
    document.addEventListener('input', onInput);
    if (!reduceMotion) frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', resize);
      document.removeEventListener('input', onInput);
    };
  }, []);

  return (
    <div
      aria-hidden
      className="relative h-72 overflow-hidden rounded-2xl border bg-[radial-gradient(420px_220px_at_50%_55%,color-mix(in_oklab,var(--primary)_18%,transparent),transparent_70%)]"
    >
      <canvas ref={canvasRef} className="absolute inset-0 size-full" />
      <img src="favicon.svg" alt="" className="absolute top-1/2 left-1/2 size-28 -translate-x-1/2 -translate-y-1/2 drop-shadow-[0_0_24px_color-mix(in_oklab,var(--primary)_45%,transparent)]" />
    </div>
  );
}
