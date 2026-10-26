#!/bin/sh
set -e
# Pull champion models from the S3 registry when configured (falls back to bundled artifacts).
if [ -n "$SENTINEL_MODEL_S3_URI" ]; then
  python -m app.core.model_sync || echo "model sync failed; continuing with bundled artifacts / fallbacks"
fi
exec "$@"
