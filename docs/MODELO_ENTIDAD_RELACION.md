# Modelo entidad-relación — FinanceAI

El siguiente diagrama se genera automáticamente a partir
de las tablas, llaves e índices del esquema principal.

Las cardinalidades se deducen de las restricciones
de nulabilidad y unicidad declaradas en SQLite.

```mermaid
erDiagram
    agent_cycles {
        INTEGER id PK
        INTEGER portfolio_id FK
        INTEGER candle_id FK
        INTEGER prediction_id FK
        INTEGER risk_config_id FK
        TEXT status
        INTEGER attempts
        INTEGER started_at
        INTEGER finished_at
        INTEGER created_at
    }
    agent_decisions {
        INTEGER id PK
        INTEGER cycle_id FK, UK
        TEXT proposed_action
        TEXT authorized_action
        TEXT rationale
        TEXT llm_model
        TEXT llm_response
        INTEGER risk_approved
        TEXT risk_reason
        REAL latency_ms
        INTEGER created_at
    }
    assets {
        INTEGER id PK
        TEXT symbol UK
        TEXT base_currency
        TEXT quote_currency
        TEXT exchange
        INTEGER active
    }
    candles {
        INTEGER id PK
        INTEGER asset_id FK
        INTEGER interval_seconds
        INTEGER open_time
        INTEGER close_time
        REAL open
        REAL high
        REAL low
        REAL close
        REAL volume
        REAL quote_volume
        TEXT source
        INTEGER created_at
    }
    equity_history {
        INTEGER id PK
        INTEGER cycle_id FK
        TEXT snapshot_type
        INTEGER cash_micros
        INTEGER position_value_micros
        INTEGER equity_micros
        REAL drawdown
        INTEGER recorded_at
    }
    error_logs {
        INTEGER id PK
        INTEGER cycle_id FK
        TEXT component
        TEXT error_type
        TEXT message
        TEXT cause
        TEXT corrective_action
        INTEGER retry_count
        INTEGER resolved
        INTEGER created_at
        INTEGER resolved_at
    }
    model_versions {
        TEXT version PK
        TEXT architecture
        INTEGER window_size
        INTEGER feature_count
        TEXT model_path
        TEXT model_sha256
        INTEGER created_at
    }
    orders {
        INTEGER id PK
        INTEGER decision_id FK, UK
        TEXT side
        TEXT status
        INTEGER quantity_sats
        INTEGER price_micros
        INTEGER notional_micros
        INTEGER fee_micros
        INTEGER slippage_micros
        TEXT execution_source
        INTEGER filled_at
        INTEGER created_at
    }
    portfolio {
        INTEGER id PK
        TEXT name UK
        TEXT mode
        TEXT strategy
        TEXT currency
        INTEGER initial_cash_micros
        INTEGER cash_micros
        TEXT status
        INTEGER created_at
        INTEGER updated_at
    }
    positions {
        INTEGER id PK
        INTEGER portfolio_id FK
        INTEGER asset_id FK
        INTEGER quantity_sats
        INTEGER cost_basis_micros
        INTEGER updated_at
    }
    predictions {
        INTEGER id PK
        INTEGER candle_id FK
        TEXT model_version FK
        REAL predicted_return
        REAL predicted_price
        INTEGER emission_time
        INTEGER target_open_time
        INTEGER target_close_time
        REAL inference_ms
        INTEGER created_at
    }
    risk_config {
        INTEGER id PK
        INTEGER portfolio_id FK
        INTEGER version
        INTEGER max_exposure_bps
        INTEGER max_daily_loss_bps
        INTEGER max_data_age_seconds
        INTEGER min_order_micros
        INTEGER fee_bps
        INTEGER slippage_bps
        REAL prediction_threshold
        INTEGER emergency_stop
        INTEGER created_at
    }
    system_logs {
        INTEGER id PK
        INTEGER cycle_id FK
        TEXT level
        TEXT component
        TEXT message
        INTEGER created_at
    }
    risk_config ||..o{ agent_cycles : "risk_config_id, portfolio_id"
    predictions |o..o{ agent_cycles : "prediction_id, candle_id"
    candles ||..o{ agent_cycles : "candle_id"
    portfolio ||..o{ agent_cycles : "portfolio_id"
    agent_cycles ||..o| agent_decisions : "cycle_id"
    assets ||..o{ candles : "asset_id"
    agent_cycles ||..o{ equity_history : "cycle_id"
    agent_cycles |o..o{ error_logs : "cycle_id"
    agent_decisions ||..o| orders : "decision_id"
    assets ||..o{ positions : "asset_id"
    portfolio ||..o{ positions : "portfolio_id"
    model_versions ||..o{ predictions : "model_version"
    candles ||..o{ predictions : "candle_id"
    portfolio ||..o{ risk_config : "portfolio_id"
    agent_cycles |o..o{ system_logs : "cycle_id"
```

## Convenciones

- PK: llave primaria.
- FK: llave foránea.
- UK: restricción individual de unicidad.
- Las relaciones identificadoras se representan con línea continua.
- Las relaciones no identificadoras utilizan línea discontinua.
- Las restricciones UNIQUE compuestas se detallan en el
  diccionario de datos y en el esquema SQL.

La representación de cardinalidades corresponde a las
restricciones declaradas en la base de datos; no incluye
reglas adicionales de negocio implementadas en Python.
