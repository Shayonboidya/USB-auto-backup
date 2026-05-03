import json
from pathlib import Path

def load_config(config_path=None):
    """Load and parse configuration from config.json, resolving all paths to absolute forms.

    If *config_path* is ``None`` the function looks for ``config.json`` in the
    same directory that contains this module (config.py).
    """
    if config_path is None:
        config_path = Path(__file__).parent / "config.json"
    else:
        config_path = Path(config_path)

    with open(config_path, 'r') as f:
        config = json.load(f)

    # Resolve backup_dir, log_file and db_path to absolute paths relative to the
    # project directory (the one that contains config.json).
    base = config_path.parent

    backup_dir = config.get('backup_dir', './backups')
    backup_path = (base / backup_dir).expanduser().resolve()
    config['backup_dir'] = str(backup_path)

    log_file = config.get('log_file', './usb_backup.log')
    log_path = (base / log_file).expanduser().resolve()
    config['log_file'] = str(log_path)

    db_path = config.get('db_path', './backups.db')
    db_file = (base / db_path).expanduser().resolve()
    config['db_path'] = str(db_file)

    return config
