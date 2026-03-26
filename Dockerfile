FROM maven:3.9-eclipse-temurin-17 AS parser-build

WORKDIR /build
COPY tools/mpp-parser/pom.xml tools/mpp-parser/pom.xml
COPY tools/mpp-parser/src tools/mpp-parser/src
RUN mvn -q -f tools/mpp-parser/pom.xml package

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PM_DASH_DATA_DIR=/data \
    PM_DASH_DB_PATH=/data/pm_dashboard.db \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src src
COPY tools/mpp-parser/pom.xml tools/mpp-parser/pom.xml
COPY --from=parser-build /build/tools/mpp-parser/target/mpp-parser-1.0.0.jar tools/mpp-parser/target/mpp-parser-1.0.0.jar

RUN python -m pip install --no-cache-dir .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn pm_dashboard.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
