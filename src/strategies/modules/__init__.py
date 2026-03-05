"""
Strategy Modules Package.

This package contains pluggable components for ComposableStrategy:
- entry: Entry signal determiners
- exit: Dynamic exit logic
- sl: Stop loss calculation
- tp: Take profit calculation
- detectors: Shared ICT indicator detectors

Uses auto-discovery to register all modules in subdirectories.
"""

import importlib
import pkgutil
from pathlib import Path


def discover_modules():
    """
    Automatically import all submodules to trigger @register_module decorators.
    """
    root_path = Path(__file__).parent
    
    # Categories to scan
    categories = ["entry", "exit", "sl", "tp"]
    
    for category in categories:
        category_path = root_path / category
        if not category_path.exists():
            continue
            
        # Iterate over all .py files in category directory
        for _, module_name, is_pkg in pkgutil.iter_modules([str(category_path)]):
            if not is_pkg:
                full_module_path = f"src.strategies.modules.{category}.{module_name}"
                try:
                    importlib.import_module(full_module_path)
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Failed to load module {full_module_path}: {e}")

# Trigger discovery on package import
discover_modules()
