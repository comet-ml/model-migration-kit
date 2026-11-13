import os

# Tests never talk to Opik or a model provider.
os.environ["OPIK_TRACK_DISABLE"] = "true"
