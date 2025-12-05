# Code Style & Conventions

## Python Version
- **Minimum**: Python 3.11
- **Type Hints**: Required for all function signatures
- **Dataclasses**: Preferred for data structures

## Formatting Standards
- **Formatter**: Black (line-length: 100)
- **Import Sorting**: isort with Black profile
- **Line Length**: 100 characters

## Type Checking
- **Tool**: mypy with strict mode
- **Rules**: 
  - `disallow_untyped_defs = true`
  - `warn_return_any = true`
  - All functions must have type hints

## Naming Conventions
- **Classes**: PascalCase (e.g., `ConfigManager`, `OrderManager`)
- **Functions**: snake_case (e.g., `load_config`, `execute_order`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `MAX_RETRIES`)
- **Private**: Leading underscore (e.g., `_internal_method`)

## Docstrings
- Use for public APIs and complex logic
- Follow Google style docstrings
- Include type information in docstrings where helpful

## File Organization
- One class per file for models
- Related utilities can share files
- All directories must have `__init__.py`
