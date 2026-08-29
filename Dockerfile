# twrh 爬蟲 pipeline images（docs/aws-deployment-plan.md A1）
#
#   docker build --target crawler   -t twrh-crawler .
#   docker build --target publisher -t twrh-publisher .
#
# crawler：每日排程任務跑 go.sh／management commands（保持小顆）
# publisher：crawler ＋ clickhouse/awscli/git，跑 publish.sh（人工觸發才拉）
# 機密（DB 密碼、Slack webhook、Sentry DSN、proxy token）一律由環境變數注入
# （AWS 上是 SSM SecureString → task definition secrets），永遠不進 image。

FROM python:3.10-slim-bookworm AS crawler

# GeoDjango 系統庫（GDAL/GEOS/PROJ）＋ psql client（工具腳本用）＋ zstd（raw offload）
RUN apt-get update && apt-get install -y --no-install-recommends \
        gdal-bin libgdal32 libgeos-c1v5 libproj25 \
        postgresql-client zstd curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==1.8.5 \
    && poetry config virtualenvs.create false

WORKDIR /app/twrh-dataset

# 相依先裝、source 後放，讓 code 改動不用重裝相依層
COPY twrh-dataset/pyproject.toml twrh-dataset/poetry.lock ./
RUN poetry install --only main --no-root --no-interaction

COPY twrh-dataset/ ./
# 容器內沒有 gitignored 的個人設定檔，一律用 env-driven 的 sample
RUN cp crawler/settings.sample.py crawler/settings.py

# EFS（/data）→ ../logs 與 datas/ 的接線，見 devop/entrypoint.sh
ENTRYPOINT ["/app/twrh-dataset/devop/entrypoint.sh"]
CMD ["./go.sh"]


FROM crawler AS publisher

RUN apt-get update && apt-get install -y --no-install-recommends \
        git zip unzip awscli \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://clickhouse.com/ | sh \
    && mv clickhouse /usr/local/bin/

COPY csv-aggregator/ /app/csv-aggregator/

CMD ["bash"]
