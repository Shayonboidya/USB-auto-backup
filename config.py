import json
from pathlib import Path

def load_config(config_path=None):
    """Load and parse configuration from config.json, resolving all paths to absolute forms."""
    if config_path is None:
        config_path = Path(__file__).parent / "config.json"
    else:
        config_path = Path(config_path)

    with open(config_path, 'r') as f:
        config = json.load(f)

    base = config_path.parent

    # Resolve path keys: absolute paths use as-is, relative paths resolve from base
    path_keys = ['backup_dir', 'log_file', 'db_path']
    for key in path_keys:
        value = config.get(key, '')
        if not value:
            continue
        p = Path(value)
        if p.is_absolute():
            resolved = p.expanduser().resolve()
        else:
            resolved = (base / value).expanduser().resolve()
        config[key] = str(resolved)

    return config
