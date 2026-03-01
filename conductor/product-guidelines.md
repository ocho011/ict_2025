# Product Guidelines: ICT 2025 Trading System

## Documentation & Prose Style
- **Technical & Concise**: Documentation must be precise and optimized for experienced developers and traders. Avoid conversational filler; focus on high-signal technical rationale and implementation details.
- **Direct & Structured**: Use clear headings, bullet points, and code blocks to ensure information is easily scannable.

## Communication & Logging
- **Machine-First (JSON)**: Primary logging and error reporting should prioritize structured JSON format. This ensures that logs can be easily ingested by automated analysis tools, monitoring systems, and audit loggers.
- **Traceability**: Every log entry must include a timestamp, component name, and line number to ensure full traceability during debugging.

## UX & Interaction Principles
- **High Signal, Low Noise**: The CLI and logs should prioritize critical events. Avoid spamming the console with repetitive information unless it is essential for real-time monitoring.
- **Transparency First**: Every critical internal state change (e.g., signal generation, order fill, position update) must be documented in the logs to ensure total transparency.
- **Visual Hierarchy**: Use consistent formatting, labels, and icons (e.g., 🚀, 🛡️, ⚠️) to distinguish between informational, success, warning, and error messages.

## Development Philosophy
- **Performance Over All**: Latency and execution speed are the highest priorities. When adding new features, optimize for low-latency data processing and order execution, even if it requires more complex implementations.
- **Precision**: ICT strategy implementations must be mathematically precise. Rounding or approximation should only occur where strictly required by the exchange (e.g., tick size).
- **Security & Integrity**: Rigorously protect API keys and sensitive configuration. Never log credentials or expose internal system states that could compromise security.
