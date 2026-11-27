# Referencia de la API de FinanceAI

## 1. Información general

La presente referencia se genera a partir del esquema
OpenAPI de la implementación real de FastAPI.

Dirección local:

`http://127.0.0.1:8000`

Documentación interactiva:

`http://127.0.0.1:8000/docs`

## 2. Autenticación

Las rutas protegidas utilizan la cabecera:

```http
X-API-Key: <CLAVE_LOCAL>
```

La clave se configura exclusivamente en el entorno local.

No debe incluirse en el código frontend, repositorios,
documentación pública ni capturas de pantalla.

## 3. Inventario de endpoints

| Método | Ruta | Operación |
|---|---|---|
| GET | `/` | Root |
| POST | `/api/v1/agent/control/{action}` | Control Endpoint |
| GET | `/api/v1/agent/decisions` | Agent Decisions |
| GET | `/api/v1/agent/recovery/status` | Recovery Endpoint |
| POST | `/api/v1/agent/recovery/{action}` | Recovery Action |
| GET | `/api/v1/agent/status` | Agent Status |
| GET | `/api/v1/database/status` | Get Database Status |
| GET | `/api/v1/incidents/history` | Incidents Endpoint |
| GET | `/api/v1/market/assets` | Get Assets |
| GET | `/api/v1/market/candles` | Get Candles |
| GET | `/api/v1/market/latest` | Get Latest |
| GET | `/api/v1/model/status` | Model Status |
| GET | `/api/v1/orders/history` | Orders Endpoint |
| GET | `/api/v1/portfolio` | Get Portfolio |
| GET | `/api/v1/portfolio/overview` | Overview Endpoint |
| POST | `/api/v1/predictions/generate` | Create Prediction |
| GET | `/api/v1/predictions/history` | History Endpoint |
| GET | `/api/v1/predictions/latest` | Get Latest Prediction |
| GET | `/api/v1/risk/config` | Get Risk Config |
| GET | `/api/v1/risk/overview` | Risk Endpoint |
| GET | `/api/v1/status` | System Status |
| GET | `/health` | Health |

## 4. Especificación individual

### GET `/`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### POST `/api/v1/agent/control/{action}`

| Parámetro | Ubicación | Tipo | Obligatorio |
|---|---|---|---|
| `action` | path | string | Sí |

**Esquema del cuerpo de solicitud:**

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Confirmation"
      }
    }
  }
}
```

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response
- `422`: Validation Error

### GET `/api/v1/agent/decisions`

| Parámetro | Ubicación | Tipo | Obligatorio |
|---|---|---|---|
| `limit` | query | integer | No |
| `offset` | query | integer | No |

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response
- `422`: Validation Error

### GET `/api/v1/agent/recovery/status`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### POST `/api/v1/agent/recovery/{action}`

| Parámetro | Ubicación | Tipo | Obligatorio |
|---|---|---|---|
| `action` | path | string | Sí |

**Esquema del cuerpo de solicitud:**

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RecoveryBody"
      }
    }
  }
}
```

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response
- `422`: Validation Error

### GET `/api/v1/agent/status`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/api/v1/database/status`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/api/v1/incidents/history`

| Parámetro | Ubicación | Tipo | Obligatorio |
|---|---|---|---|
| `limit` | query | integer | No |
| `offset` | query | integer | No |
| `status` | query | string | No |

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response
- `422`: Validation Error

### GET `/api/v1/market/assets`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/api/v1/market/candles`

| Parámetro | Ubicación | Tipo | Obligatorio |
|---|---|---|---|
| `symbol` | query | string | No |
| `limit` | query | integer | No |
| `offset` | query | integer | No |
| `start_date` | query | Consultar esquema OpenAPI | No |
| `end_date` | query | Consultar esquema OpenAPI | No |

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response
- `422`: Validation Error

### GET `/api/v1/market/latest`

| Parámetro | Ubicación | Tipo | Obligatorio |
|---|---|---|---|
| `symbol` | query | string | No |

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response
- `422`: Validation Error

### GET `/api/v1/model/status`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/api/v1/orders/history`

| Parámetro | Ubicación | Tipo | Obligatorio |
|---|---|---|---|
| `limit` | query | integer | No |
| `offset` | query | integer | No |
| `side` | query | Consultar esquema OpenAPI | No |
| `status` | query | Consultar esquema OpenAPI | No |

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response
- `422`: Validation Error

### GET `/api/v1/portfolio`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/api/v1/portfolio/overview`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### POST `/api/v1/predictions/generate`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/api/v1/predictions/history`

| Parámetro | Ubicación | Tipo | Obligatorio |
|---|---|---|---|
| `limit` | query | integer | No |
| `offset` | query | integer | No |

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response
- `422`: Validation Error

### GET `/api/v1/predictions/latest`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/api/v1/risk/config`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/api/v1/risk/overview`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/api/v1/status`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

### GET `/health`

**Respuestas documentadas en OpenAPI:**

- `200`: Successful Response

## 5. Consideraciones de seguridad

Los códigos de respuesta declarados en OpenAPI no
representan necesariamente todos los errores posibles.

Las pruebas verificaron respuestas HTTP 401 ante claves
incorrectas, ausentes o malformadas.

Las acciones de escritura están sujetas a autenticación,
confirmaciones explícitas y controles operativos.

La API no permite enviar órdenes reales a MEXC.
