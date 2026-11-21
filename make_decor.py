#!/usr/bin/env python3
"""
make_decor.py - Tạo / bổ sung file .mobileconfig (Web Clip) với icon lấy từ App Store.

Mỗi dòng trong apps.txt gồm các phần ngăn cách bằng "|":
  - Phần đầu: TÊN HIỂN THỊ bạn muốn (vd "Minecraft"), hoặc App Store ID, hoặc link App Store
  - Phần là ID số (>=5 chữ số) hoặc link apps.apple.com: dùng để tra app (chính xác hơn tên)
  - Phần có "://" khác apps.apple.com (vd fb-messenger://): URL mở khi bấm icon
  - Phần còn lại: nhãn hiển thị (nếu muốn khác với tên ở phần đầu)

Nhãn dưới icon = nhãn bạn đặt > tên bạn viết ở phần đầu > tên trên App Store (rút gọn).
Nên "Minecraft | 479516143" luôn ra nhãn "Minecraft", dù App Store ghi
"Minecraft: Play with Friends!".

Ví dụ:
  Minecraft | 479516143
  Instagram
  Messenger | fb-messenger://
  NIKKE: Goddess of Victory | NIKKE
"""
import argparse, difflib, json, os, plistlib, re, sys, time, unicodedata, uuid
import urllib.error, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 decor-maker"}
ID_RE = re.compile(r"^\d{5,}$")
STORE_RE = re.compile(r"apps\.apple\.com|itunes\.apple\.com")
MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")


def http_get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(20 * (i + 1) if e.code in (403, 429) else 2 * (i + 1))
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise last


def clean_label(s):
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[®™©]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def short_name(track_name):
    """Dùng khi dòng chỉ có ID/link: bỏ phụ đề 'Tên - mô tả', giữ nguyên ':' trong tên."""
    n = clean_label(track_name)
    return re.split(r"\s[-–—]\s", n)[0].strip() or n


def parse_line(line):
    """Trả về (khoá tra cứu, nhãn, URL mở)."""
    parts = [p.strip() for p in line.split("|") if p.strip()]
    lookup = parts[0]
    label = url = None
    for p in parts[1:]:
        if ID_RE.match(p) or STORE_RE.search(p):
            lookup = p
        elif "://" in p:
            url = p
        else:
            label = p
    return lookup, label, url


def first_part(line):
    return line.split("|")[0].strip()


def names_match(wanted, got):
    norm = lambda x: re.sub(r"[^0-9a-zà-ỹ]+", "", clean_label(x).casefold())
    a, b = norm(wanted), norm(got)
    if not a or not b:
        return True
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def lookup_in(query, country, wanted=None):
    m = re.search(r"id(\d{5,})", query) or ID_RE.match(query.strip())
    if m:
        key = m.group(1) if m.lastindex else query.strip()
        url = f"https://itunes.apple.com/lookup?id={key}&country={country}"
    else:
        q = urllib.parse.quote(query)
        url = (f"https://itunes.apple.com/search?term={q}&entity=software"
               f"&country={country}&limit=8")
    data = json.loads(http_get(url))
    results = [r for r in data.get("results", []) if r.get("artworkUrl512")]
    if not results:
        return None
    if m or not wanted:
        return results[0]
    for r in results:  # tìm theo tên: chỉ nhận kết quả có tên khớp, tránh app lạ
        if names_match(wanted, r["trackName"]):
            return r
    return None


def find_app(query, countries, wanted=None):
    for c in countries:
        app = lookup_in(query, c, wanted)
        if app:
            return app, c
        time.sleep(3.2)
    return None, None


def best_artwork(app, size, fmt):
    url = app["artworkUrl512"]
    base = re.sub(r"\d+x\d+bb\.\w+$", f"{size}x{size}bb", url)
    cands = [f"{base}.{fmt}", f"{base}.png", url] if base != url else [url]
    for u in cands:
        try:
            data = http_get(u)
            if data.startswith(MAGIC):
                return data
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("list", help="file txt chứa danh sách app")
    ap.add_argument("-o", "--output", default="decor.mobileconfig")
    ap.add_argument("--base", help="profile có sẵn để nối thêm (vd decor.xml)")
    ap.add_argument("--country", default="vn")
    ap.add_argument("--fallback", default="us",
                    help="store dự phòng nếu app không có ở --country ('' để tắt)")
    ap.add_argument("--size", type=int, default=180, help="cạnh icon: 512, 256, 180...")
    ap.add_argument("--fmt", choices=["jpg", "png"], default="jpg",
                    help="định dạng icon (jpg nhẹ hơn nhiều)")
    ap.add_argument("--replace", action="store_true",
                    help="thay payload cũ trùng nhãn/app thay vì bỏ qua")
    ap.add_argument("--report", default="apps_report.txt", help="file báo cáo kết quả")
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

    report, added, skipped, failed = [], 0, 0, []
    for n, line in enumerate(lines, 1):
        key, label, url = parse_line(line)
        try:
            hint = first_part(line)
            hint = None if (ID_RE.match(hint) or STORE_RE.search(hint)) else clean_label(hint)
            app, used = find_app(key, countries, wanted=hint)
            if hint and key != first_part(line) and key != hint:
                # đang tra bằng ID -> kiểm tra ID có đúng app không, sai thì tìm theo tên
                why = None
                if not app:
                    why = "ID không tồn tại"
                elif not names_match(hint, app["trackName"]):
                    why = f"ID ra '{app['trackName']}'"
                if why:
                    print(f"[cảnh báo] {hint}: {why} -> thử tìm theo tên")
                    time.sleep(3.2)
                    app, used = find_app(hint, countries, wanted=hint)
            if not app:
                raise RuntimeError(f"không tìm thấy app khớp tên (store: {', '.join(countries)})")

            name = clean_label(label) if label else (hint or short_name(app["trackName"]))
            tid = app.get("trackId")
            ident_ = ident(name, tid)
            same = [p for p in content
                    if p.get("PayloadIdentifier") == ident_
                    or p.get("Label", "").casefold() == name.casefold()
                    or (tid and f"id{tid}" in p.get("URL", ""))]
            if same and not a.replace:
                skipped += 1
                print(f"[bỏ qua] {name}: đã có trong profile ({same[0].get('Label')})")
                report.append(f"TRÙNG | {line} | trùng với '{same[0].get('Label')}'")
                continue
            icon = best_artwork(app, a.size, a.fmt)
            if same:
                content[:] = [p for p in content if p not in same]
            content.append(make_payload(name, url or app["trackViewUrl"], icon, ident_))
            added += 1
            note = "" if used == a.country else f" [store {used}]"
            print(f"[{n}/{len(lines)}] {line!r} -> {app['trackName']} (id {tid}){note}, "
                  f"icon {len(icon)//1024} KB")
            report.append(f"OK | {line} | {app['trackName']} | id {tid} | store {used}")
        except Exception as e:
            failed.append((line, str(e)))
            print(f"[lỗi] {line}: {e}")
            report.append(f"LỖI | {line} | {e}")
        time.sleep(3.2)  # tránh vượt giới hạn tốc độ của iTunes API

    with open(a.output, "wb") as f:
        plistlib.dump(profile, f)
    with open(a.report, "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    mb = os.path.getsize(a.output) / 1048576
    print(f"\nXong: thêm {added}, bỏ qua {skipped}, lỗi {len(failed)}. "
          f"Tổng payload: {len(content)}. File: {a.output} ({mb:.1f} MB)")
    if mb > 40:
        print("CẢNH BÁO: file > 40 MB, iPhone có thể cài lỗi/rất chậm. Giảm --size hoặc dùng --fmt jpg.")
    if failed:
        print("Các dòng lỗi:")
        for l, e in failed:
            print(f"  - {l}  ({e})")


if __name__ == "__main__":
    sys.exit(main())
