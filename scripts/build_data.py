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
"""
import json, os, re, sys
from datetime import datetime, timedelta, timezone

SGT = timezone(timedelta(hours=8))
DAILY_METRICS = ["IGEV01","IGEV05","IGEV13","IGEV14","IGEV27","IGEV28","IGEV39","IGEV40","IGEV43","IGEV44",
                 "TKEV07","TKEV02","TKEV03","TKEV04","TKEV05","TKEV16","TKEV17",
                 "YTEV01","YTEV02","YTEV10","YTEV12","YTEV19","YTEV05","YTEV06"]
MAP = {
  "instagram": {"followers_total":["IGEV01"],"views":["IGEV05"],"likes":["IGEV13","IGEV27"],"comments":["IGEV14","IGEV28"],"shares":["IGEV40","IGEV39"],"followers_gained":["IGEV43"],"followers_lost":["IGEV44"]},
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
                    x = num(r[DAILY_METRICS.index(i)]) if i in DAILY_METRICS else None
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
        for k in ("views","likes","comments","shares","followers_gained","followers_lost"):
            r[k] = int(r[k] or 0)
        if r["followers_total"] is not None: r["followers_total"] = int(r["followers_total"])
    rows.sort(key=lambda r: (r["date"], r["platform"]))
    return rows

def key_of(url):
    if not url: return None
    u = url.split("?")[0].rstrip("/")
    m = re.search(r"(?:shorts/|watch\?v=|youtu\.be/|/video/|/reel/|/p/)([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else u

def build_posts(raw):
    posts = {}
    for name in ("ig_reels.json","ig_posts.json","tt_videos.json","yt_videos.json"):
        for r in load(raw, name).get("rows", []) or []:
            k = key_of(r[2] if len(r) > 2 else None)
            if not k: continue
            posts[k] = {"views": int(num(r[3]) or 0), "likes": int(num(r[4]) or 0), "comments": int(num(r[5]) or 0), "shares": int(num(r[6]) or 0)}
    return posts

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
                        "post_url": url, "metrics": posts.get(key_of(url)) if url else None})
    out.sort(key=lambda u: u["scheduled_at"], reverse=True)
    return out

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
      "uploads": build_uploads(raw, build_posts(raw)),
    }
    with open(out_file, "w") as f: json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"Wrote {out_file}: {len(daily)} daily rows, {len(data['uploads'])} uploads")

if __name__ == "__main__":
    main()
