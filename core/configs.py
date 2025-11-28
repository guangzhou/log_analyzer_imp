
from pathlib import Path
import yaml
CONF_DIR = Path(__file__).resolve().parents[1] / "configs"
def load_yaml(name: str) -> dict:
    with open(CONF_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
APP_CFG = load_yaml("application.yaml")
COMMITTEE_CFG = load_yaml("committee.yaml")
WRITER_CFG = load_yaml("writer.yaml")
MODELS_CFG = load_yaml("models.yaml")
