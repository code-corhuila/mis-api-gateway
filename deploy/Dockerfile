FROM nginx:1.30.5-alpine
WORKDIR /app
COPY config config
COPY deploy/start.sh start.sh
USER 101:101
ENTRYPOINT ["/bin/sh", "/app/start.sh"]
