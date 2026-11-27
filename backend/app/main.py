from fastapi import FastAPI

from backend.app.core.config import (
    APP_NAME,
    APP_VERSION,
    APP_MODE
)

from backend.app.api.status import router
from backend.app.api.market import router as market_router
from backend.app.api.predictions import router as predictions_router

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "API local para predicciones financieras "
        "y operaciones exclusivamente simuladas."
    ),
    docs_url="/docs",
    redoc_url=None
)

app.include_router(router)
app.include_router(market_router)
app.include_router(predictions_router)


@app.get("/", tags=["General"])
def root():

    return {
        "project": APP_NAME,
        "version": APP_VERSION,
        "mode": APP_MODE
    }


@app.get("/health", tags=["General"])
def health():

    return {
        "status": "ok"
    }


from backend.app.api.prediction_history import (
    router as prediction_history_router
)

app.include_router(prediction_history_router)


from backend.app.api.agent_monitor import (
    router as agent_monitor_router
)

app.include_router(agent_monitor_router)


from backend.app.api.agent_control import (
    router as agent_control_router
)

app.include_router(agent_control_router)


from backend.app.api.portfolio_history import (
    router as portfolio_history_router
)

app.include_router(portfolio_history_router)


from backend.app.api.risk_incidents import (
    router as risk_incidents_router
)

app.include_router(risk_incidents_router)


from backend.app.api.agent_recovery import (
    router as agent_recovery_router
)

app.include_router(agent_recovery_router)
