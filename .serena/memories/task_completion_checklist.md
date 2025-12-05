# Task Completion Checklist

## When a Task is Completed

### 1. Code Quality
- [ ] Run `black src/ tests/` - Format code
- [ ] Run `isort src/ tests/` - Sort imports
- [ ] Run `mypy src/` - Type check (must pass)
- [ ] Run `flake8 src/ tests/` - Lint code

### 2. Testing
- [ ] Write unit tests for new functionality
- [ ] Run `pytest` - All tests must pass
- [ ] Run `pytest --cov=src` - Check coverage
- [ ] Test coverage should be >80% for new code

### 3. Documentation
- [ ] Add docstrings to public functions/classes
- [ ] Update README.md if user-facing changes
- [ ] Add type hints to all function signatures

### 4. Integration
- [ ] Verify imports work: `python -c "from src.module import Class"`
- [ ] Check no circular dependencies
- [ ] Update `__init__.py` exports if needed

### 5. Configuration
- [ ] Update example config files if config changes
- [ ] Test config loading with examples
- [ ] Verify .gitignore excludes sensitive files

### 6. Git
- [ ] Review changes: `git diff`
- [ ] Commit with descriptive message
- [ ] Use conventional commits: `feat:`, `fix:`, `refactor:`, `test:`

## Quick Validation Script
```bash
# Run all quality checks at once
black src/ tests/ && \
isort src/ tests/ && \
mypy src/ && \
flake8 src/ tests/ && \
pytest --cov=src
```

## Task Master Integration
```bash
# Update task status
task-master set-status --id=<id> --status=done

# Add implementation notes
task-master update-subtask --id=<id> --prompt="implementation details..."
```
