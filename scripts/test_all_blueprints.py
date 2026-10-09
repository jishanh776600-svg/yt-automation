import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from intelligence.semantic_blueprint_matcher import SemanticBlueprintMatcher

matcher = SemanticBlueprintMatcher()

test_queries = [
    ("wrong_turn_2003", "Chris and Jessie hide quietly under the wooden bed inside the mountain cabin"),
    ("the_hills_have_eyes_2006", "The family station wagon breaks down in the deserted rocky hills"),
    ("texas_chainsaw_2013", "Heather investigates the dark cellar and encounters Leatherface with a chainsaw"),
    ("the_conjuring_2_2016", "Janet sits terrified in her bedroom as the wooden cross swings on the wall")
]

print("\n" + "=" * 70)
print("TESTING SEMANTIC BLUEPRINT MATCHER ON ALL 4 MOVIES")
print("=" * 70)

for slug, query in test_queries:
    shot = matcher.find_best_shot(slug, query, episode_index=1, total_episodes=8)
    print(f"\n[{slug.upper()}]")
    print(f"Beat Query  : {query}")
    print(f"Matched Shot: {shot['shot_id']} (ts: {shot['timestamp_sec']}s)")
    print(f"Environment : {shot.get('environment')}")
    print(f"Action      : {shot.get('action')}")
    print(f"Characters  : {shot.get('characters')}")
    print(f"SDH Cues    : {shot.get('sdh_context')[:90]}...")
