import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/odds"
)

# Remote bet placement. Empty = betting endpoints disabled (503).
# Set via compose env; change the dev default before any real use.
BET_TOKEN = os.environ.get("BET_TOKEN", "")

# A bet stuck in requested/delivered this long is expired by the bridge sweep.
BET_EXPIRY_MINUTES = int(os.environ.get("BET_EXPIRY_MINUTES", "15"))
