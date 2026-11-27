import hashlib
import json
import math
import time
import threading

import numpy as np
import pandas as pd

from datetime import datetime, timezone
from functools import lru_cache

from backend.app.core.config import (
    BASE_DIR,
    MODEL_PATH,
    DATABASE_PATH
)

from backend.app.core.database import (
    read_connection,
    write_transaction
)

DAY = 86400
SYMBOL = "BTCUSDT"
VERSION = "1.0.0"
WINDOW = 20
REQUIRED_CLOSES = 40

FEATURES = [
    "Return",
    "SMA_Distance_20",
    "Volatility_20"
]

MANIFEST_SHA256 = (
    "684df71c7a6ecafb9bfa0ca906b69310b37a3f50f6263b945d45c02ae6960ca2"
)

MODEL_LOCK = threading.RLock()


class PredictionError(RuntimeError):
    pass


def sha256(path):

    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def verify_artifacts():

    ruta = MODEL_PATH / "manifiesto_modelo_final.json"

    if sha256(ruta) != MANIFEST_SHA256:
        raise PredictionError(
            "Manifiesto original modificado."
        )

    manifiesto = json.loads(
        ruta.read_text(encoding="utf-8")
    )

    for nombre, info in manifiesto["Archivos"].items():

        archivo = MODEL_PATH / nombre

        if not archivo.is_file():
            raise PredictionError(
                "Archivo del modelo ausente."
            )

        if (
            sha256(archivo) != info["SHA256"]
            or archivo.stat().st_size != info["Bytes"]
        ):
            raise PredictionError(
                "Integridad del modelo invalida."
            )

    if (
        manifiesto["Version"] != VERSION
        or manifiesto["Activo"] != SYMBOL
        or manifiesto["Ventana"] != WINDOW
        or manifiesto["Variables_ordenadas"] != FEATURES
        or manifiesto["Forma_entrada"] != [None, 20, 3]
    ):
        raise PredictionError(
            "Configuracion del modelo incompatible."
        )

    return manifiesto


@lru_cache(maxsize=1)
def load_model():

    import tensorflow as tf
    import joblib

    verify_artifacts()

    modelo = tf.keras.models.load_model(
        MODEL_PATH / "modelo_final.keras",
        compile=False,
        safe_mode=True
    )

    scaler_X = joblib.load(
        MODEL_PATH / "scaler_X.joblib"
    )

    scaler_y = joblib.load(
        MODEL_PATH / "scaler_y.joblib"
    )

    if tuple(modelo.input_shape) != (None, 20, 3):
        raise PredictionError(
            "Forma de entrada incompatible."
        )

    if modelo.count_params() != 1425:
        raise PredictionError(
            "Numero de parametros incompatible."
        )

    if scaler_X.n_features_in_ != 3:
        raise PredictionError(
            "Escalador X incompatible."
        )

    if scaler_y.n_features_in_ != 1:
        raise PredictionError(
            "Escalador Y incompatible."
        )

    return modelo, scaler_X, scaler_y


def build_features(closes):

    valores = np.asarray(
        closes,
        dtype=np.float64
    )

    if valores.ndim != 1 or len(valores) < REQUIRED_CLOSES:

        raise PredictionError(
            "Se requieren al menos 40 cierres."
        )

    if (
        not np.isfinite(valores).all()
        or np.any(valores <= 0)
    ):
        raise PredictionError(
            "Precios financieros invalidos."
        )

    serie = pd.Series(valores)

    rendimientos = serie.pct_change(
        fill_method=None
    )

    sma = serie.rolling(20).mean()

    volatilidad = rendimientos.rolling(20).std(
        ddof=1
    )

    datos = pd.DataFrame({
        "Return": rendimientos,
        "SMA_Distance_20": serie / sma - 1,
        "Volatility_20": volatilidad
    })

    matriz = datos[FEATURES].tail(WINDOW).to_numpy()

    if (
        matriz.shape != (20, 3)
        or not np.isfinite(matriz).all()
    ):
        raise PredictionError(
            "Ventana predictiva invalida."
        )

    return matriz


def infer_return(features):

    with MODEL_LOCK:

        verify_artifacts()

        modelo, scaler_X, scaler_y = load_model()

        escalados = scaler_X.transform(
            features
        ).reshape(1, 20, 3)

        salida = modelo(
            escalados.astype(np.float32),
            training=False
        ).numpy()

        retorno = float(
            scaler_y.inverse_transform(
                salida
            ).ravel()[0]
        )

    if not math.isfinite(retorno) or retorno <= -1:

        raise PredictionError(
            "Pronostico numerico invalido."
        )

    return retorno


def validate_window(rows, now):

    if len(rows) != REQUIRED_CLOSES:

        raise PredictionError(
            "Historial insuficiente."
        )

    for i, fila in enumerate(rows):

        if fila["close_time"] - fila["open_time"] != DAY:
            raise PredictionError(
                "Frecuencia de vela invalida."
            )

        if fila["close_time"] > now:
            raise PredictionError(
                "Vela no cerrada."
            )

        if i and (
            fila["open_time"]
            != rows[i-1]["close_time"]
        ):
            raise PredictionError(
                "Historial discontinuo."
            )

    ultima = rows[-1]

    if now >= ultima["close_time"] + DAY:

        raise PredictionError(
            "Periodo objetivo vencido. "
            "Sincronizar MEXC primero."
        )


def serialize_prediction(fila):

    datos = dict(fila)

    def fecha(t):

        return datetime.fromtimestamp(
            t,
            timezone.utc
        ).isoformat()

    return {
        "id": datos["id"],
        "symbol": SYMBOL,
        "model_version": datos["model_version"],
        "candle_id": datos["candle_id"],
        "reference_close": datos["reference_close"],
        "predicted_return": datos["predicted_return"],
        "predicted_return_pct": (
            datos["predicted_return"] * 100
        ),
        "predicted_price": datos["predicted_price"],
        "target_open_utc": fecha(
            datos["target_open_time"]
        ),
        "target_close_utc": fecha(
            datos["target_close_time"]
        ),
        "theoretical_emission_utc": fecha(
            datos["emission_time"]
        ),
        "generated_at_utc": fecha(
            datos["created_at"]
        ),
        "inference_ms": datos["inference_ms"],
        "real_trading": False
    }


def get_prediction(conexion, candle_id=None):

    sql = """
        SELECT p.*, c.close AS reference_close
        FROM predictions p
        JOIN candles c ON c.id = p.candle_id
        JOIN assets a ON a.id = c.asset_id
        WHERE p.model_version = ?
          AND a.symbol = ?
    """

    parametros = [VERSION, SYMBOL]

    if candle_id is not None:

        sql += " AND p.candle_id = ?"

        parametros.append(candle_id)

    sql += " ORDER BY c.open_time DESC LIMIT 1"

    return conexion.execute(
        sql,
        parametros
    ).fetchone()


def latest_prediction(path=DATABASE_PATH):

    with read_connection(path) as conexion:

        fila = get_prediction(conexion)

        if fila is None:
            return None

        return serialize_prediction(fila)


def generate_prediction(
    path=DATABASE_PATH,
    clock=time.time,
    inference=infer_return
):

    manifiesto = verify_artifacts()

    now = int(clock())

    with read_connection(path) as conexion:

        filas = conexion.execute("""
            SELECT c.id, c.open_time,
                   c.close_time, c.close
            FROM candles c
            JOIN assets a ON a.id = c.asset_id
            WHERE a.symbol = ?
              AND a.exchange = 'MEXC'
              AND a.active = 1
              AND c.interval_seconds = ?
            ORDER BY c.open_time DESC
            LIMIT ?
        """, (
            SYMBOL,
            DAY,
            REQUIRED_CLOSES
        )).fetchall()

        filas = list(reversed(filas))

        validate_window(filas, now)

        ultima = filas[-1]

        modelo_db = conexion.execute("""
            SELECT model_sha256
            FROM model_versions
            WHERE version = ?
        """, (VERSION,)).fetchone()

        if (
            modelo_db is None
            or modelo_db["model_sha256"]
            != manifiesto["Archivos"]["modelo_final.keras"]["SHA256"]
        ):
            raise PredictionError(
                "Modelo registrado incompatible."
            )

        existente = get_prediction(
            conexion,
            ultima["id"]
        )

        if existente is not None:

            return {
                **serialize_prediction(existente),
                "created": False
            }

    features = build_features([
        fila["close"] for fila in filas
    ])

    inicio = time.perf_counter()

    retorno = float(inference(features))

    latencia = (
        time.perf_counter() - inicio
    ) * 1000

    precio = float(
        ultima["close"] * (1 + retorno)
    )

    if (
        not math.isfinite(retorno)
        or not math.isfinite(precio)
        or precio <= 0
    ):
        raise PredictionError(
            "Prediccion no valida."
        )

    generado = int(clock())

    validate_window(filas, generado)

    with write_transaction(path) as conexion:

        vigente = conexion.execute("""
            SELECT MAX(c.open_time)
            FROM candles c
            JOIN assets a ON a.id = c.asset_id
            WHERE a.symbol = ?
              AND c.interval_seconds = ?
        """, (SYMBOL, DAY)).fetchone()[0]

        if vigente != ultima["open_time"]:

            raise PredictionError(
                "Historial actualizado durante inferencia."
            )

        existente = get_prediction(
            conexion,
            ultima["id"]
        )

        if existente is not None:

            return {
                **serialize_prediction(existente),
                "created": False
            }

        conexion.execute("""
            INSERT INTO predictions (
                candle_id,
                model_version,
                predicted_return,
                predicted_price,
                emission_time,
                target_open_time,
                target_close_time,
                inference_ms,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ultima["id"],
            VERSION,
            retorno,
            precio,
            ultima["close_time"],
            ultima["close_time"],
            ultima["close_time"] + DAY,
            latencia,
            generado
        ))

        fila = get_prediction(
            conexion,
            ultima["id"]
        )

        resultado = {
            **serialize_prediction(fila),
            "created": True
        }

    return resultado


def main():

    print("=" * 60)
    print("FINANCEAI - INFERENCIA LOCAL LSTM")
    print("=" * 60)

    verify_artifacts()

    print("Integridad del modelo: APROBADA")

    resultado = generate_prediction()

    repeticion = generate_prediction()

    assert repeticion["created"] is False
    assert resultado["id"] == repeticion["id"]

    assert (
        resultado["predicted_return"]
        == repeticion["predicted_return"]
    )

    print(json.dumps(
        resultado,
        indent=4,
        ensure_ascii=False
    ))

    print("\nRendimiento pronosticado:",
          resultado["predicted_return_pct"], "%")

    print("Precio pronosticado:",
          round(resultado["predicted_price"], 2),
          "USDT")

    evidencia = {
        "Resultado": "APROBADO",
        "Prediccion": resultado,
        "Repeticion": repeticion,
        "Idempotencia": True,
        "Reentrenamiento": False,
        "Evaluacion_TE": False,
        "Operaciones_financieras": False
    }

    (
        BASE_DIR /
        "results/control_inferencia_local.json"
    ).write_text(
        json.dumps(evidencia, indent=4),
        encoding="utf-8"
    )

    print("\nModelo LSTM: INTEGRADO")
    print("Escaladores originales: UTILIZADOS")
    print("Prediccion: ALMACENADA")
    print("Predicciones duplicadas: NO")
    print("Reentrenamiento: NO")
    print("TE reevaluado: NO")
    print("Operaciones financieras: NO")
    print("\nPASO 11.7 COMPLETADO CORRECTAMENTE")


if __name__ == "__main__":
    main()
