# ARMORY — Tool Repository

A self-hosted download portal for distributing tools across an isolated network.
Dynamic and self-service: drop files in a directory or upload them through the
browser and they appear instantly, with search, categories, and one-click
download. Built for **Ubuntu 20.04 LTS** and **Firefox 115**, standard-library
Python only (no internet, no pip).

## Contents

```
server.py            the repository web server (portal + API + upload/delete)
deploy.sh            installer -> /opt/armory + systemd service (Ubuntu 20.04)
snapshot.sh          capture live/uploaded tools back into this package
assets/uscybercom.svg  splash logo
tools/               seed tools (copied into the repo on deploy; may be empty)
manifest.seed.json   optional seed metadata (category/description/version)
```

## Deploy

```bash
sudo chmod +x armory.zip              # change permissions
python3 -m zipfile -e armory.zip .    # unzip the armory.zip file, ansible control node doesn't have unzip
sudo ./deploy.sh                      # installs and starts on port 8080
sudo PORT=80 ./deploy.sh              # Optional (or pick a port)
```

Then browse to `http://<host-ip>:8080/`. The page shows the splash, a search
box, category filters, and every file in the repository with a Download button.
Use **+ Upload** (or drag-and-drop) to add tools; set an optional category,
description, and version.

Configurable via environment variables: `PORT`, `BIND`, `INSTALL_DIR`,
`DATA_DIR`, `SVC_USER`, `MAX_UPLOAD_MB`, `ASSET_CACHE_DAYS`.

## Asset caching

Static assets (the seal, any logos) are served with a long freshness window —
**`ASSET_CACHE_DAYS` (default 30)** — so they are not re-downloaded during a
class. The server also sends `ETag`/`Last-Modified`, so after the window expires
the browser revalidates with a tiny `304 Not Modified` instead of re-pulling the
file, and if you replace an asset its ETag changes and the new version is picked
up automatically. The page HTML and the tool list are never cached, so uploads,
deletions, and redeploys always show immediately. Set a different window at
deploy time, e.g. `sudo ASSET_CACHE_DAYS=20 ./deploy.sh`.

## Adding tools

Three ways, all equivalent — the list is read live:

- **Browser:** click **+ Upload** and drop files.
- **Filesystem:** copy files into `/opt/armory/data/tools/`.
- **Pre-seed:** put files in this package's `tools/` folder before deploying.

Metadata (category/description/version) is stored in
`/opt/armory/data/manifest.json`. Files without metadata still list with their
name, size, and date.

## Surviving an environment wipe

Because the VM resets between classes, the workflow is:

1. Keep your master tool set in this package's `tools/` folder (and
   `manifest.seed.json`). `deploy.sh` seeds them every time.
2. If you add tools through the browser during a session and want to keep them,
   run `sudo ./snapshot.sh` before the wipe. It copies the live tools and
   metadata back into this package; re-zip or commit it, and the next
   `deploy.sh` brings them back.

## Manage the service

```bash
systemctl status armory
systemctl restart armory
journalctl -u armory -f
```

Re-running `deploy.sh` is safe (idempotent): it refreshes the code and service
and re-seeds without clobbering tools already present.

## Uninstall

```bash
sudo systemctl disable --now armory
sudo rm -f /etc/systemd/system/armory.service
sudo systemctl daemon-reload
sudo rm -rf /opt/armory
sudo userdel armory 2>/dev/null || true
```

## Troubleshooting
- If the webpage may be unaccesible until you add 'allow 8080/tcp' to the firewall 
```bash
sudo ufw allow 8080/tcp
```
## Notes

- Pure Python standard library; runs unprivileged on a port > 1024 by default.
- The repository data lives under `/opt/armory/data` (writable by the service
  account); the code and assets are read-only to the service.
- Uploads are capped at `MAX_UPLOAD_MB` (default 1024 MB) and filenames are
  sanitized; the server only ever reads/writes inside its tools directory.
