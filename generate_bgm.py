"""
Procedural Polyphonic Orchestral Historical BGM Generator.
Generates multi-layered classical chord progressions (cellos, violins, tension pads)
for 100% royalty-free, copyright-free historical background music.
"""
import wave
import struct
import math
from pathlib import Path

AUDIO_SAMPLE_RATE = 44100


def create_polyphonic_track(filename: Path, chords: list, duration_per_chord: float = 4.0, total_duration: float = 30.0, track_type: str = "epic"):
    """
    Synthesizes rich multi-layered polyphonic orchestral music.
    Combines sub-bass cello, harmonic minor triad chord pads, and high string shimmer.
    """
    filename.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(AUDIO_SAMPLE_RATE * total_duration)
    
    with wave.open(str(filename), "w") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(AUDIO_SAMPLE_RATE)
        
        frames = []
        for i in range(num_samples):
            t = i / AUDIO_SAMPLE_RATE
            chord_idx = int((t / duration_per_chord) % len(chords))
            freqs = chords[chord_idx]  # [bass, root, third, fifth, octave]
            
            sample_val = 0.0
            
            # 1. Warm Sub-Bass & Cello Drone (rich saw/tri harmonic mix)
            bass_freq = freqs[0]
            cello = math.sin(2 * math.pi * bass_freq * t) * 0.35 + math.sin(2 * math.pi * (bass_freq * 2) * t) * 0.15
            
            # 2. Middle String Triad Chords (warm strings with slow chorus vibrato)
            vibrato = 1.0 + 0.008 * math.sin(2 * math.pi * 5.0 * t)
            mid_strings = 0.0
            for f in freqs[1:4]:
                mid_strings += math.sin(2 * math.pi * (f * vibrato) * t) * 0.18
                mid_strings += math.sin(2 * math.pi * (f * 1.003) * t) * 0.08  # subtle stereo detune
                
            # 3. High Shimmer Violin Swell
            high_freq = freqs[-1]
            swell = (math.sin(2 * math.pi * 0.25 * t) + 1.0) / 2.0
            high_shimmer = math.sin(2 * math.pi * high_freq * t) * (0.08 * swell)
            
            # 4. Rhythmic Heartbeat / Tension Pulse (60 BPM)
            pulse_env = math.exp(-6.0 * ((t * 1.2) % 1.0))
            pulse = math.sin(2 * math.pi * 65.0 * t) * pulse_env * 0.20 if track_type == "epic" else 0.0
            
            sample_val = cello + mid_strings + high_shimmer + pulse
            sample_val = max(-1.0, min(1.0, sample_val * 0.75))
            
            int_val = int(sample_val * 32767.0)
            frames.append(struct.pack("<hh", int_val, int_val))
            
        wav_file.writeframes(b"".join(frames))
    print(f"[+] Generated rich BGM track: {filename.name} ({total_duration}s)")


def generate_all_bgm_tracks(music_dir: Path):
    # Track 1: Epic Historical Strings (D minor progression: Dm -> Bb -> Gm -> A7)
    dm_chords = [
        [73.42, 146.83, 174.61, 220.00, 293.66],  # Dm (D2, D3, F3, A3, D4)
        [58.27, 116.54, 146.83, 174.61, 233.08],  # Bb (Bb1, Bb2, D3, F3, Bb3)
        [49.00, 98.00, 116.54, 146.83, 196.00],   # Gm (G1, G2, Bb2, D3, G3)
        [55.00, 110.00, 138.59, 164.81, 220.00]   # A (A1, A2, C#3, E3, A3)
    ]
    create_polyphonic_track(music_dir / "epic_history_strings.wav", dm_chords, 3.5, 32.0, "epic")

    # Track 2: Mysterious Curiosity & Intrigue (A minor tension: Am -> F -> Dm -> E)
    am_chords = [
        [55.00, 110.00, 130.81, 164.81, 220.00],  # Am
        [43.65, 87.31, 110.00, 130.81, 174.61],   # F
        [36.71, 73.42, 87.31, 110.00, 146.83],    # Dm
        [41.20, 82.41, 103.83, 123.47, 164.81]    # E
    ]
    create_polyphonic_track(music_dir / "mysterious_curiosity_tension.wav", am_chords, 4.0, 32.0, "mystery")

    # Track 3: Victorian Intrigue & Classical Chamber (C minor: Cm -> Ab -> Fm -> G)
    cm_chords = [
        [65.41, 130.81, 155.56, 196.00, 261.63],  # Cm
        [51.91, 103.83, 130.81, 155.56, 207.65],  # Ab
        [43.65, 87.31, 103.83, 130.81, 174.61],   # Fm
        [49.00, 98.00, 123.47, 146.83, 196.00]    # G
    ]
    create_polyphonic_track(music_dir / "victorian_intrigue_chamber.wav", cm_chords, 3.0, 32.0, "chamber")


if __name__ == "__main__":
    generate_all_bgm_tracks(Path(r"C:\Users\jisha\OneDrive\Desktop\yt automation\assets\music"))
