# coding-agent v2.0.2

A local AI-powered coding assistant CLI built on [Ollama](https://ollama.ai). Runs entirely on your machine — no cloud APIs, no data leaving your system.

**What it can do:**
- Review, refactor, and edit code files via AI
- Autonomous project builder — reads a requirements file and generates a full project (Flutter + Java + Python)
- Write documents in any format: `.docx` `.pptx` `.xlsx` `.pdf` `.md` `.txt` `.csv`
- Manage git (branch, commit, push) from chat
- Run as an MCP server so Claude Code can call its tools directly

---

## How It Works

```
You (CLI / chat)
      ↓
  coding-agent CLI  (typer)
      ↓
  CodingEngine      →  Ollama (local LLM: llama3:8b / qwen2.5-coder:7b)
      ↓                       ↑ streams tokens back
  git_ops           →  GitPython  (branch / commit / push)
  file_writer       →  python-docx / python-pptx / openpyxl / fpdf2
  builder           →  Autonomous multi-service project generator
      ↓
  Local filesystem  (read / write / review / refactor / generate)
```

- **Auth** — first-run registration stores a hashed password in `~/.coding-agent/auth.json`. Sessions expire after 24 hours.
- **Directory permissions** — before reading/writing, the agent asks you to approve the directory once.
- **Multi-turn chat** — conversation history is kept in memory so follow-up questions have full context.

---

## Prerequisites

### macOS

| Requirement | Version | How to install |
|---|---|---|
| Python | 3.10+ | `brew install python@3.11` or [python.org](https://python.org) |
| pip | latest | Comes with Python |
| Ollama | latest | [ollama.ai/download](https://ollama.ai/download) — download the macOS `.dmg` |
| Git | any | `brew install git` or Xcode Command Line Tools |
| (Optional) Homebrew | — | `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` |

Verify installs:
```bash
python3.11 --version    # Python 3.11.x
ollama --version        # ollama version x.x.x
git --version           # git version x.x.x
```

---

### Windows

| Requirement | Version | How to install |
|---|---|---|
| Python | 3.10+ | [python.org/downloads](https://python.org/downloads) — check **"Add Python to PATH"** during install |
| pip | latest | Comes with Python |
| Ollama | latest | [ollama.ai/download](https://ollama.ai/download) — download the Windows `.exe` installer |
| Git | any | [git-scm.com/download/win](https://git-scm.com/download/win) — use default options |
| Windows Terminal | recommended | Microsoft Store → search "Windows Terminal" |

Verify installs (open **Command Prompt** or **PowerShell**):
```powershell
python --version        # Python 3.11.x
pip --version           # pip x.x.x
ollama --version        # ollama version x.x.x
git --version           # git version x.x.x
```

> **Windows tip:** Use **PowerShell** or **Windows Terminal** — avoid the old `cmd.exe` for best experience.

---

## Quick Start

### macOS

```bash
# 1. Install coding-agent
pip3.11 install git+https://github.com/devendrabhagat0101/Dev-2.0-AI-Assistant.git#subdirectory=coding-agent

# — or clone and install locally —
git clone https://github.com/devendrabhagat0101/Dev-2.0-AI-Assistant.git
cd Dev-2.0-AI-Assistant/coding-agent
pip3.11 install -e .

# 2. Start Ollama (keep this terminal open)
ollama serve

# 3. Pull models (new terminal)
ollama pull llama3:8b           # general chat + project planning
ollama pull qwen2.5-coder:7b    # code generation, review, refactor

# 4. Run
coding-agent --version          # coding-agent v2.0.2
coding-agent                    # start interactive chat
```

---

### Windows

```powershell
# 1. Install coding-agent (PowerShell)
pip install git+https://github.com/devendrabhagat0101/Dev-2.0-AI-Assistant.git#subdirectory=coding-agent

# — or clone and install locally —
git clone https://github.com/devendrabhagat0101/Dev-2.0-AI-Assistant.git
cd Dev-2.0-AI-Assistant\coding-agent
pip install -e .

# 2. Start Ollama
# Option A: Ollama runs as a background service after install — nothing to start manually
# Option B: if not running, open a new PowerShell and run:
ollama serve

# 3. Pull models (new PowerShell window)
ollama pull llama3:8b
ollama pull qwen2.5-coder:7b

# 4. Run
coding-agent --version          # coding-agent v2.0.2
coding-agent                    # start interactive chat
```

> **Windows PATH note:** If `coding-agent` is not found after install, add Python Scripts to PATH:
> `C:\Users\<YourName>\AppData\Local\Programs\Python\Python311\Scripts`
> Or run via: `python -m agent.cli`

---

## CLI Commands

```bash
# Chat
coding-agent                                    # interactive chat (current dir)
coding-agent chat --dir /path/to/project        # chat for a specific project

# Code quality
coding-agent review FILE                        # AI code review
coding-agent review FILE --apply                # review + apply fixes interactively
coding-agent refactor FILE                      # AI refactor (preview)
coding-agent refactor FILE --write              # refactor + write back to file

# Document generation (NEW in v2.0.2)
coding-agent write-doc "INSTRUCTION" --output FILE.docx   # Word document
coding-agent write-doc "INSTRUCTION" --output FILE.pptx   # PowerPoint slides
coding-agent write-doc "INSTRUCTION" --output FILE.xlsx   # Excel workbook
coding-agent write-doc "INSTRUCTION" --output FILE.pdf    # PDF
coding-agent write-doc "INSTRUCTION" --output FILE.md     # Markdown
coding-agent write-doc "INSTRUCTION" --output FILE.csv    # CSV

# Autonomous project builder (NEW in v2.0.1)
coding-agent build requirements.md --dir ./my-project     # build from requirements
coding-agent build requirements.docx --dir ./my-project   # .docx requirements supported

# Git & project setup
coding-agent init REPO_NAME                     # scaffold new git repo
coding-agent fix-from-chat                      # apply AI-service screenshot fixes

# MCP server
coding-agent mcp-serve                          # start MCP server (cwd)
coding-agent mcp-serve --dir /path              # start MCP server for a project

# Auth
coding-agent login                              # re-authenticate
coding-agent logout                             # end session
coding-agent whoami                             # show current user
coding-agent --version                          # show version
```

---

## Interactive Chat — Slash Commands

Inside `coding-agent` chat, type natural language or use slash commands:

| Command | What it does |
|---|---|
| `/read FILE` | Read and display a file |
| `/review FILE` | AI code review with numbered issues |
| `/edit FILE INSTRUCTION` | Apply a targeted AI edit |
| `/branch NAME` | Create and checkout a new git branch |
| `/commit "MESSAGE"` | Stage all changes and commit |
| `/push` | Push current branch to origin |
| `/remote add NAME URL` | Add a git remote |
| `/remote list` | List configured remotes |
| `/status` | Show git branch and status |
| `/model MODEL` | Switch Ollama model mid-session |
| `/tree` | Print the project file tree |
| `/clear` | Clear conversation history |
| `/help` | Show all commands |
| `/quit` | Exit |

---

## Usage Examples

### Chat — ask questions
```
> what does engine.py do?
> find all functions that call git_ops
> explain the auth flow
```

### Chat — make changes
```
> /edit agent/engine.py add a retry on OllamaUnavailableError with 3 attempts
> /branch feature/retry-logic
> /commit "feat: retry Ollama connection up to 3 times"
> /push
```

### Document generation
```bash
# Word document
coding-agent write-doc "Project summary for WeatherAgent with architecture and requirements" \
  --output summary.docx

# PowerPoint presentation
coding-agent write-doc "5-slide architecture overview for WeatherAgent" \
  --output slides.pptx

# Excel — with project context
coding-agent write-doc "API endpoints comparison table" \
  --output api_table.xlsx --context-dir ./backend

# PDF technical spec
coding-agent write-doc "WeatherAgent technical specification" \
  --output spec.pdf
```

### Autonomous project build
```bash
# Build a full Flutter + Java + Python project from requirements
coding-agent build WeatherAgent_Requirements.md --dir ./weather-project

# Build without auto-review (faster)
coding-agent build requirements.docx --dir ./my-app --no-review
```

### Code review
```bash
coding-agent review agent/engine.py
# Output:
# 1. Issue: bare except swallows errors
#    Location: stream_chat, line 73
#    Fix: catch specific exceptions
```

### Work on a different project
```bash
# macOS / Linux
coding-agent chat --dir /path/to/other-project

# Windows
coding-agent chat --dir C:\Users\Dev\projects\other-project
```

---

## Write-Doc — Supported Formats

| Format | Extension | Library | Best for |
|---|---|---|---|
| Word | `.docx` | python-docx | Reports, specs, requirements |
| PowerPoint | `.pptx` | python-pptx | Presentations, slides |
| Excel | `.xlsx` | openpyxl | Data tables, comparisons |
| PDF | `.pdf` | fpdf2 | Shareable reports |
| Markdown | `.md` | built-in | Docs, READMEs, wikis |
| Plain text | `.txt` | built-in | Notes, changelogs |
| CSV | `.csv` | built-in | Data export, spreadsheets |

---

## Autonomous Builder — How It Works

```
requirements.md / .txt / .docx
      ↓
AI Planning  (Ollama generates JSON project plan)
      ↓
For each service (Flutter UI / Java API / Python AI):
  1. Scaffold    → flutter create / mkdir
  2. Generate    → AI writes each file with cross-file context
  3. Review      → AI checks for bugs / missing imports
  4. Fix         → AI rewrites if issues found
  5. Write       → saved to disk
      ↓
Git init + commit
```

---

## MCP Server

Run as an MCP server so Claude Code (or any MCP client) can call tools directly.

### Start
```bash
# macOS / Linux
coding-agent mcp-serve --dir /path/to/your/project

# Windows
coding-agent mcp-serve --dir C:\Users\Dev\projects\my-project
```

### Register with Claude Code
Add to `~/.claude/mcp.json`:
```json
{
  "mcpServers": {
    "coding-agent": {
      "command": "coding-agent",
      "args": ["mcp-serve", "--dir", "/path/to/your/project"]
    }
  }
}
```

### MCP Tools (14 total)

| Category | Tools |
|---|---|
| **File** | `read_file`, `write_file`, `list_files`, `get_diff` |
| **Git** | `git_status`, `create_branch`, `commit_changes`, `push_branch`, `add_remote`, `list_remotes` |
| **AI** | `review_file`, `refactor_file`, `apply_edit` *(require Ollama)* |
| **Documents** | `write_document` — generates .docx/.pptx/.xlsx/.pdf/.md/.txt/.csv |

### MCP Resources

| URI | Returns |
|---|---|
| `project://tree` | Full file tree |
| `project://file/{path}` | Any file content |
| `git://status` | Branch + staged/unstaged diff |
| `git://log` | Last 20 commits |
| `git://branches` | All local branches |

### MCP Prompts

| Prompt | Purpose |
|---|---|
| `review_file(file_path)` | Numbered code review |
| `write_commit_message()` | Conventional commit from staged diff |
| `explain_code(file_path)` | Plain-English explanation |
| `fix_issue(file_path, issue_description)` | Minimal targeted fix |

---

## Models

| Use case | Default model | Override |
|---|---|---|
| Chat + planning | `llama3:8b` | `--model MODEL` |
| Code gen / review / refactor | `qwen2.5-coder:7b` | `--model MODEL` |
| Document writing | `qwen2.5-coder:7b` | `--model MODEL` |

Switch model mid-chat:
```
> /model qwen2.5-coder:7b
```

---

## Project Structure

```
coding-agent/
├── agent/
│   ├── cli.py          # CLI entry point — all commands
│   ├── engine.py       # Ollama wrapper (streaming + one-shot)
│   ├── git_ops.py      # Git operations (GitPython)
│   ├── builder.py      # Autonomous project builder (v2.0.1)
│   ├── file_writer.py  # Rich document writer — docx/pptx/xlsx/pdf (v2.0.2)
│   ├── mcp_server.py   # MCP server (14 tools + resources + prompts)
│   ├── auth.py         # Local auth + session + directory permissions
│   ├── context.py      # File tree + system prompt builder (.docx aware)
│   ├── fixer.py        # Apply AI-suggested fixes to files
│   └── config.py       # Version, model defaults, constants
├── tests/              # pytest test suite
└── pyproject.toml      # Package metadata and dependencies
```

---

## Sharing With Other Developers

```bash
# Install from GitHub (macOS / Linux)
pip install git+https://github.com/devendrabhagat0101/Dev-2.0-AI-Assistant.git#subdirectory=coding-agent

# Install from GitHub (Windows PowerShell)
pip install git+https://github.com/devendrabhagat0101/Dev-2.0-AI-Assistant.git#subdirectory=coding-agent

# Clone and install locally
git clone https://github.com/devendrabhagat0101/Dev-2.0-AI-Assistant.git
cd Dev-2.0-AI-Assistant/coding-agent
pip install -e .
```

Each developer needs their own Ollama installation and pulled models — no shared server required.

---

## Troubleshooting

### Ollama — Installation & Setup

#### How to install Ollama on Windows
1. Go to **[ollama.ai/download](https://ollama.ai/download)**
2. Click **"Download for Windows"** — downloads `OllamaSetup.exe`
3. Run the installer with default options
4. Ollama installs as a **Windows background service** — starts automatically on login

Verify in PowerShell:
```powershell
ollama --version           # ollama version 0.x.x
curl http://localhost:11434
# Response: {"status":"Ollama is running"}
```

Pull the required models:
```powershell
ollama pull llama3:8b          # ~4.7 GB — general chat + planning
ollama pull qwen2.5-coder:7b   # ~4.4 GB — code generation + review
```

> Models are stored at `C:\Users\<YourName>\.ollama\models\`

---

#### How coding-agent connects to Ollama automatically

No configuration needed. The agent connects via HTTP on startup:

```
coding-agent
     ↓
CodingEngine  →  ollama Python library
                      ↓
              HTTP POST http://localhost:11434
                      ↓
              Ollama service (Windows background / macOS process)
                      ↓
              llama3:8b / qwen2.5-coder:7b  (runs locally)
```

On every command the agent checks:
```
Ollama reachable?  →  No  →  "Run ollama serve"
Model pulled?      →  No  →  "Run ollama pull llama3:8b"
Both OK?           →  Yes →  Proceeds normally
```

#### Ollama not starting automatically on Windows
```powershell
# Check service status
Get-Service -Name "ollama"

# Start it manually
ollama serve

# Or start the Windows service
Start-Service -Name "ollama"
```

#### Using Ollama on a different host/port
```powershell
# Windows
$env:OLLAMA_HOST = "http://192.168.1.10:11434"
coding-agent

# macOS / Linux
OLLAMA_HOST=http://192.168.1.10:11434 coding-agent
```

---

### Common Errors

| Problem | Platform | Fix |
|---|---|---|
| `coding-agent: command not found` | macOS | Add to `~/.zshrc`: `export PATH="$HOME/Library/Python/3.11/bin:$PATH"` then `source ~/.zshrc` |
| `coding-agent: command not found` | Windows | Add to PATH: `C:\Users\<Name>\AppData\Local\Programs\Python\Python311\Scripts` |
| `Could not reach Ollama` | Both | Run `ollama serve` in a separate terminal |
| `Model 'llama3:8b' not found` | Both | Run `ollama pull llama3:8b` |
| `mcp>=1.0.0 requires Python >=3.10` | Both | Use `python3.11 -m pip install -e .` instead of `pip install` |
| `.docx output is corrupt` | Both | Run `pip install python-docx` |
| `.pptx / .xlsx / .pdf not generated` | Both | Run `pip install python-pptx openpyxl fpdf2` |
| `UnicodeDecodeError` on file read | Windows | Set env variable: `PYTHONUTF8=1` in System Environment Variables |
| `git: command not found` | Windows | Install Git from [git-scm.com](https://git-scm.com/download/win) and restart terminal |
| `Permission denied` on directory | Both | Run `coding-agent` and type `y` when asked to approve the directory |
| `ollama pull` very slow | Both | Normal — models are 4–8 GB. Use a wired connection if possible |
| `Build plan JSON invalid` | Both | Try a larger/better model: `--model llama3:70b` or rerun the command |
| Session expired | Both | Run `coding-agent login` to start a new 24-hour session |

---

### Verifying everything works

Run this checklist before using coding-agent:

```bash
# 1. Python version
python3 --version              # must be 3.10+

# 2. coding-agent installed
coding-agent --version         # coding-agent v2.0.2

# 3. Ollama running
curl http://localhost:11434    # {"status":"Ollama is running"}

# 4. Models available
ollama list                    # should show llama3:8b and qwen2.5-coder:7b

# 5. Quick smoke test
coding-agent whoami            # shows logged-in user (or prompts to register)
```

All 5 passing? You're ready.
