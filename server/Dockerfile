FROM python:3.13-alpine

RUN addgroup -S onair && adduser -S -G onair -u 10001 onair
WORKDIR /app
COPY on_air_server /app/on_air_server
RUN mkdir /data && chown onair:onair /data

USER onair
EXPOSE 8080
ENV PYTHONUNBUFFERED=1 ON_AIR_DATABASE=/data/on-air.sqlite3
CMD ["python", "-m", "on_air_server.app"]
