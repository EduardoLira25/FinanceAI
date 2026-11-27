import os
import re
import secrets
import shutil
import sqlite3
import plistlib
from pathlib import Path

BASE = Path(__file__).resolve().parent

env = BASE / ".env"

if not env.exists():
    plantilla = (BASE / ".env.example").read_text()

    patron = r"(?m)^([A-Za-z_][A-Za-z0-9_]*API_KEY)\s*=.*$"

    if not re.search(patron, plantilla):
        patron = r"(?m)^(API_KEY)\s*=.*$"

    assert len(re.findall(patron, plantilla)) == 1

    contenido = re.sub(
        patron,
        lambda m: m.group(1) + "=" + secrets.token_hex(32),
        plantilla
    )

    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(contenido)

for carpeta, nombre in [
    ("database", "financeai.db"),
    ("replay", "financeai_replay.db"),
    ("replay", "financeai_replay_final.db")
]:
    destino = BASE / carpeta / nombre

    if not destino.exists():
        shutil.copy2(BASE / "exports" / nombre, destino)

        with sqlite3.connect(destino) as c:
            assert c.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0] == "ok"

            for version, ruta in c.execute(
                "SELECT version, model_path FROM model_versions"
            ).fetchall():

                if Path(ruta).is_absolute():
                    c.execute(
                        "UPDATE model_versions SET model_path=? WHERE version=?",
                        (
                            str(BASE / "models/modelo_final_v1/modelo_final.keras"),
                            version
                        )
                    )

def adaptar(valor):
    if isinstance(valor, str):
        return valor.replace(
            "${PROJECT_DIR}", str(BASE)
        ).replace(
            "${HOME}", str(Path.home())
        )
    if isinstance(valor, list):
        return [adaptar(v) for v in valor]
    if isinstance(valor, dict):
        return {k: adaptar(v) for k, v in valor.items()}
    return valor

carpeta = BASE / "deployment/macos"
config = plistlib.loads(
    (carpeta / "com.financeai.daily.template.plist").read_bytes()
)

ruta = carpeta / "com.financeai.daily.plist"

if not ruta.exists():
    ruta.write_bytes(plistlib.dumps(adaptar(config)))
    ruta.chmod(0o600)

print("Configuracion local preparada.")
print("No se ha instalado launchd ni activado la cartera.")
