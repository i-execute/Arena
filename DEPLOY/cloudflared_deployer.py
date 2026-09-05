"""
Cloudflared tunnel deployer for LMArena Bridge.

Installs cloudflared binary, starts a local HTTP server serving JSX/HTML/JS
files, and opens a trycloudflare.com tunnel to expose them publicly.

Usage:
    python -m DEPLOY.cloudflared_deployer serve <file_or_dir> [--port 8080]
    python -m DEPLOY.cloudflared_deployer install [--tag 2024.1.0]
    python -m DEPLOY.cloudflared_deployer tunnel <port>
    python -m DEPLOY.cloudflared_deployer status
    python -m DEPLOY.cloudflared_deployer stop <site_id>
"""

import asyncio
import json
import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

CF_REPO = "cloudflare/cloudflared"
DEFAULT_PORT = 8080
TUNNEL_TIMEOUT = 30  # seconds to wait for trycloudflare URL
SITES_FILE = os.path.join(tempfile.gettempdir(), "lmarena_deployer_sites.json")


def _arch():
    m = platform.machine().lower()
    if "arm" in m or "aarch64" in m:
        return "arm64"
    return "amd64"


def _root_dir():
    return os.path.join(tempfile.gettempdir(), "lmarena_deployer")


def _cf_bin():
    return os.path.join(_root_dir(), "cloudflared")


def _load_sites():
    try:
        with open(SITES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_sites(sites):
    tmp = SITES_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sites, f, indent=2)
    os.replace(tmp, SITES_FILE)


def _cf_installed():
    return bool(os.path.isfile(_cf_bin()) and os.access(_cf_bin(), os.X_OK))


def _cf_version():
    if not _cf_installed():
        return None
    try:
        out = subprocess.check_output([_cf_bin(), "--version"], stderr=subprocess.STDOUT, text=True, timeout=5)
        return out.strip().split("\n")[0]
    except Exception:
        return "unknown"


async def _curl(*args, timeout=15):
    p = await asyncio.create_subprocess_exec(
        "curl", "-sL", "--max-time", str(timeout), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await p.communicate()
    return p.returncode, out, err


async def _gh_releases(force=False):
    rc, out, _ = await _curl(f"https://api.github.com/repos/{CF_REPO}/releases")
    if rc != 0:
        return []
    try:
        data = json.loads(out.decode())
        if isinstance(data, list):
            return data[:20]
    except Exception:
        pass
    return []


async def install_cf(tag=None):
    """Install cloudflared binary. If tag is None, installs latest."""
    os.makedirs(_root_dir(), exist_ok=True)
    arch = _arch()
    asset_name = f"cloudflared-linux-{arch}"

    if tag is None:
        releases = await _gh_releases()
        if not releases:
            print("❌ Failed to fetch releases. Set GITHUB_TOKEN or try later.")
            return False
        tag = releases[0].get("tag_name", "")
        if not tag:
            print("❌ Could not determine latest version")
            return False

    print(f"📦 Installing cloudflared {tag} ({arch})...")
    rc, out, _ = await _curl(
        f"https://api.github.com/repos/{CF_REPO}/releases/tags/{tag}"
    )
    if rc != 0:
        print(f"❌ GitHub API request failed")
        return False

    try:
        data = json.loads(out.decode())
    except Exception:
        print("❌ Bad GitHub API response")
        return False

    if "message" in data:
        print(f"❌ GitHub: {data['message']}")
        return False

    download_url = None
    for asset in data.get("assets", []):
        if asset.get("name", "") == asset_name:
            download_url = asset["browser_download_url"]
            break

    if not download_url:
        print(f"❌ No '{asset_name}' in release assets")
        return False

    print(f"⬇️  Downloading from {download_url}...")
    p = await asyncio.create_subprocess_exec(
        "wget", "-q", "--max-redirect=15", "-O", _cf_bin(), download_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await asyncio.wait_for(p.communicate(), timeout=300)

    size = os.path.getsize(_cf_bin()) if os.path.isfile(_cf_bin()) else 0
    if p.returncode != 0 or size < 100_000:
        print(f"❌ Download failed (size={size}): {err.decode()[:200]}")
        return False

    os.chmod(_cf_bin(), os.stat(_cf_bin()).st_mode | stat.S_IEXEC)
    print(f"✅ cloudflared installed: {_cf_version()}")
    return True


def _build_html_from_js(js_path, filename):
    """Wrap JS/JSX in an HTML file with React + Babel for browser rendering."""
    with open(js_path, "r", encoding="utf-8", errors="replace") as f:
        js_code = f.read()
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>{filename}</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script src="https://unpkg.com/react@18/umd/react.development.js"></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<style>
html, body, #root {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow-x: hidden; }}
</style>
</head>
<body>
<div id="root"></div>
<script type="text/babel">
{js_code}
const root = ReactDOM.createRoot(document.getElementById('root'));
if (typeof App !== 'undefined') {{
  root.render(React.createElement(App));
}}
</script>
</body>
</html>"""


def _start_http_server(serve_dir, port):
    """Start a simple HTTP server in a background thread."""
    handler = SimpleHTTPRequestHandler
    httpd = HTTPServer(("0.0.0.0", port), handler)
    # Serve from the given directory
    handler.directory = serve_dir
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _start_cf_tunnel(port, result_holder):
    """Start cloudflared tunnel in a thread, capture trycloudflare URL."""
    try:
        proc = subprocess.Popen(
            [_cf_bin(), "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        result_holder.append(proc)
        for line in proc.stdout:
            if "trycloudflare.com" in line:
                for part in line.split():
                    if part.startswith("https://") and "trycloudflare.com" in part:
                        result_holder.insert(0, part.strip())
                        return
    except Exception as e:
        logger.error(f"cloudflared tunnel error: {e}")


async def serve(target, port=DEFAULT_PORT):
    """Deploy a file or directory via cloudflared tunnel."""
    target = os.path.abspath(target)
    if not os.path.exists(target):
        print(f"❌ File/directory not found: {target}")
        return

    if not _cf_installed():
        print("⚠️  cloudflared not installed. Installing latest...")
        ok = await install_cf()
        if not ok:
            print("❌ Failed to install cloudflared. Install manually or check network.")
            return

    # Prepare serve directory
    site_id = uuid.uuid4().hex[:12]
    site_dir = os.path.join(_root_dir(), f"site_{site_id}")
    os.makedirs(site_dir, exist_ok=True)

    if os.path.isfile(target):
        filename = os.path.basename(target)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext in ("js", "jsx"):
            html = _build_html_from_js(target, filename)
            with open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8") as f:
                f.write(html)
            print(f"📄 Wrapped {filename} in React HTML shell")
        elif ext == "html":
            shutil.copy2(target, os.path.join(site_dir, "index.html"))
        else:
            shutil.copy2(target, os.path.join(site_dir, filename))
    elif os.path.isdir(target):
        for item in os.listdir(target):
            src = os.path.join(target, item)
            dst = os.path.join(site_dir, item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
        # Ensure index.html exists
        if not os.path.exists(os.path.join(site_dir, "index.html")):
            for item in os.listdir(site_dir):
                if item.endswith(".js") or item.endswith(".jsx"):
                    html = _build_html_from_js(
                        os.path.join(site_dir, item), item
                    )
                    with open(os.path.join(site_dir, "index.html"), "w") as f:
                        f.write(html)
                    break
        print(f"📁 Copied directory contents to {site_dir}")

    # Start HTTP server
    print(f"🌐 Starting HTTP server on port {port}...")
    httpd = _start_http_server(site_dir, port)
    await asyncio.sleep(1)

    # Start cloudflared tunnel
    print(f"🚇 Starting cloudflared tunnel...")
    result_holder = []
    cf_thread = threading.Thread(
        target=_start_cf_tunnel, args=(port, result_holder), daemon=True
    )
    cf_thread.start()

    # Wait for URL
    url = None
    for _ in range(TUNNEL_TIMEOUT):
        await asyncio.sleep(1)
        if result_holder and isinstance(result_holder[0], str):
            url = result_holder[0]
            break

    if not url:
        print(f"❌ cloudflared did not return a trycloudflare.com URL within {TUNNEL_TIMEOUT}s")
        httpd.shutdown()
        shutil.rmtree(site_dir, ignore_errors=True)
        return

    cf_proc = None
    for item in result_holder:
        if hasattr(item, "terminate"):
            cf_proc = item
            break

    # Save site info
    sites = _load_sites()
    sites[site_id] = {
        "name": os.path.basename(target),
        "url": url,
        "port": port,
        "dir": site_dir,
        "started": time.time(),
    }
    _save_sites(sites)

    print()
    print(f"✅ Site deployed!")
    print(f"   URL: {url}")
    print(f"   Local: http://localhost:{port}")
    print(f"   Site ID: {site_id}")
    print(f"   Stop: python -m DEPLOY.cloudflared_deployer stop {site_id}")
    print()

    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n🛑 Stopping...")
        httpd.shutdown()
        if cf_proc:
            cf_proc.terminate()
        shutil.rmtree(site_dir, ignore_errors=True)
        sites = _load_sites()
        sites.pop(site_id, None)
        _save_sites(sites)
        print("✅ Stopped")


async def tunnel(port):
    """Open a cloudflared tunnel to an already-running local port."""
    if not _cf_installed():
        print("⚠️  cloudflared not installed. Installing latest...")
        ok = await install_cf()
        if not ok:
            return

    print(f"🚇 Opening tunnel to localhost:{port}...")
    result_holder = []
    cf_thread = threading.Thread(
        target=_start_cf_tunnel, args=(port, result_holder), daemon=True
    )
    cf_thread.start()

    url = None
    for _ in range(TUNNEL_TIMEOUT):
        await asyncio.sleep(1)
        if result_holder and isinstance(result_holder[0], str):
            url = result_holder[0]
            break

    if not url:
        print(f"❌ No tunnel URL within {TUNNEL_TIMEOUT}s")
        return

    print(f"✅ Tunnel URL: {url}")
    print(f"   Pointing to: http://localhost:{port}")

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        for item in result_holder:
            if hasattr(item, "terminate"):
                item.terminate()
        print("\n🛑 Tunnel closed")


async def stop(site_id):
    """Stop a deployed site by ID."""
    sites = _load_sites()
    site = sites.get(site_id)
    if not site:
        # Try partial match
        for sid, s in sites.items():
            if sid.startswith(site_id):
                site_id = sid
                site = s
                break

    if not site:
        print(f"❌ Site '{site_id}' not found")
        return

    site_dir = site.get("dir")
    if site_dir and os.path.isdir(site_dir):
        shutil.rmtree(site_dir, ignore_errors=True)

    sites.pop(site_id, None)
    _save_sites(sites)
    print(f"✅ Stopped site {site_id} ({site.get('url', '?')})")


async def status():
    """Show all active deployed sites."""
    sites = _load_sites()
    if not sites:
        print("No active sites.")
        return

    print(f"Active sites: {len(sites)}")
    print("-" * 60)
    for sid, s in sites.items():
        age = int(time.time() - s.get("started", 0))
        print(f"  {sid}")
        print(f"    name: {s.get('name', '?')}")
        print(f"    url:  {s.get('url', '?')}")
        print(f"    port: {s.get('port', '?')}")
        print(f"    age:  {age}s")
        print()


def active_urls():
    """Return dict of {site_id: url} for currently active tunnels (sync)."""
    sites = _load_sites()
    return {sid: s.get("url", "") for sid, s in sites.items() if s.get("url")}


def restart_sites():
    """Re-serve all currently known sites (redeploy). Returns list of (name,url)."""
    sites = _load_sites()
    redeployed = []
    for sid, s in list(sites.items()):
        name = s.get("name", "?")
        port = s.get("port", DEFAULT_PORT)
        target = s.get("dir")
        # Best-effort: re-open a tunnel to the recorded port
        try:
            asyncio.run(_open_tunnel(port, sid))
            redeployed.append((name, s.get("url", "?")))
        except Exception as e:
            logger.error(f"redeploy {name} failed: {e}")
    return redeployed


async def _open_tunnel(port, site_id=None):
    """Open a cloudflared tunnel to a port; returns the URL or None."""
    if not _cf_installed():
        print("⚠️  cloudflared not installed. Installing latest...")
        ok = await install_cf()
        if not ok:
            return None
    result_holder = []
    cf_thread = threading.Thread(
        target=_start_cf_tunnel, args=(port, result_holder), daemon=True
    )
    cf_thread.start()
    url = None
    for _ in range(TUNNEL_TIMEOUT):
        await asyncio.sleep(1)
        if result_holder and isinstance(result_holder[0], str):
            url = result_holder[0]
            break
    return url


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Cloudflared tunnel deployer for LMArena Bridge"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Deploy a file or directory")
    p_serve.add_argument("target", help="File (.js/.jsx/.html) or directory to serve")
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local port")

    p_tunnel = sub.add_parser("tunnel", help="Tunnel to an existing local port")
    p_tunnel.add_argument("port", type=int, help="Local port to tunnel")

    p_install = sub.add_parser("install", help="Install or update cloudflared")
    p_install.add_argument("--tag", default=None, help="Specific version tag")

    p_stop = sub.add_parser("stop", help="Stop a deployed site")
    p_stop.add_argument("site_id", help="Site ID to stop")

    sub.add_parser("status", help="Show active sites")
    sub.add_parser("urls", help="Print active tunnel URLs (one per line)")
    sub.add_parser("redeploy", help="Re-open tunnels for all known sites")
    sub.add_parser("version", help="Show cloudflared version")

    args = parser.parse_args()

    if args.command == "serve":
        asyncio.run(serve(args.target, args.port))
    elif args.command == "tunnel":
        asyncio.run(tunnel(args.port))
    elif args.command == "install":
        asyncio.run(install_cf(args.tag))
    elif args.command == "stop":
        asyncio.run(stop(args.site_id))
    elif args.command == "status":
        asyncio.run(status())
    elif args.command == "urls":
        urls = active_urls()
        if urls:
            for sid, u in urls.items():
                print(f"{sid}: {u}")
        else:
            print("No active tunnel URLs.")
    elif args.command == "redeploy":
        results = restart_sites()
        if results:
            for name, u in results:
                print(f"✅ {name} -> {u}")
        else:
            print("No sites to redeploy.")
    elif args.command == "version":
        v = _cf_version()
        print(f"cloudflared: {v or 'not installed'}")
        print(f"binary: {_cf_bin()}")


if __name__ == "__main__":
    main()
