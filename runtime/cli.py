"""
CLI Entrypoint for AL-AMR Autonomous Runtime Service.
Usage:
    python -m runtime.cli [--once] [--dry-run] [--interval SECONDS] [--niche NICHE]
"""
import sys
import argparse
import logging

from runtime.config import RuntimeConfig
from runtime.service import AutonomousRuntimeService
from core.content_profile import set_active_profile, get_profile_by_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("AutonomousCLI")


def parse_args():
    parser = argparse.ArgumentParser(
        description="AL-AMR Autonomous Runtime & Deployment Bridge",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Execute a single autonomous tick and exit cleanly"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force execution in sandboxed dry-run mode (zero external mutations)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Loop interval between execution ticks in seconds"
    )
    parser.add_argument(
        "--harvest-interval",
        type=float,
        default=None,
        help="Interval between intelligence harvest cycles in seconds"
    )
    parser.add_argument(
        "--target-buffer",
        type=int,
        default=None,
        help="Target buffer stock of ready Shorts"
    )
    parser.add_argument(
        "--niche",
        type=str,
        default=None,
        help="Set active content niche profile before starting"
    )
    parser.add_argument(
        "--canary",
        action="store_true",
        help="Execute a single controlled live-cloud canary production and exit"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Apply niche override if provided
    if args.niche:
        prof = get_profile_by_name(args.niche)
        if not prof:
            logger.error(f"Unknown niche profile '{args.niche}'.")
            sys.exit(1)
        set_active_profile(prof)
        logger.info(f"Active content profile set to: {prof.name}")

    # Build runtime configuration
    config = RuntimeConfig.from_env()
    if args.dry_run:
        config.dry_run = True
    if args.canary:
        config.canary_mode = True
    if args.interval is not None:
        config.interval_sec = args.interval
    if args.harvest_interval is not None:
        config.harvest_interval_sec = args.harvest_interval
    if args.target_buffer is not None:
        config.target_buffer_stock = args.target_buffer

    if args.canary:
        logger.info("[CANARY] Executing controlled production canary run...")
        service = AutonomousRuntimeService(config=config)
        telemetry = service.run_canary()
        logger.info(f"[CANARY] Canary completed with outcome: {telemetry.get('status')}")
        if telemetry.get("status") != "SUCCESS":
            sys.exit(1)
        return

    logger.info(
        f"Starting Autonomous Runtime (DryRun: {config.dry_run}, "
        f"Interval: {config.interval_sec}s, TargetBuffer: {config.target_buffer_stock})"
    )

    service = AutonomousRuntimeService(config=config)
    try:
        service.start(run_once=args.once)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
        service.stop()


if __name__ == "__main__":
    main()
