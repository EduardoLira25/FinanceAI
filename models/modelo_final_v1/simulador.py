import numpy as np
import pandas as pd

def simular_estrategia(
    datos,
    posiciones_deseadas,
    capital_inicial=100000.0,
    comision=0.001
):

    datos = datos.reset_index(drop=True).copy()

    posiciones_deseadas = np.asarray(
        posiciones_deseadas
    )

    assert len(datos) == len(posiciones_deseadas)
    assert len(datos) > 0
    assert np.isin(posiciones_deseadas, [0, 1]).all()
    assert capital_inicial > 0
    assert 0 <= comision < 1
    assert datos["Target_Date"].is_monotonic_increasing
    assert not datos["Target_Date"].duplicated().any()

    efectivo = float(capital_inicial)
    cantidad_btc = 0.0

    costos_totales = 0.0
    compras = 0
    ventas = 0

    capital_entrada = None

    resultados_operaciones = []

    historial = []

    equity_anterior = capital_inicial

    for i, fila in datos.iterrows():

        precio_apertura = float(fila["Open"])
        precio_cierre = float(fila["Close"])

        assert np.isfinite(precio_apertura)
        assert np.isfinite(precio_cierre)
        assert precio_apertura > 0
        assert precio_cierre > 0

        posicion_deseada = int(
            posiciones_deseadas[i]
        )

        comision_apertura = 0.0
        comision_liquidacion = 0.0

        liquidacion_final = False

        # COMPRAR BTC
        if posicion_deseada == 1 and cantidad_btc == 0:

            capital_entrada = efectivo

            cantidad_btc = efectivo / (
                precio_apertura * (1 + comision)
            )

            importe_compra = (
                cantidad_btc * precio_apertura
            )

            comision_apertura = (
                importe_compra * comision
            )

            costos_totales += comision_apertura

            efectivo = 0.0

            compras += 1

            accion = "COMPRAR"

        # VENDER BTC
        elif posicion_deseada == 0 and cantidad_btc > 0:

            importe_venta = (
                cantidad_btc * precio_apertura
            )

            comision_apertura = (
                importe_venta * comision
            )

            efectivo += (
                importe_venta - comision_apertura
            )

            costos_totales += comision_apertura

            resultados_operaciones.append(
                efectivo - capital_entrada
            )

            cantidad_btc = 0.0
            capital_entrada = None

            ventas += 1

            accion = "VENDER"

        # MANTENER POSICIÓN
        elif cantidad_btc > 0:

            accion = "MANTENER_BTC"

        else:

            accion = "MANTENER_EFECTIVO"

        # Liquidar cualquier posición abierta
        # al cierre del último día
        if i == len(datos) - 1 and cantidad_btc > 0:

            importe_liquidacion = (
                cantidad_btc * precio_cierre
            )

            comision_liquidacion = (
                importe_liquidacion * comision
            )

            efectivo += (
                importe_liquidacion -
                comision_liquidacion
            )

            costos_totales += comision_liquidacion

            resultados_operaciones.append(
                efectivo - capital_entrada
            )

            cantidad_btc = 0.0
            capital_entrada = None

            ventas += 1
            liquidacion_final = True

        # Valor total de la cartera al cierre
        equity = efectivo + cantidad_btc * precio_cierre

        rendimiento_cartera = (
            equity / equity_anterior - 1
        )

        equity_anterior = equity

        # Controles de riesgo
        assert efectivo >= -1e-8
        assert cantidad_btc >= 0
        assert np.isfinite(equity)
        assert equity > 0

        historial.append({
            "Emission_Time": fila["Emission_Time"],
            "Target_Date": fila["Target_Date"],
            "Open": precio_apertura,
            "Close": precio_cierre,
            "Rendimiento_predicho":
                fila["Rendimiento_predicho"],
            "Rendimiento_real":
                fila["Rendimiento_real"],
            "Posicion_deseada": posicion_deseada,
            "Accion": accion,
            "Liquidacion_final": liquidacion_final,
            "Efectivo": efectivo,
            "Cantidad_BTC": cantidad_btc,
            "Comision_apertura": comision_apertura,
            "Comision_liquidacion": comision_liquidacion,
            "Costos_acumulados": costos_totales,
            "Equity": equity,
            "Rendimiento_cartera": rendimiento_cartera
        })

    df_simulacion = pd.DataFrame(historial)

    # Calcular drawdown incluyendo capital inicial
    serie_equity = np.concatenate([
        [capital_inicial],
        df_simulacion["Equity"].to_numpy()
    ])

    maximos = np.maximum.accumulate(serie_equity)

    drawdown = 1 - serie_equity / maximos

    max_drawdown = float(np.max(drawdown))

    df_simulacion["Drawdown"] = drawdown[1:]

    capital_final = float(
        df_simulacion["Equity"].iloc[-1]
    )

    rendimiento_neto = (
        capital_final / capital_inicial - 1
    )

    operaciones_cerradas = len(
        resultados_operaciones
    )

    # Win Rate: operaciones completas rentables
    win_rate = (
        float(
            np.mean(
                np.asarray(resultados_operaciones) > 0
            ) * 100
        )
        if operaciones_cerradas > 0
        else np.nan
    )

    assert cantidad_btc == 0
    assert compras == ventas == operaciones_cerradas

    metricas = {
        "Capital_inicial": capital_inicial,
        "Capital_final": capital_final,
        "Beneficio_neto": capital_final - capital_inicial,
        "Rendimiento_neto_pct": rendimiento_neto * 100,
        "Max_drawdown_pct": max_drawdown * 100,
        "Compras": compras,
        "Ventas": ventas,
        "Transacciones": compras + ventas,
        "Operaciones_cerradas": operaciones_cerradas,
        "Win_rate_pct": win_rate,
        "Costos_totales": costos_totales
    }

    return metricas, df_simulacion
