import json
import re

def sanitize_data(data):
    # Sanitize input data to prevent injection attacks
    if isinstance(data, dict):
        return {k: sanitize_data(v) for k, v in data.items()}
    elif isinstance(data, str):
        return re.sub(r'[^\w\s-]', '', data)  # Allow only word characters, spaces, and hyphens
    return data

def emit_telemetry_event(event_name, data):
    # Validate event name
    valid_events = {
        'champion_retained',
        'champion_replaced',
        'constitution_violation_blocked',
        'ledger_entry_written',
        'challenger_proposed'
    }
    if event_name not in valid_events:
        raise ValueError("Invalid event name")

    # Sanitize the data
    sanitized_data = sanitize_data(data)

    # Emit the telemetry event (placeholder for actual emission logic)
    print(json.dumps({'event': event_name, 'data': sanitized_data}))

    # Here you would add the logic to send the telemetry data to your telemetry service
