#!/usr/bin/env python3
"""USOL - Universal System Optimization Layer.

Frontend colorido para o APT, com icones e
funcionalidades extras (info, doctor, stats, size, fetch, history).
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm
from rich.markup import escape
from rich import box

console = Console(highlight=False)

# Icones de codepoint unico (sem seletor de variacao U+FE0F): alguns terminais
# renderizam base+FE0F com largura diferente da calculada, o que torda as
# bordas das tabelas/paineis. Preferir sempre emoji ja "wide" por padrao.
ICON = {
    "install": "📦",
    "remove": "🚮",
    "purge": "🔥",
    "update": "🔄",
    "upgrade": "🔼",
    "search": "🔍",
    "list": "📋",
    "clean": "🧹",
    "history": "📜",
    "info": "📘",
    "doctor": "🩺",
    "stats": "📊",
    "size": "💾",
    "fetch": "🌐",
    "ok": "✅",
    "err": "❌",
    "warn": "❗",
    "up_arrow": "🔼",
    "dot_on": "●",
    "dot_off": "○",
    "rocket": "🚀",
}

VERSION = "1.0.0"

# Credito do criador protegido por hash: qualquer edicao do nome abaixo
# quebra a verificacao de integridade e o programa se recusa a rodar.
_CREATOR_NAME = "Passos, OMAR"
_CREATOR_HASH = "c98eacea704a8023c097ba92943d9dc7d9163be9b6f31a22c75d436d9c342a0f"


def _verify_creator():
    if hashlib.sha256(_CREATOR_NAME.encode()).hexdigest() != _CREATOR_HASH:
        sys.stderr.write(
            "usol: verificacao de integridade falhou (credito do criador foi alterado).\n"
            "Restaure o valor original de _CREATOR_NAME em usol.py para continuar.\n"
        )
        sys.exit(1)
    return _CREATOR_NAME


CREATOR = _verify_creator()

# (icone, descricao, categoria) - fonte unica para o parser e para a tela de ajuda
COMMAND_META = {
    "update":       (ICON["update"], "Atualizar a lista de pacotes", "Gerenciamento de pacotes"),
    "upgrade":      (ICON["upgrade"], "Atualizar pacotes instalados", "Gerenciamento de pacotes"),
    "full-upgrade": ("🔝", "Atualizacao completa do sistema", "Gerenciamento de pacotes"),
    "install":      (ICON["install"], "Instalar pacotes", "Gerenciamento de pacotes"),
    "remove":       (ICON["remove"], "Remover pacotes", "Gerenciamento de pacotes"),
    "purge":        (ICON["purge"], "Remover pacotes e configuracoes", "Gerenciamento de pacotes"),
    "autoremove":   ("🧽", "Remocao automatica de pacotes orfaos", "Gerenciamento de pacotes"),
    "autopurge":    ("🪣", "Limpeza automatica (purge) de pacotes orfaos", "Gerenciamento de pacotes"),
    "clean":        (ICON["clean"], "Limpar cache de pacotes baixados", "Gerenciamento de pacotes"),
    "show":         ("📄", "Exibir detalhes de pacotes", "Consulta"),
    "search":       (ICON["search"], "Pesquisar pacotes", "Consulta"),
    "list":         (ICON["list"], "Listar pacotes", "Consulta"),
    "history":      (ICON["history"], "Exibir historico de operacoes do APT", "Consulta"),
    "info":         (ICON["info"], "Informacoes do sistema", "Extras USOL"),
    "doctor":       (ICON["doctor"], "Diagnostico de saude dos pacotes", "Extras USOL"),
    "stats":        (ICON["stats"], "Estatisticas de pacotes instalados", "Extras USOL"),
    "size":         (ICON["size"], "Maiores pacotes instalados", "Extras USOL"),
    "fetch":        (ICON["fetch"], "Testar latencia dos espelhos configurados", "Extras USOL"),
}
CATEGORY_ORDER = ["Gerenciamento de pacotes", "Consulta", "Extras USOL"]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

BANNER_STYLE = {
    "install": "bold green",
    "remove": "bold red",
    "purge": "bold red",
    "update": "bold cyan",
    "upgrade": "bold yellow",
    "clean": "bold cyan",
    "doctor": "bold magenta",
    "stats": "bold magenta",
    "size": "bold magenta",
    "fetch": "bold blue",
}


def banner(title, icon_key, style=None):
    style = style or BANNER_STYLE.get(icon_key, "bold cyan")
    icon = ICON.get(icon_key, "")
    console.print(Panel.fit(f"[{style}]{icon}  {title}[/{style}]", border_style=style.replace("bold ", "")))


def ok(msg):
    console.print(f"[bold green]{ICON['ok']} {msg}[/bold green]")


def err(msg):
    console.print(f"[bold red]{ICON['err']} {msg}[/bold red]")


def warn(msg):
    console.print(f"[bold yellow]{ICON['warn']} {msg}[/bold yellow]")


def is_root():
    return os.geteuid() == 0


def sudo(cmd):
    return cmd if is_root() else ["sudo"] + cmd


def run_live(cmd):
    """Executa um comando herdando stdio (saida nativa colorida do apt)."""
    try:
        return subprocess.run(cmd).returncode
    except FileNotFoundError:
        err(f"Comando nao encontrado: {cmd[0]}")
        return 127
    except KeyboardInterrupt:
        warn("Cancelado pelo usuario.")
        return 130


def capture(cmd):
    """Executa um comando capturando saida, retorna (code, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"comando nao encontrado: {cmd[0]}"


def human_kb(kb):
    kb = float(kb)
    for unit in ("KB", "MB", "GB", "TB"):
        if kb < 1024 or unit == "TB":
            return f"{kb:.1f} {unit}"
        kb /= 1024


def installed_set():
    code, out, _ = capture(["dpkg-query", "-W", "-f=${Package}\n"])
    return set(out.split()) if code == 0 else set()


# --------------------------------------------------------------------------
# Simulacao de transacoes (install / remove / purge / upgrade)
# --------------------------------------------------------------------------

ACTION_MAP = {
    "Inst": ("instalar", "green", "install"),
    "Remv": ("remover", "red", "remove"),
    "Purg": ("purgar", "red", "purge"),
    "Conf": ("configurar", "cyan", "install"),
}


def simulate(cmd):
    """Roda apt-get -s <cmd> e retorna (linhas de transacao, texto resumo)."""
    code, out, error = capture(["apt-get", "-s"] + cmd)
    if code != 0:
        return None, error
    lines = []
    summary = ""
    for line in out.splitlines():
        m = re.match(r"^(Inst|Remv|Purg|Conf)\s+(\S+)\s*(.*)$", line)
        if m:
            action, pkg, rest = m.groups()
            if "(" in rest and ")" in rest:
                version = rest[rest.index("(") + 1: rest.rindex(")")]
            elif "[" in rest and "]" in rest:
                version = rest[rest.index("[") + 1: rest.rindex("]")]
            else:
                version = ""
            lines.append((action, pkg, version))
        elif line.startswith("After this operation") or "disk space" in line:
            summary = line.strip()
    return lines, summary


def show_transaction_table(lines, summary):
    if not lines:
        warn("Nada a fazer. Todos os pacotes ja estao no estado desejado.")
        return False
    table = Table(box=box.ROUNDED, header_style="bold magenta")
    table.add_column("Acao")
    table.add_column("Pacote", style="bold")
    table.add_column("Versao", style="dim")
    seen = set()
    for action, pkg, ver in lines:
        if action == "Conf" and pkg in seen:
            continue
        seen.add(pkg)
        label, color, icon_key = ACTION_MAP[action]
        table.add_row(f"[{color}]{ICON[icon_key]} {label}[/{color}]", escape(pkg), escape(ver))
    console.print(table)
    if summary:
        console.print(f"[dim]{summary}[/dim]")
    return True


def transactional_command(title, icon_key, apt_verb, pkgs, yes, dry_run, extra_flags=None):
    banner(title, icon_key)
    sim_cmd = [apt_verb] + (extra_flags or []) + list(pkgs)
    lines, summary = simulate(sim_cmd)
    if lines is None:
        err(f"Falha ao simular operacao: {summary}")
        return 1
    if not show_transaction_table(lines, summary):
        return 0
    if dry_run:
        console.print("[dim]Modo --dry-run: nenhuma alteracao foi feita.[/dim]")
        return 0
    if not yes and not Confirm.ask("[bold]Continuar?[/bold]", default=True):
        warn("Operacao cancelada.")
        return 0
    real_cmd = sudo(["apt-get", "-y", apt_verb] + (extra_flags or []) + list(pkgs))
    code = run_live(real_cmd)
    ok(f"{title} concluido.") if code == 0 else err(f"{title} falhou (codigo {code}).")
    return code


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

def cmd_update(args):
    banner("Atualizando lista de pacotes", "update")
    code = run_live(sudo(["apt-get", "update"]))
    ok("Lista de pacotes atualizada.") if code == 0 else err("Falha ao atualizar lista de pacotes.")
    return code


def cmd_upgrade(args):
    return transactional_command("Atualizar pacotes", "upgrade", "upgrade", [], args.yes, args.dry_run)


def cmd_full_upgrade(args):
    return transactional_command("Atualizacao completa do sistema", "upgrade", "dist-upgrade", [], args.yes, args.dry_run)


def cmd_install(args):
    if not args.packages:
        err("Informe ao menos um pacote.")
        return 1
    extra = ["--purge"] if args.purge else []
    return transactional_command("Instalar pacotes", "install", "install", args.packages, args.yes, args.dry_run, extra)


def cmd_remove(args):
    if not args.packages:
        err("Informe ao menos um pacote.")
        return 1
    return transactional_command("Remover pacotes", "remove", "remove", args.packages, args.yes, args.dry_run)


def cmd_purge(args):
    if not args.packages:
        err("Informe ao menos um pacote.")
        return 1
    return transactional_command("Limpar pacotes (purge)", "purge", "purge", args.packages, args.yes, args.dry_run)


def cmd_autoremove(args):
    return transactional_command("Remocao automatica", "remove", "autoremove", [], args.yes, args.dry_run)


def cmd_autopurge(args):
    return transactional_command("Limpeza automatica (purge)", "purge", "autoremove", [], args.yes, args.dry_run, ["--purge"])


def cmd_clean(args):
    banner("Limpando cache de pacotes", "clean")
    cache_dir = "/var/cache/apt/archives"
    before = shutil.disk_usage(cache_dir).used if os.path.isdir(cache_dir) else 0
    code, out, _ = capture(["du", "-sb", cache_dir])
    before_bytes = int(out.split()[0]) if code == 0 and out else 0
    code = run_live(sudo(["apt-get", "clean"]))
    code2, out2, _ = capture(["du", "-sb", cache_dir])
    after_bytes = int(out2.split()[0]) if code2 == 0 and out2 else 0
    freed = max(before_bytes - after_bytes, 0)
    if code == 0:
        ok(f"Cache limpo. {human_kb(freed / 1024)} liberados.")
    else:
        err("Falha ao limpar cache.")
    return code


SHOW_HIGHLIGHT = {"Package", "Version", "Installed-Size", "Maintainer", "Architecture", "Depends", "Recommends", "Suggests", "Section", "Priority", "Homepage", "Description"}


def cmd_show(args):
    for pkg in args.packages:
        code, out, error = capture(["apt-cache", "show", pkg])
        if code != 0 or not out.strip():
            err(f"Pacote '{pkg}' nao encontrado.")
            continue
        block = out.split("\n\n")[0]
        colored_lines = []
        for line in block.splitlines():
            m = re.match(r"^([A-Za-z-]+):(.*)$", line)
            if m and m.group(1) in SHOW_HIGHLIGHT:
                field, value = m.groups()
                colored_lines.append(f"[bold cyan]{field}:[/bold cyan][bold]{escape(value)}[/bold]")
            else:
                colored_lines.append(f"[dim]{escape(line)}[/dim]")
        console.print(Panel("\n".join(colored_lines), title=f"[bold]{ICON['info']} {escape(pkg)}[/bold]", border_style="cyan", box=box.ROUNDED))


def cmd_search(args):
    term = " ".join(args.terms)
    code, out, _ = capture(["apt-cache", "search", term])
    if code != 0 or not out.strip():
        warn(f"Nenhum pacote encontrado para '{term}'.")
        return 0
    inst = installed_set()
    table = Table(box=box.ROUNDED, header_style="bold magenta", title=f"[bold cyan]{ICON['search']} Resultados para '{escape(term)}'[/bold cyan]")
    table.add_column("")
    table.add_column("Pacote", style="bold")
    table.add_column("Descricao", style="dim")
    rows = sorted(out.strip().splitlines())
    for line in rows[: args.limit]:
        if " - " not in line:
            continue
        pkg, desc = line.split(" - ", 1)
        mark = f"[green]{ICON['dot_on']}[/green]" if pkg in inst else f"[dim]{ICON['dot_off']}[/dim]"
        table.add_row(mark, escape(pkg), escape(desc))
    console.print(table)
    if len(rows) > args.limit:
        console.print(f"[dim]... e mais {len(rows) - args.limit} resultado(s). Use --limit para ver mais.[/dim]")
    return 0


def cmd_list(args):
    table = Table(box=box.ROUNDED, header_style="bold magenta")
    table.add_column("")
    table.add_column("Pacote", style="bold")
    table.add_column("Versao", style="dim")

    if args.upgradable:
        code, out, _ = capture(["apt", "list", "--upgradable"])
        title = "Pacotes atualizaveis"
        for line in out.splitlines():
            if "/" not in line:
                continue
            parts = line.split()
            pkg = parts[0].split("/")[0]
            ver = parts[1] if len(parts) > 1 else ""
            table.add_row(f"[yellow]{ICON['up_arrow']}[/yellow]", escape(pkg), escape(ver))
    else:
        title = "Pacotes instalados"
        code, out, _ = capture(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"])
        rows = out.strip().splitlines()
        if args.terms:
            term = args.terms[0].lower()
            rows = [r for r in rows if term in r.lower()]
        for line in rows:
            pkg, _, ver = line.partition("\t")
            table.add_row(f"[green]{ICON['dot_on']}[/green]", escape(pkg), escape(ver))
    table.title = f"[bold cyan]{ICON['list']} {title}[/bold cyan]"
    console.print(table)
    return 0


def cmd_history(args):
    log = Path("/var/log/apt/history.log")
    if not log.exists():
        err("Historico do APT nao encontrado (/var/log/apt/history.log).")
        return 1
    text = log.read_text(errors="ignore")
    entries = text.strip().split("\n\n")
    table = Table(box=box.ROUNDED, header_style="bold magenta", title=f"{ICON['history']} Historico de operacoes")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Data", style="cyan")
    table.add_column("Comando", style="bold")
    table.add_column("Acao")

    action_style = {"Install": "green", "Remove": "red", "Upgrade": "yellow", "-": "dim"}
    action_icon = {"Install": ICON["install"], "Remove": ICON["remove"], "Upgrade": ICON["upgrade"], "-": ""}

    parsed = []
    for entry in entries:
        if "Start-Date:" not in entry:
            continue
        date_m = re.search(r"Start-Date:\s*(.+)", entry)
        cmd_m = re.search(r"Commandline:\s*(.+)", entry)
        action = "Install" if "Install:" in entry else "Remove" if "Remove:" in entry else "Upgrade" if "Upgrade:" in entry else "-"
        parsed.append((date_m.group(1) if date_m else "?", cmd_m.group(1) if cmd_m else "?", action))

    parsed = list(reversed(parsed))[: args.limit]
    for i, (date, cmdline, action) in enumerate(parsed, 1):
        style = action_style[action]
        table.add_row(str(len(parsed) - i + 1), escape(date), escape(cmdline), f"[{style}]{action_icon[action]} {action}[/{style}]")
    console.print(table)
    return 0


def cmd_info(args):
    os_release = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                os_release[k] = v.strip('"')
    except FileNotFoundError:
        pass

    _, kernel, _ = capture(["uname", "-r"])
    _, arch, _ = capture(["uname", "-m"])
    _, up_out, _ = capture(["uptime", "-p"])
    inst_count = len(installed_set())
    _, upg_out, _ = capture(["apt", "list", "--upgradable"])
    upg_count = max(len(upg_out.strip().splitlines()) - 1, 0)
    cache_dir = "/var/cache/apt/archives"
    _, du_out, _ = capture(["du", "-sh", cache_dir])
    cache_size = du_out.split()[0] if du_out else "?"

    table = Table.grid(padding=(0, 2))
    table.add_row("[bold cyan]Sistema:[/bold cyan]", f"[bold]{escape(os_release.get('PRETTY_NAME', '?'))}[/bold]")
    table.add_row("[bold cyan]Kernel:[/bold cyan]", kernel.strip())
    table.add_row("[bold cyan]Arquitetura:[/bold cyan]", arch.strip())
    table.add_row("[bold cyan]Uptime:[/bold cyan]", up_out.strip() or "?")
    table.add_row("[bold cyan]Pacotes instalados:[/bold cyan]", f"[bold green]{inst_count}[/bold green]")
    table.add_row("[bold cyan]Atualizaveis:[/bold cyan]", f"[bold yellow]{upg_count}[/bold yellow]" if upg_count else "[green]0[/green]")
    table.add_row("[bold cyan]Cache do APT:[/bold cyan]", cache_size)
    table.add_row("", "")
    table.add_row("[bold cyan]USOL versao:[/bold cyan]", f"[bold magenta]{VERSION}[/bold magenta]")
    table.add_row("[bold cyan]Criado por:[/bold cyan]", f"[bold magenta]{CREATOR}[/bold magenta]")
    console.print(Panel(table, title=f"[bold]{ICON['info']} USOL - Informacoes do sistema[/bold]", border_style="cyan", box=box.ROUNDED))
    return 0


def cmd_doctor(args):
    banner("Diagnostico do sistema de pacotes", "doctor")
    checks = []

    code, out, _ = capture(["dpkg", "--audit"])
    checks.append(("Pacotes com instalacao incompleta", code == 0 and not out.strip(), out.strip()))

    code, out, err_out = capture(["sudo", "-n"] + ["apt-get", "check"])
    lower_err = (err_out or "").lower()
    if code != 0 and "sudo" in lower_err and ("senha" in lower_err or "password" in lower_err):
        detail = "requer privilegios de root (execute 'sudo usol doctor' para este teste)"
    else:
        detail = err_out.strip() or out.strip()
    checks.append(("Consistencia de dependencias (apt-get check)", code == 0, detail))

    code, out, _ = capture(["apt-mark", "showhold"])
    held = out.strip().splitlines() if out.strip() else []
    checks.append(("Pacotes retidos (hold)", not held, ", ".join(held)))

    code, out, err_out = capture(["apt-get", "-s", "autoremove"])
    removable = len(re.findall(r"^Remv\s", out, re.MULTILINE))
    checks.append(("Pacotes orfaos (candidatos a autoremove)", removable == 0, f"{removable} pacote(s)"))

    for title, passed, detail in checks:
        if passed:
            console.print(f"  [bold green]{ICON['ok']}[/bold green] [bold]{title}[/bold]")
        else:
            console.print(f"  [bold yellow]{ICON['warn']}[/bold yellow] [bold]{title}[/bold]")
            if detail:
                console.print(f"      [dim italic]{detail[:200]}[/dim italic]")
    return 0


def cmd_stats(args):
    banner("Estatisticas de pacotes", "stats")
    code, out, _ = capture(["dpkg-query", "-W", "-f=${Installed-Size}\t${Package}\n"])
    rows = []
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0].isdigit():
            rows.append((int(parts[0]), parts[1]))
    rows.sort(reverse=True)
    total_kb = sum(r[0] for r in rows)

    console.print(f"  [bold cyan]Total de pacotes instalados:[/bold cyan] [bold green]{len(rows)}[/bold green]")
    console.print(f"  [bold cyan]Espaco total ocupado:[/bold cyan] [bold yellow]{human_kb(total_kb)}[/bold yellow]")
    console.print()
    table = Table(box=box.ROUNDED, header_style="bold magenta", title="[bold magenta]Top 10 maiores pacotes[/bold magenta]")
    table.add_column("Pacote", style="bold")
    table.add_column("Tamanho", justify="right", style="yellow")
    table.add_column("")
    max_kb = rows[0][0] if rows else 1
    for kb, pkg in rows[:10]:
        bar_len = int((kb / max_kb) * 20)
        bar = "█" * bar_len
        table.add_row(escape(pkg), human_kb(kb), f"[cyan]{bar}[/cyan]")
    console.print(table)
    return 0


def cmd_size(args):
    code, out, _ = capture(["dpkg-query", "-W", "-f=${Installed-Size}\t${Package}\n"])
    rows = []
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0].isdigit():
            rows.append((int(parts[0]), parts[1]))
    rows.sort(reverse=True)
    table = Table(box=box.ROUNDED, header_style="bold magenta", title=f"[bold magenta]{ICON['size']} Maiores pacotes instalados[/bold magenta]")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Pacote", style="bold")
    table.add_column("Tamanho", justify="right", style="yellow")
    max_kb = rows[0][0] if rows else 1
    for i, (kb, pkg) in enumerate(rows[: args.top], 1):
        bar_len = int((kb / max_kb) * 20)
        table.add_row(str(i), escape(pkg), f"{human_kb(kb)}  [cyan]{'█' * bar_len}[/cyan]")
    console.print(table)
    return 0


def cmd_fetch(args):
    banner("Testando velocidade dos espelhos (mirrors)", "fetch")
    sources = []
    candidates = [Path("/etc/apt/sources.list")] + list(Path("/etc/apt/sources.list.d").glob("*.list")) + list(Path("/etc/apt/sources.list.d").glob("*.sources"))
    for f in candidates:
        if not f.exists():
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for m in re.finditer(r"https?://[^\s]+", text):
            sources.append(m.group(0).split("/dists/")[0].rstrip("/"))
    sources = sorted(set(sources))
    if not sources:
        warn("Nenhum repositorio encontrado em sources.list.")
        return 0

    table = Table(box=box.ROUNDED, header_style="bold magenta", title=f"[bold blue]{ICON['fetch']} Latencia dos espelhos[/bold blue]")
    table.add_column("Espelho", style="cyan")
    table.add_column("Tempo", justify="right")

    results = []
    for url in sources:
        code, out, _ = capture(["curl", "-o", "/dev/null", "-s", "-m", "5", "-w", "%{time_total}", url])
        if code == 0 and out:
            results.append((float(out), url))
        else:
            results.append((float("inf"), url))
    results.sort()
    for t, url in results:
        if t == float("inf"):
            table.add_row(escape(url), "[red]timeout[/red]")
        else:
            color = "green" if t < 0.5 else "yellow" if t < 1.5 else "red"
            table.add_row(escape(url), f"[{color}]{t:.2f}s[/{color}]")
    console.print(table)
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="usol", description="USOL - frontend colorido para o APT.", add_help=False)
    p.add_argument("-h", "--help", action="store_true", help="mostra esta mensagem de ajuda")
    p.add_argument("--version", action="version", version=f"usol {VERSION}\nCriado por: {CREATOR}")
    sub = p.add_subparsers(dest="command")

    def add(name, needs_pkgs=False, terms=False):
        icon, desc, _ = COMMAND_META[name]
        sp = sub.add_parser(name, help=f"{icon} {desc}")
        if needs_pkgs:
            sp.add_argument("packages", nargs="*", help="pacotes")
        if terms:
            sp.add_argument("terms", nargs="+", help="termo de busca")
        return sp

    for name in ("update", "clean", "autoremove", "autopurge"):
        sp = add(name)
        if name in ("autoremove", "autopurge"):
            sp.add_argument("-y", "--yes", action="store_true")
            sp.add_argument("--dry-run", action="store_true")

    for name in ("upgrade", "full-upgrade"):
        sp = add(name)
        sp.add_argument("-y", "--yes", action="store_true")
        sp.add_argument("--dry-run", action="store_true")

    sp = add("install", needs_pkgs=True)
    sp.add_argument("-y", "--yes", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--purge", action="store_true", help="purgar pacotes removidos na transacao")

    for name in ("remove", "purge"):
        sp = add(name, needs_pkgs=True)
        sp.add_argument("-y", "--yes", action="store_true")
        sp.add_argument("--dry-run", action="store_true")

    add("show", needs_pkgs=True)

    sp = add("search", terms=True)
    sp.add_argument("--limit", type=int, default=30)

    sp = add("list")
    sp.add_argument("terms", nargs="*")
    sp.add_argument("--installed", action="store_true")
    sp.add_argument("--upgradable", action="store_true")

    sp = add("history")
    sp.add_argument("--limit", type=int, default=20)

    add("info")
    add("doctor")
    add("stats")

    sp = add("size")
    sp.add_argument("--top", type=int, default=20)

    add("fetch")

    return p


COMMANDS = {
    "update": cmd_update, "upgrade": cmd_upgrade, "full-upgrade": cmd_full_upgrade,
    "install": cmd_install, "remove": cmd_remove, "purge": cmd_purge,
    "autoremove": cmd_autoremove, "autopurge": cmd_autopurge, "clean": cmd_clean,
    "show": cmd_show, "search": cmd_search, "list": cmd_list, "history": cmd_history,
    "info": cmd_info, "doctor": cmd_doctor, "stats": cmd_stats, "size": cmd_size, "fetch": cmd_fetch,
}


CATEGORY_STYLE = {
    "Gerenciamento de pacotes": "green",
    "Consulta": "cyan",
    "Extras USOL": "magenta",
}

EXAMPLES = [
    ("usol install htop cowsay", "instala um ou mais pacotes"),
    ("usol search editor de texto", "pesquisa pacotes pelo nome/descricao"),
    ("usol upgrade -y", "atualiza o sistema sem confirmar"),
    ("usol remove --dry-run pkg", "simula a remocao, sem aplicar"),
    ("usol doctor", "verifica a saude do sistema de pacotes"),
    ("usol <comando> -h", "ajuda detalhada de um comando"),
]


def print_help_screen():
    console.print(Panel.fit(
        f"[bold cyan]{ICON['rocket']} USOL[/bold cyan] [dim]v{VERSION}[/dim]\n"
        "[dim]Universal System Optimization Layer - frontend colorido para o APT[/dim]\n"
        f"[dim]Criado por: [/dim][bold]{CREATOR}[/bold]",
        border_style="cyan", box=box.ROUNDED,
    ))

    by_category = {cat: [] for cat in CATEGORY_ORDER}
    for name, (icon, desc, cat) in COMMAND_META.items():
        by_category[cat].append((name, icon, desc))

    for cat in CATEGORY_ORDER:
        style = CATEGORY_STYLE.get(cat, "white")
        table = Table.grid(padding=(0, 2))
        table.add_column(no_wrap=True)
        table.add_column()
        for name, icon, desc in by_category[cat]:
            table.add_row(f"{icon}  [bold {style}]{name}[/bold {style}]", f"[dim]{desc}[/dim]")
        console.print(Panel(table, title=f"[{style}]{cat}[/{style}]", border_style=style, box=box.ROUNDED))

    ex_table = Table.grid(padding=(0, 2))
    ex_table.add_column(no_wrap=True)
    ex_table.add_column()
    for cmdline, desc in EXAMPLES:
        ex_table.add_row(f"[bold yellow]❯[/bold yellow] [bold]{cmdline}[/bold]", f"[dim]{desc}[/dim]")
    console.print(Panel(ex_table, title="[yellow]Exemplos[/yellow]", border_style="yellow", box=box.ROUNDED))

    console.print("[dim]Use 'usol <comando> --help' para ver todas as opcoes de um comando.[/dim]")


def print_footer():
    console.print("[dim italic]by PASSOS, OMAR[/dim italic]")


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.help or not args.command:
        print_help_screen()
        print_footer()
        return 0
    code = COMMANDS[args.command](args) or 0
    print_footer()
    return code


if __name__ == "__main__":
    sys.exit(main())
