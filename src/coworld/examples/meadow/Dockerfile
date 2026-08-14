FROM docker.io/library/python:3.12-slim

# numpy backs the grader's exact-optimum DP; boto3 backs the LLM player's
# Bedrock sidecar path (see BEDROCK.md).
RUN pip install --no-cache-dir fastapi==0.115.5 uvicorn[standard]==0.34.2 websockets==15.0.1 \
    pydantic==2.11.5 numpy==2.2.6 boto3==1.38.27

ENV PYTHONPATH=/app
WORKDIR /app

# Mirror the source-tree layout so absolute imports
# (`coworld.examples.meadow.*`) resolve identically here and in tests.
# The `coworld` and `coworld.examples` packages contribute nothing else to
# the runtime image, so empty stub __init__.py files suffice.
RUN mkdir -p /app/coworld/examples && \
    touch /app/coworld/__init__.py /app/coworld/examples/__init__.py

COPY __init__.py /app/coworld/examples/meadow/__init__.py
COPY headless.py /app/coworld/examples/meadow/headless.py
COPY shared /app/coworld/examples/meadow/shared
COPY game /app/coworld/examples/meadow/game
COPY player /app/coworld/examples/meadow/player
COPY grader /app/coworld/examples/meadow/grader

CMD ["python", "-m", "coworld.examples.meadow.game.server"]
