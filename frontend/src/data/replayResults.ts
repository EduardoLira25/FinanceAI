export const replayResults = {
  "period": "05/11/2024 - 04/12/2024",
  "cycles": 90,
  "portfolios": [
    {
      "strategy": "LSTM",
      "initial": 50000.0,
      "final": 53437.293399,
      "pnl": 3437.293399000002,
      "returnPct": 6.874586797999993
    },
    {
      "strategy": "LSTM + Qwen3",
      "initial": 50000.0,
      "final": 53810.27561,
      "pnl": 3810.275609999997,
      "returnPct": 7.620551220000005
    },
    {
      "strategy": "Buy & Hold",
      "initial": 50000.0,
      "final": 72666.164456,
      "pnl": 22666.164456,
      "returnPct": 45.33232891199999
    }
  ],
  "orders": [
    {
      "strategy": "Buy & Hold",
      "side": "BUY",
      "date": "2024-11-05 00:00",
      "quantity": 0.73691956,
      "price": 67850.01,
      "amount": 49999.999516,
      "type": "Orden simulada"
    },
    {
      "strategy": "LSTM",
      "side": "BUY",
      "date": "2024-11-07 00:00",
      "quantity": 0.16540519,
      "price": 75571.99,
      "amount": 12499.999365,
      "type": "Orden simulada"
    },
    {
      "strategy": "LSTM + Qwen3",
      "side": "BUY",
      "date": "2024-11-07 00:00",
      "quantity": 0.16540519,
      "price": 75571.99,
      "amount": 12499.999365,
      "type": "Orden simulada"
    },
    {
      "strategy": "LSTM",
      "side": "SELL",
      "date": "2024-11-08 00:00",
      "quantity": 0.16540519,
      "price": 75857.9,
      "amount": 12547.290362,
      "type": "Orden simulada"
    },
    {
      "strategy": "LSTM",
      "side": "BUY",
      "date": "2024-11-10 00:00",
      "quantity": 0.16316256,
      "price": 76683.17,
      "amount": 12511.822327,
      "type": "Orden simulada"
    },
    {
      "strategy": "LSTM",
      "side": "SELL",
      "date": "2024-11-30 00:00",
      "quantity": 0.16316256,
      "price": 97460.01,
      "amount": 15901.824729,
      "type": "Orden simulada"
    },
    {
      "strategy": "LSTM + Qwen3",
      "side": "SELL",
      "date": "Cierre del periodo",
      "quantity": 0.16540519,
      "price": 98608.0,
      "amount": 16310.274975,
      "type": "Liquidacion final"
    },
    {
      "strategy": "Buy & Hold",
      "side": "SELL",
      "date": "Cierre del periodo",
      "quantity": 0.73691956,
      "price": 98608.0,
      "amount": 72666.163972,
      "type": "Liquidacion final"
    }
  ]
}
