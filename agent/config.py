# ── Version ───────────────────────────────────────────────────────────────────
VERSION = "2.0.4"

# ── Model identifiers ─────────────────────────────────────────────────────────
DEFAULT_MODEL = "llama3:8b"          # general chat + planning
CODER_MODEL   = "qwen2.5-coder:7b"  # code generation, review, refactor
BUILD_MODEL   = "qwen2.5-coder:7b"  # autonomous builder (code-focused)

# ── Context window ────────────────────────────────────────────────────────────
# Increased from 32 K → 64 K to handle larger multi-file projects
CONTEXT_MAX_CHARS = 64_000

# ── Directories never included in the project context snapshot ────────────────
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
    ".dart_tool",
    ".gradle",
    ".flutter-plugins",
    ".flutter-plugins-dependencies",
}

# ── File extensions treated as plain text ─────────────────────────────────────
TEXT_EXTENSIONS: set[str] = {
    # Python
    ".py", ".pyi",
    # JavaScript / TypeScript
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    # Systems / Backend
    ".go", ".rs", ".java", ".kt", ".swift",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    ".cs", ".rb", ".php",
    # Mobile / Frontend
    ".dart",
    # Functional
    ".ex", ".exs",
    # Shell
    ".sh", ".bash", ".zsh", ".fish",
    # Web
    ".html", ".css", ".scss", ".sass",
    # Data / Config
    ".sql", ".graphql",
    ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf",
    ".env.example", ".gitignore", ".dockerignore",
    # Docs / Requirements  ← NEW: agent can now read requirements files
    ".md", ".txt", ".rst",
    # Build files
    "Dockerfile", "Makefile", "Gradlefile",
    ".gradle",          # Gradle build scripts
    ".properties",      # Spring Boot application.properties
    "pubspec.yaml",     # Flutter dependency file (also matched by .yaml)
}

# ── Hard-skip filenames regardless of extension ───────────────────────────────
IGNORED_FILENAMES: set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    "secrets.yaml",
    "secrets.yml",
}
