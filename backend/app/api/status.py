import hashlib
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.security import verify_api_key
from backend.app.services.prediction import verify_artifacts, PredictionError

from backend.app.core.config import (
    APP_NAME,
    APP_VERSION,
    APP_MODE,
    MODEL_PATH
)

from backend.app.core.database import (
    read_connection,
    database_status
)

router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)]
)


@router.get("/status", tags=["Sistema"])
def system_status():

    try:

        estado = database_status()

    except (sqlite3.Error, RuntimeError, OSError):

        raise HTTPException(
            status_code=503,
            detail="Base de datos no disponible."
        )

    return {
        "project": APP_NAME,
        "version": APP_VERSION,
        "status": "ok",
        "mode": APP_MODE,
        "database": estado["status"],
        "agent_enabled": False,
        "real_trading": False
    }


@router.get("/database/status", tags=["Sistema"])
def get_database_status():

    try:

        return database_status()

    except (sqlite3.Error, RuntimeError, OSError):

        raise HTTPException(
            status_code=503,
            detail="Base de datos no disponible."
        )


@router.get("/model/status", tags=["Modelo"])
def model_status():

    with read_connection() as conexion:

        fila = conexion.execute("""
            SELECT
                version,
                architecture,
                window_size,
                feature_count,
                model_sha256
            FROM model_versions
            WHERE version = ?
        """, ("1.0.0",)).fetchone()

    if fila is None:

        raise HTTPException(
            status_code=503,
            detail="Modelo no registrado."
        )

    archivos_requeridos = [
        "modelo_final.keras",
        "scaler_X.joblib",
        "scaler_y.joblib",
        "manifiesto_modelo_final.json"
    ]

    disponibles = all(
        (MODEL_PATH / nombre).is_file()
        for nombre in archivos_requeridos
    )

    if not disponibles:

        raise HTTPException(
            status_code=503,
            detail="Archivos del modelo no disponibles."
        )

    huella = hashlib.sha256(
        (MODEL_PATH / "modelo_final.keras").read_bytes()
    ).hexdigest()

    if huella != fila["model_sha256"]:

        raise HTTPException(
            status_code=503,
            detail="Integridad del modelo no verificada."
        )

    return {
        "status": "available",
        "version": fila["version"],
        "architecture": fila["architecture"],
        "window_size": fila["window_size"],
        "feature_count": fila["feature_count"],
        "integrity_verified": True,
        "inference_service_ready": True
    }


@router.get("/portfolio", tags=["Cartera"])
def get_portfolio():

    with read_connection() as conexion:

        cartera = conexion.execute("""
            SELECT *
            FROM portfolio
            WHERE name = ?
        """, ("FinanceAI_Paper",)).fetchone()

        if cartera is None:

            raise HTTPException(
                status_code=404,
                detail="Cartera no encontrada."
            )

        posiciones = conexion.execute("""
            SELECT
                a.symbol,
                p.quantity_sats,
                p.cost_basis_micros
            FROM positions p
            JOIN assets a ON a.id = p.asset_id
            WHERE p.portfolio_id = ?
        """, (cartera["id"],)).fetchall()

    return {
        "name": cartera["name"],
        "mode": cartera["mode"],
        "strategy": cartera["strategy"],
        "currency": cartera["currency"],
        "status": cartera["status"],
        "initial_cash": cartera["initial_cash_micros"] / 1_000_000,
        "cash": cartera["cash_micros"] / 1_000_000,
        "positions": [
            {
                "symbol": fila["symbol"],
                "quantity": fila["quantity_sats"] / 100_000_000,
                "cost_basis": fila["cost_basis_micros"] / 1_000_000
            }
            for fila in posiciones
        ],
        "real_trading": False
    }
