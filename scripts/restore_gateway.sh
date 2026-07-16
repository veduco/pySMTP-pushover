#!/usr/bin/env bash

# Establish targeted layout boundaries matching core constants
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="/opt/smtp-pushover/configs"

# Fallback gracefully if custom configs path doesn't exist
if [ ! -d "${CONFIG_DIR}" ]; then
    CONFIG_DIR="${SCRIPT_DIR}"
fi

# Dynamically locate the PID file based on the parent of the configuration directory
PID_FILE="$(find "$(dirname "${CONFIG_DIR}")" -name smtp.pid)"

ACTIVE_CONFIG="${CONFIG_DIR}/config.json"
ACTIVE_VAULT="${CONFIG_DIR}/vault.json"

# Color constants for clean scannable feedback
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

execute_restore() {
    local target_backup="$1"
    local epoch
    epoch=$(date +%s)

    if [ ! -f "${target_backup}" ]; then
        log_error "Target snapshot file not found: ${target_backup}"
    fi

    log_warn "Initiating state restoration from: $(basename "${target_backup}")"

    # Step 1: Create defensive rollback points without the word "valid"
    log_info "Creating fallback archive boundaries..."
    if [ -f "${ACTIVE_CONFIG}" ]; then
        cp "${ACTIVE_CONFIG}" "${CONFIG_DIR}/config.rollback.${epoch}.json"
        log_info "Archived active configuration to: config.rollback.${epoch}.json"
    fi
    if [ -f "${ACTIVE_VAULT}" ]; then
        cp "${ACTIVE_VAULT}" "${CONFIG_DIR}/vault.rollback.${epoch}.json"
        log_info "Archived active vault to: vault.rollback.${epoch}.json"
    fi

    # Step 2: Unpack the unified snapshot keys into separate files using python
    log_info "Extracting discrete configuration blocks from unified snapshot..."

    python3 -c "
import json, sys
with open(sys.argv[1], 'r') as f:
    data = json.load(f)

# Extract nested objects securely
config_data = data.get('config', {})
vault_data = data.get('vault', {})

# Save decoupled structures back to live runtime file targets
with open(sys.argv[2], 'w') as f:
    json.dump(config_data, f, indent=2)
with open(sys.argv[3], 'w') as f:
    json.dump(vault_data, f, indent=2)
" "${target_backup}" "${ACTIVE_CONFIG}" "${ACTIVE_VAULT}"

    if [ $? -eq 0 ]; then
        log_info "Successfully unpacked and updated ${ACTIVE_CONFIG}"
        log_info "Successfully unpacked and updated ${ACTIVE_VAULT}"
    else
        log_error "Failed to parse JSON blocks from unified gateway snapshot template."
    fi

    # Step 3: Fire signaling hooks down to the gateway worker process space
    if [ -n "${PID_FILE}" ] && [ -f "${PID_FILE}" ]; then
        local pid
        pid=$(cat "${PID_FILE}")
        if kill -0 "${pid}" 2>/dev/null; then
            log_info "Sending hot-swap signal (SIGUSR2) to running process ID: ${pid}"
            kill -SIGUSR2 "${pid}"
            log_info "Hot reload scheduled successfully."
        else
            log_warn "Process ID ${pid} found in pidfile but is not running on host."
        fi
    else
        log_warn "No active 'smtp.pid' file discovered. Gateway reload deferred until manual launch."
    fi

    echo -e "${GREEN}Restoration operation complete.${NC}"
    exit 0
}

# --- Main Entry Point ---

# Route A: Supplied explicit target file directly via command argument
if [ -n "$1" ]; then
    TARGET_FILE="$1"
    if [ ! -f "${TARGET_FILE}" ] && [ -f "${CONFIG_DIR}/${TARGET_FILE}" ]; then
        TARGET_FILE="${CONFIG_DIR}/${TARGET_FILE}"
    fi
    execute_restore "${TARGET_FILE}"
fi

# Route B: Interactive scanner mode
log_info "Scanning directory '${CONFIG_DIR}' for active valid gateway configurations..."

# Map backup snapshots safely into an array using pure numerical timestamp token sorting
unset backups
while IFS= read -r -d '' file; do
    backups+=("$file")
done < <(find "${CONFIG_DIR}" -maxdepth 1 -type f -name ".gateway.valid.*.json" -print0 | sort -t'.' -k4,4rn -z)

TOTAL_BACKUPS=${#backups[@]}

if [ "${TOTAL_BACKUPS}" -eq 0 ]; then
    log_error "No valid historical backup snapshots (*valid.*.json) discovered inside target path."
fi

echo -e "\nAvailable historical snapshots (Sorted Descending):"
echo "--------------------------------------------------------------------------------"

for i in "${!backups[@]}"; do
    filename=$(basename "${backups[$i]}")

    # Extract timestamp token (Token 4 is the epoch value when using hidden dot file prefixes)
    epoch_token=$(echo "${filename}" | cut -d'.' -f4)

    # Format the time cleanly leveraging local system timezone rules
    if date -d "@${epoch_token}" +'%Y-%m-%d %H:%M:%S' &>/dev/null; then
        human_time=$(date -d "@${epoch_token}" +'%Y-%m-%d %H:%M:%S')
    else
        human_time=$(date -r "${epoch_token}" +'%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "Unknown Date")
    fi

    printf "  [%2d]  %s   (Timestamp: %s)\n" "$((i+1))" "${filename}" "${human_time}"
done
echo "--------------------------------------------------------------------------------"

while true; do
    read -r -p "Select a configuration token number to restore [1-${TOTAL_BACKUPS}]: " selection

    if [[ "${selection}" =~ ^[0-9]+$ ]] && [ selection -ge 1 ] && [ selection -le "${TOTAL_BACKUPS}" ]; then
        SELECTED_INDEX=$((selection-1))
        TARGET_BACKUP="${backups[${SELECTED_INDEX}]}"
        break
    else
        echo -e "${RED}Invalid input selection index matrix. Please enter a valid number.${NC}"
    fi
done

execute_restore "${TARGET_BACKUP}"
