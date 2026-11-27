import sqlite3

from fastapi import (
    APIRouter,
    Depends,
    HTTPException
)

from backend.app.core.security import verify_api_key

from backend.app.services.prediction import (
    generate_prediction,
    latest_prediction,
    PredictionError
)

router = APIRouter(
    prefix="/api/v1/predictions",
    dependencies=[Depends(verify_api_key)],
    tags=["Predicciones"]
)


@router.get("/latest")
def get_latest_prediction():

    try:

        resultado = latest_prediction()

    except (sqlite3.Error, OSError, RuntimeError):

        raise HTTPException(
            status_code=503,
            detail="Servicio de predicciones no disponible."
        )

    if resultado is None:

        raise HTTPException(
            status_code=404,
            detail="No existen predicciones almacenadas."
        )

    return resultado


@router.post("/generate")
def create_prediction():

    try:

        return generate_prediction()

    except PredictionError:

        raise HTTPException(
            status_code=409,
            detail="Datos o modelo no aptos para prediccion."
        )

    except (sqlite3.Error, OSError, RuntimeError):

        raise HTTPException(
            status_code=503,
            detail="Servicio de predicciones no disponible."
        )
