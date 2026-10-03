"""
Forgotten Files - Production Visual QA Batch Runner (Sep 2026).
Executes real-world end-to-end Visual QA on a controlled batch of exactly 3 Shorts
using the newly hardened visual pipeline (Pexels -> Pixabay -> Archival -> Local pool -> Fail closed).

Rules:
- Authoritative Forgotten Files Voice: af_bella
- 100% Real moving video (VIDEO_ONLY = True, zero static images)
- Clean full-screen 1080x1920 9:16 vertical video
- Scene-by-scene candidate logging & evaluation
- Output to isolated directory: data/renders/qa_batch_sep2026/
- ZERO Drive uploads, ZERO YouTube uploads, ZERO scheduling.
"""
import os
import sys
import json
import time
import shutil
import uuid
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Set, Optional

# Ensure repository root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from core.database import SessionLocal, init_db
from core.models import Job, Topic, ScriptRecord, AssetRecord, RenderOutput
from core.state_machine import StateMachine, JobState
from config.settings import RENDERS_DIR, ASSETS_DIR, DATA_DIR, FFMPEG_EXE
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT, AUDIO_SAMPLE_RATE

from engines.tts_engine import TTSEngine, get_active_voice, resolve_voice_config
from engines.caption_engine import CaptionEngine
from engines.visual_intelligence.voice_policy import VoiceVariationPolicy
from engines.visual_intelligence.voice_delivery import DeliveryProfile
from engines.sfx_manager import SFXManager, SFX_CATALOG
from engines.audio_mixer import AudioMixer
from engines.render_engine import RenderEngine
from engines.qa_engine import QAEngine
from engines.asset_fetcher import AssetFetcher
from core.media_validator import PhysicalVideoValidator
from engines.visual_intelligence.models import VisualIntent, VisualCandidate, VisualContentType


QA_OUTPUT_DIR = RENDERS_DIR / "qa_batch_sep2026"
QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


QA_TOPICS = [
    {
        "id": "short_01_mary_celeste",
        "title": "The Mystery of the Mary Celeste",
        "category": "Historical Mystery",
        "style_archetype": "HISTORICAL_MYSTERY",
        "hook": "Ten sailors vanished without struggle.",
        "context": "A pristine merchant brig was found drifting quietly under full sail.",
        "escalation": "Warm morning tea sat untouched, while six months of provisions remained intact below deck.",
        "reveal": "Yet the entire crew and single lifeboat had vanished into open water without trace.",
        "loop_twist": "Investigators discovered that no violence ever occurred before...",
        "sfx_cues": [
            {"sfx_id": "user_whoosh_quick", "start_time": 0.0, "duration": 0.8},
            {"sfx_id": "editorial_hit_reveal", "start_time": 12.5, "duration": 1.2}
        ],
        "scenes": [
            {
                "beat_index": 0,
                "stage": "hook_1",
                "narration": "Ten sailors vanished without struggle.",
                "query": "wooden sailing ship mist ocean",
                "visual_prompt": "Mysterious wooden ship sailing through dense eerie mist on vast dark ocean",
                "motion": "slow_pan_left"
            },
            {
                "beat_index": 1,
                "stage": "hook_2",
                "narration": "A pristine merchant brig",
                "query": "brigantine sailing ship open sea",
                "visual_prompt": "Historic brigantine merchant ship cutting through open ocean waters",
                "motion": "subtle_zoom_in"
            },
            {
                "beat_index": 2,
                "stage": "context_1",
                "narration": "was found drifting quietly under full sail.",
                "query": "tall ship white sails ocean",
                "visual_prompt": "Vintage tall sailing ship with massive white sails catching ocean wind",
                "motion": "dynamic_reframe"
            },
            {
                "beat_index": 3,
                "stage": "escalation_1",
                "narration": "Warm morning tea sat untouched,",
                "query": "steaming hot tea cup wooden table",
                "visual_prompt": "Steaming hot mug of tea resting quietly on rustic dark wooden table",
                "motion": "subtle_zoom_in"
            },
            {
                "beat_index": 4,
                "stage": "escalation_2",
                "narration": "while six months of provisions remained intact below deck.",
                "query": "wooden cargo barrels ship hold",
                "visual_prompt": "Rows of heavy wooden cargo barrels and provisions stored inside dark ship cargo hold",
                "motion": "slow_pan_right"
            },
            {
                "beat_index": 5,
                "stage": "reveal_1",
                "narration": "Yet the entire crew and single lifeboat",
                "query": "empty rowboat adrift waves",
                "visual_prompt": "Small wooden lifeboat drifting empty among rolling open ocean swells",
                "motion": "zoom_in"
            },
            {
                "beat_index": 6,
                "stage": "reveal_2",
                "narration": "had vanished into open water without trace.",
                "query": "vast open ocean storm waves horizon",
                "visual_prompt": "Immense dark ocean waters with rolling swells stretching toward distant horizon",
                "motion": "dynamic_reframe"
            },
            {
                "beat_index": 7,
                "stage": "loop_twist",
                "narration": "Investigators discovered that no violence ever occurred before...",
                "query": "vintage nautical map compass maritime log",
                "visual_prompt": "Antique nautical navigation chart with brass compass and maritime logbook",
                "motion": "subtle_zoom_out"
            }
        ]
    },
    {
        "id": "short_02_lake_peigneur",
        "title": "The Lake Peigneur Sinkhole Disaster",
        "category": "Bizarre Historical Event",
        "style_archetype": "BIZARRE_DISASTER",
        "hook": "A tiny drill swallowed an entire lake.",
        "context": "An oil rig accidentally punctured a massive salt mine underneath shallow water.",
        "escalation": "Water violently roared down the hole, creating a colossal whirlpool that sucked down eleven barges and trees.",
        "reveal": "Miraculously, fifty-five miners sprinted through rising mud and survived.",
        "loop_twist": "Today, peaceful waters hide the bizarre afternoon when...",
        "sfx_cues": [
            {"sfx_id": "user_whoosh_quick", "start_time": 0.0, "duration": 0.8},
            {"sfx_id": "cinematic_impact_heavy", "start_time": 10.5, "duration": 1.4}
        ],
        "scenes": [
            {
                "beat_index": 0,
                "stage": "hook_1",
                "narration": "A tiny drill swallowed",
                "query": "offshore oil drilling rig water platform",
                "visual_prompt": "Massive steel oil drilling rig tower operating over open water",
                "motion": "dynamic_reframe"
            },
            {
                "beat_index": 1,
                "stage": "hook_2",
                "narration": "an entire lake.",
                "query": "aerial view calm lake water trees",
                "visual_prompt": "High altitude aerial drone shot overlooking calm freshwater lake and green trees",
                "motion": "subtle_zoom_out"
            },
            {
                "beat_index": 2,
                "stage": "context_1",
                "narration": "An oil rig accidentally punctured",
                "query": "rotary drill bit drilling machine action",
                "visual_prompt": "Heavy industrial steel rotary drill bit rotating and grinding into bedrock",
                "motion": "zoom_in"
            },
            {
                "beat_index": 3,
                "stage": "context_2",
                "narration": "a massive salt mine underneath shallow water.",
                "query": "underground salt mine cavern tunnel",
                "visual_prompt": "Sprawling subterranean cavern with immense crystalline salt rock pillars and tunnels",
                "motion": "slow_pan_left"
            },
            {
                "beat_index": 4,
                "stage": "escalation_1",
                "narration": "Water violently roared down the hole,",
                "query": "rushing water churning vortex waterfall",
                "visual_prompt": "Violent torrents of rushing foaming water plunging down into churning abyss",
                "motion": "dynamic_reframe"
            },
            {
                "beat_index": 5,
                "stage": "escalation_2",
                "narration": "creating a colossal whirlpool that sucked down eleven barges and trees.",
                "query": "massive water whirlpool rapids swirling",
                "visual_prompt": "Terrifying large water vortex swirling and swallowing water with turbulent rapids",
                "motion": "zoom_in"
            },
            {
                "beat_index": 6,
                "stage": "reveal",
                "narration": "Miraculously, fifty-five miners sprinted through rising mud and survived.",
                "query": "miners emergency evacuation running dark tunnel",
                "visual_prompt": "Industrial underground miners with headlamps running through dark misty tunnel",
                "motion": "slow_pan_right"
            },
            {
                "beat_index": 7,
                "stage": "loop_twist",
                "narration": "Today, peaceful waters hide the bizarre afternoon when...",
                "query": "calm reflective lake sunset afternoon water",
                "visual_prompt": "Tranquil glassy lake water reflecting warm afternoon sunlight",
                "motion": "subtle_zoom_out"
            }
        ]
    },
    {
        "id": "short_03_kettle_war",
        "title": "The Kettle War of 1784",
        "category": "Unusual War",
        "style_archetype": "HISTORICAL_MILITARY_ODDITY",
        "hook": "Two battle fleets clashed over soup.",
        "context": "A heavily armed flagship intercepted enemy patrol vessels guarding the contested river.",
        "escalation": "Tensions peaked until imperial gunners fired one thunderous warning cannonball across the water.",
        "reveal": "The shot hit nothing except a brass soup kettle boiling on deck, splashing hot stew everywhere.",
        "loop_twist": "The terrified crew instantly surrendered after...",
        "sfx_cues": [
            {"sfx_id": "user_whoosh_quick", "start_time": 0.0, "duration": 0.8},
            {"sfx_id": "editorial_hit_reveal", "start_time": 10.0, "duration": 1.0}
        ],
        "scenes": [
            {
                "beat_index": 0,
                "stage": "hook_1",
                "narration": "Two battle fleets clashed",
                "query": "historic warships naval fleet sailing",
                "visual_prompt": "Historic wooden naval warships sailing in tight battle formation across choppy water",
                "motion": "slow_pan_left"
            },
            {
                "beat_index": 1,
                "stage": "hook_2",
                "narration": "over soup.",
                "query": "brass cauldron soup boiling campfire",
                "visual_prompt": "Vintage metal brass cauldron boiling stew vigorously over glowing coals and flames",
                "motion": "subtle_zoom_in"
            },
            {
                "beat_index": 2,
                "stage": "context",
                "narration": "A heavily armed flagship intercepted enemy patrol vessels guarding the contested river.",
                "query": "vintage tall ship river patrol sailing",
                "visual_prompt": "Majestic vintage warship cruising slowly along a wide natural river waterway",
                "motion": "slow_pan_right"
            },
            {
                "beat_index": 3,
                "stage": "escalation_1",
                "narration": "Tensions peaked until imperial gunners",
                "query": "antique cannon warship deck battle ready",
                "visual_prompt": "Heavy antique brass cannon mounted on wooden ship deck ready for action",
                "motion": "zoom_in"
            },
            {
                "beat_index": 4,
                "stage": "escalation_2",
                "narration": "fired one thunderous warning cannonball across the water.",
                "query": "cannon firing smoke blast explosion",
                "visual_prompt": "Warship cannon firing with intense flame muzzle flash and billowing thick white smoke",
                "motion": "dynamic_reframe"
            },
            {
                "beat_index": 5,
                "stage": "reveal_1",
                "narration": "The shot hit nothing except a brass soup kettle boiling on deck,",
                "query": "metal pot boiling soup splash steam",
                "visual_prompt": "Heavy metal cooking pot boiling with soup and splashing liquid under pressure",
                "motion": "zoom_in"
            },
            {
                "beat_index": 6,
                "stage": "reveal_2",
                "narration": "splashing hot stew everywhere.",
                "query": "bubbling hot stew simmering broth steam",
                "visual_prompt": "Close-up of hot bubbling stew with rising steam and simmering broth",
                "motion": "subtle_zoom_in"
            },
            {
                "beat_index": 7,
                "stage": "loop_twist",
                "narration": "The terrified crew instantly surrendered after...",
                "query": "white flag surrender waving ship mast",
                "visual_prompt": "White surrender flag fluttering on wooden ship mast in wind",
                "motion": "subtle_zoom_out"
            }
        ]
    }
]


def execute_visual_qa_short(
    db,
    item: Dict[str, Any],
    tts_engine: TTSEngine,
    caption_engine: CaptionEngine,
    sfx_manager: SFXManager,
    audio_mixer: AudioMixer,
    asset_fetcher: AssetFetcher,
    render_engine: RenderEngine,
    qa_engine: QAEngine
) -> Dict[str, Any]:
    short_id = item["id"]
    title = item["title"]
    category = item["category"]
    full_script = f"{item['hook']} {item['context']} {item['escalation']} {item['reveal']} {item['loop_twist']}"
    words = full_script.split()
    word_count = len(words)

    print(f"\n" + "="*80)
    print(f"STARTING VISUAL QA SHORT: {short_id.upper()}")
    print(f"Title: {title}")
    print(f"Category: {category} | Words: {word_count} | Hook: '{item['hook']}' ({len(item['hook'].split())} words)")
    print(f"="*80)

    # 1. DB Records
    job_uuid = f"job_{short_id}_{uuid.uuid4().hex[:6]}"
    topic_uuid = f"top_{short_id}_{uuid.uuid4().hex[:6]}"

    topic = Topic(id=topic_uuid, title=title, category=category, summary=full_script[:120], score=99.0)
    db.add(topic)
    db.commit()

    job = Job(id=job_uuid, topic_id=topic_uuid, state=JobState.SCRIPT_READY.value)
    db.add(job)
    db.commit()

    script = ScriptRecord(
        id=f"scr_{uuid.uuid4().hex[:8]}",
        topic_id=topic_uuid,
        hook=item["hook"],
        context=item["context"],
        escalation=item["escalation"],
        reveal=item["reveal"],
        loop_twist=item["loop_twist"],
        full_text=full_script,
        word_count=word_count,
        estimated_duration_sec=round(word_count / 3.4, 1)
    )
    db.add(script)
    db.commit()

    # 2. TTS Narration with af_bella
    voice_policy = VoiceVariationPolicy()
    decision = voice_policy.select_voice_and_delivery(
        category=category,
        title=title,
        script_text=full_script,
        bgm_policy="DUCKED"
    )
    delivery_spec = decision.delivery_spec
    production_voice = "af_bella"

    print(f"[TTS] Synthesizing Voice ({production_voice}) with Studio Mastering...")
    voice_asset, audio_duration = tts_engine.generate_narration(
        db=db,
        text=full_script,
        voice=production_voice,
        delivery_spec=delivery_spec
    )
    voice_path = Path(voice_asset.local_path)
    print(f"[TTS] Generated Mastered Narration: {voice_path.name} ({audio_duration:.2f}s)")

    # 3. Dynamic Active-Word ASS Subtitles
    ass_path = caption_engine.generate_ass_subtitles(voice_path)
    print(f"[CAPTIONS] ASS Subtitles Rendered: {ass_path.name}")

    # 4. SFX Layer
    sfx_layer_path = RENDERS_DIR / f"sfx_layer_{job.id}.wav"
    rendered_sfx_path = sfx_manager.render_sfx_layer(
        sfx_cues=item["sfx_cues"],
        total_duration=audio_duration,
        output_path=sfx_layer_path
    )
    print(f"[SFX] Studio SFX Layer: {rendered_sfx_path.name if rendered_sfx_path else 'None'}")

    # 5. Audio Mixing
    master_audio_path = RENDERS_DIR / f"master_{job.id}.wav"
    master_audio_path, _ = audio_mixer.mix_audio(
        voice_path=voice_path,
        music_path=None,
        output_path=master_audio_path,
        duration=audio_duration,
        job_id=job.id,
        sfx_layer_path=rendered_sfx_path,
        bgm_policy="NONE"
    )
    print(f"[AUDIO] Master Audio Mixed: {master_audio_path.name}")

    # 6. Synchronized Visual Shot Planning & Retrieval
    scene_defs = item["scenes"]
    num_shots = len(scene_defs)
    base_shot_dur = round(audio_duration / num_shots, 2)
    shots_data = []
    asset_map = {}
    candidate_telemetry = []
    used_urls: Set[str] = set()

    for idx, sc in enumerate(scene_defs):
        s_id = f"shot_{idx+1:02d}_{uuid.uuid4().hex[:4]}"
        dur = base_shot_dur if idx < num_shots - 1 else round(audio_duration - (base_shot_dur * (num_shots - 1)), 2)
        start_t = round(idx * base_shot_dur, 2)

        v_intent = VisualIntent(
            beat_id=s_id,
            beat_index=idx,
            narration_text=sc["narration"],
            start_time=start_t,
            end_time=round(start_t + dur, 2),
            duration=dur,
            search_queries=[sc["query"]],
            subject=sc["query"],
            preferred_visual_type=VisualContentType.REAL_VIDEO,
            preferred_source="real_footage"
        )

        shot_dict = {
            "shot_id": s_id,
            "shot_index": idx,
            "start_time": start_t,
            "end_time": round(start_t + dur, 2),
            "duration": dur,
            "narration_segment": sc["narration"],
            "narrative_stage": sc["stage"],
            "search_query": sc["query"],
            "visual_prompt": sc["visual_prompt"],
            "camera_motion": sc["motion"],
            "transition": "cut" if idx == 0 else "crossfade",
            "visual_intent": v_intent.to_dict(),
            "asset_type": "video"
        }
        shots_data.append(shot_dict)

        print(f"\n--- Scene {idx+1}/{num_shots}: [{sc['stage']}] ---")
        print(f"    Narration: \"{sc['narration']}\" ({dur:.2f}s)")
        print(f"    Target Query: \"{sc['query']}\"")

        # Intercept Candidate Evaluation
        # 1. Acquire candidates through source router
        t_acq0 = time.time()
        raw_candidates = asset_fetcher.source_router.acquire_candidates(
            intent=v_intent,
            count_per_tier=4,
            exclude_urls=used_urls
        )
        
        # 2. Filter & Rank candidates
        video_candidates = [
            c for c in raw_candidates
            if getattr(c, "is_video", False)
            and not PhysicalVideoValidator.is_image_url(getattr(c, "media_url", "") or getattr(c, "source_url", ""))
        ]

        recent_history = asset_fetcher.vi_diversity.get_recent_usage_counts()
        ranked = asset_fetcher.vi_scorer.rank_candidates(
            candidates=video_candidates,
            intent=v_intent,
            recent_usage_counts=recent_history,
            job_used_urls=used_urls
        ) if video_candidates else []

        print(f"    Candidates evaluated: {len(video_candidates)} videos across providers")
        scene_eval_records = []
        for c in video_candidates:
            is_sel = (len(ranked) > 0 and c.candidate_id == ranked[0].candidate_id)
            score_val = getattr(c, "raw_score", 0.0)
            rec = {
                "candidate_id": c.candidate_id,
                "source_provider": c.source_name,
                "title": c.title,
                "source_url": c.source_url,
                "media_url": c.media_url,
                "resolution": f"{c.width}x{c.height}",
                "duration": getattr(c, "duration", 0.0),
                "motion_detected": (c.content_type in [VisualContentType.REAL_VIDEO, VisualContentType.GENERIC_STOCK_VIDEO]),
                "score": round(score_val, 3),
                "selected": is_sel,
                "rejection_reason": getattr(c, "rejection_reason", None) if not is_sel else None
            }
            scene_eval_records.append(rec)
            status_tag = "[SELECTED]" if is_sel else "[REJECTED]"
            print(f"      {status_tag} {c.source_name} | {c.width}x{c.height} | Score: {score_val:.3f} | {c.title[:45]}")

        # Execute standard fetch
        selected_asset = asset_fetcher.fetch_asset_for_shot(db, shot_dict, used_urls_in_job=used_urls)
        asset_map[s_id] = selected_asset
        used_urls.add(selected_asset.source_url)

        # Validate physically
        is_phys_valid = PhysicalVideoValidator.is_valid_video(selected_asset.local_path)
        print(f"    Result Asset: {selected_asset.id} | Source: {selected_asset.source} | Valid MP4: {is_phys_valid}")

        candidate_telemetry.append({
            "scene_index": idx + 1,
            "stage": sc["stage"],
            "timestamp_start": start_t,
            "timestamp_end": round(start_t + dur, 2),
            "duration": dur,
            "narration": sc["narration"],
            "query": sc["query"],
            "selected_source": selected_asset.source,
            "selected_path": selected_asset.local_path,
            "physical_valid": is_phys_valid,
            "candidates": scene_eval_records
        })

    # 7. Video Assembly & Rendering
    print(f"\n[RENDER] Assembling 1080x1920 Short with {num_shots} scenes...")
    render_out = render_engine.assemble_short(
        db=db,
        job_id=job.id,
        shots_data=shots_data,
        asset_map=asset_map,
        master_audio_path=master_audio_path,
        ass_subtitle_path=ass_path,
        motion_style="DYNAMIC_VIDEO_MOTION"
    )
    raw_video_path = Path(render_out.video_path)
    file_size_mb = render_out.file_size_bytes / 1e6
    print(f"[RENDER] Completed Assembly: {raw_video_path.name} ({file_size_mb:.2f} MB)")

    # 8. Copy to Isolated QA Directory
    final_qa_path = QA_OUTPUT_DIR / f"{short_id}.mp4"
    shutil.copy2(raw_video_path, final_qa_path)
    print(f"[QA_VAULT] Saved to Isolated QA Destination: {final_qa_path}")

    # 9. Forensic Inspection & Black Screen Detection
    media_info = qa_engine.inspect_media(final_qa_path)
    cmd_bd = [
        FFMPEG_EXE,
        "-i", str(final_qa_path),
        "-vf", "blackdetect=d=0.5:pix_th=0.10",
        "-f", "null",
        "-"
    ]
    res_bd = subprocess.run(cmd_bd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    black_detected = "black_start" in res_bd.stderr.decode("utf-8", errors="ignore")

    print(f"[QA_AUDIT] Forensic Analysis for {final_qa_path.name}:")
    print(f"           Resolution: {media_info.get('width')}x{media_info.get('height')}")
    print(f"           Duration: {media_info.get('duration'):.2f}s | FPS: {media_info.get('fps')}")
    print(f"           Has Video: {media_info.get('has_video')} | Has Audio: {media_info.get('has_audio')}")
    print(f"           Black Screen Detected: {black_detected}")

    audit_data = {
        "short_id": short_id,
        "title": title,
        "category": category,
        "script": {
            "hook": item["hook"],
            "context": item["context"],
            "escalation": item["escalation"],
            "reveal": item["reveal"],
            "loop_twist": item["loop_twist"],
            "full_text": full_script,
            "word_count": word_count
        },
        "audio": {
            "voice": production_voice,
            "duration": audio_duration,
            "master_audio": str(master_audio_path)
        },
        "render": {
            "qa_path": str(final_qa_path),
            "file_size_mb": round(file_size_mb, 2),
            "media_info": media_info,
            "black_screen_detected": black_detected
        },
        "scenes": candidate_telemetry
    }

    audit_json_path = QA_OUTPUT_DIR / f"{short_id}_audit.json"
    with open(audit_json_path, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2)
    print(f"[AUDIT] Detailed telemetry saved to: {audit_json_path}")

    return audit_data


def main():
    print("="*80)
    print("AL-AMR / FORGOTTEN FILES: PRODUCTION VISUAL QA BATCH EXECUTION")
    print(f"Destination Directory: {QA_OUTPUT_DIR}")
    print("="*80)

    db = SessionLocal()
    init_db()

    tts_engine = TTSEngine()
    caption_engine = CaptionEngine()
    sfx_manager = SFXManager()
    audio_mixer = AudioMixer()
    asset_fetcher = AssetFetcher()
    render_engine = RenderEngine()
    qa_engine = QAEngine()

    batch_results = []
    for item in QA_TOPICS:
        try:
            res = execute_visual_qa_short(
                db=db,
                item=item,
                tts_engine=tts_engine,
                caption_engine=caption_engine,
                sfx_manager=sfx_manager,
                audio_mixer=audio_mixer,
                asset_fetcher=asset_fetcher,
                render_engine=render_engine,
                qa_engine=qa_engine
            )
            batch_results.append(res)
        except Exception as e:
            print(f"[FATAL_SHORT_ERROR] Failed generating {item['id']}: {e}")
            import traceback
            traceback.print_exc()

    db.close()

    # Consolidated Batch Summary
    summary_path = QA_OUTPUT_DIR / "batch_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(batch_results, f, indent=2)

    print("\n" + "="*80)
    print(f"QA BATCH EXECUTION COMPLETED: {len(batch_results)}/{len(QA_TOPICS)} Shorts Rendered")
    print(f"Summary Written: {summary_path}")
    print("="*80)


if __name__ == "__main__":
    main()
