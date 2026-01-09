"""
ICT Strategy Parameter Profiles

Defines pre-configured parameter sets for different signal frequency targets.

Profiles:
- STRICT: 1-2 signals/week (current baseline)
- BALANCED: 5-10 signals/week (recommended)
- RELAXED: 15-20 signals/week (testing only)
"""

from enum import Enum
from typing import Dict


class ICTProfile(Enum):
    """ICT strategy parameter profiles."""

    STRICT = "strict"
    BALANCED = "balanced"
    RELAXED = "relaxed"


# Profile parameter definitions
PROFILE_PARAMETERS = {
    ICTProfile.STRICT: {
        "swing_lookback": 5,
        "displacement_ratio": 1.5,
        "fvg_min_gap_percent": 0.001,
        "ob_min_strength": 1.5,
        "liquidity_tolerance": 0.001,
        "rr_ratio": 2.0,
        "description": "Strict parameters (1-2 signals/week) - Current baseline",
        "signal_frequency": "1-2 per week",
        "use_case": "High-quality signals, minimal false positives",
    },
    ICTProfile.BALANCED: {
        "swing_lookback": 5,
        "displacement_ratio": 1.3,
        "fvg_min_gap_percent": 0.001,
        "ob_min_strength": 1.3,
        "liquidity_tolerance": 0.002,
        "rr_ratio": 2.0,
        "description": "Balanced parameters (5-10 signals/week) - Recommended",
        "signal_frequency": "5-10 per week",
        "use_case": "Good signal-to-noise ratio, suitable for active trading",
    },
    ICTProfile.RELAXED: {
        "swing_lookback": 3,
        "displacement_ratio": 1.1,
        "fvg_min_gap_percent": 0.0005,
        "ob_min_strength": 1.1,
        "liquidity_tolerance": 0.005,
        "rr_ratio": 2.0,
        "description": "Relaxed parameters (15-20 signals/week) - Testing only",
        "signal_frequency": "15-20 per week",
        "use_case": "Maximum signals, higher false positive risk",
    },
}


def get_profile_parameters(profile: ICTProfile) -> Dict[str, float]:
    """
    Get parameter values for a specific profile.

    Args:
        profile: ICTProfile enum value

    Returns:
        Dictionary with parameter values

    Raises:
        ValueError: If profile is not recognized
    """
    if profile not in PROFILE_PARAMETERS:
        raise ValueError(f"Unknown profile: {profile}")

    return {
        k: v
        for k, v in PROFILE_PARAMETERS[profile].items()
        if k not in ["description", "signal_frequency", "use_case"]
    }


def get_profile_info(profile: ICTProfile) -> Dict[str, str]:
    """
    Get descriptive information about a profile.

    Args:
        profile: ICTProfile enum value

    Returns:
        Dictionary with description, signal_frequency, use_case
    """
    if profile not in PROFILE_PARAMETERS:
        raise ValueError(f"Unknown profile: {profile}")

    return {
        "description": PROFILE_PARAMETERS[profile]["description"],
        "signal_frequency": PROFILE_PARAMETERS[profile]["signal_frequency"],
        "use_case": PROFILE_PARAMETERS[profile]["use_case"],
    }


def load_profile_from_name(profile_name: str) -> ICTProfile:
    """
    Load profile from string name.

    Args:
        profile_name: Profile name string (e.g., "strict", "balanced", "relaxed")

    Returns:
        ICTProfile enum value

    Raises:
        ValueError: If profile name is not recognized
    """
    profile_name_lower = profile_name.lower()

    for profile in ICTProfile:
        if profile.value == profile_name_lower:
            return profile

    raise ValueError(
        f"Unknown profile name: {profile_name}. "
        f"Valid options: {', '.join([p.value for p in ICTProfile])}"
    )


def list_all_profiles() -> Dict[str, Dict]:
    """
    List all available profiles with their parameters and info.

    Returns:
        Dictionary mapping profile names to their full configuration
    """
    return {
        profile.value: {
            **get_profile_parameters(profile),
            **get_profile_info(profile),
        }
        for profile in ICTProfile
    }


def compare_profiles() -> str:
    """
    Generate a comparison table of all profiles.

    Returns:
        Formatted string with profile comparison
    """
    profiles = list_all_profiles()

    output = []
    output.append("\n" + "=" * 80)
    output.append("ICT Strategy Parameter Profiles Comparison")
    output.append("=" * 80)

    # Header
    output.append(
        f"\n{'Parameter':<25} {'Strict':<15} {'Balanced':<15} {'Relaxed':<15}"
    )
    output.append("-" * 80)

    # Parameters
    params = [
        "swing_lookback",
        "displacement_ratio",
        "fvg_min_gap_percent",
        "ob_min_strength",
        "liquidity_tolerance",
        "rr_ratio",
    ]

    for param in params:
        strict_val = profiles["strict"][param]
        balanced_val = profiles["balanced"][param]
        relaxed_val = profiles["relaxed"][param]

        output.append(
            f"{param:<25} {strict_val:<15} {balanced_val:<15} {relaxed_val:<15}"
        )

    output.append("-" * 80)

    # Signal frequency
    output.append(
        f"{'Signal Frequency':<25} "
        f"{profiles['strict']['signal_frequency']:<15} "
        f"{profiles['balanced']['signal_frequency']:<15} "
        f"{profiles['relaxed']['signal_frequency']:<15}"
    )

    output.append("-" * 80)

    # Use cases
    output.append("\nUse Cases:")
    for profile_name, config in profiles.items():
        output.append(f"  {profile_name.upper()}: {config['use_case']}")

    output.append("\n" + "=" * 80 + "\n")

    return "\n".join(output)


if __name__ == "__main__":
    # Demo usage
    print(compare_profiles())

    print("\nBalanced Profile Parameters:")
    balanced_params = get_profile_parameters(ICTProfile.BALANCED)
    for key, value in balanced_params.items():
        print(f"  {key}: {value}")

    print("\nBalanced Profile Info:")
    balanced_info = get_profile_info(ICTProfile.BALANCED)
    for key, value in balanced_info.items():
        print(f"  {key}: {value}")
