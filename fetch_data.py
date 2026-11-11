import os, re, json, datetime as dt, requests

A = "https://youtubeanalytics.googleapis.com/v2/reports"
Y = "https://www.googleapis.com/youtube/v3"
S = requests.Session()

r = requests.post("https://oauth2.googleapis.com/token", data={
    "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
    "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"})
r.raise_for_status()
S.headers["Authorization"] = "Bearer " + r.json()["access_token"]

today = dt.date.today()
END = (today - dt.timedelta(days=1)).isoformat()


def get(url, **p):
    r = S.get(url, params=p)
    r.raise_for_status()
    return r.json()


def rep(metrics, dims="", flt="", start="2017-01-01", sort="", n=0):
    p = dict(ids="channel==MINE", startDate=start, endDate=END)
    if dims: p["dimensions"] = dims
    if flt: p["filters"] = flt
    if sort: p["sort"] = sort
    if n: p["maxResults"] = n
    for ms in (metrics, [m for m in metrics if m != "dislikes"]):  # fallback without dislikes
        p["metrics"] = ",".join(ms)
        try:
            j = get(A, **p)
            h = [c["name"] for c in j["columnHeaders"]]
            return [dict(zip(h, row)) for row in j.get("rows", [])]
        except requests.HTTPError as e:
            print("WARN", dims, flt, e.response.text[:200])
    return []


KEYS = dict(views="views", minutes="estimatedMinutesWatched", avgDur="averageViewDuration",
            gained="subscribersGained", lost="subscribersLost", likes="likes",
            dislikes="dislikes", comments="comments", shares="shares")


def series(start, flt=""):
    rows = {r["day"]: r for r in rep(list(KEYS.values()), "day", flt, start)}
    d0 = dt.date.fromisoformat(start)
    days = [(d0 + dt.timedelta(i)).isoformat() for i in range((dt.date.fromisoformat(END) - d0).days + 1)]
    return days, {a: [rows.get(d, {}).get(b, 0) for d in days] for a, b in KEYS.items()}


def top(dim, metric, flt="", n=15, start="2017-01-01"):
    return [{"k": r[dim], "v": r[metric]} for r in rep([metric], dim, flt, start, "-" + metric, n)]


ch = get(Y + "/channels", part="snippet,statistics,contentDetails", mine="true")["items"][0]
uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
ids, tok = [], None
while True:
    j = get(Y + "/playlistItems", part="contentDetails", playlistId=uploads, maxResults=50, pageToken=tok)
    ids += [i["contentDetails"]["videoId"] for i in j["items"]]
    tok = j.get("nextPageToken")
    if not tok: break


def secs(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


videos = []
for i in range(0, len(ids), 50):
    for v in get(Y + "/videos", part="snippet,contentDetails,statistics", id=",".join(ids[i:i + 50]))["items"]:
        pub = v["snippet"]["publishedAt"]
        start = max(pub[:10], "2017-01-01")
        days, daily = series(start, "video==" + v["id"])
        ret = [r["audienceWatchRatio"] for r in rep(["audienceWatchRatio"], "elapsedVideoTimeRatio", "video==" + v["id"], start)]
        videos.append(dict(id=v["id"], title=v["snippet"]["title"], published=pub,
                           duration=secs(v["contentDetails"]["duration"]),
                           views=int(v["statistics"].get("viewCount", 0)),
                           days=days, daily=daily, retention=ret,
                           countries=top("country", "views", "video==" + v["id"], 10, start)))

days, daily = series((today - dt.timedelta(days=365)).isoformat())
st = ch["statistics"]
data = dict(
    updated=dt.datetime.utcnow().isoformat(timespec="seconds"),
    channel=dict(title=ch["snippet"]["title"], subs=int(st.get("subscriberCount", 0)),
                 views=int(st.get("viewCount", 0)), videos=int(st.get("videoCount", 0))),
    days=days, daily=daily,
    countries=top("country", "views"),
    traffic=top("insightTrafficSourceType", "views"),
    devices=top("deviceType", "views"),
    demographics=[{"k": f'{r["ageGroup"]}_{r["gender"]}', "v": r["viewerPercentage"]}
                  for r in rep(["viewerPercentage"], "ageGroup,gender", start=(today - dt.timedelta(days=365)).isoformat())],
    videos=videos)

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
print("OK", len(videos), "videos")
