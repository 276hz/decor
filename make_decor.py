#!/usr/bin/env python3
"""
make_decor.py - Tạo / bổ sung file .mobileconfig (Web Clip) với icon gốc lấy từ App Store.

Cách dùng:
  1) Tạo file apps.txt, mỗi dòng một app. Chấp nhận:
       Instagram
       TikTok
       389801252                      (App Store ID)
       https://apps.apple.com/vn/app/zalo/id579523206
       Facebook | fb://               (thêm "| URL" để tự đặt URL mở khi bấm icon)
       Messenger | Mess | fb-messenger://   (tên | nhãn hiển thị | URL)
     Dòng bắt đầu bằng # bị bỏ qua.

  2) Chạy:
       python3 make_decor.py apps.txt -o decor.mobileconfig
     Nối thêm vào profile cũ:
       python3 make_decor.py apps.txt --base decor.xml -o decor.mobileconfig

Tuỳ chọn: --country vn (store dùng để tìm), --name "tên profile", --org "276hz"
"""
import argparse, json, plistlib, re, sys, time, uuid
import urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 decor-maker"}


def http_get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))  # iTunes API giới hạn ~20 req/phút
    raise last


def find_app(query, country):
    """Trả về dict kết quả iTunes cho 1 app (theo ID, link hoặc tên)."""
    m = re.search(r"id(\d{5,})", query) or re.fullmatch(r"(\d{5,})", query.strip())
    if m:
        url = f"https://itunes.apple.com/lookup?id={m.group(1)}&country={country}"
    else:
        q = urllib.parse.quote(query)
        url = (f"https://itunes.apple.com/search?term={q}&entity=software"
               f"&country={country}&limit=1")
    data = json.loads(http_get(url))
    if not data.get("results"):
        return None
    return data["results"][0]


def best_artwork(app):
    """Lấy artwork 512; thử đổi đuôi sang PNG cho đúng chuẩn Apple, lỗi thì dùng bản gốc."""
    url = app["artworkUrl512"]
    png = re.sub(r"\.(jpg|jpeg)$", ".png", url, flags=re.I)
    for u in ([png, url] if png != url else [url]):
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


def parse_line(line):
    parts = [p.strip() for p in line.split("|")]
    query = parts[0]
    label = url = None
    if len(parts) == 2:
        url = parts[1]
    elif len(parts) >= 3:
        label, url = parts[1] or None, parts[2] or None
    return query, label, url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("list", help="file txt chứa danh sách app")
    ap.add_argument("-o", "--output", default="decor.mobileconfig")
    ap.add_argument("--base", help="profile có sẵn để nối thêm (vd decor.xml)")
    ap.add_argument("--country", default="vn")
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

    existing = {p.get("PayloadIdentifier") for p in profile["PayloadContent"]}
    lines = [l.strip() for l in open(a.list, encoding="utf-8")
             if l.strip() and not l.strip().startswith("#")]

    added, failed = 0, []
    for line in lines:
        query, label, url = parse_line(line)
        try:
            app = find_app(query, a.country)
            if not app:
                raise RuntimeError("không tìm thấy trên App Store")
            icon = best_artwork(app)
            name = label or app["trackName"].split(" - ")[0].split(":")[0].strip()
            ident_ = ident(name, app.get("trackId"))
            if ident_ in existing:
                print(f"[bỏ qua] {name}: đã có trong profile")
                continue
            payload = make_payload(name, url or app["trackViewUrl"], icon, ident_)
            profile["PayloadContent"].append(payload)
            existing.add(ident_)
            added += 1
            print(f"[ok] {query!r} -> {app['trackName']} (id {app.get('trackId')}), "
                  f"icon {len(icon)//1024} KB")
        except Exception as e:
            failed.append((line, str(e)))
            print(f"[lỗi] {line}: {e}")
        time.sleep(3.2)  # tránh vượt giới hạn tốc độ của iTunes API

    with open(a.output, "wb") as f:
        plistlib.dump(profile, f)
    print(f"\nXong: thêm {added} app, lỗi {len(failed)}. Tổng payload: "
          f"{len(profile['PayloadContent'])}. File: {a.output}")


if __name__ == "__main__":
    sys.exit(main())
