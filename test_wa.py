"""
test_wa.py - functional tests for the WhatsApp Web automation module.

Usage (module file must be importable, default name: wa.py):
    python test_wa.py --phone 9876543210
    python test_wa.py --phone 919876543210 --only text --headed
    python test_wa.py --phone 9876543210 --only image,caption
    python test_wa.py --phone 9876543210 --files a.jpg b.jpg --only custom
    python test_wa.py --phone 9876543210 --module my_wa_module

Tests: text, image, caption, multi, custom, invalid
On any failure the browser screenshot WhatsApp last saw is written to
debug_<test>.png so you can see exactly where the attach flow got stuck.
"""
import argparse, base64, importlib, os, struct, sys, tempfile, time, zlib

# ------------------------------------------------------------------ helpers
def make_png(path, w=400, h=300, shift=0):
    """Write a small gradient PNG using only the standard library."""
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # filter byte
        for x in range(w):
            rows += bytes(((x + shift) % 256, (y * 255 // h), (255 - x * 255 // w) % 256))
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return path


def save_data_url(data_url, path):
    if not data_url or "," not in data_url:
        return False
    with open(path, "wb") as f:
        f.write(base64.b64decode(data_url.split(",", 1)[1]))
    return True


class Runner:
    def __init__(self, wa, phone):
        self.wa, self.phone = wa, phone
        self.results = []
        self.tmp = tempfile.mkdtemp(prefix="wa_test_")

    def wait_ready(self, timeout=180):
        print("Waiting for WhatsApp session to be ready...")
        end, last = time.time() + timeout, None
        while time.time() < end:
            st = self.wa.state["status"]
            if st != last:
                print(f"  status: {st}")
                last = st
            if st == "ready":
                return True
            if st == "qr":
                if save_data_url(self.wa.state.get("qr"), "qr.png"):
                    print("  QR saved to qr.png - scan it with your phone (Linked devices).")
            if st == "error":
                print("  error:", self.wa.state.get("err"))
            time.sleep(3)
        return False

    def run(self, name, text, files=(), expect_error=None, phone=None):
        print(f"\n=== TEST: {name} ===")
        print(f"  text={text!r} files={[os.path.basename(f) for f in files]}")
        t0 = time.time()
        steps = []
        def step(msg):
            steps.append(msg)
            print(f"  [{time.time() - t0:5.1f}s] {msg}")
        ok, detail = False, ""
        try:
            self.wa.send(phone or self.phone, text, files, step)
            if expect_error:
                detail = "expected an error but send succeeded"
            else:
                ok = True
        except Exception as e:
            detail = f"{type(e).__name__}: {e}"
            if expect_error and expect_error.lower() in str(e).lower():
                ok, detail = True, f"got expected error: {e}"
        dt = time.time() - t0
        if not ok:
            shot = f"debug_{name}.png"
            if save_data_url(self.wa.state.get("debug"), shot):
                detail += f"  (screenshot -> {shot})"
        print(f"  {'PASS' if ok else 'FAIL'} in {dt:.1f}s {detail}")
        self.results.append((name, ok, dt, detail))
        return ok

    def summary(self):
        print("\n" + "=" * 52)
        for name, ok, dt, detail in self.results:
            print(f"{'PASS' if ok else 'FAIL':5} {name:10} {dt:6.1f}s  {detail if not ok else ''}")
        failed = [r for r in self.results if not r[1]]
        print(f"\n{len(self.results) - len(failed)}/{len(self.results)} passed")
        return 0 if not failed else 1


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", required=True, help="recipient, 10 digits (uses WA_CC) or full international")
    ap.add_argument("--module", default="wa", help="module name containing the automation code (default: wa)")
    ap.add_argument("--only", default="text,image,caption,multi,invalid",
                    help="comma list: text,image,caption,multi,custom,invalid")
    ap.add_argument("--files", nargs="*", default=[], help="your own files for the 'custom' test")
    ap.add_argument("--caption", default="Test caption from test_wa.py")
    ap.add_argument("--headed", action="store_true", help="show the browser window (sets WA_HEADLESS=0)")
    args = ap.parse_args()
    if args.headed:
        os.environ["WA_HEADLESS"] = "0"

    sys.path.insert(0, os.getcwd())
    wa = importlib.import_module(args.module)

    r = Runner(wa, args.phone)
    if not r.wait_ready():
        print("Session never became ready. Last state:", {k: (v if k not in ("qr", "debug") else bool(v))
                                                         for k, v in wa.state.items()})
        save_data_url(wa.state.get("debug") or wa.state.get("qr"), "debug_startup.png")
        return 2

    img1 = make_png(os.path.join(r.tmp, "test1.png"), shift=0)
    img2 = make_png(os.path.join(r.tmp, "test2.png"), shift=90)
    stamp = time.strftime("%H:%M:%S")
    wanted = [t.strip() for t in args.only.split(",") if t.strip()]

    for t in wanted:
        if t == "text":
            r.run("text", f"[test_wa] plain text {stamp}")
        elif t == "image":
            r.run("image", "", [img1])
        elif t == "caption":
            r.run("caption", f"{args.caption} {stamp}", [img1])
        elif t == "multi":
            r.run("multi", "", [img1, img2])
        elif t == "custom":
            if not args.files:
                print("\n'custom' needs --files"); continue
            r.run("custom", args.caption, args.files)
        elif t == "invalid":
            r.run("invalid", "should not send", phone="0000000000", expect_error="not on whatsapp")
        else:
            print(f"unknown test: {t}")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())