#!/usr/bin/env python3
"""
Validate liquidation configuration before deployment.

Usage:
    python scripts/validate_liquidation_config.py [--strict] [--env=testnet|production]
"""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import LiquidationConfig
from src.execution.config_validator import LiquidationConfigValidator


def main():
    parser = argparse.ArgumentParser(
        description="Validate liquidation configuration before deployment"
    )
    parser.add_argument(
        "--strict", action="store_true", help="Fail on warnings (not just errors)"
    )
    parser.add_argument(
        "--env",
        choices=["testnet", "production"],
        default="production",
        help="Target environment for validation",
    )
    args = parser.parse_args()

    # Load configuration
    config = LiquidationConfig()

    # Validate
    validator = LiquidationConfigValidator()
    result = validator.validate_production_config(
        config, is_testnet=(args.env == "testnet")
    )

    # Check deployment readiness
    readiness = validator.check_deployment_readiness(
        config, is_testnet=(args.env == "testnet")
    )

    # Print results
    print(f"\n{'=' * 60}")
    print(f"Liquidation Configuration Validation - {args.env.upper()}")
    print(f"{'=' * 60}\n")

    print(f"✓ Valid: {result.is_valid}")
    print(f"✓ Ready: {readiness.is_ready}")
    print(f"\nIssues found: {len(result.issues)}")

    for issue in result.issues:
        symbol = "🔴" if issue.level.value in ["error", "critical"] else "⚠️"
        print(f"{symbol} [{issue.level.value.upper()}] {issue.message}")

    print(f"\nRecommendations:")
    for rec in readiness.recommendations:
        print(f"  • {rec}")

    # Exit code
    if not readiness.is_ready or (args.strict and result.has_warnings):
        print(f"\n{'=' * 60}")
        print(f"❌ Configuration validation FAILED")
        print(f"{'=' * 60}\n")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"✅ Configuration validated successfully")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
