# Manual de instalación de FinanceAI

## Entorno de referencia

- macOS ARM64.
- Python 3.13.18.
- Node.js 24.14.1.
- Ollama 0.40.18.
- Modelo qwen3:8b.
- 16 GB de RAM en el equipo utilizado.

## Instalación

Desde la carpeta FinanceAI extraída del ZIP:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-lock-macos.txt
python -m pip install matplotlib==3.10.0
python setup_local.py
cd frontend
npm ci
npm run build
cd ..
ollama pull qwen3:8b
python -m backend.run_dashboard
```

Abrir http://127.0.0.1:5173.

El script setup_local.py genera una clave local y restaura
las bases SQLite entregadas, sin sobrescribir bases existentes.

El modelo Qwen3 descargado debe coincidir con la versión
y el digest esperado por el backend.

La instalación del programador launchd es opcional.
No activar la cartera sin revisar los controles de seguridad.

La instalación completa en una computadora diferente
permanece pendiente de validación independiente.
