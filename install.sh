#!/bin/sh

# mommy-chaogu installer for macOS and Linux.
#
# Usage:
#   curl -LsSf https://github.com/coffee-man666/mommy-chaogu/raw/refs/heads/main/install.sh | sh
#
# Optional overrides:
#   MOMMY_INSTALL_SOURCE='mommy-chaogu @ https://example.com/package.whl'
#   MOMMY_INSTALL_PYTHON=3.13

set -eu

REPOSITORY="coffee-man666/mommy-chaogu"

# 默认安装最新 release（版本可复现、自报版本与实际一致）；API 无法解析时失败，
# 不静默退回 main。想跟踪 main 开发版，必须显式指定：
#   MOMMY_INSTALL_SOURCE='mommy-chaogu @ https://github.com/coffee-man666/mommy-chaogu/archive/refs/heads/main.tar.gz'
resolve_default_source() {
    latest_tag=""
    latest_payload=""
    if command -v curl >/dev/null 2>&1; then
        latest_payload=$(curl -LsSf --max-time 10 \
            "https://api.github.com/repos/${REPOSITORY}/releases/latest" 2>/dev/null) || return 1
    elif command -v wget >/dev/null 2>&1; then
        latest_payload=$(wget -q -T 10 -O - \
            "https://api.github.com/repos/${REPOSITORY}/releases/latest" 2>/dev/null) || return 1
    fi
    latest_tag=$(printf '%s' "$latest_payload" \
        | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)
    case "$latest_tag" in
        v[0-9]*.[0-9]*.[0-9]*) : ;;
        *) return 1 ;;
    esac
    printf '%s' "mommy-chaogu @ https://github.com/${REPOSITORY}/archive/refs/tags/${latest_tag}.tar.gz"
}
if [ -n "${MOMMY_INSTALL_SOURCE:-}" ]; then
    # Explicit source is already a user decision; do not probe GitHub latest.
    PACKAGE_SOURCE=$MOMMY_INSTALL_SOURCE
else
    PACKAGE_SOURCE=$(resolve_default_source) || {
        printf '\033[1;31merror:\033[0m 无法解析最新 release；请检查网络，或显式设置 MOMMY_INSTALL_SOURCE。\n' >&2
        exit 1
    }
fi
PYTHON_VERSION=${MOMMY_INSTALL_PYTHON:-3.12}

info() {
    printf '\033[1;34m%s\033[0m\n' "$1"
}

success() {
    printf '\033[1;32m%s\033[0m\n' "$1"
}

fail() {
    printf '\033[1;31merror:\033[0m %s\n' "$1" >&2
    exit 1
}

download() {
    source_url=$1
    destination=$2
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "$source_url" -o "$destination"
    elif command -v wget >/dev/null 2>&1; then
        wget -q "$source_url" -O "$destination"
    else
        fail "需要 curl 或 wget 才能继续安装。"
    fi
}

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return 0
    fi
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

case "$(uname -s 2>/dev/null || true)" in
    Darwin|Linux) ;;
    *) fail "当前安装脚本支持 macOS 和 Linux；Windows 安装器正在准备中。" ;;
esac

temporary_directory=""
cleanup() {
    if [ -n "$temporary_directory" ] && [ -d "$temporary_directory" ]; then
        rm -rf "$temporary_directory"
    fi
}
trap cleanup EXIT HUP INT TERM

if uv_binary=$(find_uv); then
    info "使用现有 uv：$uv_binary"
else
    info "没有检测到 uv，正在安装…"
    temporary_directory=$(mktemp -d "${TMPDIR:-/tmp}/mommy-chaogu-install.XXXXXX")
    uv_installer="$temporary_directory/uv-install.sh"
    download "https://astral.sh/uv/install.sh" "$uv_installer"
    sh "$uv_installer"
    uv_binary=$(find_uv) || fail "uv 已运行安装程序，但仍未找到可执行文件。"
fi

info "正在安装 mommy-chaogu（Python ${PYTHON_VERSION}）…"
"$uv_binary" tool install \
    --quiet \
    --quiet \
    --refresh-package mommy-chaogu \
    --reinstall-package mommy-chaogu \
    --python "$PYTHON_VERSION" \
    "$PACKAGE_SOURCE"

tool_bin_dir=$("$uv_binary" tool dir --bin)
mommy_binary="$tool_bin_dir/mommy"
[ -x "$mommy_binary" ] || fail "安装结束后没有找到 mommy 命令：$mommy_binary"
"$mommy_binary" --help >/dev/null

case ":$PATH:" in
    *":$tool_bin_dir:"*) path_ready=1 ;;
    *)
        path_ready=0
        "$uv_binary" tool update-shell >/dev/null 2>&1 || true
        ;;
esac

printf '\n'
success "mommy-chaogu 安装完成。"
printf '\n第一次运行：\n\n  mommy\n\n'
printf '它会自动进入模型配置；也可以运行 `mommy setup` 手动配置。\n'
if [ "$path_ready" -eq 0 ]; then
    printf '\n如果当前终端仍提示找不到 mommy，请重新打开终端后再运行。\n'
fi
