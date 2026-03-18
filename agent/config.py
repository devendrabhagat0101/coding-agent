# Model identifiers
DEFAULT_MODEL = "llama3:8b"
CODER_MODEL = "qwen2.5-coder:7b"

# How much file content to include in the system prompt before truncating.
# ~32 K chars keeps most models inside their context window comfortably.
CONTEXT_MAX_CHARS = 32_000

# Directories never included in the project context snapshot
IGNORED_DIRS: set[str] = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    ".tox",
    ".eggs",
    "*.egg-info",
    ".idea",
    ".vscode",
}

# File extensions treated as plain text (everything else is skipped)
TEXT_EXTENSIONS: set[str] = {
    ".py", ".pyi",
    ".js", ".mjs", ".cjs",
    ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    ".cs", ".rb", ".php", ".swift", ".kt",
    ".dart", ".ex", ".exs",
    ".sh", ".bash", ".zsh", ".fish",
    ".html", ".css", ".scss", ".sass",
    ".sql", ".graphql",
    ".md", ".txt", ".rst",
    ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf",
    ".env.example", ".gitignore", ".dockerignore",
    "Dockerfile", "Makefile",
}

# Hard-skip these filenames regardless of extension (may contain secrets)
IGNORED_FILENAMES: set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    "secrets.yaml",
    "secrets.yml",
}
