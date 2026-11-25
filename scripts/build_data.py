#!/usr/bin/env python3
"""Build data.json for the dashboard from raw Metricool answers.

Usage: python3 scripts/build_data.py RAW_DIR OUT_FILE
RAW_DIR holds the Metricool tool answers saved as JSON:
  daily.json       getAnalyticsDataByMetrics with DAILY_METRICS (in this order)
  ig_reels.json    getAnalyticsDataByMetrics with IG_REELS
  ig_posts.json    getAnalyticsDataByMetrics with IG_POSTS
  tt_videos.json   getAnalyticsDataByMetrics with TT_VIDEOS
  yt_videos.json   getAnalyticsDataByMetrics with YT_VIDEOS
  planner.json     getScheduledPosts
  best_<platform>.json  getBestTimeToPostByNetwork for instagram, tiktok, youtube
YouTube comes from Windsor.ai when these files are present (each a get_data answer):
  yt_w_daily.json   fields date, views, likes, comments, shares, subscribers_gained_channel, subscribers_lost_channel
  yt_w_videos.json  fields video, video_title, published_at, video_view_count, video_like_count, video_comment_count, videourl, videoimage
  yt_w_watch.json   fields video, shares, estimated_minutes_watched, average_view_duration
  yt_w_channel.json fields subscriber_count
"""
import json, os, re, sys
from datetime import datetime, timedelta, timezone

SGT = timezone(timedelta(hours=8))
DAILY_METRICS = ["IGEV01","IGEV05","IGEV13","IGEV14","IGEV27","IGEV28","IGEV39","IGEV40","IGEV43","IGEV44",
                 "TKEV07","TKEV02","TKEV03","TKEV04","TKEV05","TKEV16","TKEV17",
                 "YTEV01","YTEV02","YTEV10","YTEV12","YTEV19","YTEV05","YTEV06",
                 "IGEV15","IGEV29"]
MAP = {
  "instagram": {"followers_total":["IGEV01"],"views":["IGEV05"],"likes":["IGEV13","IGEV27"],"comments":["IGEV14","IGEV28"],"shares":["IGEV40","IGEV39"],"followers_gained":["IGEV43"],"followers_lost":["IGEV44"],"saves":["IGEV15","IGEV29"]},
  "tiktok":    {"followers_total":["TKEV07"],"views":["TKEV02"],"likes":["TKEV03"],"comments":["TKEV04"],"shares":["TKEV05"],"followers_gained":["TKEV16"],"followers_lost":["TKEV17"]},
  "youtube":   {"followers_total":["YTEV01"],"views":["YTEV02"],"likes":["YTEV10"],"comments":["YTEV12"],"shares":["YTEV19"],"followers_gained":["YTEV05"],"followers_lost":["YTEV06"]},
}

def load(raw, name):
    p = os.path.join(raw, name)
    if not os.path.exists(p): return {}
    with open(p) as f: txt = f.read().strip()
    if not txt: return {}
    a = json.loads(txt)
    if isinstance(a, str): a = json.loads(a)
    if isinstance(a, dict) and "result" in a and len(a) == 1: a = a["result"]
    if isinstance(a, str): a = json.loads(a)
    return a

def num(v):
    if v is None or v == "": return None
    try: return float(v)
    except Exception: return None

def build_daily(ans, today):
    out = {}
    for r in ans.get("rows", []) or []:
        d = str(r[-1]); date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if date > today: continue
        for p, m in MAP.items():
            row = {"date": date, "platform": p}; anyv = False
            for k, ids in m.items():
                v = None
                for i in ids:
                    j = DAILY_METRICS.index(i) if i in DAILY_METRICS else -1
                    x = num(r[j]) if 0 <= j < len(r) - 1 else None
                    if x is not None: v = (v or 0) + x
                row[k] = v
                if v is not None: anyv = True
            if anyv: out[(p, date)] = row
    rows = sorted(out.values(), key=lambda r: (r["platform"], r["date"]))
    # Where Metricool gives a follower total but no gained/lost, take the change in the total.
    last = {}
    for r in rows:
        t, prev = r["followers_total"], last.get(r["platform"])
        if r["followers_gained"] is None and r["followers_lost"] is None and t is not None and prev is not None:
            diff = t - prev; r["followers_gained"] = max(diff, 0); r["followers_lost"] = max(-diff, 0)
        if t is not None: last[r["platform"]] = t
    for r in rows:
        for k in ("views","likes","comments","shares","followers_gained","followers_lost","saves"):
            r[k] = int(r.get(k) or 0)
        if r["followers_total"] is not None: r["followers_total"] = int(r["followers_total"])
    rows.sort(key=lambda r: (r["date"], r["platform"]))
    return rows

def key_of(url):
    if not url: return None
    u = url.split("?")[0].rstrip("/")
    m = re.search(r"(?:shorts/|watch\?v=|youtu\.be/|/video/|/reel/|/p/)([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else u

# Column layout of each post list, in the order the metrics are requested.
POST_LISTS = {
  "ig_reels.json":  ("instagram", ["published","text","url","views","likes","comments","shares","thumb","saves","avg_watch","watch"]),
  "ig_posts.json":  ("instagram", ["published","text","url","views","likes","comments","shares","thumb","saves"]),
  "tt_videos.json": ("tiktok",    ["published","text","url","views","likes","comments","shares","thumb","watch","completion"]),
  "yt_videos.json": ("youtube",   ["published","title","url","views","likes","comments","shares","thumb","watch_minutes","avg_watch"]),
}

def iso_utc(v):
    v = str(v or "")
    if re.fullmatch(r"\d{14}", v): return f"{v[:4]}-{v[4:6]}-{v[6:8]}T{v[8:10]}:{v[10:12]}:{v[12:14]}Z"
    if re.fullmatch(r"\d{8}", v): return f"{v[:4]}-{v[4:6]}-{v[6:8]}T00:00:00Z"
    return v or None

def build_posts(raw):
    posts = {}
    for name, (platform, cols) in POST_LISTS.items():
        for r in load(raw, name).get("rows", []) or []:
            c = dict(zip(cols, r))
            k = key_of(c.get("url"))
            if not k: continue
            views = int(num(c.get("views")) or 0)
            watch = num(c.get("watch"))
            if c.get("watch_minutes") is not None: watch = (num(c.get("watch_minutes")) or 0) * 60
            avg = num(c.get("avg_watch"))
            if avg is None and watch is not None and views: avg = watch / views
            title = c.get("title") or re.split(r"\n| \u2014 | DM ", str(c.get("text") or ""))[0].strip()
            url = str(c.get("url") or "").split("?")[0] if platform == "tiktok" else c.get("url")
            posts[k] = {"key": k, "platform": platform, "published": iso_utc(c.get("published")), "title": title or "Untitled",
                        "url": url, "thumb": c.get("thumb") or None,
                        "views": views, "likes": int(num(c.get("likes")) or 0), "comments": int(num(c.get("comments")) or 0),
                        "shares": int(num(c.get("shares")) or 0),
                        "saves": None if c.get("saves") is None and platform != "instagram" else int(num(c.get("saves")) or 0),
                        "watch_seconds": None if watch is None else round(watch, 1),
                        "avg_watch_seconds": None if avg is None else round(avg, 2),
                        "completion_rate": num(c.get("completion"))}
    return posts

def yt_thumb(url):
    m = re.search(r"(?:shorts/|watch\?v=|youtu\.be/)([A-Za-z0-9_-]{6,})", url or "")
    return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg" if m else None

def build_uploads(raw, posts):
    out = []
    for p in (load(raw, "planner.json").get("data") or []):
        if p.get("draft"): continue
        for pr in p.get("providers") or []:
            net = pr.get("network")
            if net not in MAP: continue
            st = str(pr.get("status") or "").upper()
            status = "success" if re.search("PUBLISHED|SUCCESS|DONE", st) else "failed" if re.search("ERROR|FAIL|REJECT", st) else "pending"
            title = ((p.get("youtubeData") or {}).get("title") if net == "youtube" else None) or \
                    ((p.get("tiktokData") or {}).get("title") if net == "tiktok" else None) or \
                    (str(p.get("text") or "").split("\n")[0].strip()) or "Untitled"
            url = pr.get("publicUrl") or (pr.get("id") if str(pr.get("id") or "").startswith("http") else None)
            when = ((p.get("publicationDate") or {}).get("dateTime") or "")
            when = when + "+08:00" if when and "+" not in when else when
            out.append({"id": f"{p.get('id')}-{net}", "platform": net, "title": title,
                        "workflow": "Metricool · " + ("auto-publish" if p.get("autoPublish") else "manual publish"),
                        "scheduled_at": when, "posted_at": when if status == "success" else None,
                        "status": status, "error": (pr.get("errorMessage") or pr.get("error") or pr.get("detailedStatus") or "Failed") if status == "failed" else None,
                        "post_url": url, "media": (p.get("media") or [None])[0],
                        "metrics": ({k: posts[key_of(url)][k] for k in ("views","likes","comments","shares")} if url and key_of(url) in posts else None)})
    out.sort(key=lambda u: u["scheduled_at"], reverse=True)
    return out

def build_gallery(posts, uploads):
    items = {k: dict(v) for k, v in posts.items()}
    for u in uploads:
        if u["status"] != "success" or not u.get("post_url"): continue
        k = key_of(u["post_url"])
        it = items.get(k)
        if it is None:
            it = items[k] = {"key": k, "platform": u["platform"], "published": u["scheduled_at"], "title": u["title"], "url": u["post_url"],
                             "thumb": None, "views": None, "likes": None, "comments": None, "shares": None, "saves": None,
                             "watch_seconds": None, "avg_watch_seconds": None, "completion_rate": None}
        if u["platform"] != "instagram": it["title"] = u["title"]
        it["media"] = it.get("media") or u.get("media")
        if u["platform"] == "youtube": it["thumb"] = it.get("thumb") or yt_thumb(u["post_url"])
    out = sorted(items.values(), key=lambda p: p.get("published") or "", reverse=True)
    for p in out: p.setdefault("media", None)
    return out

def build_best_times(raw):
    out = {}
    for p in MAP:
        cells = []
        for d in (load(raw, f"best_{p}.json").get("data") or []):
            for h in d.get("bestTimesByHour") or []:
                cells.append([int(d["dayOfWeek"]), int(h["hourOfDay"]), num(h.get("value")) or 0])
        if cells: out[p] = cells
    return out

def wrows(raw, name):
    a = load(raw, name)
    if isinstance(a, dict): a = a.get("data") or []
    return a if isinstance(a, list) else []

def apply_windsor_youtube(raw, daily, posts, today):
    wd, wv = wrows(raw, "yt_w_daily.json"), wrows(raw, "yt_w_videos.json")
    if not wd and not wv: return False
    if wd:
        old = {r["date"]: r for r in daily if r["platform"] == "youtube"}
        daily[:] = [r for r in daily if r["platform"] != "youtube"]
        for w in wd:
            d = str(w.get("date"))[:10]
            if d > today: continue
            r = old.pop(d, {"date": d, "platform": "youtube", "followers_total": None})
            r.update({"views": int(num(w.get("views")) or 0), "likes": int(num(w.get("likes")) or 0), "comments": int(num(w.get("comments")) or 0),
                      "shares": int(num(w.get("shares")) or 0), "followers_gained": int(num(w.get("subscribers_gained_channel")) or 0),
                      "followers_lost": int(num(w.get("subscribers_lost_channel")) or 0), "saves": 0})
            daily.append(r)
        for r in old.values():  # keep Metricool subscriber totals for days Windsor has no row
            r.update({"views": 0, "likes": 0, "comments": 0, "shares": 0, "followers_gained": 0, "followers_lost": 0}); daily.append(r)
    ch = wrows(raw, "yt_w_channel.json")
    subs = num(ch[0].get("subscriber_count")) if ch else None
    if subs is not None:
        t = next((r for r in daily if r["platform"] == "youtube" and r["date"] == today), None)
        if t is None:
            t = {"date": today, "platform": "youtube", "views": 0, "likes": 0, "comments": 0, "shares": 0, "followers_gained": 0, "followers_lost": 0, "saves": 0}
            daily.append(t)
        t["followers_total"] = int(subs)
    if wv:
        watch = {w.get("video"): w for w in wrows(raw, "yt_w_watch.json")}
        for k in [k for k, p in posts.items() if p["platform"] == "youtube"]: del posts[k]
        for v in wv:
            vid = v.get("video")
            if not vid: continue
            w = watch.get(vid, {})
            mins = num(w.get("estimated_minutes_watched"))
            pub = str(v.get("published_at") or "")
            posts[vid] = {"key": vid, "platform": "youtube", "published": pub if pub.endswith("Z") or not pub else pub + ("Z" if "T" in pub else "T00:00:00Z"),
                          "title": v.get("video_title") or "Untitled", "url": v.get("videourl") or f"https://www.youtube.com/shorts/{vid}",
                          "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                          "views": int(num(v.get("video_view_count")) or 0), "likes": int(num(v.get("video_like_count")) or 0),
                          "comments": int(num(v.get("video_comment_count")) or 0), "shares": int(num(w.get("shares")) or 0) if w else None,
                          "saves": None, "watch_seconds": None if mins is None else round(mins * 60, 1),
                          "avg_watch_seconds": num(w.get("average_view_duration")), "completion_rate": None}
    daily.sort(key=lambda r: (r["date"], r["platform"]))
    return True

def carry_over(data, prev):
    """Keep the last good figures when a source briefly returns nothing (e.g. after a reconnect)."""
    if not prev: return
    old = {(r["platform"], r["date"]): r for r in prev.get("daily", [])}
    new = {(r["platform"], r["date"]): r for r in data["daily"]}
    for k, o in old.items():
        n = new.get(k)
        if n is None:
            data["daily"].append(o); continue
        for f in ("views", "likes", "comments", "shares", "saves"):
            if not n.get(f) and o.get(f): n[f] = o[f]
        if n.get("followers_total") is None and o.get("followers_total") is not None: n["followers_total"] = o["followers_total"]
    data["daily"].sort(key=lambda r: (r["date"], r["platform"]))
    have = {p["key"] for p in data["posts"]}
    old_posts = {p["key"]: p for p in prev.get("posts", [])}
    for p in data["posts"]:
        o = old_posts.get(p["key"])
        if o:
            for f in ("views", "likes", "comments", "shares", "saves", "watch_seconds", "avg_watch_seconds", "completion_rate", "thumb", "media"):
                if p.get(f) in (None, 0) and o.get(f) not in (None, 0): p[f] = o[f]
    data["posts"] += [o for k, o in old_posts.items() if k not in have]
    data["posts"].sort(key=lambda p: p.get("published") or "", reverse=True)
    for u in data["uploads"]:
        if u.get("metrics") is None and u.get("post_url"):
            o = old_posts.get(key_of(u["post_url"]))
            if o and o.get("views") is not None:
                u["metrics"] = {f: o.get(f) or 0 for f in ("views", "likes", "comments", "shares")}

def main():
    raw, out_file = sys.argv[1], sys.argv[2]
    now = datetime.now(SGT)
    today = now.strftime("%Y-%m-%d")
    daily = build_daily(load(raw, "daily.json"), today)
    if not daily: sys.exit("No daily rows from Metricool; leaving data.json unchanged.")
    data = {
      "meta": {"brand": "Precious Jewellery Designs", "timezone": "Asia/Singapore",
               "as_of": today, "source": "Metricool", "pulled_at": now.strftime("%Y-%m-%dT%H:%M:00+08:00"), "data_url": ""},
      "accounts": [{"platform": "instagram", "handle": "@ptc.sg"}, {"platform": "tiktok", "handle": "@ptc.sg"}, {"platform": "youtube", "handle": "PTC channel"}],
      "daily": daily,
    }
    posts = build_posts(raw)
    data["meta"]["youtube_source"] = "Windsor.ai" if apply_windsor_youtube(raw, daily, posts, today) else "Metricool"
    data["uploads"] = build_uploads(raw, posts)
    data["posts"] = build_gallery(posts, data["uploads"])
    data["best_times"] = build_best_times(raw)
    try:
        with open(out_file) as f: prev = json.load(f)
    except Exception:
        prev = None
    carry_over(data, prev)
    with open(out_file, "w") as f: json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"Wrote {out_file}: {len(daily)} daily rows, {len(data['uploads'])} uploads, {len(data['posts'])} posts, best times for {', '.join(data['best_times']) or 'none'}")

if __name__ == "__main__":
    main()
