#!/usr/bin/env python3
"""
make_decor.py - Tạo / bổ sung file .mobileconfig (Web Clip) với icon gốc lấy từ App Store.

Mỗi dòng trong apps.txt gồm các phần ngăn cách bằng "|", thứ tự tuỳ ý sau phần đầu:
  - Phần đầu: tên app HOẶC App Store ID HOẶC link App Store (dùng để tìm app)
  - Phần có ID số (>=5 chữ số) hoặc link apps.apple.com: dùng để tra app (ưu tiên hơn tên)
  - Phần có "://" khác apps.apple.com (vd fb-messenger://): URL mở khi bấm icon
  - Phần còn lại: nhãn hiển thị dưới icon

Ví dụ:
  Instagram
  Minecraft | 479516143
  Minecraft | 479516143 | https://apps.apple.com/vn/app/id479516143
  Messenger | fb-messenger://
  Messenger | Mess | fb-messenger://
  # dòng bắt đầu bằng # bị bỏ qua
"""
import argparse, json, plistlib, re, sys, time, uuid
import urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 decor-maker"}
ID_RE = re.compile(r"^\d{5,}$")
STORE_RE = re.compile(r"apps\.apple\.com|itunes\.apple\.com")


def http_get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise last


def parse_line(line):
    """Trả về (khoá tra cứu, nhãn, URL mở)."""
    parts = [p.strip() for p in line.split("|") if p.strip()]
    lookup = parts[0]
    label = url = None
    for p in parts[1:]:
        if ID_RE.match(p) or STORE_RE.search(p):
            lookup = p              # ID / link store -> chính xác hơn tên
        elif "://" in p:
            url = p
        else:
            label = p
    return lookup, label, url


def lookup_in(query, country):
    m = re.search(r"id(\d{5,})", query) or ID_RE.match(query.strip())
    if m:
        key = m.group(1) if m.lastindex else query.strip()
        url = f"https://itunes.apple.com/lookup?id={key}&country={country}"
    else:
        q = urllib.parse.quote(query)
        url = (f"https://itunes.apple.com/search?term={q}&entity=software"
               f"&country={country}&limit=1")
    data = json.loads(http_get(url))
    return data["results"][0] if data.get("results") else None


def find_app(query, countries):
    for c in countries:
        app = lookup_in(query, c)
        if app:
            return app, c
        time.sleep(3.2)
    return None, None


def best_artwork(app, size):
    url = app["artworkUrl512"]
    base = re.sub(r"\d+x\d+bb\.\w+$", f"{size}x{size}bb", url)
    cands = [base + ".png", url] if base != url else [url]
    for u in cands:
        try:
            return http_get(u)
        except Exception:
            continue
    raise RuntimeError("không tải được artwork")


def ident(label, app_id):
    slug = re.sub(r"[^a-z0-9]+", "", label.lower()) or "app"
    return f"com.decor.{slug}{app_id or ''}.webclip"


def make_payload(label, url, icon, identifier):
    return {
        "FullScreen": True,
        "Icon": icon,
        "IsRemovable": True,
        "Label": label,
        "PayloadDescription": label,
        "PayloadDisplayName": label,
        "PayloadIdentifier": identifier,
        "PayloadOrganization": label,
        "PayloadType": "com.apple.webClip.managed",
        "PayloadUUID": str(uuid.uuid4()).upper(),
        "PayloadVersion": 1,
        "URL": url,
        "Precomposed": True,
    }


def short_name(track_name):
    return re.split(r"\s[-–—:]\s|:", track_name)[0].strip() or track_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("list", help="file txt chứa danh sách app")
    ap.add_argument("-o", "--output", default="decor.mobileconfig")
    ap.add_argument("--base", help="profile có sẵn để nối thêm (vd decor.xml)")
    ap.add_argument("--country", default="vn")
    ap.add_argument("--fallback", default="us",
                    help="store dự phòng nếu app không có ở --country ('' để tắt)")
    ap.add_argument("--size", type=int, default=512, help="cạnh icon: 512, 256, 180...")
    ap.add_argument("--replace", action="store_true",
                    help="thay payload cũ trùng nhãn thay vì bỏ qua")
    ap.add_argument("--name", default="𝘥𝘦𝘤𝘰𝘳𝘢𝘵𝘪𝘰𝘯𝘴✨")
    ap.add_argument("--org", default="276hz")
    a = ap.parse_args()

    if a.base:
        with open(a.base, "rb") as f:
            profile = plistlib.load(f)
    else:
        profile = {
            "PayloadContent": [],
            "PayloadDisplayName": a.name,
            "PayloadDescription": "decor",
            "PayloadIdentifier": "com.decor.profile",
            "PayloadOrganization": a.org,
            "PayloadRemovalDisallowed": False,
            "PayloadType": "Configuration",
            "PayloadUUID": str(uuid.uuid4()).upper(),
            "PayloadVersion": 1,
        }

    countries = [a.country] + ([a.fallback] if a.fallback and a.fallback != a.country else [])
    content = profile["PayloadContent"]
    lines = [l.strip() for l in open(a.list, encoding="utf-8")
             if l.strip() and not l.strip().startswith("#")]

    added, skipped, failed = 0, 0, []
    for line in lines:
        key, label, url = parse_line(line)
        try:
            app, used = find_app(key, countries)
            if not app:
                raise RuntimeError(f"không tìm thấy (đã thử store: {', '.join(countries)})")
            name = label or short_name(app["trackName"])
            ident_ = ident(name, app.get("trackId"))

            same = [p for p in content
                    if p.get("PayloadIdentifier") == ident_
                    or p.get("Label", "").casefold() == name.casefold()]
            if same and not a.replace:
                skipped += 1
                print(f"[bỏ qua] {name}: đã có trong profile (dùng --replace để thay)")
                continue
            icon = best_artwork(app, a.size)
            if same:
                content[:] = [p for p in content if p not in same]
            content.append(make_payload(name, url or app["trackViewUrl"], icon, ident_))
            added += 1
            note = "" if used == a.country else f" [store {used}]"
            print(f"[ok] {line!r} -> {app['trackName']} (id {app.get('trackId')}){note}, "
                  f"icon {len(icon)//1024} KB")
        except Exception as e:
            failed.append((line, str(e)))
            print(f"[lỗi] {line}: {e}")
        time.sleep(3.2)  # tránh vượt giới hạn tốc độ của iTunes API

    with open(a.output, "wb") as f:
        plistlib.dump(profile, f)
    print(f"\nXong: thêm {added}, bỏ qua {skipped}, lỗi {len(failed)}. "
          f"Tổng payload: {len(content)}. File: {a.output}")
    if failed:
        print("Các dòng lỗi:")
        for l, e in failed:
            print(f"  - {l}  ({e})")


if __name__ == "__main__":
    sys.exit(main())
