# Diccionario de datos — FinanceAI

## 1. Información general

| Parámetro | Valor |
|---|---|
| Motor | SQLite |
| Versión verificada | 3.54.1 |
| Versión del esquema | 1 |
| Tablas principales | 13 |
| Columnas | 122 |
| Llaves foráneas | 15 |
| Índices totales | 18 |
| Índices explícitos | 5 |

Los metadatos se extrajeron directamente de SQLite mediante
consultas de solo lectura.

## 2. Convenciones

- Las cantidades monetarias con sufijo `_micros` se expresan
  en microunidades de USDT: 1 USDT equivale a 1,000,000.
- Las cantidades con sufijo `_sats` se expresan en satoshis:
  1 BTC equivale a 100,000,000.
- Los puntos base representan centésimas de porcentaje:
  100 puntos base equivalen al 1%.
- Los campos temporales enteros utilizan segundos Unix UTC.
- Los rendimientos decimales se multiplican por 100 para
  expresarlos como porcentajes.
- Los valores CHECK, UNIQUE y las restricciones compuestas
  se conservan en las definiciones SQL originales.

## 3. Clasificación de entidades

### Mercado y prediccion

- `assets`: Catálogo de activos financieros.
- `candles`: Velas OHLCV históricas y actualizadas.
- `model_versions`: Registro de versiones del modelo predictivo.
- `predictions`: Pronósticos financieros asociados a velas.

### Administracion financiera

- `portfolio`: Carteras financieras virtuales.
- `positions`: Posiciones y costos de adquisición.
- `risk_config`: Configuraciones versionadas de riesgo.
- `orders`: Órdenes financieras simuladas.
- `equity_history`: Valoraciones históricas del patrimonio.

### Agente de inteligencia artificial

- `agent_cycles`: Ciclos operativos del agente.
- `agent_decisions`: Propuestas y acciones autorizadas.

### Auditoria

- `system_logs`: Eventos operativos del sistema.
- `error_logs`: Incidentes y acciones correctivas.

## 4. Definición de las tablas

### 4.1. `agent_cycles`

Ciclos operativos del agente.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 0.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `portfolio_id` | INTEGER | Sí | — | risk_config.portfolio_id, portfolio.id | — | Referencia a la cartera. |
| `candle_id` | INTEGER | Sí | — | predictions.candle_id, candles.id | — | Referencia a la vela de mercado. |
| `prediction_id` | INTEGER | No | — | predictions.id | — | Referencia al pronóstico. |
| `risk_config_id` | INTEGER | Sí | — | risk_config.id | — | Referencia a la configuración de riesgo. |
| `status` | TEXT | Sí | — | — | 'PENDING' | Estado de la entidad. |
| `attempts` | INTEGER | Sí | — | — | 0 | Número de intentos registrados. |
| `started_at` | INTEGER | No | — | — | — | Instante de inicio. |
| `finished_at` | INTEGER | No | — | — | — | Instante de finalización. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |

**Relaciones referenciales**

- `(risk_config_id, portfolio_id)` → `risk_config` `(id, portfolio_id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.
- `(prediction_id, candle_id)` → `predictions` `(id, candle_id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.
- `(candle_id)` → `candles` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.
- `(portfolio_id)` → `portfolio` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `idx_cycles_status`: (status). Único: No. Parcial: No.

```sql
CREATE INDEX idx_cycles_status
ON agent_cycles(status)
```

- `sqlite_autoindex_agent_cycles_1`: (portfolio_id, candle_id). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE agent_cycles (
    id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolio(id),
    candle_id INTEGER NOT NULL REFERENCES candles(id),
    prediction_id INTEGER,
    risk_config_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN (
            'PENDING', 'RUNNING', 'WAITING_EXECUTION',
            'COMPLETED', 'REJECTED', 'PAUSED', 'ERROR'
        )),
    attempts INTEGER NOT NULL DEFAULT 0
        CHECK (attempts >= 0),
    started_at INTEGER,
    finished_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    FOREIGN KEY (prediction_id, candle_id)
        REFERENCES predictions(id, candle_id),
    FOREIGN KEY (risk_config_id, portfolio_id)
        REFERENCES risk_config(id, portfolio_id),
    UNIQUE (portfolio_id, candle_id)
) STRICT;
```

### 4.2. `agent_decisions`

Propuestas y acciones autorizadas.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 0.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `cycle_id` | INTEGER | Sí | — | agent_cycles.id | — | Referencia al ciclo operativo. |
| `proposed_action` | TEXT | Sí | — | — | — | Acción propuesta. |
| `authorized_action` | TEXT | Sí | — | — | — | Acción autorizada. |
| `rationale` | TEXT | Sí | — | — | — | Justificación de la propuesta. |
| `llm_model` | TEXT | No | — | — | — | Modelo de lenguaje utilizado. |
| `llm_response` | TEXT | No | — | — | — | Respuesta registrada del modelo de lenguaje. |
| `risk_approved` | INTEGER | Sí | — | — | — | Resultado de la autorización de riesgo. |
| `risk_reason` | TEXT | No | — | — | — | Motivo de la decisión de riesgo. |
| `latency_ms` | REAL | No | — | — | — | Latencia registrada en milisegundos. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |

**Relaciones referenciales**

- `(cycle_id)` → `agent_cycles` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `sqlite_autoindex_agent_decisions_1`: (cycle_id). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE agent_decisions (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER NOT NULL UNIQUE REFERENCES agent_cycles(id),
    proposed_action TEXT NOT NULL
        CHECK (proposed_action IN ('BUY', 'HOLD', 'SELL')),
    authorized_action TEXT NOT NULL
        CHECK (authorized_action IN ('BUY', 'HOLD', 'SELL')),
    rationale TEXT NOT NULL,
    llm_model TEXT,
    llm_response TEXT,
    risk_approved INTEGER NOT NULL
        CHECK (risk_approved IN (0, 1)),
    risk_reason TEXT,
    latency_ms REAL CHECK (latency_ms >= 0),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (risk_approved = 1 OR authorized_action = 'HOLD')
) STRICT;
```

### 4.3. `assets`

Catálogo de activos financieros.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 1.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `symbol` | TEXT | Sí | — | — | — | Símbolo del activo. |
| `base_currency` | TEXT | Sí | — | — | — | Moneda base. |
| `quote_currency` | TEXT | Sí | — | — | — | Moneda de cotización. |
| `exchange` | TEXT | Sí | — | — | — | Fuente o mercado de intercambio. |
| `active` | INTEGER | Sí | — | — | 1 | Indicador de disponibilidad del activo. |

**Relaciones referenciales**

No contiene llaves foráneas.

**Índices y restricciones de unicidad**

- `sqlite_autoindex_assets_1`: (symbol). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE assets (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    exchange TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
        CHECK (active IN (0, 1))
) STRICT;
```

### 4.4. `candles`

Velas OHLCV históricas y actualizadas.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 2521.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `asset_id` | INTEGER | Sí | — | assets.id | — | Referencia al activo financiero. |
| `interval_seconds` | INTEGER | Sí | — | — | 86400 | Duración de la vela en segundos. |
| `open_time` | INTEGER | Sí | — | — | — | Inicio del intervalo de mercado. |
| `close_time` | INTEGER | Sí | — | — | — | Fin del intervalo de mercado. |
| `open` | REAL | Sí | — | — | — | Precio de apertura. |
| `high` | REAL | Sí | — | — | — | Precio máximo. |
| `low` | REAL | Sí | — | — | — | Precio mínimo. |
| `close` | REAL | Sí | — | — | — | Precio de cierre. |
| `volume` | REAL | Sí | — | — | — | Volumen negociado. |
| `quote_volume` | REAL | No | — | — | — | Volumen en moneda de cotización. |
| `source` | TEXT | Sí | — | — | — | Origen de los datos. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |

**Relaciones referenciales**

- `(asset_id)` → `assets` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `sqlite_autoindex_candles_1`: (asset_id, interval_seconds, open_time). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE candles (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    interval_seconds INTEGER NOT NULL DEFAULT 86400
        CHECK (interval_seconds = 86400),
    open_time INTEGER NOT NULL,
    close_time INTEGER NOT NULL,
    open REAL NOT NULL CHECK (open > 0),
    high REAL NOT NULL CHECK (high > 0),
    low REAL NOT NULL CHECK (low > 0),
    close REAL NOT NULL CHECK (close > 0),
    volume REAL NOT NULL CHECK (volume >= 0),
    quote_volume REAL CHECK (quote_volume >= 0),
    source TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (close_time = open_time + interval_seconds),
    CHECK (open_time % interval_seconds = 0),
    CHECK (high >= max(open, close, low)),
    CHECK (low <= min(open, close, high)),
    UNIQUE (asset_id, interval_seconds, open_time)
) STRICT;
```

### 4.5. `equity_history`

Valoraciones históricas del patrimonio.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 0.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `cycle_id` | INTEGER | Sí | — | agent_cycles.id | — | Referencia al ciclo operativo. |
| `snapshot_type` | TEXT | Sí | — | — | — | Tipo de valoración patrimonial. |
| `cash_micros` | INTEGER | Sí | — | — | — | Efectivo en microunidades de USDT. |
| `position_value_micros` | INTEGER | Sí | — | — | — | Valor de la posición en microunidades. |
| `equity_micros` | INTEGER | Sí | — | — | — | Patrimonio total en microunidades. |
| `drawdown` | REAL | Sí | — | — | — | Caída relativa desde un máximo previo. |
| `recorded_at` | INTEGER | Sí | — | — | — | Instante asociado al registro. |

**Relaciones referenciales**

- `(cycle_id)` → `agent_cycles` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `idx_equity_time`: (recorded_at). Único: No. Parcial: No.

```sql
CREATE INDEX idx_equity_time
ON equity_history(recorded_at)
```

- `sqlite_autoindex_equity_history_1`: (cycle_id, snapshot_type). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE equity_history (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER NOT NULL REFERENCES agent_cycles(id),
    snapshot_type TEXT NOT NULL
        CHECK (snapshot_type IN ('EXECUTION', 'VALUATION')),
    cash_micros INTEGER NOT NULL CHECK (cash_micros >= 0),
    position_value_micros INTEGER NOT NULL
        CHECK (position_value_micros >= 0),
    equity_micros INTEGER NOT NULL CHECK (equity_micros >= 0),
    drawdown REAL NOT NULL CHECK (drawdown BETWEEN 0 AND 1),
    recorded_at INTEGER NOT NULL,
    CHECK (equity_micros = cash_micros + position_value_micros),
    UNIQUE (cycle_id, snapshot_type)
) STRICT;
```

### 4.6. `error_logs`

Incidentes y acciones correctivas.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 0.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `cycle_id` | INTEGER | No | — | agent_cycles.id | — | Referencia al ciclo operativo. |
| `component` | TEXT | Sí | — | — | — | Componente responsable. |
| `error_type` | TEXT | Sí | — | — | — | Clasificación del error. |
| `message` | TEXT | Sí | — | — | — | Descripción del evento o incidente. |
| `cause` | TEXT | No | — | — | — | Causa registrada del incidente. |
| `corrective_action` | TEXT | No | — | — | — | Acción correctiva documentada. |
| `retry_count` | INTEGER | Sí | — | — | 0 | Cantidad de reintentos. |
| `resolved` | INTEGER | Sí | — | — | 0 | Indicador de resolución del incidente. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |
| `resolved_at` | INTEGER | No | — | — | — | Instante de resolución. |

**Relaciones referenciales**

- `(cycle_id)` → `agent_cycles` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `idx_error_logs_resolved`: (resolved). Único: No. Parcial: No.

```sql
CREATE INDEX idx_error_logs_resolved
ON error_logs(resolved)
```


**Definición SQL completa**

```sql
CREATE TABLE error_logs (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER REFERENCES agent_cycles(id),
    component TEXT NOT NULL,
    error_type TEXT NOT NULL,
    message TEXT NOT NULL,
    cause TEXT,
    corrective_action TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0
        CHECK (retry_count >= 0),
    resolved INTEGER NOT NULL DEFAULT 0
        CHECK (resolved IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    resolved_at INTEGER
) STRICT;
```

### 4.7. `model_versions`

Registro de versiones del modelo predictivo.

- Tabla STRICT: Sí.
- Llave primaria: `version`.
- Registros al documentar: 1.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `version` | TEXT | Sí | 1 | — | — | Identificador o versión de la configuración. |
| `architecture` | TEXT | Sí | — | — | — | Arquitectura del modelo. |
| `window_size` | INTEGER | Sí | — | — | — | Longitud de la ventana de entrada. |
| `feature_count` | INTEGER | Sí | — | — | — | Cantidad de variables de entrada. |
| `model_path` | TEXT | Sí | — | — | — | Ubicación del artefacto del modelo. |
| `model_sha256` | TEXT | Sí | — | — | — | Huella de integridad del modelo. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |

**Relaciones referenciales**

No contiene llaves foráneas.

**Índices y restricciones de unicidad**

- `sqlite_autoindex_model_versions_1`: (version). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE model_versions (
    version TEXT PRIMARY KEY,
    architecture TEXT NOT NULL,
    window_size INTEGER NOT NULL CHECK (window_size > 0),
    feature_count INTEGER NOT NULL CHECK (feature_count > 0),
    model_path TEXT NOT NULL,
    model_sha256 TEXT NOT NULL CHECK (length(model_sha256) = 64),
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;
```

### 4.8. `orders`

Órdenes financieras simuladas.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 0.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `decision_id` | INTEGER | Sí | — | agent_decisions.id | — | Referencia a la decisión del agente. |
| `side` | TEXT | Sí | — | — | — | Sentido de la orden: compra o venta. |
| `status` | TEXT | Sí | — | — | 'PENDING' | Estado de la entidad. |
| `quantity_sats` | INTEGER | Sí | — | — | — | Cantidad de Bitcoin en satoshis. |
| `price_micros` | INTEGER | No | — | — | — | Precio en microunidades de USDT. |
| `notional_micros` | INTEGER | No | — | — | — | Importe nominal de la operación. |
| `fee_micros` | INTEGER | Sí | — | — | 0 | Comisión en microunidades de USDT. |
| `slippage_micros` | INTEGER | Sí | — | — | 0 | Deslizamiento en microunidades de USDT. |
| `execution_source` | TEXT | No | — | — | — | Fuente de la ejecución simulada. |
| `filled_at` | INTEGER | No | — | — | — | Instante de ejecución de la orden. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |

**Relaciones referenciales**

- `(decision_id)` → `agent_decisions` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `idx_orders_status`: (status). Único: No. Parcial: No.

```sql
CREATE INDEX idx_orders_status
ON orders(status)
```

- `sqlite_autoindex_orders_1`: (decision_id). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    decision_id INTEGER NOT NULL UNIQUE
        REFERENCES agent_decisions(id),
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN (
            'PENDING', 'FILLED', 'REJECTED', 'CANCELLED'
        )),
    quantity_sats INTEGER NOT NULL CHECK (quantity_sats > 0),
    price_micros INTEGER CHECK (price_micros > 0),
    notional_micros INTEGER CHECK (notional_micros > 0),
    fee_micros INTEGER NOT NULL DEFAULT 0
        CHECK (fee_micros >= 0),
    slippage_micros INTEGER NOT NULL DEFAULT 0
        CHECK (slippage_micros >= 0),
    execution_source TEXT,
    filled_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (
        status != 'FILLED'
        OR (
            price_micros IS NOT NULL
            AND notional_micros IS NOT NULL
            AND filled_at IS NOT NULL
            AND execution_source IS NOT NULL
        )
    )
) STRICT;
```

### 4.9. `portfolio`

Carteras financieras virtuales.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 1.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `name` | TEXT | Sí | — | — | — | Nombre de la entidad. |
| `mode` | TEXT | Sí | — | — | — | Modalidad de simulación financiera. |
| `strategy` | TEXT | Sí | — | — | — | Estrategia asociada a la cartera. |
| `currency` | TEXT | Sí | — | — | 'USDT' | Moneda de la cartera. |
| `initial_cash_micros` | INTEGER | Sí | — | — | — | Capital inicial en microunidades de USDT. |
| `cash_micros` | INTEGER | Sí | — | — | — | Efectivo en microunidades de USDT. |
| `status` | TEXT | Sí | — | — | 'PAUSED' | Estado de la entidad. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |
| `updated_at` | INTEGER | Sí | — | — | unixepoch() | Instante de actualización del registro. |

**Relaciones referenciales**

No contiene llaves foráneas.

**Índices y restricciones de unicidad**

- `sqlite_autoindex_portfolio_1`: (name). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE portfolio (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL
        CHECK (mode IN ('PAPER_LIVE', 'REPLAY')),
    strategy TEXT NOT NULL
        CHECK (strategy IN ('LLM', 'MODEL_ONLY', 'BUY_HOLD')),
    currency TEXT NOT NULL DEFAULT 'USDT',
    initial_cash_micros INTEGER NOT NULL
        CHECK (initial_cash_micros > 0),
    cash_micros INTEGER NOT NULL CHECK (cash_micros >= 0),
    status TEXT NOT NULL DEFAULT 'PAUSED'
        CHECK (status IN ('ACTIVE', 'PAUSED', 'STOPPED')),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;
```

### 4.10. `positions`

Posiciones y costos de adquisición.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 1.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `portfolio_id` | INTEGER | Sí | — | portfolio.id | — | Referencia a la cartera. |
| `asset_id` | INTEGER | Sí | — | assets.id | — | Referencia al activo financiero. |
| `quantity_sats` | INTEGER | Sí | — | — | 0 | Cantidad de Bitcoin en satoshis. |
| `cost_basis_micros` | INTEGER | Sí | — | — | 0 | Costo de adquisición en microunidades de USDT. |
| `updated_at` | INTEGER | Sí | — | — | unixepoch() | Instante de actualización del registro. |

**Relaciones referenciales**

- `(asset_id)` → `assets` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.
- `(portfolio_id)` → `portfolio` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `sqlite_autoindex_positions_1`: (portfolio_id, asset_id). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE positions (
    id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolio(id),
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    quantity_sats INTEGER NOT NULL DEFAULT 0
        CHECK (quantity_sats >= 0),
    cost_basis_micros INTEGER NOT NULL DEFAULT 0
        CHECK (cost_basis_micros >= 0),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (portfolio_id, asset_id)
) STRICT;
```

### 4.11. `predictions`

Pronósticos financieros asociados a velas.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 1.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `candle_id` | INTEGER | Sí | — | candles.id | — | Referencia a la vela de mercado. |
| `model_version` | TEXT | Sí | — | model_versions.version | — | Versión del modelo predictivo. |
| `predicted_return` | REAL | Sí | — | — | — | Rendimiento pronosticado en escala decimal. |
| `predicted_price` | REAL | Sí | — | — | — | Precio pronosticado. |
| `emission_time` | INTEGER | Sí | — | — | — | Instante nominal de emisión del pronóstico. |
| `target_open_time` | INTEGER | Sí | — | — | — | Inicio del periodo pronosticado. |
| `target_close_time` | INTEGER | Sí | — | — | — | Fin del periodo pronosticado. |
| `inference_ms` | REAL | No | — | — | — | Tiempo de inferencia en milisegundos. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |

**Relaciones referenciales**

- `(model_version)` → `model_versions` `(version)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.
- `(candle_id)` → `candles` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `sqlite_autoindex_predictions_2`: (id, candle_id). Único: Sí. Parcial: No.
- `sqlite_autoindex_predictions_1`: (candle_id, model_version). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE predictions (
    id INTEGER PRIMARY KEY,
    candle_id INTEGER NOT NULL REFERENCES candles(id),
    model_version TEXT NOT NULL
        REFERENCES model_versions(version),
    predicted_return REAL NOT NULL,
    predicted_price REAL NOT NULL CHECK (predicted_price > 0),
    emission_time INTEGER NOT NULL,
    target_open_time INTEGER NOT NULL,
    target_close_time INTEGER NOT NULL,
    inference_ms REAL CHECK (inference_ms >= 0),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (target_close_time = target_open_time + 86400),
    CHECK (emission_time = target_open_time),
    UNIQUE (candle_id, model_version),
    UNIQUE (id, candle_id)
) STRICT;
```

### 4.12. `risk_config`

Configuraciones versionadas de riesgo.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 1.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `portfolio_id` | INTEGER | Sí | — | portfolio.id | — | Referencia a la cartera. |
| `version` | INTEGER | Sí | — | — | — | Identificador o versión de la configuración. |
| `max_exposure_bps` | INTEGER | Sí | — | — | — | Límite de exposición para compras, en puntos base. |
| `max_daily_loss_bps` | INTEGER | Sí | — | — | — | Límite diario de pérdida para compras, en puntos base. |
| `max_data_age_seconds` | INTEGER | Sí | — | — | — | Antigüedad máxima de datos en segundos. |
| `min_order_micros` | INTEGER | Sí | — | — | — | Importe mínimo de orden en microunidades. |
| `fee_bps` | INTEGER | Sí | — | — | — | Comisión en puntos base. |
| `slippage_bps` | INTEGER | Sí | — | — | — | Deslizamiento en puntos base. |
| `prediction_threshold` | REAL | Sí | — | — | — | Umbral de la estrategia cuantitativa. |
| `emergency_stop` | INTEGER | Sí | — | — | 0 | Indicador de paro de emergencia. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |

**Relaciones referenciales**

- `(portfolio_id)` → `portfolio` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `sqlite_autoindex_risk_config_2`: (id, portfolio_id). Único: Sí. Parcial: No.
- `sqlite_autoindex_risk_config_1`: (portfolio_id, version). Único: Sí. Parcial: No.

**Definición SQL completa**

```sql
CREATE TABLE risk_config (
    id INTEGER PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolio(id),
    version INTEGER NOT NULL CHECK (version > 0),
    max_exposure_bps INTEGER NOT NULL
        CHECK (max_exposure_bps BETWEEN 0 AND 10000),
    max_daily_loss_bps INTEGER NOT NULL
        CHECK (max_daily_loss_bps BETWEEN 0 AND 10000),
    max_data_age_seconds INTEGER NOT NULL
        CHECK (max_data_age_seconds > 0),
    min_order_micros INTEGER NOT NULL
        CHECK (min_order_micros > 0),
    fee_bps INTEGER NOT NULL
        CHECK (fee_bps BETWEEN 0 AND 10000),
    slippage_bps INTEGER NOT NULL
        CHECK (slippage_bps BETWEEN 0 AND 10000),
    prediction_threshold REAL NOT NULL
        CHECK (prediction_threshold > 0),
    emergency_stop INTEGER NOT NULL DEFAULT 0
        CHECK (emergency_stop IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (portfolio_id, version),
    UNIQUE (id, portfolio_id)
) STRICT;
```

### 4.13. `system_logs`

Eventos operativos del sistema.

- Tabla STRICT: Sí.
- Llave primaria: `id`.
- Registros al documentar: 2.

| Columna | Tipo | NOT NULL | PK | FK | Predeterminado | Descripción |
|---|---|---|---|---|---|---|
| `id` | INTEGER | No | 1 | — | — | Identificador del registro. |
| `cycle_id` | INTEGER | No | — | agent_cycles.id | — | Referencia al ciclo operativo. |
| `level` | TEXT | Sí | — | — | — | Nivel del evento. |
| `component` | TEXT | Sí | — | — | — | Componente responsable. |
| `message` | TEXT | Sí | — | — | — | Descripción del evento o incidente. |
| `created_at` | INTEGER | Sí | — | — | unixepoch() | Instante de creación del registro. |

**Relaciones referenciales**

- `(cycle_id)` → `agent_cycles` `(id)`. ON DELETE: `NO ACTION`. ON UPDATE: `NO ACTION`.

**Índices y restricciones de unicidad**

- `idx_system_logs_time`: (created_at). Único: No. Parcial: No.

```sql
CREATE INDEX idx_system_logs_time
ON system_logs(created_at)
```


**Definición SQL completa**

```sql
CREATE TABLE system_logs (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER REFERENCES agent_cycles(id),
    level TEXT NOT NULL
        CHECK (level IN ('INFO', 'WARNING', 'ERROR')),
    component TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;
```

## 5. Notas sobre restricciones

La columna NOT NULL refleja el indicador reportado por
SQLite. Las llaves primarias también tienen reglas propias
de integridad, aunque dicho indicador sea cero.

Las llaves foráneas compuestas se documentan como una sola
restricción, conservando el orden de sus columnas.

La base principal contiene 13 tablas. La copia histórica
finalizada incluye adicionalmente `replay_liquidations`,
sin modificar el esquema operativo principal.

Los conteos de registros corresponden al momento de generar
este documento y no representan valores permanentes.
