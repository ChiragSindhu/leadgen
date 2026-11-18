import os, tarfile, tempfile, shutil, threading, uuid, requests

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
_LOCKS, _LG = {}, threading.Lock()
def _lock(mid):
    with _LG: return _LOCKS.setdefault(mid, threading.Lock())

def local_media(m):
    """Cached on-disk copy of a media row (id, path, type, size).
    Safe under concurrent requests: one download per file at a time, each into its own temp file,
    and a cached copy is only trusted if its size matches the size stored in the database
    (a corrupt or partial copy from an earlier run is replaced automatically)."""
    p = os.path.join(CACHE, f"{m['id']}.{MEDIA_EXT.get(m['type'], 'bin')}")
    want = int(m.get("size") or 0)
    def good():
        try: n = os.path.getsize(p)
        except OSError: return False
        return n > 0 and (not want or n == want)
    if good(): return p
    with _lock(m["id"]):
        if good(): return p                                   # another request finished it while we waited
        tmp = f"{p}.{uuid.uuid4().hex}.part"
        try:
            if not download_to(m["path"], tmp): raise FileNotFoundError(m["path"])
            n = os.path.getsize(tmp)
            if n == 0 or (want and n != want): raise IOError(f"incomplete download ({n} of {want} bytes)")
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass
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