#!/usr/bin/env python3
"""
Analyze ICT strategy condition statistics from logs.

This script parses trading logs to identify ICT strategy bottlenecks
by analyzing which conditions fail most frequently.

Usage:
    python scripts/analyze_ict_conditions.py [--log-file=path] [--hours=24]
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List


def parse_log_file(log_file: Path, hours: int = 24) -> Dict[str, any]:
    """
    Parse log file and extract ICT condition data.

    Args:
        log_file: Path to log file
        hours: Number of hours to analyze (default: 24)

    Returns:
        Dictionary with condition statistics
    """
    stats = {
        "total_checks": 0,
        "signals_generated": 0,
        "conditions": {
            "killzone": 0,
            "trend": 0,
            "zone": 0,
            "fvg_ob": 0,
            "inducement": 0,
            "displacement": 0,
        },
        "failures": defaultdict(int),
        "near_misses": [],  # 4/5 or 5/6 conditions met
    }

    # Calculate time threshold
    cutoff_time = datetime.now() - timedelta(hours=hours)

    # Regex patterns for log parsing
    condition_pattern = re.compile(
        r"ICT Conditions Check: trend=(\w+), killzone=(True|False), "
        r"in_zone=(True|False), fvgs=(\d+), obs=(\d+), "
        r"inducements=(\d+), displacements=(\d+)"
    )

    signal_pattern = re.compile(
        r"ICT (LONG|SHORT) Signal: trend=(\w+), zone=(\w+), "
        r"fvg=(True|False), ob=(True|False), "
        r"inducement=(True|False), displacement=(True|False)"
    )

    if not log_file.exists():
        print(f"⚠️  Log file not found: {log_file}")
        return stats

    with open(log_file, "r") as f:
        for line in f:
            # Parse timestamp
            try:
                timestamp_str = line.split()[0] + " " + line.split()[1]
                timestamp = datetime.fromisoformat(timestamp_str.replace(",", "."))

                # Skip lines older than threshold
                if timestamp < cutoff_time:
                    continue
            except (IndexError, ValueError):
                continue  # Skip lines without valid timestamp

            # Check for condition check logs
            match = condition_pattern.search(line)
            if match:
                stats["total_checks"] += 1
                trend, killzone, in_zone, fvgs, obs, inducements, displacements = match.groups()

                # Track condition successes
                if trend and trend != "None":
                    stats["conditions"]["trend"] += 1

                if killzone == "True":
                    stats["conditions"]["killzone"] += 1

                if in_zone == "True":
                    stats["conditions"]["zone"] += 1

                if int(fvgs) > 0 or int(obs) > 0:
                    stats["conditions"]["fvg_ob"] += 1

                if int(inducements) > 0:
                    stats["conditions"]["inducement"] += 1

                if int(displacements) > 0:
                    stats["conditions"]["displacement"] += 1

                # Count conditions met
                conditions_met = sum(
                    [
                        trend and trend != "None",
                        killzone == "True",
                        in_zone == "True",
                        int(fvgs) > 0 or int(obs) > 0,
                        int(inducements) > 0,
                        int(displacements) > 0,
                    ]
                )

                # Track near misses (4 or 5 conditions met but no signal)
                if conditions_met >= 4 and "No signal" in line:
                    stats["near_misses"].append(
                        {
                            "timestamp": timestamp_str,
                            "conditions_met": conditions_met,
                            "missing": [
                                "trend" if not (trend and trend != "None") else None,
                                "killzone" if killzone != "True" else None,
                                "zone" if in_zone != "True" else None,
                                "fvg_ob" if int(fvgs) == 0 and int(obs) == 0 else None,
                                "inducement" if int(inducements) == 0 else None,
                                "displacement" if int(displacements) == 0 else None,
                            ],
                        }
                    )

            # Check for signal logs
            signal_match = signal_pattern.search(line)
            if signal_match:
                stats["signals_generated"] += 1

    return stats


def calculate_success_rates(stats: Dict[str, any]) -> Dict[str, float]:
    """
    Calculate success rates for each condition.

    Args:
        stats: Statistics dictionary from parse_log_file

    Returns:
        Dictionary with success rates (0-1)
    """
    total = stats["total_checks"]
    if total == 0:
        return {}

    return {
        condition: count / total for condition, count in stats["conditions"].items()
    }


def identify_bottlenecks(success_rates: Dict[str, float]) -> List[str]:
    """
    Identify bottleneck conditions (lowest success rates).

    Args:
        success_rates: Condition success rates

    Returns:
        List of bottleneck conditions, sorted by failure rate
    """
    # Sort by success rate (ascending)
    sorted_conditions = sorted(success_rates.items(), key=lambda x: x[1])

    # Identify conditions with <50% success rate
    bottlenecks = [cond for cond, rate in sorted_conditions if rate < 0.5]

    return bottlenecks


def print_report(stats: Dict[str, any], success_rates: Dict[str, float]) -> None:
    """
    Print formatted analysis report.

    Args:
        stats: Statistics dictionary
        success_rates: Condition success rates
    """
    print("\n" + "=" * 70)
    print("ICT Strategy Condition Analysis Report")
    print("=" * 70)

    print(f"\n📊 Overall Statistics (Last {args.hours} hours)")
    print(f"   Total condition checks: {stats['total_checks']}")
    print(f"   Signals generated: {stats['signals_generated']}")

    if stats["total_checks"] > 0:
        signal_rate = (stats["signals_generated"] / stats["total_checks"]) * 100
        print(f"   Signal rate: {signal_rate:.2f}%")

    print(f"\n✅ Condition Success Rates:")
    print(f"   {'Condition':<15} {'Success Rate':<15} {'Count':<10} {'Status'}")
    print(f"   {'-' * 60}")

    # Sort by success rate (ascending) to show failures first
    sorted_conditions = sorted(success_rates.items(), key=lambda x: x[1])

    for condition, rate in sorted_conditions:
        count = stats["conditions"][condition]
        status = "✅ OK" if rate >= 0.7 else "⚠️  WARN" if rate >= 0.5 else "🔴 BOTTLENECK"
        print(f"   {condition:<15} {rate * 100:>6.1f}%        {count:<10} {status}")

    # Identify bottlenecks
    bottlenecks = identify_bottlenecks(success_rates)
    if bottlenecks:
        print(f"\n🔴 Identified Bottlenecks:")
        for bottleneck in bottlenecks:
            rate = success_rates[bottleneck]
            print(f"   - {bottleneck}: {rate * 100:.1f}% success rate")

    # Near misses analysis
    if stats["near_misses"]:
        print(f"\n⚠️  Near Misses (4+ conditions met, no signal): {len(stats['near_misses'])}")
        print(f"   Showing last 5:")

        for near_miss in stats["near_misses"][-5:]:
            missing = [m for m in near_miss["missing"] if m]
            print(
                f"   - {near_miss['timestamp']}: "
                f"{near_miss['conditions_met']}/6 met, "
                f"missing: {', '.join(missing)}"
            )

    print(f"\n💡 Recommendations:")
    if bottlenecks:
        if "inducement" in bottlenecks or "displacement" in bottlenecks:
            print("   1. Consider relaxing inducement/displacement detection parameters")
            print("      - Increase lookback window for inducement detection")
            print("      - Lower displacement_ratio threshold")
        if "fvg_ob" in bottlenecks:
            print("   2. Relax FVG/OB detection parameters")
            print("      - Increase fvg_min_gap_percent (allow smaller gaps)")
            print("      - Lower ob_min_strength threshold")
        if "zone" in bottlenecks:
            print("   3. Widen premium/discount zones")
            print("      - Increase lookback period for range calculation")
        if "trend" in bottlenecks:
            print("   4. Adjust trend detection sensitivity")
            print("      - Increase swing_lookback parameter")
    else:
        print("   ✅ No critical bottlenecks detected")
        print("   - Current parameters appear well-balanced")
        if stats["signals_generated"] < 5:
            print("   - Consider using 'Balanced' or 'Relaxed' profile for more signals")

    print(f"\n{'=' * 70}\n")


def main():
    """Main analysis function."""
    parser = argparse.ArgumentParser(
        description="Analyze ICT strategy condition statistics from logs"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default="logs/trading.log",
        help="Path to log file (default: logs/trading.log)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Number of hours to analyze (default: 24)",
    )
    parser.add_argument(
        "--json-output",
        type=str,
        help="Optional: Save analysis results as JSON",
    )

    global args
    args = parser.parse_args()

    # Parse log file
    log_file = Path(args.log_file)
    stats = parse_log_file(log_file, args.hours)

    # Calculate success rates
    success_rates = calculate_success_rates(stats)

    # Print report
    print_report(stats, success_rates)

    # Save JSON output if requested
    if args.json_output:
        output = {
            "stats": stats,
            "success_rates": success_rates,
            "bottlenecks": identify_bottlenecks(success_rates),
        }

        # Convert defaultdict to regular dict for JSON serialization
        output["stats"]["failures"] = dict(output["stats"]["failures"])

        with open(args.json_output, "w") as f:
            json.dump(output, f, indent=2, default=str)

        print(f"✅ JSON output saved to: {args.json_output}")


if __name__ == "__main__":
    main()
