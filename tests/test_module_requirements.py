"""
Tests for ModuleRequirements dataclass.

Covers: creation, immutability, merge logic, validation.
"""

import pytest
from types import MappingProxyType

from src.models.module_requirements import ModuleRequirements


class TestModuleRequirementsCreation:
    """Test basic creation and defaults."""

    def test_empty_returns_empty_requirements(self):
        req = ModuleRequirements.empty()
        assert req.timeframes == frozenset()
        assert dict(req.min_candles) == {}

    def test_creation_with_values(self):
        req = ModuleRequirements(
            timeframes=frozenset({"5m", "1h"}),
            min_candles={"5m": 50, "1h": 100},
        )
        assert req.timeframes == frozenset({"5m", "1h"})
        assert req.min_candles["5m"] == 50
        assert req.min_candles["1h"] == 100

    def test_min_candles_wrapped_in_mapping_proxy(self):
        req = ModuleRequirements(
            timeframes=frozenset({"5m"}),
            min_candles={"5m": 50},
        )
        assert isinstance(req.min_candles, MappingProxyType)


class TestModuleRequirementsImmutability:
    """Test that ModuleRequirements is truly immutable."""

    def test_cannot_mutate_min_candles(self):
        req = ModuleRequirements(
            timeframes=frozenset({"5m"}),
            min_candles={"5m": 50},
        )
        with pytest.raises(TypeError):
            req.min_candles["5m"] = 9999

    def test_cannot_add_to_min_candles(self):
        req = ModuleRequirements(
            timeframes=frozenset({"5m"}),
            min_candles={"5m": 50},
        )
        with pytest.raises(TypeError):
            req.min_candles["1h"] = 100

    def test_cannot_reassign_attributes(self):
        req = ModuleRequirements.empty()
        with pytest.raises(AttributeError):
            req.timeframes = frozenset({"5m"})


class TestModuleRequirementsValidation:
    """Test __post_init__ validation."""

    def test_invalid_min_candles_key_raises_valueerror(self):
        with pytest.raises(ValueError, match="not in timeframes"):
            ModuleRequirements(
                timeframes=frozenset({"5m"}),
                min_candles={"1h": 100},
            )

    def test_empty_timeframes_skips_validation(self):
        """Empty timeframes with min_candles is allowed (edge case)."""
        req = ModuleRequirements(
            timeframes=frozenset(),
            min_candles={"5m": 50},
        )
        assert dict(req.min_candles) == {"5m": 50}

    def test_valid_subset_passes(self):
        req = ModuleRequirements(
            timeframes=frozenset({"5m", "1h", "4h"}),
            min_candles={"5m": 50, "1h": 100},
        )
        assert len(req.min_candles) == 2


class TestModuleRequirementsMerge:
    """Test merge logic."""

    def test_merge_empty_requirements(self):
        result = ModuleRequirements.merge(
            ModuleRequirements.empty(),
            ModuleRequirements.empty(),
        )
        assert result.timeframes == frozenset()
        assert dict(result.min_candles) == {}

    def test_merge_single_requirement(self):
        req = ModuleRequirements(
            timeframes=frozenset({"5m"}),
            min_candles={"5m": 50},
        )
        result = ModuleRequirements.merge(req)
        assert result.timeframes == frozenset({"5m"})
        assert result.min_candles["5m"] == 50

    def test_merge_unions_timeframes(self):
        r1 = ModuleRequirements(
            timeframes=frozenset({"5m", "1h"}),
            min_candles={"5m": 50, "1h": 50},
        )
        r2 = ModuleRequirements(
            timeframes=frozenset({"1h", "4h"}),
            min_candles={"1h": 30, "4h": 50},
        )
        result = ModuleRequirements.merge(r1, r2)
        assert result.timeframes == frozenset({"5m", "1h", "4h"})

    def test_merge_takes_max_min_candles(self):
        r1 = ModuleRequirements(
            timeframes=frozenset({"1h"}),
            min_candles={"1h": 50},
        )
        r2 = ModuleRequirements(
            timeframes=frozenset({"1h"}),
            min_candles={"1h": 200},
        )
        result = ModuleRequirements.merge(r1, r2)
        assert result.min_candles["1h"] == 200

    def test_merge_with_empty(self):
        req = ModuleRequirements(
            timeframes=frozenset({"5m"}),
            min_candles={"5m": 50},
        )
        result = ModuleRequirements.merge(req, ModuleRequirements.empty())
        assert result.timeframes == frozenset({"5m"})
        assert result.min_candles["5m"] == 50

    def test_merge_multiple_requirements(self):
        r1 = ModuleRequirements(
            timeframes=frozenset({"5m", "1h", "4h"}),
            min_candles={"5m": 50, "1h": 50, "4h": 50},
        )
        r2 = ModuleRequirements(
            timeframes=frozenset({"1h", "4h"}),
            min_candles={"1h": 50, "4h": 50},
        )
        r3 = ModuleRequirements.empty()
        r4 = ModuleRequirements.empty()
        result = ModuleRequirements.merge(r1, r2, r3, r4)
        assert result.timeframes == frozenset({"5m", "1h", "4h"})
        assert result.min_candles["5m"] == 50
        assert result.min_candles["1h"] == 50
        assert result.min_candles["4h"] == 50
