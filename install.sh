#!/usr/bin/env bash
# install.sh - Instalador automatizado do USOL (Universal System Optimization Layer)
set -euo pipefail

# --------------------------------------------------------------------------
# Cores / estilo (segue a linguagem visual do usol.py)
# --------------------------------------------------------------------------
if [ -t 1 ]; then
    BOLD=$(tput bold 2>/dev/null || true)
    # RESET fixo em "ESC[0m": tput sgr0 pode expandir para "ESC(B ESC[m" (troca
    # de charset + reset) dependendo do terminfo, e os bytes extras "(B" nao
    # sao removidos pelo filtro de ANSI, o que descalibra o padding das caixas.
    RESET=$'\033[0m'
    RED=$(tput setaf 1 2>/dev/null || true); GREEN=$(tput setaf 2 2>/dev/null || true)
    YELLOW=$(tput setaf 3 2>/dev/null || true); CYAN=$(tput setaf 6 2>/dev/null || true)
    MAGENTA=$(tput setaf 5 2>/dev/null || true); DIM=$(tput dim 2>/dev/null || true)
    TYPE_DELAY="0.008"
else
    BOLD=""; RESET=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; MAGENTA=""; DIM=""
    TYPE_DELAY="0"
fi

# --------------------------------------------------------------------------
# Janela de terminal simulada (moldura em modo texto)
# --------------------------------------------------------------------------
TERM_COLS="$(tput cols 2>/dev/null || echo 80)"
if [ "$TERM_COLS" -ge 78 ]; then INNER=72; else INNER=$((TERM_COLS - 6)); fi
[ "$INNER" -lt 40 ] && INNER=40

WIN_TITLE="$(id -un 2>/dev/null || echo usol)@$(hostname -s 2>/dev/null || echo installer): ~/scripts/USOL"
BOX_OPEN=0

repeat_char() {
    local char="$1" n="$2" out="" i
    for (( i = 0; i < n; i++ )); do out+="$char"; done
    printf '%s' "$out"
}

visible_len() {
    # wc -L mede a largura real de exibicao (respeita caracteres largos como
    # emoji), diferente de ${#str} que conta codepoints e desalinha a borda
    # quando a linha tem icones tipo ✅ ❌ ❗ (largura 2 no terminal).
    printf '%s' "$1" | sed -E 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\x1b\([A-Za-z0-9]//g' | wc -L
}

box_line() {
    local text="$1" vlen pad
    vlen=$(visible_len "$text")
    pad=$((INNER - 1 - vlen))
    [ "$pad" -lt 0 ] && pad=0
    printf '│ %s%*s│\n' "$text" "$pad" ''
}

box_open() {
    printf '╭%s╮\n' "$(repeat_char ─ "$INNER")"
    box_line "${RED}●${RESET} ${YELLOW}●${RESET} ${GREEN}●${RESET}   ${BOLD}${WIN_TITLE}${RESET}"
    printf '├%s┤\n' "$(repeat_char ─ "$INNER")"
    BOX_OPEN=1
}

box_close() {
    printf '╰%s╯\n' "$(repeat_char ─ "$INNER")"
    echo
    BOX_OPEN=0
}

# Simula uma linha de comando sendo digitada dentro da janela.
type_line() {
    local text="$1" len=${#1} i ch pad
    if [ "$TYPE_DELAY" = "0" ]; then
        box_line "${YELLOW}${BOLD}\$ ${text}${RESET}"
        return
    fi
    printf '│ %s%s$ %s' "$YELLOW" "$BOLD" "$RESET"
    for (( i=0; i<len; i++ )); do
        ch="${text:$i:1}"
        printf '%s' "$ch"
        sleep "$TYPE_DELAY"
    done
    pad=$((INNER - 3 - len))
    [ "$pad" -lt 0 ] && pad=0
    printf '%*s│\n' "$pad" ''
}

# --------------------------------------------------------------------------
# Mensagens (roteiam para dentro da janela quando ela esta aberta)
# --------------------------------------------------------------------------
_emit() {
    if [ "$BOX_OPEN" -eq 1 ]; then
        box_line "$1"
    elif [ "${2:-0}" -eq 1 ]; then
        echo "$1" >&2
    else
        echo "$1"
    fi
}

ok()   { _emit "${GREEN}✅ $*${RESET}"; }
warn() { _emit "${YELLOW}❗ $*${RESET}"; }
err()  { _emit "${RED}❌ $*${RESET}" 1; }
info() { _emit "${CYAN}$*${RESET}"; }

fail_exit() {
    err "$1"
    [ "$BOX_OPEN" -eq 1 ] && box_close
    print_footer
    exit 1
}

# --------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_USOL="$SCRIPT_DIR/usol.py"
INSTALL_DIR="${USOL_INSTALL_DIR:-$HOME/.local/share/usol}"
BIN_DIR="$HOME/.local/bin"
BIN_LINK="$BIN_DIR/usol"
LOG_FILE="$INSTALL_DIR/install.log"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

MISSING_PKGS=()
INSTALLED_PKGS=()
DEPS_ACTION="nenhuma dependencia faltando"
INSTALL_STATUS="NAO VERIFICADO"

print_banner() {
    echo "${BOLD}${CYAN}$(repeat_char = 61)${RESET}"
    echo "${BOLD}${CYAN}   USOL - Instalador automatizado${RESET}"
    echo "${DIM}   Universal System Optimization Layer${RESET}"
    echo "${BOLD}${CYAN}$(repeat_char = 61)${RESET}"
    echo
}

print_footer() {
    echo
    echo
    echo "${DIM}by PASSOS, OMAR${RESET}"
}

# --------------------------------------------------------------------------
# 1. Deteccao do sistema operacional
# --------------------------------------------------------------------------
detect_os() {
    if [ ! -f "$SOURCE_USOL" ]; then
        fail_exit "usol.py nao encontrado em $SCRIPT_DIR. Execute este instalador de dentro da pasta do projeto."
    fi

    box_open
    type_line "detectando sistema operacional..."

    if [ ! -f /etc/os-release ]; then
        fail_exit "Nao foi possivel identificar o sistema operacional (/etc/os-release ausente)."
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_NAME="${PRETTY_NAME:-${NAME:-desconhecido}}"
    OS_ID="${ID:-desconhecido}"
    KERNEL="$(uname -r)"
    ARCH="$(uname -m)"

    if ! command -v apt-get >/dev/null 2>&1; then
        fail_exit "USOL requer uma distribuicao baseada em APT/dpkg (Debian, Ubuntu, Kali, Parrot, Mint...). apt-get nao encontrado neste sistema (ID: $OS_ID)."
    fi

    ok "Sistema: $OS_NAME ($ARCH)"
    ok "Kernel: $KERNEL"
    box_close
}

# --------------------------------------------------------------------------
# 2. Deteccao de recursos do computador
# --------------------------------------------------------------------------
detect_resources() {
    box_open
    type_line "verificando cpu, memoria e disco..."

    CPU_COUNT="$(nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo)"

    MEM_TOTAL_KB="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
    MEM_AVAIL_KB="$(awk '/MemAvailable/ {print $2}' /proc/meminfo)"
    MEM_TOTAL_MB=$((MEM_TOTAL_KB / 1024))
    MEM_AVAIL_MB=$((MEM_AVAIL_KB / 1024))

    DISK_FREE_KB="$(df -Pk "$HOME" | tail -1 | awk '{print $4}')"
    DISK_FREE_MB=$((DISK_FREE_KB / 1024))

    info "Processadores : ${BOLD}${CPU_COUNT}${RESET}"
    info "Memoria RAM   : ${BOLD}${MEM_TOTAL_MB} MB${RESET} total (${MEM_AVAIL_MB} MB disponivel)"
    info "Disco livre   : ${BOLD}${DISK_FREE_MB} MB${RESET} em \$HOME"

    MIN_DISK_MB=20
    if [ "$DISK_FREE_MB" -lt "$MIN_DISK_MB" ]; then
        fail_exit "Espaco em disco insuficiente (${DISK_FREE_MB} MB livres, minimo ${MIN_DISK_MB} MB)."
    fi
    ok "Recursos suficientes para a instalacao."
    box_close
}

# --------------------------------------------------------------------------
# 3. Deteccao do que falta para o USOL funcionar
# --------------------------------------------------------------------------
detect_dependencies() {
    box_open
    type_line "checando dependencias (python3, rich, apt)..."

    for tool in apt-get apt-cache dpkg; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            fail_exit "Ferramenta essencial '$tool' nao encontrada. Sistema APT parece incompleto/corrompido."
        fi
    done
    ok "apt-get, apt-cache e dpkg presentes."

    if command -v python3 >/dev/null 2>&1; then
        PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
        PY_MAJOR="$(python3 -c 'import sys; print(sys.version_info[0])')"
        PY_MINOR="$(python3 -c 'import sys; print(sys.version_info[1])')"
        if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]; }; then
            warn "Python $PY_VERSION encontrado, mas o USOL requer 3.8+."
            MISSING_PKGS+=("python3")
        else
            ok "Python $PY_VERSION encontrado (requisito: 3.8+)."
        fi
    else
        warn "python3 nao encontrado."
        PY_VERSION="ausente"
        MISSING_PKGS+=("python3")
    fi

    if command -v python3 >/dev/null 2>&1 && python3 -c "import rich" >/dev/null 2>&1; then
        RICH_VERSION="$(python3 -c 'from importlib.metadata import version; print(version("rich"))' 2>/dev/null || echo '?')"
        ok "Biblioteca Python 'rich' encontrada (versao $RICH_VERSION)."
    else
        warn "Biblioteca Python 'rich' nao encontrada."
        RICH_VERSION="ausente"
        MISSING_PKGS+=("python3-rich")
    fi

    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        mapfile -t MISSING_PKGS < <(printf "%s\n" "${MISSING_PKGS[@]}" | sort -u)
    fi
    box_close
}

# --------------------------------------------------------------------------
# 4. Pergunta ao usuario se deseja instalar o que falta
# --------------------------------------------------------------------------
prompt_install_missing() {
    if [ ${#MISSING_PKGS[@]} -eq 0 ]; then
        box_open
        type_line "resolvendo dependencias..."
        ok "Todos os requisitos ja estao satisfeitos, nada a instalar."
        box_close
        return
    fi

    box_open
    type_line "resolvendo dependencias..."
    warn "Pacotes que faltam: ${MISSING_PKGS[*]}"
    box_close

    local resp
    read -r -p "${YELLOW}${BOLD}❯${RESET} Deseja instalar esses pacotes agora via apt? [S/n] " resp || resp=""
    resp="${resp:-S}"
    case "$resp" in
        [sS]*)
            local sudo_cmd=()
            if [ "$(id -u)" -ne 0 ]; then
                sudo_cmd=("sudo")
            fi
            echo
            echo "${DIM}--- saida nativa do apt-get ---${RESET}"
            "${sudo_cmd[@]}" apt-get update
            "${sudo_cmd[@]}" apt-get install -y "${MISSING_PKGS[@]}"
            echo "${DIM}--------------------------------${RESET}"
            echo
            INSTALLED_PKGS=("${MISSING_PKGS[@]}")
            DEPS_ACTION="instalados via apt: ${MISSING_PKGS[*]}"
            ok "Pacotes instalados com sucesso."
            ;;
        *)
            DEPS_ACTION="instalacao recusada pelo usuario (faltando: ${MISSING_PKGS[*]})"
            warn "Instalacao das dependencias foi recusada. O USOL pode nao funcionar corretamente."
            ;;
    esac
}

# --------------------------------------------------------------------------
# 5. Instalacao do USOL
# --------------------------------------------------------------------------
install_usol() {
    box_open
    type_line "copiando arquivos para $INSTALL_DIR..."

    mkdir -p "$INSTALL_DIR" "$BIN_DIR"
    cp -f "$SOURCE_USOL" "$INSTALL_DIR/usol.py"
    [ -f "$SCRIPT_DIR/README.md" ] && cp -f "$SCRIPT_DIR/README.md" "$INSTALL_DIR/README.md"
    chmod +x "$INSTALL_DIR/usol.py"

    ln -sf "$INSTALL_DIR/usol.py" "$BIN_LINK"
    chmod +x "$BIN_LINK"

    ok "Arquivos instalados em: $INSTALL_DIR"
    ok "Atalho executavel criado em: $BIN_LINK"

    case ":$PATH:" in
        *":$BIN_DIR:"*)
            ;;
        *)
            warn "$BIN_DIR nao esta no seu PATH."
            box_line "${CYAN}Adicione ao ~/.bashrc ou ~/.zshrc: export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
            ;;
    esac

    # secure_path do sudo (/etc/sudoers) normalmente nao inclui ~/.local/bin,
    # entao "sudo usol" (ou root puro, com HOME=/root) nao acha o comando sem
    # um link tambem em /usr/local/bin, que esta no PATH padrao de todo usuario.
    SYSTEM_LINK="/usr/local/bin/usol"
    if [ -w /usr/local/bin ] 2>/dev/null; then
        ln -sf "$INSTALL_DIR/usol.py" "$SYSTEM_LINK"
        ok "Atalho para root/sudo criado em: $SYSTEM_LINK"
    elif command -v sudo >/dev/null 2>&1; then
        if sudo ln -sf "$INSTALL_DIR/usol.py" "$SYSTEM_LINK" 2>/dev/null; then
            ok "Atalho para root/sudo criado em: $SYSTEM_LINK"
        else
            warn "Nao foi possivel criar $SYSTEM_LINK (sudo indisponivel ou recusado)."
            box_line "${CYAN}'sudo usol' nao vai funcionar ate voce rodar manualmente:${RESET}"
            box_line "${CYAN}  sudo ln -sf $INSTALL_DIR/usol.py $SYSTEM_LINK${RESET}"
        fi
    else
        warn "Sem sudo disponivel para criar $SYSTEM_LINK."
    fi
    box_close
}

# --------------------------------------------------------------------------
# 6. Verificacao final
# --------------------------------------------------------------------------
verify_install() {
    box_open
    type_line "usol --version"
    local version_out
    if version_out="$("$BIN_LINK" --version 2>&1)"; then
        box_line "${MAGENTA}${version_out}${RESET}"
        ok "usol esta executando corretamente."
        INSTALL_STATUS="OK"
    else
        err "Falha ao executar usol apos a instalacao."
        INSTALL_STATUS="FALHOU"
    fi
    box_close
}

# --------------------------------------------------------------------------
# 7. Log final com todas as informacoes
# --------------------------------------------------------------------------
print_final_log() {
    {
        echo "USOL - log de instalacao"
        echo "Data/hora: $TIMESTAMP"
        echo "----------------------------------------------------------------"
        echo "Sistema operacional : $OS_NAME ($ARCH)"
        echo "Kernel              : $KERNEL"
        echo "CPUs                : $CPU_COUNT"
        echo "RAM total / livre   : ${MEM_TOTAL_MB} MB / ${MEM_AVAIL_MB} MB"
        echo "Disco livre em HOME : ${DISK_FREE_MB} MB"
        echo "Python detectado    : $PY_VERSION"
        echo "rich detectado      : $RICH_VERSION"
        echo "Dependencias        : $DEPS_ACTION"
        echo "Pasta de instalacao : $INSTALL_DIR"
        echo "Atalho no PATH      : $BIN_LINK"
        echo "Status da instalacao: $INSTALL_STATUS"
        echo "----------------------------------------------------------------"
    } > "$LOG_FILE"

    box_open
    type_line "cat ${LOG_FILE/#$HOME/\~}"
    while IFS= read -r line; do
        box_line "${DIM}${line}${RESET}"
    done < "$LOG_FILE"
    box_close

    ok "Log salvo em: $LOG_FILE"
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
main() {
    [ -t 1 ] && clear
    print_banner
    detect_os
    detect_resources
    detect_dependencies
    prompt_install_missing
    install_usol
    verify_install
    print_final_log
    print_footer
}

main "$@"
