"""Non-secret outage/power evidence only. Never used to gate or dispatch work."""
import json


def snapshot(health):
    if isinstance(health, str):
        try:
            health = json.loads(health)
        except (TypeError, ValueError):
            health = {}
    if not isinstance(health, dict):
        return {}
    fields = ('heartbeat_ms', 'uptime_ms', 'pid', 'app_version', 'version_code', 'device_id', 'worker_id')
    out = {k: health[k] for k in fields if k in health}
    worker = health.get('worker_health')
    if isinstance(worker, dict):
        out['worker_health'] = {k: worker[k] for k in ('os_uptime_ms', 'boot_count', 'user_unlocked',
            'interactive', 'keyguard_locked', 'battery_optimization_exempt', 'diagnostic_error') if k in worker}
        battery = worker.get('battery')
        if isinstance(battery, dict):
            out['worker_health']['battery'] = {k: battery[k] for k in ('level_percent', 'plugged', 'status',
                'charging', 'temperature_tenths_c', 'warning', 'current_now_ua', 'charge_counter_uah', 'observed_at_ms') if k in battery}
    return out


def power_key(health):
    worker = snapshot(health).get('worker_health', {})
    battery = worker.get('battery', {})
    return (worker.get('boot_count'), battery.get('level_percent'), battery.get('plugged'),
            battery.get('warning'), worker.get('battery_optimization_exempt'))
