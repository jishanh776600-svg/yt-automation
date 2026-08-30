"""
Audio Mixer Engine.
Integrates user-provided local BGM library with AI mood classification,
multidimensional narrative context matching (topic, emotional tone, intensity, pacing, atmosphere, seriousness),
and explicit 3-stage audio production:
  Stage A: Narration-only audio
  Stage B: BGM-only audio (trimmed, looped, volume adjusted, faded)
  Stage C: Final master mixed audio (-14 LUFS normalized)
"""
import os
import json
import uuid
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from config.settings import MUSIC_DIR, SFX_DIR, VOICE_DIR, RENDERS_DIR, FFMPEG_EXE, GEMINI_API_KEY
from config.constants import (
    AUDIO_SAMPLE_RATE, TARGET_LUFS, BGM_MIX_VOLUME_DB,
    BGM_FADE_IN_SEC, BGM_FADE_OUT_SEC, LicenseType
)
from core.models import AssetRecord

logger = logging.getLogger(__name__)


# 4 Approved Core BGM Tracks with distinct Mood & Context Mappings
BGM_LIBRARY = {
    "best_historical": {
        "primary_files": ["No copyright Best Historical.wav", "No copyright Best Historical.mp3"],
        "display_name": "No copyright Best Historical",
        "mood": "Historical / Serious Documentary / Royal / Medieval / Warfare",
        "default_intensity": "Medium-High",
        "description": "Epic historical orchestral music designed for medieval warfare, monarchies, royal scandals, ancient empires, and serious historical politics.",
        "keywords": [
            "war", "battle", "army", "empire", "king", "queen", "court", "parliament",
            "revolution", "monarch", "dynasty", "coronation", "treaty", "feud", "rebellion",
            "emperor", "pope", "crusade", "medieval", "royal", "duel", "regime", "conquest",
            "siege", "knight", "throne", "castle", "crown", "republic", "legion", "armada",
            "commander", "soldier", "navy", "military", "napoleon", "caesar", "churchill",
            "latrine", "privy", "scandal", "erfurt", "tax", "beards", "laws", "aristocrats", "collapse"
        ]
    },
    "emotional_sad": {
        "primary_files": ["Empty - Emotional Sad Background.wav", "Empty - Emotional Sad Background.mp3"],
        "display_name": "Empty - Emotional Sad Background",
        "mood": "Emotional / Sad / Mournful / Poignant / Human Tragedy",
        "default_intensity": "Subdued-Poignant",
        "description": "Deeply emotional and somber melody for tragic human events, personal loss, poignant sacrifices, heartbreak, and mourning.",
        "keywords": [
            "sad", "tragedy", "tragic", "emotional", "loss", "grief", "poignant", "mourn", "sacrifice",
            "heartbreak", "death", "tears", "memorial", "ruin", "sorrow", "farewell", "crying",
            "dying", "famine", "plague", "victim", "burial", "fatal", "suffering", "sorrowful",
            "heartbreaking", "perished", "massacre", "destitution", "orphan", "starved", "grave",
            "lonely", "tear", "sympathy", "deprived", "destitute", "grieving", "sorrow", "regret"
        ]
    },
    "flux_ambient": {
        "primary_files": ["The Flux Beneath It All.wav", "The Flux Beneath It All.mp3"],
        "display_name": "The Flux Beneath It All",
        "mood": "Dark Mystery / Atmospheric Intrigue / Scientific Wonder / Bizarre Oddity",
        "default_intensity": "Atmospheric-Tense",
        "description": "Atmospheric ambient pulse for unexplained mysteries, bizarre historical oddities, strange cataclysms, disasters, scientific discoveries, and curiosity.",
        "keywords": [
            "mystery", "secret", "strange", "lost", "invention", "wonder", "science", "curiosity",
            "puzzle", "ancient", "unexplained", "phenomenon", "intrigue", "dark", "riddle",
            "cryptic", "alchemist", "astronomy", "unknown", "hidden", "discovery", "experiment",
            "baffling", "artifact", "voynich", "roanoke", "atlantis", "conspiracy", "code",
            "anomaly", "alien", "weird", "disaster", "cataclysm", "eruption",
            "volcano", "tsunami", "explosion", "stink", "molasses", "smell", "flood",
            "miracle", "supernatural", "unbelievable", "peculiar", "unusual", "mysterious"
        ]
    },
    "suspense_climax": {
        "primary_files": ["No Copyright Background Music.wav", "No Copyright Background Music.mp3"],
        "display_name": "No Copyright Background Music",
        "mood": "High Tension / Suspense / Thriller / Heist / Race Against Time",
        "default_intensity": "High-Driving",
        "description": "Intense cinematic build-up with driving tempo for high-stakes tension, thrilling escapes, heists, manhunts, assassinations, and urgent countdowns.",
        "keywords": [
            "suspense", "tension", "climax", "escape", "hunt", "chase", "race", "danger",
            "thriller", "build", "shock", "intense", "countdown", "panic", "heist", "manhunt",
            "assassination", "robbery", "ambush", "plot", "trapped", "deadly", "urgent",
            "strike", "pursuit", "breakout", "hostage", "bomb", "confrontation", "alarm",
            "ticking", "undercover", "spy", "infiltrate", "stealth", "infiltrator", "fugitive",
            "assassin", "pursuer", "critical", "threat", "danger", "peril", "emergency"
        ]
    }
}

# Alias for backward compatibility
BGM_CATALOG = BGM_LIBRARY


class AudioMixer:
    """Combines voiceover, ducked background music (-13 dB), and sound effects into balanced master audio."""

    def __init__(self):
        self.music_dir = MUSIC_DIR
        self.sfx_dir = SFX_DIR
        self.renders_dir = RENDERS_DIR
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)

    def classify_story_mood_ai(
        self,
        topic_title: str,
        category: str,
        script_text: str
    ) -> Optional[Tuple[str, str, str, str]]:
        """
        Uses Gemini AI to perform multidimensional narrative analysis:
        (topic, genre, emotional tone, intensity, pacing, atmosphere, seriousness)
        and classifies into ONE of the 4 approved BGM tracks.
        Returns: (track_key, detected_mood, detected_intensity, reason) or None.
        """
        if not GEMINI_API_KEY:
            return None

        prompt = (
            f"You are an expert audio director for short historical documentaries.\n"
            f"Analyze this story and select the single best matching background music track from the ONLY 4 approved tracks:\n\n"
            f"APPROVED TRACKS:\n"
            f"1. 'best_historical': Best for historical documentary, war, disaster, strange/bizarre historical events, riots, laws, monarchies, and serious history.\n"
            f"2. 'emotional_sad': Best for poignant human tragedy, sadness, loss, emotional grief, heartfelt sacrifice, and sorrow.\n"
            f"3. 'flux_ambient': Best for dark mystery, strange inventions, lost civilizations, curiosity, scientific wonder, and atmospheric intrigue.\n"
            f"4. 'suspense_climax': Best for high-stakes tension, thrilling escapes, dramatic climax, urgent countdowns, and general high-energy documentary content.\n\n"
            f"STORY DETAILS:\n"
            f"Title: {topic_title}\n"
            f"Category/Genre: {category}\n"
            f"Script Text: {script_text}\n\n"
            f"Evaluate the story's emotional tone, intensity, pacing, atmosphere, and seriousness.\n"
            f"Respond ONLY in valid JSON format:\n"
            f'{{\n'
            f'  "track": "best_historical" | "emotional_sad" | "flux_ambient" | "suspense_climax",\n'
            f'  "mood": "<short mood & atmospheric description>",\n'
            f'  "intensity": "Low" | "Medium" | "High" | "Dramatic",\n'
            f'  "reason": "<1-2 sentence justification for why this track fits the story better than the others>"\n'
            f'}}'
        )

        from config.settings import GEMINI_MODEL
        for model_name in [GEMINI_MODEL]:
            try:
                from core.gemini_client import get_gemini_client
                gemini_client = get_gemini_client()
                response = gemini_client.generate_content(
                    model=model_name,
                    contents=prompt
                )
                clean_text = response.text.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_text)
                track_key = data.get("track")
                if track_key in BGM_LIBRARY:
                    detected_mood = data.get("mood", BGM_LIBRARY[track_key]["mood"])
                    detected_intensity = data.get("intensity", BGM_LIBRARY[track_key]["default_intensity"])
                    reason = data.get("reason", "AI multidimensional mood and tone analysis")
                    return track_key, detected_mood, detected_intensity, reason
            except Exception as e:
                logger.debug(f"AI story mood classification fallback ({model_name}): {e}")

        return None

    def select_bgm_track(
        self,
        category: str = "",
        title: str = "",
        summary: str = "",
        script_text: str = ""
    ) -> Tuple[Path, str, str, str]:
        """
        Selects the most appropriate BGM track based on AI classification and semantic keywords.
        Returns: (track_path, track_key, detected_mood, reason_for_selection)
        """
        # 1. Attempt Multidimensional AI Mood Classification
        ai_result = self.classify_story_mood_ai(title, category, script_text)
        if ai_result:
            selected_key, detected_mood, detected_intensity, reason = ai_result
            reason = f"[AI Analyzed] {reason}"
        else:
            # 2. Balanced Semantic Heuristic Fallback Analysis
            cat_lower = (category or "").lower()
            title_lower = (title or "").lower()
            sum_lower = (summary or "").lower()
            script_lower = (script_text or "").lower()

            scores = {}
            for key, info in BGM_LIBRARY.items():
                cat_score = sum(3 for kw in info["keywords"] if kw in cat_lower)
                title_score = sum(2 for kw in info["keywords"] if kw in title_lower)
                sum_score = sum(1 for kw in info["keywords"] if kw in sum_lower)
                script_score = sum(1 for kw in info["keywords"] if kw in script_lower)
                scores[key] = cat_score + title_score + sum_score + script_score

            max_score = max(scores.values()) if scores else 0
            keys_with_max = [k for k, v in scores.items() if v == max_score] if max_score > 0 else []

            if max_score > 0 and len(keys_with_max) == 1:
                selected_key = keys_with_max[0]
                detected_intensity = BGM_LIBRARY[selected_key]["default_intensity"]
                score_str = ", ".join(f"{k}:{v}" for k, v in scores.items())
                reason = f"Keyword matching ({selected_key} with {scores[selected_key]} pts [{score_str}])"
            else:
                # Deterministic balanced rotation across the 4 valid tracks
                import hashlib
                hash_input = f"{title}_{category}_{summary}_{script_text[:50]}"
                hash_int = int(hashlib.md5(hash_input.encode("utf-8")).hexdigest(), 16)
                keys_list = list(BGM_LIBRARY.keys())
                selected_key = keys_list[hash_int % len(keys_list)]
                detected_intensity = BGM_LIBRARY[selected_key]["default_intensity"]
                reason = f"Deterministic balanced rotation across 4 BGM tracks (Hash index: {hash_int % len(keys_list)})"

            detected_mood = BGM_LIBRARY[selected_key]["mood"]

        # Resolve physical file on disk (dynamically from self.music_dir)
        track_info = BGM_LIBRARY[selected_key]
        target_path = None

        for filename in track_info["primary_files"]:
            candidate = self.music_dir / filename
            if candidate.exists() and candidate.stat().st_size > 1000:
                target_path = candidate
                break

        if not target_path or not target_path.exists():
            for f in self.music_dir.iterdir():
                if f.is_file() and f.suffix.lower() in [".wav", ".mp3", ".m4a"]:
                    target_path = f
                    break

        if not target_path or not target_path.exists():
            raise FileNotFoundError(f"No BGM audio tracks found in {self.music_dir}")

        # Explicit Logging of BGM Decision
        logger.info("==================================================")
        logger.info(f"BGM Decision -> Topic: {title or category}")
        logger.info(f"Detected Mood: {detected_mood}")
        logger.info(f"Detected Intensity: {detected_intensity}")
        logger.info(f"Selected BGM: {track_info['display_name']} ({target_path.name})")
        logger.info(f"Reason: {reason}")
        logger.info(f"BGM Source Path: {target_path}")
        logger.info(f"Mix Target Level: {BGM_MIX_VOLUME_DB} dB")
        logger.info("==================================================")

        return target_path, selected_key, detected_mood, reason

    def get_background_music(
        self,
        db: Session,
        category: str = "Unusual Wars",
        title: str = "",
        summary: str = "",
        script_text: str = ""
    ) -> AssetRecord:
        """
        Selects suitable background music track and records it in Asset database with full metadata.
        """
        music_file, track_key, mood, reason = self.select_bgm_track(
            category=category,
            title=title,
            summary=summary,
            script_text=script_text
        )

        meta_dict = {
            "bgm_track": track_key,
            "display_name": BGM_LIBRARY[track_key]["display_name"],
            "mood": mood,
            "reason": reason,
            "filename": music_file.name
        }

        asset_id = f"bgm_{uuid.uuid4().hex[:10]}"
        asset = AssetRecord(
            id=asset_id,
            asset_type="music",
            source="youtube_audio_library_cc0",
            source_url="https://studio.youtube.com/channel/audio_library",
            license=LicenseType.YOUTUBE_AUDIO_LIBRARY.value,
            commercial_use=True,
            attribution_required=False,
            local_path=str(music_file),
            duration_sec=35.0,
            metadata_json=json.dumps(meta_dict)
        )
        db.add(asset)
        db.commit()
        return asset

    def generate_stage_b_bgm_only(
        self,
        source_music_path: Path,
        output_bgm_only_path: Path,
        duration: float,
        bgm_volume_db: float = BGM_MIX_VOLUME_DB
    ) -> Path:
        """
        Stage B: Produces standalone, listenable BGM-only audio file
        with exact looping, trimming, volume scaling (-13 dB), and fade in/out.
        """
        output_bgm_only_path.parent.mkdir(parents=True, exist_ok=True)
        fade_out_start = max(0.5, duration - BGM_FADE_OUT_SEC)

        filter_b = (
            f"aloop=loop=-1:size=2e+09,atrim=0:{duration},"
            f"volume={bgm_volume_db}dB,"
            f"afade=t=in:ss=0:d={BGM_FADE_IN_SEC},"
            f"afade=t=out:st={fade_out_start:.2f}:d={BGM_FADE_OUT_SEC},"
            f"aformat=channel_layouts=stereo:sample_rates={AUDIO_SAMPLE_RATE}"
        )

        cmd_b = [
            FFMPEG_EXE, "-y",
            "-i", str(source_music_path),
            "-af", filter_b,
            "-c:a", "pcm_s16le",
            str(output_bgm_only_path)
        ]
        subprocess.run(cmd_b, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return output_bgm_only_path

    def mix_audio(
        self,
        voice_path: Path,
        music_path: Path,
        output_path: Path,
        duration: float,
        bgm_volume_db: float = BGM_MIX_VOLUME_DB,
        job_id: str = "",
        sfx_layer_path: Optional[Path] = None
    ) -> Tuple[Path, Path]:
        """
        Produces Stage B (BGM-only) and Stage C (Master mixed audio normalized to -14.0 LUFS)
        incorporating Voice (dominant), SFX layer (ducked accents), and BGM (ducked bed).
        Returns: (master_audio_path, bgm_only_path)
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        job_tag = job_id if job_id else uuid.uuid4().hex[:8]
        bgm_only_path = self.renders_dir / f"bgm_only_{job_tag}.wav"
        self.generate_stage_b_bgm_only(
            source_music_path=music_path,
            output_bgm_only_path=bgm_only_path,
            duration=duration,
            bgm_volume_db=bgm_volume_db
        )

        has_sfx = bool(sfx_layer_path and sfx_layer_path.exists() and sfx_layer_path.stat().st_size > 1000)

        if has_sfx:
            filter_complex = (
                f"[0:a]aresample={AUDIO_SAMPLE_RATE},aformat=channel_layouts=stereo[v];"
                f"[1:a]aresample={AUDIO_SAMPLE_RATE},aformat=channel_layouts=stereo[bgm];"
                f"[2:a]aresample={AUDIO_SAMPLE_RATE},aformat=channel_layouts=stereo[sfx];"
                f"[v][bgm][sfx]amix=inputs=3:duration=first:dropout_transition=2:normalize=0[mixed];"
                f"[mixed]loudnorm=I={TARGET_LUFS}:LRA=7:tp=-1.0[outa]"
            )
            cmd_inputs = ["-i", str(voice_path), "-i", str(bgm_only_path), "-i", str(sfx_layer_path)]
        else:
            filter_complex = (
                f"[0:a]aresample={AUDIO_SAMPLE_RATE},aformat=channel_layouts=stereo[v];"
                f"[1:a]aformat=channel_layouts=stereo[bgm];"
                f"[v][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mixed];"
                f"[mixed]loudnorm=I={TARGET_LUFS}:LRA=7:tp=-1.0[outa]"
            )
            cmd_inputs = ["-i", str(voice_path), "-i", str(bgm_only_path)]

        cmd = [
            FFMPEG_EXE, "-y",
            *cmd_inputs,
            "-filter_complex", filter_complex,
            "-map", "[outa]",
            "-ac", "2",
            "-ar", str(AUDIO_SAMPLE_RATE),
            "-c:a", "aac",
            "-b:a", "256k",
            str(output_path)
        ]

        logger.info(
            f"Mixing master audio (Voice: {voice_path.name} + BGM: {music_path.name} at {bgm_volume_db}dB "
            f"+ SFX: {'YES' if has_sfx else 'NONE'}, Master Target: {TARGET_LUFS} LUFS, Duration: {duration:.2f}s)"
        )
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if res.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1000:
            err_msg = res.stderr.decode("utf-8", errors="ignore")
            logger.warning(f"Audio mixing warning ({err_msg}). Executing direct repair remix...")
            repair_filter = (
                f"[0:a]aresample={AUDIO_SAMPLE_RATE},aformat=channel_layouts=stereo[v];"
                f"[1:a]aformat=channel_layouts=stereo[bgm];"
                f"[v][bgm]amix=inputs=2:duration=first:normalize=0[outa]"
            )
            cmd_repair = [
                FFMPEG_EXE, "-y",
                "-i", str(voice_path),
                "-i", str(bgm_only_path),
                "-filter_complex", repair_filter,
                "-map", "[outa]",
                "-ac", "2",
                "-ar", str(AUDIO_SAMPLE_RATE),
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_path)
            ]
            subprocess.run(cmd_repair, check=True)

        if not output_path.exists() or output_path.stat().st_size < 1000:
            raise RuntimeError(f"Master audio mixing failed: Output file {output_path} is missing or empty.")

        logger.info(f"[+] Master audio successfully mixed with BGM: {output_path.name} ({output_path.stat().st_size} bytes)")
        return output_path, bgm_only_path
