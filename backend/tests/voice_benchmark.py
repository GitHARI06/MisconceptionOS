"""Voice pipeline benchmark: run this on the machine that runs the tutor.

It measures, with the real engines:
  * Edge-TTS: time to the first audio chunk (what the learner waits for)
    and total synthesis time, per voice.
  * Whisper: word error rate (WER) and latency for each model size, with and
    without the physics vocabulary prompt the tutor uses, optionally with
    background noise mixed in.

Test speech is produced by Edge-TTS in several accents (US, Indian, British),
so no recordings are needed.

Usage (from the backend folder):
    python tests/voice_benchmark.py
    python tests/voice_benchmark.py --models base.en small.en --noise-snr 15
    python tests/voice_benchmark.py --device cpu --quick
"""

import argparse
import asyncio
import os
import re
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DISABLE_WHISPER_WARMUP", "true")

from app.audio_service import PHYSICS_PROMPT, speech_text  # noqa: E402

UTTERANCES = [
    "There must be a forward force of twelve newtons pushing it or it will stop.",
    "The net force is zero so the puck keeps moving because of inertia.",
    "Let's learn thermodynamics.",
    "What is entropy and why does it always increase?",
    "They hit the ground at the same time because both objects are round.",
    "Acceleration is zero so by F equals m a the net force must be zero.",
    "I don't know, I haven't learned this yet.",
    "Can you explain the difference between velocity and acceleration?",
    "Heat flows from the hot coffee to the colder room.",
    "What happens to the refraction of light when it enters glass?",
    "Voltage equals current times resistance according to Ohm's law.",
    "Its speed stays the same because no net force acts on the probe.",
    "Is momentum conserved when two carts collide?",
    "Gravity accelerates everything at nine point eight meters per second squared.",
    "Why doesn't the feather fall as fast as the hammer on Earth?",
]
VOICES = ["en-US-AndrewMultilingualNeural", "en-IN-PrabhatNeural", "en-IN-NeerjaNeural", "en-GB-RyanNeural"]

_NUMBERS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}


def normalize(text: str):
    text = text.lower().replace("'", "")
    text = re.sub(r"(\d)\.(\d)", r"\1 point \2", text)
    words = re.findall(r"[a-z0-9]+", text)
    return [_NUMBERS.get(w, w) for w in words]


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)] / len(ref)


async def synthesize(text: str, voice: str):
    import edge_tts
    t0 = time.perf_counter()
    first = None
    audio = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            if first is None:
                first = time.perf_counter() - t0
            audio.extend(chunk["data"])
    return bytes(audio), first or 0.0, time.perf_counter() - t0


def add_noise(path: str, snr_db: float):
    import numpy as np
    from faster_whisper import decode_audio
    audio = decode_audio(path)
    power = float(np.mean(audio ** 2)) or 1e-9
    noise = np.random.default_rng(0).normal(0, (power / (10 ** (snr_db / 10))) ** 0.5, audio.shape)
    return (audio + noise).astype("float32")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=["tiny.en", "base.en", "small.en"])
    parser.add_argument("--voices", nargs="+", default=VOICES)
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--noise-snr", type=float, default=None, help="mix in white noise at this SNR (dB), e.g. 15")
    parser.add_argument("--quick", action="store_true", help="5 sentences, 2 voices")
    args = parser.parse_args()

    utterances = UTTERANCES[:5] if args.quick else UTTERANCES
    voices = args.voices[:2] if args.quick else args.voices
    workdir = tempfile.mkdtemp(prefix="voicebench_")

    print(f"\n== Text-to-speech (Edge) : {len(utterances)} sentences x {len(voices)} voices")
    samples = []
    tts_first, tts_total = [], []
    for voice in voices:
        for i, text in enumerate(utterances):
            try:
                audio, first, total = asyncio.run(synthesize(speech_text(text), voice))
            except Exception as exc:
                print(f"   ! {voice}: {exc}")
                break
            path = os.path.join(workdir, f"{voice}_{i}.mp3")
            with open(path, "wb") as f:
                f.write(audio)
            samples.append((voice, text, path))
            tts_first.append(first)
            tts_total.append(total)
    if not samples:
        sys.exit("Edge-TTS produced no audio (is this machine online?).")
    print(f"   first audio chunk: median {statistics.median(tts_first)*1000:.0f} ms, "
          f"p90 {sorted(tts_first)[int(len(tts_first)*0.9)-1]*1000:.0f} ms")
    print(f"   full sentence:     median {statistics.median(tts_total)*1000:.0f} ms")

    from faster_whisper import WhisperModel
    device = args.device
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    compute = "float16" if device == "cuda" else "int8"
    noise_note = f", white noise at {args.noise_snr:g} dB SNR" if args.noise_snr is not None else ""
    print(f"\n== Speech-to-text (Whisper on {device}{noise_note})")
    print(f"   {'model':<10} {'prompt':<7} {'WER':>6} {'median latency':>15} {'worst sentence'}")

    results = []
    for name in args.models:
        try:
            model = WhisperModel(name, device=device, compute_type=compute)
        except Exception as exc:
            print(f"   {name:<10} could not load: {exc}")
            continue
        for use_prompt in (False, True):
            errors, latencies, worst = [], [], (0.0, "", "")
            for voice, text, path in samples:
                source = add_noise(path, args.noise_snr) if args.noise_snr is not None else path
                t0 = time.perf_counter()
                segments, _ = model.transcribe(
                    source, language="en", beam_size=5 if device == "cuda" else 1,
                    initial_prompt=PHYSICS_PROMPT if use_prompt else None,
                    condition_on_previous_text=False, temperature=0.0, vad_filter=True,
                )
                hypothesis = " ".join(s.text.strip() for s in segments)
                latencies.append(time.perf_counter() - t0)
                error = wer(text, hypothesis)
                errors.append(error)
                if error > worst[0]:
                    worst = (error, text, hypothesis)
            mean_wer = sum(errors) / len(errors)
            results.append((name, use_prompt, mean_wer, statistics.median(latencies)))
            print(f"   {name:<10} {'yes' if use_prompt else 'no':<7} {mean_wer*100:5.1f}% {statistics.median(latencies)*1000:12.0f} ms"
                  f"   {('heard: ' + worst[2][:60]) if worst[0] else '-'}")

    if results:
        best = min(results, key=lambda r: (round(r[2], 3), r[3]))
        print(f"\nMost accurate: {best[0]} {'with' if best[1] else 'without'} the physics prompt "
              f"({best[2]*100:.1f}% WER, {best[3]*1000:.0f} ms). The tutor always uses the prompt.")
        print("Set WHISPER_MODEL_SIZE in backend/.env to choose a model; STT_PREFERENCE=whisper makes "
              "Whisper's transcript win over the browser's.")


if __name__ == "__main__":
    main()
