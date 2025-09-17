# pg-agents
pg-agents

## TradingView Webhook Integration

This service includes an endpoint to receive and process webhook alerts from TradingView. This allows you to connect your Pine Script strategies directly to the trading agent.

### Configuration

1.  **Set the Secret Token**: To secure the webhook endpoint, you must set a secret token in your environment. Add the following line to your `.env` file or set it as an environment variable:

    ```
    WEBHOOK_SECRET_TOKEN=your_super_secret_token_here
    ```

2.  **Run the API Server**: The webhook is handled by a separate FastAPI web server. You need to run this server in addition to the agent scheduler. Use the following command:

    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000
    ```

### Usage in TradingView

1.  **Webhook URL**: In your TradingView alert settings, use the URL of your deployed API server. For a local setup, this would typically be `http://<your-local-ip>:8000/webhook/tradingview`.

2.  **Message Body**: The alert's message body must be a JSON object with the following structure:

    ```json
    {
      "symbol": "BINANCE:BTCUSDT",
      "side": "buy",
      "qty": 0.01,
      "price": 65000.0,
      "ts": "2025-09-17T10:00:00Z",
      "strategy": "your_strategy_name_v1",
      "idempotency_key": "a_unique_key_for_this_alert"
    }
    ```
    -   `symbol`: The trading symbol.
    -   `side`: Must be either `"buy"` or `"sell"`.
    -   `qty`: The quantity to trade.
    -   `price`: The price at which the signal was generated. Used for SL/TP calculation.
    -   `ts`: The timestamp of the alert in ISO 8601 format.
    -   `strategy`: A name for your strategy.
    -   `idempotency_key`: A unique string to prevent duplicate processing of the same alert.

3.  **HTTP Headers**: You must add a custom HTTP header to your webhook request:
    -   **Header Name**: `X-Auth-Token`
    -   **Header Value**: The same secret token you configured in `WEBHOOK_SECRET_TOKEN`.
