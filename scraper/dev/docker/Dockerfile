ARG SCRAPER_BASE_VERSION
FROM --platform=linux/amd64 docsearch-scraper-base:$SCRAPER_BASE_VERSION
LABEL maintainer="contact@typesense.org"

WORKDIR /home/seleuser
USER 1000
COPY scraper/src ./src

ENTRYPOINT ["pipenv", "run", "python", "-m", "src.index"]
