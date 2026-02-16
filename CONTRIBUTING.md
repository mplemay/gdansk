# Contributing to Gdansk

Thank you for your interest in contributing to Gdansk! We welcome contributions from the community.

## Development Setup

To set up a development environment:

```bash
# Clone the repository
git clone https://github.com/mattlemay/gdansk.git
cd gdansk

# Install dependencies (including dev dependencies)
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=gdansk

# Run tests for a specific file
uv run pytest src/gdansk/__tests__/unit/test_core.py
```

## Code Quality

We use several tools to maintain code quality:

```bash
# Run linters
uv run ruff check .

# Auto-fix linting issues
uv run ruff check . --fix

# Format code
uv run ruff format .

# Type checking
uv run ty check src

# Markdown linting
uv run rumdl .
```

## Pre-commit Hooks

We use pre-commit hooks to ensure code quality. Install them with:

```bash
uv run pre-commit install
```

The hooks will run automatically on `git commit`. You can also run them manually:

```bash
uv run pre-commit run --all-files
```

## Project Structure

```text
gdansk/
├── src/
│   ├── lib.rs              # Rust bundler implementation
│   └── gdansk/
│       ├── __init__.py     # Package exports
│       ├── core.py         # Python Amber class
│       ├── _core.pyi       # Type stubs for Rust extension
│       └── __tests__/      # Test files
├── examples/               # Example MCP servers
├── Cargo.toml             # Rust dependencies
└── pyproject.toml         # Python project config
```

## Coding Guidelines

### Python

- Follow PEP 8 style guidelines (enforced by ruff)
- Use type hints for all function signatures
- Write docstrings for public functions and classes
- Use dataclasses for data structures
- Target Python 3.11+ syntax and features

### Rust

- Follow standard Rust formatting (rustfmt)
- Use clippy for linting
- Write comprehensive error messages
- Include unit tests for new functionality

### Testing

- Write tests for all new features
- Place unit tests in `src/gdansk/__tests__/unit/`
- Place integration tests in `src/gdansk/__tests__/integration/`
- Use descriptive test names
- Aim for high test coverage

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linters
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to your fork (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### PR Guidelines

- Provide a clear description of the changes
- Reference any related issues
- Ensure all tests pass
- Update documentation if needed
- Keep PRs focused on a single feature or fix

## Questions?

Feel free to open an issue for questions or discussions about contributing.

## License

By contributing to Gdansk, you agree that your contributions will be licensed under the MIT License.
