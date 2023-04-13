FROM ubuntu:latest

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    curl

# Install Poetry
RUN python3 -m venv /app

RUN --mount=type=cache,id=poetry,target=/root/.cache/ curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Set working directory
WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,id=poetry,target=/root/.cache/,sharing=locked \
    . /app/bin/activate && \
    poetry install --no-root

# Copy project
COPY . .

# Copy files
EXPOSE 8000

# Run the app in gpt_bash/main.py (Activate the virtual environment)
#CMD ["python3", "gpt_bash/main.py"]
CMD . /app/bin/activate && python3 gpt_bash/main.py




