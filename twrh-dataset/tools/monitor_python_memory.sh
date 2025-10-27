#!/bin/bash
# Monitor memory usage for Python processes periodically

# Configuration
LOG_FILE="python_memory_usage.log"
INTERVAL=60  # seconds between checks (default: 1 minute)

# Create or append to log file with header
if [ ! -f "$LOG_FILE" ]; then
    echo "Timestamp,PID,Process Name,%CPU,%MEM,RSS(KB),VSZ(KB),Command" > "$LOG_FILE"
fi

echo "Starting Python process memory monitoring..."
echo "Logging to: $LOG_FILE"
echo "Interval: ${INTERVAL}s"
echo "Press Ctrl+C to stop"

# Function to log memory usage
log_memory() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Get all Python processes
    ps aux | grep -E '[p]ython' | while read -r line; do
        # Parse ps output
        pid=$(echo "$line" | awk '{print $2}')
        cpu=$(echo "$line" | awk '{print $3}')
        mem=$(echo "$line" | awk '{print $4}')
        vsz=$(echo "$line" | awk '{print $5}')
        rss=$(echo "$line" | awk '{print $6}')
        cmd=$(echo "$line" | awk '{for(i=11;i<=NF;i++) printf $i" "; print ""}')
        process_name=$(echo "$cmd" | awk '{print $1}')
        
        # Append to log file
        echo "$timestamp,$pid,$process_name,$cpu,$mem,$rss,$vsz,$cmd" >> "$LOG_FILE"
    done
}

# Trap Ctrl+C to exit gracefully
trap 'echo -e "\nStopping monitor..."; exit 0' INT

# Main monitoring loop
while true; do
    log_memory
    sleep "$INTERVAL"
done
write to 