# FinanceAI — Manual de usuario

## 1. Introducción

FinanceAI es una plataforma académica de análisis financiero,
predicción mediante Deep Learning y negociación simulada
asistida por inteligencia artificial.

El sistema utiliza exclusivamente dinero virtual.

No es necesario disponer de una cuenta financiera en MEXC
ni depositar fondos reales.

## 2. Requisitos de funcionamiento

- Entorno de FinanceAI previamente instalado.
- Base de datos SQLite inicializada.
- Modelo LSTM y escaladores disponibles.
- Navegador web.
- Conexión a internet para actualizar el mercado.
- Ollama y Qwen3 para ejecutar ciclos del agente.
- macOS para utilizar el programador launchd implementado.

## 3. Iniciar FinanceAI

Abrir Terminal y ejecutar:

```bash
cd "$HOME/Documents/FinanceAI"
source .venv/bin/activate
python -m backend.run_dashboard
```

Esperar a que aparezca el mensaje:

`FINANCEAI - CONEXION SEGURA APROBADA`

Abrir en el navegador:

http://127.0.0.1:5173

El proceso inicia el backend FastAPI y el gateway
que proporciona acceso al frontend.

Para detener ambos servidores, utilizar Control+C
en la Terminal donde se inició FinanceAI.

Detener el dashboard no desinstala el programador
automático launchd.

## 4. Secciones de FinanceAI

### 4.1 Dashboard

Ruta: `/`

Presenta una visión general del sistema, incluyendo
información financiera, estado de los servicios,
pronósticos y principales indicadores.

### 4.2 Mercado

Ruta: `/mercado`

Permite consultar información de BTCUSDT obtenida
mediante los servicios públicos de MEXC.

Las velas contienen precios de apertura, máximo,
mínimo, cierre y volumen.

La predicción utiliza información de velas cerradas.
No debe confundirse una vela en formación con una
observación histórica definitiva.

### 4.3 Predicciones

Ruta: `/predicciones`

Presenta las predicciones generadas por el modelo LSTM.

El rendimiento pronosticado representa una estimación
del cambio de precio durante el siguiente periodo diario.

Un rendimiento positivo no garantiza una subida real.
Un rendimiento negativo tampoco garantiza una caída.

Las predicciones históricas pueden compararse con los
resultados observados cuando se dispone del cierre
del periodo objetivo.

### 4.4 Agente IA

Ruta: `/agente`

Permite consultar y controlar el funcionamiento del
agente financiero basado en Qwen3.

La sección presenta:

- Estado operativo de la cartera.
- Disponibilidad del motor de inteligencia artificial.
- Flujo de decisión.
- Última decisión registrada.
- Historial de decisiones.
- Estado del programador automático.
- Controles de activación, pausa y paro de emergencia.

Las acciones posibles del agente son:

| Acción | Significado |
|---|---|
| BUY | Propuesta de compra |
| SELL | Propuesta de venta |
| HOLD | Mantener el estado financiero |

Una propuesta BUY o SELL no significa necesariamente
que se haya ejecutado una orden.

El motor de riesgo puede rechazarla y autorizar HOLD.

### 4.5 Cartera

Ruta: `/cartera`

Permite consultar la situación financiera de la
cartera virtual.

| Concepto | Significado |
|---|---|
| Capital inicial | Fondos virtuales asignados al comenzar |
| Efectivo | USDT virtuales disponibles |
| Posición | Cantidad virtual de Bitcoin |
| Valor de posición | Valoración de Bitcoin en USDT |
| Patrimonio | Efectivo más valor de las posiciones |
| Rendimiento | Variación respecto al capital inicial |
| Drawdown | Caída respecto a un máximo previo |

La cartera principal comienza con 50,000 USDT
virtuales y sin posiciones abiertas.

Los resultados de las simulaciones históricas
se conservan por separado.

### 4.6 Operaciones

Ruta: `/operaciones`

Muestra el historial de órdenes simuladas.

Una decisión HOLD no genera una orden financiera.

Las operaciones ejecutadas se conservan en SQLite
y no se eliminan al reiniciar el dashboard.

### 4.7 Riesgo

Ruta: `/riesgo`

Presenta las restricciones financieras aplicadas
por el motor determinista de riesgo.

Configuración inicial:

| Parámetro | Valor |
|---|---|
| Exposición para nuevas compras | 25% |
| Límite de pérdida diaria para compras | 2% |
| Antigüedad máxima de vela | 3600 segundos |
| Orden mínima | 10 USDT |
| Comisión simulada | 0% |
| Deslizamiento simulado | 0% |

La exposición existente puede superar el 25%
debido a la apreciación del activo.

El límite de pérdida diaria restringe nuevas compras;
no garantiza una pérdida máxima absoluta.

### 4.8 Incidentes

Ruta: `/incidentes`

Permite consultar los errores operativos registrados.

El sistema puede registrar problemas relacionados con:

- Conexión a MEXC.
- Límites de solicitudes.
- Datos desactualizados.
- Indisponibilidad de Ollama.
- Respuestas inválidas del agente.
- Problemas de persistencia.

Los incidentes deben revisarse antes de continuar
cuando el supervisor exige recuperación.

## 5. Estados operativos

| Estado | Significado |
|---|---|
| ACTIVE | Cartera autorizada para operar bajo controles |
| PAUSED | Cartera pausada |
| STOPPED | Cartera detenida por paro de emergencia |

La activación no garantiza una compra ni una venta.

También deben cumplirse las restricciones temporales,
financieras y de recuperación.

## 6. Ejecutar un ciclo manual

Desde la sección Agente IA:

1. Comprobar que el sistema funciona en Paper Trading.
2. Revisar los incidentes y el estado de riesgo.
3. Autorizar la activación de la cartera mediante
   el control correspondiente.
4. Solicitar un ciclo manual y confirmar la acción.
5. Consultar el resultado y el historial de decisiones.
6. Revisar las órdenes y el patrimonio, si corresponde.

No ejecutar ciclos utilizando datos vencidos.

La ventana de inicio programada es distinta de los
controles de antigüedad aplicados a un ciclo manual.

Si una vela ya fue procesada, el sistema debe evitar
duplicar la operación correspondiente.

## 7. Automatización diaria

FinanceAI utiliza launchd, el programador de macOS.

| Parámetro | Configuración |
|---|---|
| Frecuencia | Diaria |
| Horario local de referencia | 18:05 |
| Horario UTC | 00:05 |
| Ventana de inicio UTC | 00:05–00:45 |
| Intentos automáticos diarios | Máximo uno |

El horario local supone una zona UTC-6.

El panel Automatización diaria permite conocer:

- Si el servicio está instalado y cargado.
- El estado de la cartera.
- La siguiente ejecución programada.
- El último intento registrado.
- El resultado del supervisor.
- Los registros pendientes de revisión.

El servicio puede estar habilitado aunque la
cartera permanezca pausada.

Para consultar su estado mediante Terminal:

```bash
python -m backend.scheduler_state
```

Para verificar el ejecutor sin realizar operaciones:

```bash
python -m backend.run_scheduled_agent --check
```

La Mac debe estar disponible, con la sesión
correspondiente y conexión a internet.

La aplicación no funciona como un servicio en la nube.

## 8. Pausa y paro de emergencia

### Pausar el agente

Utilizar el control de pausa disponible en la
sección Agente IA.

La pausa impide nuevas operaciones autorizadas.
No liquida automáticamente posiciones existentes.

### Paro de emergencia

Utilizar el control de parada de emergencia cuando
se necesite bloquear la operación financiera.

El paro impide nuevas compras y ventas.

Restablecer el paro de emergencia requiere
una revisión explícita.

El restablecimiento devuelve la cartera al estado
pausado; no inicia automáticamente un ciclo.

## 9. Recuperación de incidentes

1. Consultar los incidentes pendientes.
2. Identificar y corregir la causa del problema.
3. Revisar las operaciones y el estado persistido.
4. Documentar el motivo de recuperación.
5. Utilizar los controles autorizados de recuperación.

La recuperación puede permitir nuevamente la operación
de la cartera. Debe revisarse el estado resultante.

No eliminar registros financieros para intentar
resolver un error.

### Recuperar un intento del programador

Si existe un intento interrumpido o fallido:

1. Comprobar que no hay un proceso activo.
2. Pausar la cartera.
3. Resolver los incidentes pendientes.
4. Comprobar que no hay ciclos incompletos.
5. Revisar el registro del intento.

Ejemplo de revisión autorizada:

```bash
python -m backend.scheduler_state   --review AAAA-MM-DD   --reason "Motivo documentado de la revisión"   --confirm PAPER_ONLY
```

Sustituir AAAA-MM-DD por la fecha UTC del registro.

La revisión conserva el intento original y no
permite repetir automáticamente ese mismo día.

Los registros corruptos requieren revisión técnica.

## 10. Solución de problemas

| Problema | Acción recomendada |
|---|---|
| Dashboard no disponible | Verificar que los servidores estén iniciados |
| Puerto ocupado | Identificar el proceso que utiliza el puerto |
| Datos obsoletos | Esperar datos válidos y revisar la sincronización |
| Ollama no disponible | Revisar instalación, modelo y puerto local |
| Puerto 11434 ocupado | Identificar el servidor antes de detenerlo |
| Cartera pausada | Revisar los controles antes de autorizarla |
| Incidente pendiente | Corregir la causa y realizar recuperación |
| Ciclo duplicado | Consultar el registro existente |
| Programador deshabilitado | Revisar instalación y estado de launchd |

No eliminar la base de datos principal ni modificar
el modelo para solucionar estos problemas.

## 11. Consultar los resultados históricos

Las evidencias comparativas se encuentran en:

- `replay/comparacion_final.csv`
- `replay/metricas_comparativas_finales.json`
- `replay/series_comparativas_diarias.csv`
- `replay/liquidaciones_finales.csv`
- `replay/figuras/`

El experimento histórico contiene 90 ciclos:
30 por cada estrategia evaluada.

Estas carteras son independientes de la cartera
principal utilizada con información actualizada.

## 12. Cerrar FinanceAI

Para cerrar el dashboard:

1. Cerrar la página del navegador.
2. Presionar Control+C en la Terminal del dashboard.

Si se desea impedir nuevas operaciones del agente,
primero debe pausarse la cartera.

Cerrar el navegador o detener los servidores HTTP
no deshabilita por sí mismo launchd.

## 13. Estado al momento de la auditoría

- 450 pruebas automatizadas aprobadas.
- 10 escenarios adversos verificados.
- 20 controles de autenticación aprobados.
- 90 ciclos históricos completados.
- 30 inferencias válidas de Qwen3.
- Programador instalado y cargado.
- Cartera principal pausada.
- Capital principal de 50,000 USDT virtuales.
- Primer ciclo automático con mercado actualizado pendiente.

## 14. Advertencia académica

FinanceAI es una herramienta experimental y educativa.

No utiliza dinero real ni constituye asesoramiento
financiero.

Los pronósticos y resultados históricos no garantizan
rendimientos futuros.
