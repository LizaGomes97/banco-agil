#!/usr/bin/env bash
# Cria um swapfile de 2GB em VPS com pouca RAM (ex.: 1GB).
# Idempotente — se já houver swap suficiente, sai sem mudar nada.
#
# Uso:
#   sudo bash deploy/setup-swap.sh
#
# O que faz:
#   1. Verifica se já existe swap; se houver >=1G, sai.
#   2. Cria /swapfile de 2G, permissão 600.
#   3. Ativa e adiciona no /etc/fstab para persistir após reboot.
#   4. Ajusta swappiness=10 e vfs_cache_pressure=50 (melhor pra VPS).

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "[swap] Execute como root (use sudo)." >&2
    exit 1
fi

CURRENT_SWAP_KB="$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)"
CURRENT_SWAP_MB=$(( CURRENT_SWAP_KB / 1024 ))

if (( CURRENT_SWAP_MB >= 1024 )); then
    echo "[swap] Já existe ${CURRENT_SWAP_MB}MB de swap — nada a fazer."
    exit 0
fi

SWAP_FILE="/swapfile"
SWAP_SIZE_GB=2

echo "[swap] Criando ${SWAP_SIZE_GB}GB em ${SWAP_FILE}..."

if [[ ! -f "${SWAP_FILE}" ]]; then
    # fallocate é O(1); se falhar (alguns FS não suportam), cai para dd
    fallocate -l "${SWAP_SIZE_GB}G" "${SWAP_FILE}" \
        || dd if=/dev/zero of="${SWAP_FILE}" bs=1M count=$((SWAP_SIZE_GB * 1024)) status=progress
fi

chmod 600 "${SWAP_FILE}"
mkswap "${SWAP_FILE}" >/dev/null
swapon "${SWAP_FILE}"

# Persiste no fstab (evita duplicidade)
if ! grep -q "^${SWAP_FILE}" /etc/fstab; then
    echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
fi

# Tuning específico pra VPS: menos agressivo em swappar, menos cache inode
sysctl -w vm.swappiness=10 >/dev/null
sysctl -w vm.vfs_cache_pressure=50 >/dev/null

# Persiste sysctl
cat > /etc/sysctl.d/99-banco-agil-swap.conf <<EOF
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF

echo "[swap] OK — swap ativo:"
free -h | grep -E '^(Mem|Swap)'
