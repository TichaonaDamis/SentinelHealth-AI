# Airflow image for SentinelHealth pipelines (runs on MWAA-compatible versions or ECS).
FROM apache/airflow:2.10.5-python3.12

USER root
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
USER airflow

COPY --chown=airflow:root airflow/requirements.txt /opt/sentinel/requirements.txt
COPY --chown=airflow:root ml /opt/sentinel/ml
RUN pip install --no-cache-dir -r /opt/sentinel/requirements.txt /opt/sentinel/ml

COPY --chown=airflow:root airflow/dags /opt/airflow/dags
COPY --chown=airflow:root airflow/plugins /opt/airflow/plugins
