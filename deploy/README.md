# Production Deploy

## Docker Compose

1. Copy `.env.production.example` to `.env` and fill secrets.
2. Build and start:

```bash
docker compose up -d --build
```

3. Logs:

```bash
docker compose logs -f prom-repricer-bot
```

4. Health:

```bash
docker inspect --format='{{json .State.Health}}' prom-repricer-bot
```

## systemd

Recommended directory on the server:

```bash
sudo mkdir -p /opt/prom-repricer-bot
sudo rsync -a --exclude .venv --exclude .env ./ /opt/prom-repricer-bot/
cd /opt/prom-repricer-bot
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo cp deploy/prom-repricer-bot.service /etc/systemd/system/prom-repricer-bot.service
```

Create `/opt/prom-repricer-bot/.env` from `.env.production.example`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable prom-repricer-bot
sudo systemctl start prom-repricer-bot
sudo systemctl status prom-repricer-bot
```

Logs:

```bash
journalctl -u prom-repricer-bot -f
```

Healthcheck manually:

```bash
cd /opt/prom-repricer-bot
.venv/bin/python -m scripts.healthcheck
```
