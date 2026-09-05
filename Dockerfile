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

# locales：沒有它 Info-ZIP 的 setlocale 失敗、不寫 UTF-8 檔名旗標，編碼表/ 在
# zip 內變亂碼（2026-09-05 雲上 dry-run 實踩：publish_ui_stats 因此多算 CSV）
RUN apt-get update && apt-get install -y --no-install-recommends \
        git openssh-client zip unzip awscli locales \
    && rm -rf /var/lib/apt/lists/* \
    # 光裝 locales 不夠：要 locale-gen 出 locale-archive，zip 才認得 UTF-8（雲上實測）
    && sed -i 's/^# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen \
    && curl -fsSL https://clickhouse.com/ | sh \
    && mv clickhouse /usr/local/bin/

ENV LC_ALL=C.UTF-8
COPY csv-aggregator/ /app/csv-aggregator/

CMD ["bash"]
