FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY tmux_status_server/ tmux_status_server/

RUN pip install --no-cache-dir .

RUN useradd -r -s /usr/sbin/nologin appuser
USER appuser

EXPOSE 7850

ENTRYPOINT ["tmux-status-server"]
CMD ["--host", "0.0.0.0"]
