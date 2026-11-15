import os, tarfile, tempfile, shutil, requests

URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
MEDIA_BUCKET = os.getenv("SUPABASE_BUCKET", "wa-media")
PROFILE_BUCKET = os.getenv("SUPABASE_PROFILE_BUCKET", "wa-profile")   # create as PRIVATE
PROFILE_OBJ = "profile.tar.gz"
CACHE = os.path.join(tempfile.gettempdir(), "wa-media-cache"); os.makedirs(CACHE, exist_ok=True)

MEDIA_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "video/mp4": "mp4", "video/3gpp": "3gp"}

def configured(): return bool(URL and KEY)
def _h(): return {"Authorization": f"Bearer {KEY}", "apikey": KEY}

# ---------- generic object calls ----------
def upload(path, data, ctype, bucket=MEDIA_BUCKET):
    """data: bytes or an open binary file. Overwrites if it exists."""
    r = requests.post(f"{URL}/storage/v1/object/{bucket}/{path}", data=data, timeout=300,
                      headers={**_h(), "Content-Type": ctype, "x-upsert": "true"})
    r.raise_for_status()

def download_to(path, dest, bucket=MEDIA_BUCKET):
    """Stream object to dest. Returns False if it doesn't exist."""
    with requests.get(f"{URL}/storage/v1/object/{bucket}/{path}", headers=_h(), stream=True, timeout=300) as r:
        if r.status_code in (400, 404): return False
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20): f.write(chunk)
    return True

def delete(path, bucket=MEDIA_BUCKET):
    try: requests.delete(f"{URL}/storage/v1/object/{bucket}", json={"prefixes": [path]}, headers=_h(), timeout=20)
    except Exception: pass

# ---------- media library ----------
def local_media(m):
    """Cached on-disk copy of a media row (id, path, type)."""
    p = os.path.join(CACHE, f"{m['id']}.{MEDIA_EXT.get(m['type'], 'bin')}")
    if not os.path.exists(p):
        tmp = p + ".part"
        if not download_to(m["path"], tmp): raise FileNotFoundError(m["path"])
        os.replace(tmp, p)
    return p

def purge_cache(mid):
    for fn in os.listdir(CACHE):
        if fn.startswith(mid): os.remove(os.path.join(CACHE, fn))

# ---------- WhatsApp browser profile ----------
SKIP_DIRS = {"Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache", "DawnCache", "DawnGraphiteCache",
             "DawnWebGPUCache", "Crashpad", "BrowserMetrics", "component_crx_cache", "CacheStorage", "ScriptCache",
             "optimization_guide_model_store", "Safe Browsing", "Media Cache"}
SKIP_FILES = {"SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"}

def _filter(ti):
    parts = ti.name.split("/")
    if any(p in SKIP_DIRS for p in parts) or parts[-1] in SKIP_FILES: return None
    return ti

def backup_profile(pdir):
    """tar.gz the profile (minus caches), verify it, upload it."""
    fd, tmp = tempfile.mkstemp(suffix=".tgz"); os.close(fd)
    try:
        with tarfile.open(tmp, "w:gz") as t: t.add(pdir, arcname=".", filter=_filter)
        with tarfile.open(tmp) as t: t.getmembers()            # integrity check before overwriting the good copy
        with open(tmp, "rb") as f: upload(PROFILE_OBJ, f, "application/gzip", PROFILE_BUCKET)
        return True
    finally: os.remove(tmp)

def restore_profile(pdir):
    """Download and unpack the profile into pdir. Returns True if one was restored."""
    fd, tmp = tempfile.mkstemp(suffix=".tgz"); os.close(fd)
    try:
        if not download_to(PROFILE_OBJ, tmp, PROFILE_BUCKET): return False
        shutil.rmtree(pdir, ignore_errors=True); os.makedirs(pdir, exist_ok=True)
        with tarfile.open(tmp) as t:
            try: t.extractall(pdir, filter="data")
            except TypeError: t.extractall(pdir)               # Python < 3.12
        return True
    finally: os.remove(tmp)