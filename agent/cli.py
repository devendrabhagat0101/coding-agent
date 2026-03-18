"""
CLI entry-point.

Default (no subcommand)
    coding-agent          → login gate → directory permission → start chat

Explicit commands
    coding-agent chat     [--dir DIR] [--model MODEL]
    coding-agent refactor FILE [--model MODEL] [--write] [--branch BRANCH]
    coding-agent init     REPO_NAME [--dir DIR]
    coding-agent login
    coding-agent logout
    coding-agent whoami
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.text import Text
import textwrap

from .config import CODER_MODEL, DEFAULT_MODEL, BUILD_MODEL, VERSION
from .context import build_file_tree, build_system_prompt
from .engine import CodingEngine, OllamaUnavailableError
from . import git_ops
from . import auth as _auth
from . import fixer as _fixer

# ── Typer app ─────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="coding-agent",
    help="Local AI coding agent powered by Ollama.",
    add_completion=False,
    pretty_exceptions_enable=False,
    invoke_without_command=True,   # run callback even with no subcommand
)

console     = Console()
err_console = Console(stderr=True, style="bold red")


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _engine_or_exit(model: str) -> CodingEngine:
    engine = CodingEngine(model=model)
    available = engine.list_local_models()
    if not available:
        err_console.print(
            "[bold red]✗ Cannot reach Ollama.[/] "
            "Run [cyan]ollama serve[/] and make sure at least one model is pulled."
        )
        raise typer.Exit(code=1)
    if model not in available:
        console.print(
            f"[yellow]⚠ Model [bold]{model}[/bold] not found locally.[/]\n"
            f"  Available: {', '.join(available)}\n"
            f"  Pull it with: [cyan]ollama pull {model}[/cyan]"
        )
        raise typer.Exit(code=1)
    return engine


def _stream_to_console(engine: CodingEngine, user_msg: str, **kwargs) -> str:
    tokens: list[str] = []
    try:
        with console.status("", spinner="dots"):
            gen  = engine.stream_chat(user_msg, **kwargs)
            first = next(gen, None)
        if first is None:
            return ""
        console.print()
        for token in [first, *gen]:
            tokens.append(token)
            console.print(token, end="", highlight=False)
        console.print()
    except OllamaUnavailableError as exc:
        err_console.print(f"\n✗ {exc}")
        raise typer.Exit(code=1) from exc
    return "".join(tokens)


def _extract_code_blocks(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
    return [(m.group(1) or "text", m.group(2)) for m in pattern.finditer(text)]


def _extract_file_blocks(text: str) -> list[tuple[str, str]]:
    """
    Scan an LLM reply for filename + content pairs.
    Returns list of (filename, content) — content is the raw text to write.

    Detects three patterns (in priority order):
      1. <!-- FILE: name.ext --> immediately before a code block  (preferred)
      2. **Creating `name.ext`** / **name.ext:** before a code block
      3. cat > name.ext  inside a bash code block
    """
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    # ── Pattern 1: <!-- FILE: filename --> ────────────────────────────────────
    p1 = re.compile(
        r"<!--\s*FILE:\s*([\w.\-/]+\.\w+)\s*-->\s*\n```(?:\w*)\n(.*?)```",
        re.DOTALL,
    )
    for m in p1.finditer(text):
        fname, content = m.group(1).strip(), m.group(2)
        if fname not in seen:
            results.append((fname, content))
            seen.add(fname)

    # ── Pattern 2: **Creating `filename.ext`** or **filename.ext:** ──────────
    p2 = re.compile(
        r"\*\*(?:[Cc]reating\s+)?[`\"]?([\w.\-/]+\.\w+)[`\"]?(?:\s+file)?[:\s]*\*\*"
        r"(?:.*?\n)*?```(?:\w*)\n(.*?)```",
        re.DOTALL,
    )
    for m in p2.finditer(text):
        fname, content = m.group(1).strip(), m.group(2)
        if fname not in seen:
            results.append((fname, content))
            seen.add(fname)

    # ── Pattern 3: cat > filename.ext  inside bash blocks ────────────────────
    bash_re = re.compile(r"```(?:bash|sh|shell|zsh)?\n(.*?)```", re.DOTALL)
    cat_re  = re.compile(
        r"(?:^\$\s*)?cat\s*>\s*([\w.\-/]+\.\w+)\s*\n(.*?)(?=(?:^\$\s*exit|\Z))",
        re.DOTALL | re.MULTILINE,
    )
    for bb in bash_re.finditer(text):
        for cm in cat_re.finditer(bb.group(1)):
            fname   = cm.group(1).strip()
            content = re.sub(r"^\$\s*", "", cm.group(2), flags=re.MULTILINE).rstrip()
            if fname not in seen:
                results.append((fname, content))
                seen.add(fname)

    return results


def _write_detected_files(
    file_blocks: list[tuple[str, str]],
    root: Path,
    engine,
) -> None:
    """Prompt the user and write each (filename, content) pair to *root*."""
    from .file_writer import SUPPORTED_FORMATS, write_document

    TEXT_EXTS = {".md", ".txt", ".csv", ".py", ".js", ".ts", ".html", ".css",
                 ".json", ".yaml", ".yml", ".toml", ".sh", ".bash", ".rb",
                 ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cpp", ".h",
                 ".sql", ".graphql", ".ini", ".cfg", ".env.example", ".rst"}

    console.print()
    console.print(
        Panel(
            "\n".join(f"  [cyan]{fname}[/]" for fname, _ in file_blocks),
            title=f"[bold yellow]↓ {len(file_blocks)} file(s) detected[/]",
            border_style="yellow",
            expand=False,
        )
    )

    if not Confirm.ask(f"Write to [cyan]{root}[/]?", default=True):
        console.print("[dim]Files not written.[/]")
        return

    for fname, content in file_blocks:
        out_path = (root / fname).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ext = Path(fname).suffix.lower()

        if ext in SUPPORTED_FORMATS and ext not in TEXT_EXTS:
            # Binary format (pptx, xlsx, pdf, docx) — use write_document
            console.print(f"[dim]Generating [cyan]{fname}[/] via document writer …[/]")
            try:
                from rich.progress import Progress, SpinnerColumn, TextColumn
                with Progress(SpinnerColumn(), TextColumn(f"[cyan]{fname}[/]"), transient=True) as prog:
                    prog.add_task("")
                    result = write_document(
                        instruction=(
                            f"Create a {ext.lstrip('.')} file named '{fname}' "
                            f"with the following content:\n\n{content}"
                        ),
                        output=out_path,
                        engine=engine,
                        context=content,
                    )
                size = result.stat().st_size
                console.print(f"[green]✓[/] Written [cyan]{result}[/]  ({size:,} bytes)")
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]✗ Failed to generate {fname}:[/] {exc}")
        else:
            # Plain text — write directly
            out_path.write_text(content, encoding="utf-8")
            size = out_path.stat().st_size
            console.print(f"[green]✓[/] Written [cyan]{out_path}[/]  ({size:,} bytes)")


# ── Auth / permission flow ─────────────────────────────────────────────────────

def _first_time_setup() -> str:
    """Walk the user through account creation. Returns username."""
    console.print(
        Panel(
            "[bold cyan]Welcome to coding-agent![/]\n\n"
            "This is your first time running the tool.\n"
            "Create a local account to get started.",
            title="First-time setup",
            expand=False,
        )
    )
    while True:
        username = Prompt.ask("[bold]Choose a username[/]").strip()
        if username:
            break
        console.print("[yellow]Username cannot be empty.[/]")

    while True:
        password = Prompt.ask("[bold]Choose a password[/]", password=True)
        confirm  = Prompt.ask("[bold]Confirm password[/]",  password=True)
        if password != confirm:
            console.print("[yellow]Passwords do not match. Try again.[/]")
            continue
        if len(password) < 4:
            console.print("[yellow]Password must be at least 4 characters.[/]")
            continue
        break

    _auth.register(username, password)
    _auth.create_session(username)
    console.print(f"[green]✓[/] Account created. Welcome, [bold cyan]{username}[/]!\n")
    return username


def _prompt_login() -> str:
    """Prompt for password, verify, create session. Returns username."""
    username = _auth.get_stored_username() or "user"
    console.print(
        Panel(
            f"[bold]coding-agent[/]  —  [cyan]{username}[/]",
            title="Login",
            expand=False,
        )
    )
    for attempt in range(3):
        password = Prompt.ask("[bold]Password[/]", password=True)
        result   = _auth.verify_credentials(password)
        if result:
            _auth.create_session(result)
            console.print(f"[green]✓[/] Logged in as [bold cyan]{result}[/]\n")
            return result
        remaining = 2 - attempt
        if remaining > 0:
            console.print(f"[red]✗ Incorrect password.[/] {remaining} attempt(s) left.")

    err_console.print("✗ Too many failed attempts. Exiting.")
    raise typer.Exit(code=1)


def _ensure_logged_in() -> str:
    """Return username, running setup or login flow as needed."""
    if not _auth.has_account():
        return _first_time_setup()
    session = _auth.get_active_session()
    if session:
        return session["username"]
    return _prompt_login()


def _request_directory_permission(directory: Path) -> None:
    """
    Show a permission panel for *directory*.
    Exits if the user declines.
    Approved directories are remembered permanently.
    """
    if _auth.is_directory_approved(directory):
        return   # already approved, silent pass

    console.print(
        Panel(
            f"[bold yellow]coding-agent[/] is requesting access to:\n\n"
            f"  [bold cyan]{directory.resolve()}[/]\n\n"
            f"  [dim]• Read all files in this directory[/]\n"
            f"  [dim]• Write and modify files[/]\n"
            f"  [dim]• Execute git operations[/]",
            title="[bold]Access Request[/]",
            border_style="yellow",
            expand=False,
        )
    )
    allowed = Confirm.ask("Allow coding-agent to access this folder?", default=False)
    if not allowed:
        console.print("[dim]Access denied. Exiting.[/]")
        raise typer.Exit(code=0)

    _auth.approve_directory(directory)
    console.print(f"[green]✓[/] Access granted. This folder will be remembered.\n")


# ── Default callback (runs when no subcommand is given) ───────────────────────

def _version_callback(value: bool) -> None:
    if value:
        console.print(f"coding-agent [bold cyan]v{VERSION}[/]")
        raise typer.Exit()


@app.callback()
def _default(
    ctx: typer.Context,
    directory: Path = typer.Option(
        Path.cwd(),
        "--dir", "-d",
        help="Project root (default: current directory).",
        show_default=False,
    ),
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model", "-m",
        help=f"Ollama model (default: {DEFAULT_MODEL}).",
    ),
    version: bool = typer.Option(
        False,
        "--version", "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """
    Run with no subcommand to launch the interactive chat agent
    after login and directory-permission checks.
    """
    if ctx.invoked_subcommand is not None:
        return   # a real subcommand was given — let it handle everything

    root     = directory.resolve()
    username = _ensure_logged_in()
    _request_directory_permission(root)

    # Hand off to the chat loop
    _run_chat(root=root, model=model, username=username)


# ── Chat helpers ───────────────────────────────────────────────────────────────

CHAT_HELP = textwrap.dedent("""\
    [bold cyan]Chat commands[/]
      [green]/help[/]                           show this message
      [green]/clear[/]                          clear conversation history
      [green]/tree[/]                           print the project file tree
      [green]/model MODEL[/]                    switch model mid-session
      [green]/read FILE[/]                      read a file (.docx supported) and inject into chat
      [green]/review FILE[/]                    AI code review — numbered corrections list
      [green]/edit FILE INSTRUCTION[/]          apply a targeted change to a file
      [green]/convert FILE OUTPUT.ext[/]        convert any file to docx/pptx/xlsx/pdf/md/txt/csv
      [green]/branch NAME[/]                    create & checkout a new git branch
      [green]/commit "MSG"[/]                   commit all current changes
      [green]/push [BRANCH][/]                  push current (or named) branch to origin
      [green]/remote add NAME URL[/]            add a git remote (e.g. origin on GitHub)
      [green]/remote list[/]                    list configured remotes
      [green]/status[/]                         show git status
      [green]/quit[/]  or Ctrl-D                exit
""")


def _run_chat(root: Path, model: str, username: str, no_context: bool = False) -> None:
    engine = _engine_or_exit(model)

    if not no_context:
        console.print(f"[dim]Loading project context from[/] [cyan]{root}[/] …")
        engine.add_system(build_system_prompt(root))
        console.print("[dim]Context loaded.[/]\n")

    console.print(
        Panel(
            f"[bold green]coding-agent[/]  •  [dim]user:[/] [cyan]{username}[/]  "
            f"•  [dim]model:[/] [cyan]{model}[/]\n"
            f"[dim]dir:[/] [cyan]{root}[/]\n"
            "[dim]Type [green]/help[/] for commands, Ctrl-D or /quit to exit.[/]",
            expand=False,
        )
    )

    while True:
        try:
            user_input = Prompt.ask(f"\n[bold blue]{username}[/]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # ── Slash commands ────────────────────────────────────────────────────
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd   = parts[0].lower()
            arg   = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/quit", "/exit", "/q"):
                console.print("[dim]Bye.[/]")
                break
            elif cmd == "/help":
                console.print(CHAT_HELP)
            elif cmd == "/clear":
                engine.clear_history()
                if not no_context:
                    engine.add_system(build_system_prompt(root))
                console.print("[dim]History cleared.[/]")
            elif cmd == "/tree":
                console.print(Syntax(build_file_tree(root), "text", line_numbers=False))
            elif cmd == "/model":
                if not arg:
                    console.print(f"[dim]Current model: [cyan]{engine.model}[/]")
                else:
                    engine.set_model(arg)
                    console.print(f"[dim]Switched to [cyan]{arg}[/]")
            elif cmd == "/branch":
                if not arg:
                    console.print("[yellow]Usage: /branch <name>[/]")
                else:
                    try:
                        git_ops.create_branch(root, arg)
                        console.print(f"[green]✓[/] Switched to branch [cyan]{arg}[/]")
                    except (ValueError, Exception) as exc:
                        console.print(f"[red]✗ {exc}[/]")
            elif cmd == "/commit":
                msg = arg.strip('"\'') if arg else Prompt.ask("Commit message")
                try:
                    sha = git_ops.commit_changes(root, msg)
                    console.print(f"[green]✓[/] Committed [cyan]{sha}[/]: {msg}")
                except (ValueError, RuntimeError) as exc:
                    console.print(f"[red]✗ {exc}[/]")
            elif cmd == "/status":
                repo = git_ops.get_repo(root)
                if repo is None:
                    console.print("[yellow]Not a git repository.[/]")
                else:
                    branch = git_ops.current_branch(root)
                    status = git_ops.status_summary(root)
                    console.print(
                        f"[dim]branch:[/] [cyan]{branch}[/]  [dim]status:[/] {status}"
                    )

            elif cmd == "/read":
                if not arg:
                    console.print("[yellow]Usage: /read <file>[/]")
                else:
                    target = Path(arg) if Path(arg).is_absolute() else root / arg
                    if not target.exists():
                        console.print(f"[red]✗ File not found:[/] {target}")
                    else:
                        from .context import _read_file
                        content  = _read_file(target)   # handles .docx, .txt, and all text files
                        lang     = target.suffix.lstrip(".") or "text"
                        rel      = target.relative_to(root) if target.is_relative_to(root) else target
                        console.print(
                            Panel(
                                Syntax(content, lang if lang != "docx" else "text",
                                       theme="monokai", line_numbers=True),
                                title=f"[bold cyan]{rel}[/]",
                                border_style="cyan",
                                expand=False,
                            )
                        )
                        # Inject into conversation so the model can answer questions
                        inject = (
                            f"I've just read `{rel}`. Here's its content:\n\n"
                            f"```\n{content}\n```\n\n"
                            "Please keep this file in mind for my next questions."
                        )
                        reply = _stream_to_console(engine, inject)
                        _ = reply

            elif cmd == "/convert":
                # /convert SOURCE OUTPUT.ext
                # e.g.  /convert report.docx slides.pptx
                #        /convert notes.txt  summary.pdf
                conv_parts = arg.split(maxsplit=1)
                if len(conv_parts) < 2:
                    console.print(
                        "[yellow]Usage: /convert <source_file> <output_file.ext>[/]\n"
                        "[dim]Supported output formats: .docx .pptx .xlsx .pdf .md .txt .csv[/]"
                    )
                else:
                    src_arg, out_arg = conv_parts[0], conv_parts[1]
                    src    = Path(src_arg) if Path(src_arg).is_absolute() else root / src_arg
                    out    = Path(out_arg) if Path(out_arg).is_absolute() else root / out_arg

                    if not src.exists():
                        console.print(f"[red]✗ Source file not found:[/] {src}")
                    else:
                        from .context import _read_file
                        from .file_writer import write_document, SUPPORTED_FORMATS

                        out_fmt = out.suffix.lower()
                        if out_fmt not in SUPPORTED_FORMATS:
                            console.print(
                                f"[red]✗ Unsupported output format:[/] {out_fmt}\n"
                                f"[dim]Supported: {', '.join(sorted(SUPPORTED_FORMATS))}[/]"
                            )
                        else:
                            # Read source content
                            src_content = _read_file(src)
                            src_rel     = src.relative_to(root) if src.is_relative_to(root) else src

                            console.print(
                                f"[dim]Converting[/] [cyan]{src_rel}[/] "
                                f"[dim]→[/] [cyan]{out.name}[/] …"
                            )

                            instruction = (
                                f"Convert the following document content into a well-structured "
                                f"{out_fmt.lstrip('.')} file. Preserve all sections, tables, "
                                f"bullet points, and key information from the source.\n\n"
                                f"Source file: {src.name}\n\n"
                                f"{src_content}"
                            )

                            from rich.progress import Progress, SpinnerColumn, TextColumn
                            try:
                                with Progress(
                                    SpinnerColumn(),
                                    TextColumn(f"[cyan]Generating {out_fmt} …"),
                                    transient=True,
                                ) as prog:
                                    prog.add_task("")
                                    result = write_document(
                                        instruction=instruction,
                                        output=out.resolve(),
                                        engine=engine,
                                        context=src_content,
                                    )
                                size = result.stat().st_size
                                console.print(
                                    Panel(
                                        f"[bold green]✓ Converted![/]\n\n"
                                        f"  [dim]Source :[/] [cyan]{src_rel}[/]\n"
                                        f"  [dim]Output :[/] [cyan]{result}[/]\n"
                                        f"  [dim]Size   :[/] {size:,} bytes",
                                        expand=False,
                                    )
                                )
                            except Exception as exc:  # noqa: BLE001
                                console.print(f"[red]✗ Conversion failed:[/] {exc}")

            elif cmd == "/review":
                if not arg:
                    console.print("[yellow]Usage: /review <file>[/]")
                else:
                    target = Path(arg) if Path(arg).is_absolute() else root / arg
                    if not target.exists():
                        console.print(f"[red]✗ File not found:[/] {target}")
                    else:
                        content = target.read_text(encoding="utf-8", errors="replace")
                        lang    = target.suffix.lstrip(".") or "text"
                        rel     = target.relative_to(root) if target.is_relative_to(root) else target
                        review_prompt = (
                            f"Review `{rel}` for bugs, security issues, and improvements.\n\n"
                            "Format your response as a **numbered list** — one item per issue.\n"
                            "For each item include:\n"
                            "  - **Issue**: what is wrong or could be better\n"
                            "  - **Location**: function name or approximate line\n"
                            "  - **Fix**: the exact change needed\n\n"
                            "After the list, add a short summary of overall code quality.\n\n"
                            f"```{lang}\n{content}\n```"
                        )
                        console.print(f"\n[bold green]agent[/] [dim](reviewing {rel})[/]", end="")
                        _stream_to_console(engine, review_prompt)

            elif cmd == "/edit":
                # /edit FILE INSTRUCTION — e.g. /edit main.py add null check to process()
                parts2 = arg.split(maxsplit=1)
                if len(parts2) < 2:
                    console.print("[yellow]Usage: /edit <file> <instruction>[/]")
                else:
                    file_arg, instruction = parts2[0], parts2[1]
                    target = Path(file_arg) if Path(file_arg).is_absolute() else root / file_arg
                    if not target.exists():
                        console.print(f"[red]✗ File not found:[/] {target}")
                    else:
                        original = target.read_text(encoding="utf-8", errors="replace")
                        lang     = target.suffix.lstrip(".") or "text"
                        rel      = target.relative_to(root) if target.is_relative_to(root) else target

                        console.print(f"[dim]Applying edit to[/] [cyan]{rel}[/] …")
                        from . import fixer as _fixer_local
                        try:
                            fixed = _fixer_local.apply_fix_with_engine(
                                engine, target, instruction, instruction
                            )
                        except OllamaUnavailableError as exc:
                            err_console.print(f"✗ {exc}")
                            continue

                        diff = _fixer_local.unified_diff(original, fixed, target.name)
                        if not diff:
                            console.print("[yellow]⚠ No changes produced.[/]")
                        else:
                            console.print(
                                Panel(
                                    Syntax(diff, "diff", theme="monokai", line_numbers=False),
                                    title=f"[bold]Diff — {target.name}[/]",
                                    border_style="cyan",
                                    expand=False,
                                )
                            )
                            if Confirm.ask("Apply this change?", default=True):
                                target.write_text(fixed, encoding="utf-8")
                                console.print(f"[green]✓[/] Written to [cyan]{rel}[/]")
                                if Confirm.ask("Commit this change?", default=False):
                                    msg = engine.complete(
                                        f"Short imperative git commit message (≤72 chars) for: {instruction}",
                                        temperature=0.1,
                                    ).strip().strip('"').strip("'")
                                    try:
                                        sha = git_ops.commit_changes(root, f"fix: {msg}", files=[str(target)])
                                        console.print(f"[green]✓[/] Committed [cyan]{sha}[/]: {msg}")
                                    except (ValueError, RuntimeError) as exc:
                                        console.print(f"[yellow]⚠ Commit failed: {exc}[/]")
                            else:
                                console.print("[dim]Edit discarded.[/]")

            elif cmd == "/push":
                branch_arg = arg.strip() or None
                try:
                    url = git_ops.push_branch(root, branch=branch_arg)
                    pushed = branch_arg or git_ops.current_branch(root)
                    console.print(f"[green]✓[/] Pushed [cyan]{pushed}[/] → [dim]{url}[/]")
                except (ValueError, Exception) as exc:
                    console.print(f"[red]✗ Push failed:[/] {exc}")

            elif cmd == "/remote":
                sub_parts = arg.split(maxsplit=2)
                sub = sub_parts[0].lower() if sub_parts else ""
                if sub == "list" or not sub:
                    remotes = git_ops.list_remotes(root)
                    if not remotes:
                        console.print("[dim]No remotes configured.[/]")
                    else:
                        for name, url in remotes:
                            console.print(f"  [cyan]{name}[/]  {url}")
                elif sub == "add":
                    if len(sub_parts) < 3:
                        console.print("[yellow]Usage: /remote add <name> <url>[/]")
                    else:
                        r_name, r_url = sub_parts[1], sub_parts[2]
                        try:
                            git_ops.add_remote(root, r_name, r_url)
                            console.print(f"[green]✓[/] Added remote [cyan]{r_name}[/] → {r_url}")
                        except (ValueError, Exception) as exc:
                            console.print(f"[red]✗ {exc}[/]")
                else:
                    console.print(f"[yellow]Unknown remote sub-command: {sub}[/]  Use 'add' or 'list'.")

            else:
                console.print(f"[yellow]Unknown command: {cmd}[/]  Type /help for help.")
            continue

        # ── Normal message ────────────────────────────────────────────────────
        console.print("\n[bold green]agent[/]", end="")
        reply  = _stream_to_console(engine, user_input)

        # Auto-detect files in the reply and offer to write them to disk
        file_blocks = _extract_file_blocks(reply)
        if file_blocks:
            _write_detected_files(file_blocks, root, engine)
        else:
            blocks = _extract_code_blocks(reply)
            if len(blocks) == 1:
                lang, code = blocks[0]
                console.print(
                    Panel(
                        Syntax(code.rstrip(), lang or "text", theme="monokai", line_numbers=True),
                        title=f"[dim]{lang}[/]",
                        border_style="dim",
                        expand=False,
                    )
                )


# ── Subcommand: chat ───────────────────────────────────────────────────────────

@app.command()
def chat(
    directory: Path = typer.Option(
        Path.cwd(), "--dir", "-d", show_default=False,
        help="Project root to use as context.",
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m"),
    no_context: bool = typer.Option(False, "--no-context"),
) -> None:
    """Start an interactive chat session (with login + permission gate)."""
    root     = directory.resolve()
    username = _ensure_logged_in()
    _request_directory_permission(root)
    _run_chat(root=root, model=model, username=username, no_context=no_context)


# ── Subcommand: refactor ───────────────────────────────────────────────────────

@app.command()
def refactor(
    file: Path = typer.Argument(..., help="File to refactor."),
    model: str = typer.Option(CODER_MODEL, "--model", "-m"),
    instruction: str = typer.Option("", "--instruction", "-i"),
    write: bool  = typer.Option(False, "--write", "-w"),
    branch: str  = typer.Option("", "--branch", "-b"),
    context: bool = typer.Option(True, "--context/--no-context"),
) -> None:
    """Refactor a file using qwen2.5-coder (or another model)."""
    if not file.exists():
        err_console.print(f"✗ File not found: {file}")
        raise typer.Exit(code=1)

    root     = Path.cwd().resolve()
    username = _ensure_logged_in()
    _request_directory_permission(root)

    engine  = _engine_or_exit(model)
    source  = file.read_text(encoding="utf-8", errors="replace")
    lang    = file.suffix.lstrip(".") or "text"
    goal    = instruction or "Improve readability, add type hints and docstrings, follow best practices."

    system_parts = [
        "You are an expert software engineer specialising in code refactoring.",
        "Return ONLY the refactored code inside a single fenced code block.",
        "Do not add explanations outside the block.",
    ]
    if context:
        system_parts.append(f"\n## Project Structure\n```\n{build_file_tree(root)}\n```")

    console.print(
        Panel(
            f"[bold]Refactoring[/] [cyan]{file}[/]\n"
            f"[dim]model:[/] [cyan]{model}[/]  [dim]goal:[/] {goal}",
            expand=False,
        )
    )

    console.print("\n[bold green]agent[/]", end="")
    reply = _stream_to_console(
        engine,
        f"Refactor `{file.name}` ({lang}).\n\n**Goal:** {goal}\n\n```{lang}\n{source}\n```",
        system="\n".join(system_parts),
        temperature=0.1,
    )

    blocks = _extract_code_blocks(reply)
    if not blocks:
        console.print("\n[yellow]⚠ No code block found in response.[/]")
        raise typer.Exit(code=0)

    _, refactored_code = blocks[0]
    refactored_code    = refactored_code.rstrip() + "\n"

    console.print(
        Panel(
            Syntax(refactored_code, lang, theme="monokai", line_numbers=True),
            title=f"[bold]Refactored: {file.name}[/]",
            border_style="green",
        )
    )

    if not write:
        console.print("[dim]Pass [bold]--write[/] to overwrite the file.[/]")
        return

    if branch:
        try:
            git_ops.create_branch(root, branch)
            console.print(f"[green]✓[/] Created & switched to branch [cyan]{branch}[/]")
        except (ValueError, Exception) as exc:
            console.print(f"[red]✗ Could not create branch: {exc}[/]")
            if not Confirm.ask("Continue writing without branching?"):
                raise typer.Exit(code=1) from exc

    file.write_text(refactored_code, encoding="utf-8")
    console.print(f"[green]✓[/] Wrote refactored code to [cyan]{file}[/]")

    if branch:
        try:
            commit_msg = engine.complete(
                f"Write a short imperative git commit message (≤72 chars) for: {goal}\nFile: {file.name}",
                temperature=0.1,
            ).strip().strip('"').strip("'")
            sha = git_ops.commit_changes(root, commit_msg, files=[str(file)])
            console.print(f"[green]✓[/] Committed [cyan]{sha}[/]: {commit_msg}")
        except (ValueError, RuntimeError) as exc:
            console.print(f"[yellow]⚠ Auto-commit failed: {exc}[/]")


# ── Subcommand: init ───────────────────────────────────────────────────────────

@app.command()
def init(
    repo_name: str = typer.Argument(..., help="Name of the new repository."),
    directory: Path = typer.Option(Path.cwd(), "--dir", "-d", show_default=False),
    description: str = typer.Option("", "--description"),
    scaffold: bool = typer.Option(True, "--scaffold/--no-scaffold"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m"),
) -> None:
    """Initialise a new git repository and optionally scaffold a starter project."""
    repo_path = (directory / repo_name).resolve()

    if repo_path.exists():
        err_console.print(f"✗ Directory already exists: {repo_path}")
        raise typer.Exit(code=1)

    username = _ensure_logged_in()
    _request_directory_permission(directory.resolve())

    console.print(f"[dim]Creating repository at[/] [cyan]{repo_path}[/] …")
    try:
        git_ops.init_repo(repo_path)
    except Exception as exc:
        err_console.print(f"✗ Failed to initialise repo: {exc}")
        raise typer.Exit(code=1) from exc

    _auth.approve_directory(repo_path)   # auto-approve new repo
    console.print(f"[green]✓[/] Initialised git repo: [cyan]{repo_path}[/]")

    if not scaffold:
        console.print("[dim]Done.[/]")
        return

    engine       = _engine_or_exit(model)
    project_desc = description or Prompt.ask("Describe the project", default="a Python CLI tool")

    system = (
        "You are an expert software architect. "
        "Respond with ONLY fenced code blocks. Each block must start with a comment "
        "`# FILE: relative/path/to/file.ext` on its first line. No explanations outside blocks."
    )
    user_msg = (
        f"Scaffold a starter project for: **{project_desc}**\n\n"
        f"Repository: `{repo_name}`\n\n"
        "Include: README.md, main source file(s), pyproject.toml, one test file."
    )

    console.print(f"\n[dim]Scaffolding with [cyan]{model}[/] …[/]\n")
    console.print("[bold green]agent[/]", end="")
    reply = _stream_to_console(engine, user_msg, system=system, temperature=0.3)

    written: list[str] = []
    for lang, code in _extract_code_blocks(reply):
        first_line  = code.lstrip().splitlines()[0] if code.strip() else ""
        file_match  = re.match(r"^[#/]+\s*FILE:\s*(.+)", first_line)
        if not file_match:
            continue
        target = repo_path / file_match.group(1).strip()
        target.parent.mkdir(parents=True, exist_ok=True)
        clean = "".join(code.splitlines(keepends=True)[1:]).lstrip("\n")
        target.write_text(clean, encoding="utf-8")
        written.append(file_match.group(1).strip())
        console.print(f"  [green]✓[/] {file_match.group(1).strip()}")

    if written:
        try:
            sha = git_ops.commit_changes(repo_path, f"feat: scaffold {project_desc}")
            console.print(f"\n[green]✓[/] Committed scaffold as [cyan]{sha}[/]")
        except (ValueError, RuntimeError) as exc:
            console.print(f"[yellow]⚠ Auto-commit failed: {exc}[/]")

    console.print(
        Panel(
            f"[bold green]Repository ready![/]\n\n"
            f"  [dim]Path:[/]   [cyan]{repo_path}[/]\n"
            f"  [dim]Files:[/]  {', '.join(written) or 'none written'}",
            expand=False,
        )
    )


# ── Subcommand: login ──────────────────────────────────────────────────────────

@app.command()
def login() -> None:
    """Log in to coding-agent (starts a new 24-hour session)."""
    if not _auth.has_account():
        _first_time_setup()
    else:
        _prompt_login()


# ── Subcommand: logout ─────────────────────────────────────────────────────────

@app.command()
def logout() -> None:
    """End the current session."""
    _auth.logout()
    console.print("[dim]Logged out.[/]")


# ── Subcommand: whoami ─────────────────────────────────────────────────────────

@app.command()
def whoami() -> None:
    """Show the current logged-in user and approved directories."""
    session = _auth.get_active_session()
    if session:
        console.print(f"[bold cyan]{session['username']}[/]  [dim](session active)[/]")
    else:
        console.print("[dim]Not logged in.[/]")

    dirs = _auth.list_approved_directories()
    if dirs:
        console.print("\n[dim]Approved directories:[/]")
        for d in dirs:
            console.print(f"  [green]✓[/] {d}")


# ── Subcommand: review ────────────────────────────────────────────────────────

@app.command()
def review(
    file: Path = typer.Argument(..., help="File to review."),
    model: str = typer.Option(CODER_MODEL, "--model", "-m"),
    apply: bool = typer.Option(
        False, "--apply", "-a",
        help="Interactively pick and apply corrections after the review.",
    ),
    context: bool = typer.Option(True, "--context/--no-context"),
) -> None:
    """
    AI code review: lists numbered bugs & improvements.
    Use --apply to pick corrections and patch them one-by-one.
    """
    if not file.exists():
        err_console.print(f"✗ File not found: {file}")
        raise typer.Exit(code=1)

    root     = Path.cwd().resolve()
    username = _ensure_logged_in()
    _request_directory_permission(root)

    engine  = _engine_or_exit(model)
    source  = file.read_text(encoding="utf-8", errors="replace")
    lang    = file.suffix.lstrip(".") or "text"

    system_parts = [
        "You are a senior software engineer conducting a code review.",
        "Be precise and actionable. Focus on real bugs, security issues, and meaningful improvements.",
        "Do NOT suggest style-only changes unless they affect readability significantly.",
    ]
    if context:
        system_parts.append(f"\n## Project Structure\n```\n{build_file_tree(root)}\n```")

    review_prompt = (
        f"Review `{file.name}` for bugs, security issues, and improvements.\n\n"
        "Format as a **numbered list** — one item per issue.\n"
        "For each item:\n"
        "  - **Issue**: what is wrong\n"
        "  - **Location**: function name or line reference\n"
        "  - **Fix**: the exact change needed\n\n"
        "End with a one-line overall quality verdict.\n\n"
        f"```{lang}\n{source}\n```"
    )

    console.print(
        Panel(
            f"[bold]Reviewing[/] [cyan]{file}[/]\n"
            f"[dim]model:[/] [cyan]{model}[/]  [dim]apply:[/] {apply}",
            expand=False,
        )
    )

    console.print("\n[bold green]agent[/]", end="")
    review_text = _stream_to_console(
        engine,
        review_prompt,
        system="\n".join(system_parts),
        temperature=0.2,
    )

    if not apply:
        console.print(
            "\n[dim]Run with [bold]--apply[/] to interactively patch selected corrections.[/]"
        )
        return

    # ── Interactive apply ──────────────────────────────────────────────────────
    console.print("\n[dim]Enter correction numbers to apply (comma-separated), or press Enter to skip:[/]")
    raw = Prompt.ask("[bold]Apply corrections[/]", default="").strip()
    if not raw:
        console.print("[dim]No corrections applied.[/]")
        return

    chosen = [s.strip() for s in raw.split(",") if s.strip().isdigit()]
    if not chosen:
        console.print("[yellow]No valid numbers entered.[/]")
        return

    original_content = source
    for num in chosen:
        console.print(f"\n[dim]Applying correction #{num} …[/]")
        patch_prompt = (
            f"From the review of `{file.name}`, apply **only correction #{num}**.\n\n"
            f"Review:\n{review_text}\n\n"
            f"Current file:\n```{lang}\n{original_content}\n```\n\n"
            "Return the complete updated file in a single fenced code block. No other text."
        )

        patched_reply = engine.complete(
            patch_prompt,
            system=(
                "You are an expert engineer applying a targeted fix. "
                "Return ONLY the complete updated file inside a single fenced code block."
            ),
            temperature=0.1,
        )

        blocks = _extract_code_blocks(patched_reply)
        if not blocks:
            console.print(f"[yellow]⚠ Could not extract patched code for correction #{num}. Skipping.[/]")
            continue

        patched_code = blocks[0][1].rstrip() + "\n"
        diff = _fixer.unified_diff(original_content, patched_code, file.name)

        if not diff:
            console.print(f"[yellow]⚠ No changes produced for correction #{num}.[/]")
            continue

        console.print(
            Panel(
                Syntax(diff, "diff", theme="monokai", line_numbers=False),
                title=f"[bold]Correction #{num} — {file.name}[/]",
                border_style="cyan",
                expand=False,
            )
        )

        if Confirm.ask(f"Apply correction #{num}?", default=True):
            original_content = patched_code  # chain: next correction builds on this
            console.print(f"[green]✓[/] Correction #{num} staged in memory.")
        else:
            console.print(f"[dim]Correction #{num} skipped.[/]")

    # Final write
    if original_content != source:
        if Confirm.ask(f"\nWrite all applied corrections to [cyan]{file}[/]?", default=True):
            file.write_text(original_content, encoding="utf-8")
            console.print(f"[green]✓[/] Written to [cyan]{file}[/]")

            if Confirm.ask("Commit?", default=False):
                commit_msg = engine.complete(
                    f"Short imperative git commit message (≤72 chars) for code review fixes on {file.name}",
                    temperature=0.1,
                ).strip().strip('"').strip("'")
                try:
                    sha = git_ops.commit_changes(root, f"fix: {commit_msg}", files=[str(file)])
                    console.print(f"[green]✓[/] Committed [cyan]{sha}[/]: {commit_msg}")
                except (ValueError, RuntimeError) as exc:
                    console.print(f"[yellow]⚠ Commit failed: {exc}[/]")
    else:
        console.print("[dim]No changes written.[/]")


# ── Subcommand: mcp-serve ─────────────────────────────────────────────────────

@app.command(name="mcp-serve")
def mcp_serve(
    directory: Path = typer.Option(
        Path.cwd(), "--dir", "-d", show_default=False,
        help="Project root the MCP tools will operate on (default: cwd).",
    ),
) -> None:
    """
    Start the coding-agent MCP server.

    Exposes all coding-agent capabilities (file I/O, git ops, AI review/edit)
    as MCP tools that Claude or any MCP-compatible AI can call.

    Register in ~/.claude/mcp.json:

    \\b
        {
          "mcpServers": {
            "coding-agent": {
              "command": "coding-agent",
              "args": ["mcp-serve", "--dir", "/path/to/your/project"]
            }
          }
        }
    """
    from .mcp_server import serve
    root = directory.resolve()
    console.print(
        Panel(
            f"[bold green]coding-agent MCP server[/]\n\n"
            f"  [dim]Project root:[/] [cyan]{root}[/]\n\n"
            f"  [dim]Tools[/]     [dim](AI takes action):[/]\n"
            f"    File  : read_file, write_file, list_files, get_diff\n"
            f"    Git   : git_status, create_branch, commit_changes,\n"
            f"            push_branch, add_remote, list_remotes\n"
            f"    AI    : review_file, refactor_file, apply_edit  [dim](needs Ollama)[/]\n\n"
            f"  [dim]Resources[/] [dim](AI browses passively):[/]\n"
            f"    project://tree   project://file/{{path}}\n"
            f"    git://status     git://log     git://branches\n\n"
            f"  [dim]Prompts[/]   [dim](reusable templates):[/]\n"
            f"    review_file · write_commit_message\n"
            f"    explain_code · fix_issue\n\n"
            f"  [dim]Waiting for MCP client connections …[/]",
            title="[bold]MCP Server[/]",
            border_style="green",
            expand=False,
        )
    )
    serve(project_root=str(root))


# ── Subcommand: fix-from-chat ──────────────────────────────────────────────────

_SEV_COLOUR = {"HIGH": "red", "CRITICAL": "bold red", "MEDIUM": "yellow", "LOW": "dim"}


@app.command(name="fix-from-chat")
def fix_from_chat(
    ai_url: str = typer.Option(
        "http://localhost:8082",
        "--url", "-u",
        help="AI service base URL.",
    ),
    directory: Path = typer.Option(
        Path.cwd(), "--dir", "-d", show_default=False,
        help="Project root where fixes will be applied.",
    ),
    model: str = typer.Option(
        DEFAULT_MODEL, "--model", "-m",
        help="Ollama model used to apply fixes.",
    ),
    auto_commit: bool = typer.Option(
        False, "--commit/--no-commit",
        help="Automatically commit each applied fix.",
    ),
) -> None:
    """
    Fetch pending screenshot fixes from the chatbot and apply them locally.

    Steps
    -----
    1. Pull PENDING fix requests from the AI service
    2. For each fix: show the analysis, ask for the target file path
    3. Apply the fix using the LLM, show a diff
    4. Confirm → write file → optionally commit
    5. Mark fix as APPLIED in the AI service
    """
    root     = directory.resolve()
    username = _ensure_logged_in()
    _request_directory_permission(root)
    engine   = _engine_or_exit(model)

    console.print(f"[dim]Polling[/] [cyan]{ai_url}/api/chat/pending-fixes[/] …")

    try:
        fixes = _fixer.fetch_pending_fixes(ai_url)
    except ConnectionError as exc:
        err_console.print(f"✗ {exc}")
        raise typer.Exit(code=1) from exc

    if not fixes:
        console.print("[dim]No pending fixes. Attach a screenshot in the chatbot first.[/]")
        return

    console.print(f"[green]✓[/] Found [bold]{len(fixes)}[/] pending fix(es)\n")

    for idx, fix in enumerate(fixes, 1):
        fix_id  = fix.get("fix_id", "?")
        title   = fix.get("issue_title", "Unknown issue")
        desc    = fix.get("description", "")
        sev     = fix.get("severity", "MEDIUM")
        files   = fix.get("likely_files", [])
        suggestion = fix.get("suggested_fix", "")
        sev_col = _SEV_COLOUR.get(sev, "white")

        console.print(
            Panel(
                f"[bold]#{idx}  Fix ID:[/] [cyan]{fix_id}[/]\n\n"
                f"[bold]Issue [{sev_col}]{sev}[/{sev_col}]:[/] {title}\n\n"
                f"{desc}\n\n"
                f"[dim]Likely files:[/] {', '.join(files) or '—'}\n\n"
                f"[dim]Suggested fix:[/] {suggestion}",
                title="[bold yellow]Pending Fix[/]",
                border_style="yellow",
                expand=False,
            )
        )

        # Ask which file to target
        default_file = files[0] if files else ""
        raw = Prompt.ask(
            f"[bold]File to fix[/] [dim](relative to {root}, Enter to skip)[/]",
            default=default_file,
        ).strip()

        if not raw:
            console.print("[dim]Skipped.[/]\n")
            continue

        target = root / raw
        if not target.exists():
            console.print(f"[red]✗ File not found:[/] {target}")
            if not Confirm.ask("Skip this fix?", default=True):
                continue
            continue

        # Apply fix via LLM
        console.print(f"[dim]Applying fix to[/] [cyan]{target}[/] with [cyan]{model}[/] …")
        try:
            original_content = target.read_text(encoding="utf-8")
            fixed_content    = _fixer.apply_fix_with_engine(
                engine, target, suggestion, f"{title}: {desc}"
            )
        except OllamaUnavailableError as exc:
            err_console.print(f"✗ {exc}")
            raise typer.Exit(code=1) from exc
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"✗ Failed to apply fix: {exc}")
            continue

        # Show unified diff
        diff = _fixer.unified_diff(original_content, fixed_content, target.name)
        if diff:
            console.print(
                Panel(
                    Syntax(diff, "diff", theme="monokai", line_numbers=False),
                    title=f"[bold]Diff — {target.name}[/]",
                    border_style="cyan",
                    expand=False,
                )
            )
        else:
            console.print("[yellow]⚠ No changes produced — the file may already be correct.[/]")
            _fixer.mark_resolved(fix_id, "DISMISSED", ai_url)
            continue

        if not Confirm.ask("Apply this change?", default=True):
            console.print("[dim]Skipped.[/]\n")
            _fixer.mark_resolved(fix_id, "DISMISSED", ai_url)
            continue

        # Write
        target.write_text(fixed_content, encoding="utf-8")
        console.print(f"[green]✓[/] Written to [cyan]{target}[/]")

        # Optionally commit
        if auto_commit or Confirm.ask("Commit this fix?", default=False):
            commit_msg = engine.complete(
                f"Write a short imperative git commit message (≤72 chars) for: {title}",
                temperature=0.1,
            ).strip().strip('"').strip("'")
            try:
                sha = git_ops.commit_changes(root, f"fix: {commit_msg}", files=[str(target)])
                console.print(f"[green]✓[/] Committed [cyan]{sha}[/]: {commit_msg}")
            except (ValueError, RuntimeError) as exc:
                console.print(f"[yellow]⚠ Commit failed: {exc}[/]")

        # Mark as applied in AI service
        _fixer.mark_resolved(fix_id, "APPLIED", ai_url)
        console.print(f"[dim]Fix {fix_id} marked as APPLIED in chatbot.[/]\n")

    console.print("[bold green]Done.[/] All pending fixes processed.")


# ── Subcommand: write-doc  (v2.0.2 — Rich File Writer) ───────────────────────

@app.command(name="write-doc")
def write_doc(
    instruction: str = typer.Argument(
        ...,
        help='What to write. e.g. "Project summary for WeatherAgent with architecture section"',
    ),
    output: Path = typer.Option(
        ..., "--output", "-o",
        help="Output file path. Extension sets the format: .docx .pptx .xlsx .pdf .md .txt .csv",
    ),
    model: str = typer.Option(
        CODER_MODEL, "--model", "-m",
        help=f"Ollama model (default: {CODER_MODEL}).",
    ),
    context_dir: Path = typer.Option(
        None, "--context-dir", "-c",
        help="Optional project directory to include as context.",
        show_default=False,
    ),
) -> None:
    """
    Generate and write a document from a natural language instruction.

    Supported output formats:
      .docx  Word document
      .pptx  PowerPoint presentation
      .xlsx  Excel workbook
      .pdf   PDF document
      .md    Markdown
      .txt   Plain text
      .csv   CSV table

    Examples:
      coding-agent write-doc "Project summary for WeatherAgent" --output summary.docx
      coding-agent write-doc "Architecture slides for WeatherAgent" --output slides.pptx
      coding-agent write-doc "API endpoint comparison table" --output api_table.xlsx
      coding-agent write-doc "Weekly status report" --output report.pdf
    """
    from .file_writer import write_document, SUPPORTED_FORMATS

    fmt = output.suffix.lower()
    if fmt not in SUPPORTED_FORMATS:
        err_console.print(
            f"✗ Unsupported format: [bold]{fmt}[/]\n"
            f"  Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )
        raise typer.Exit(code=1)

    _ensure_logged_in()

    engine = _engine_or_exit(model)

    # Optionally load project context
    context = ""
    if context_dir and context_dir.exists():
        from .context import read_project_files
        _request_directory_permission(context_dir.resolve())
        context = read_project_files(context_dir.resolve())

    console.print(
        Panel(
            f"[bold green]write-doc[/]  [dim]v{VERSION}[/]\n\n"
            f"  [dim]Instruction:[/] {instruction}\n"
            f"  [dim]Output     :[/] [cyan]{output}[/]\n"
            f"  [dim]Format     :[/] [cyan]{fmt}[/]\n"
            f"  [dim]Model      :[/] [cyan]{model}[/]",
            title="[bold cyan]coding-agent write-doc[/]",
            expand=False,
        )
    )

    from rich.progress import Progress, SpinnerColumn, TextColumn
    with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), transient=True) as prog:
        prog.add_task(f"Generating {fmt} document …")
        try:
            result = write_document(
                instruction=instruction,
                output=output.resolve(),
                engine=engine,
                context=context,
            )
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"\n✗ Failed to write document: {exc}")
            raise typer.Exit(code=1) from exc

    console.print(
        Panel(
            f"[bold green]Done![/]\n\n"
            f"  [dim]File:[/] [cyan]{result}[/]\n"
            f"  [dim]Size:[/] {result.stat().st_size:,} bytes",
            expand=False,
        )
    )


# ── Subcommand: build  (v2.0.1 — Autonomous Project Builder) ──────────────────

@app.command()
def build(
    requirements: Path = typer.Argument(
        ...,
        help="Requirements file (.md / .txt / .docx).",
    ),
    directory: Path = typer.Option(
        Path.cwd(), "--dir", "-d", show_default=False,
        help="Output directory where the project will be created.",
    ),
    model: str = typer.Option(
        BUILD_MODEL, "--model", "-m",
        help=f"Ollama model for code generation (default: {BUILD_MODEL}).",
    ),
    review: bool = typer.Option(
        True, "--review/--no-review",
        help="Auto-review and fix each generated file (default: on).",
    ),
    git_commit: bool = typer.Option(
        True, "--git/--no-git",
        help="Git init and commit all generated files (default: on).",
    ),
) -> None:
    """
    Autonomous project builder — reads a requirements file and generates
    a complete multi-service project (Flutter UI + Java Spring Boot + Python)
    using only local Ollama models. No paid APIs required.

    Example:
        coding-agent build WeatherAgent_Requirements.md --dir ./weather-project
        coding-agent build requirements.docx --dir ./my-app --no-review
    """
    if not requirements.exists():
        err_console.print(f"✗ Requirements file not found: {requirements}")
        raise typer.Exit(code=1)

    _ensure_logged_in()
    _request_directory_permission(directory.resolve())

    from .builder import build as _build, OllamaUnavailableError as _OllamaErr
    from .engine import OllamaUnavailableError

    console.print(
        Panel(
            f"[bold green]Autonomous Project Builder[/]  [dim]v{VERSION}[/]\n\n"
            f"  [dim]Requirements:[/] [cyan]{requirements}[/]\n"
            f"  [dim]Output dir  :[/] [cyan]{directory.resolve()}[/]\n"
            f"  [dim]Model       :[/] [cyan]{model}[/]\n"
            f"  [dim]Auto-review :[/] {'[green]on[/]' if review else '[dim]off[/]'}\n"
            f"  [dim]Git commit  :[/] {'[green]on[/]' if git_commit else '[dim]off[/]'}",
            title="[bold cyan]coding-agent build[/]",
            expand=False,
        )
    )

    try:
        _build(
            req_file=requirements.resolve(),
            output_dir=directory.resolve(),
            model=model,
            do_review=review,
            do_git=git_commit,
        )
    except (OllamaUnavailableError, RuntimeError) as exc:
        err_console.print(f"\n✗ Build failed: {exc}")
        raise typer.Exit(code=1) from exc
