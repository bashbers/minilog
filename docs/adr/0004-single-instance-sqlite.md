# Operate as one application instance backed by SQLite

Each deployment will run one FastAPI instance with one Uvicorn worker against a local SQLite database configured for WAL, foreign keys, and a busy timeout. This keeps household operation and recovery simple at the cost of horizontal scaling; clustered instances and network-mounted SQLite are explicitly unsupported.
