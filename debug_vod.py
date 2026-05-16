import os, sys
sys.path.insert(0, "src")
from src.services.research import ResearchService

s = ResearchService(
    config_path="config", data_dir="data",
    twitch_client_id="ubva9cb33zyehaoc6mbwl03dpb20z5",
    twitch_client_secret="zanz2itfc9jc2h3lbh08t1j16b1me9",
)

live = s.get_live_streamers()
print("Live streamers:", [(l["name"], l.get("stream_info", {}).get("user_id")) for l in live])

for l in live:
    uid = l["stream_info"]["user_id"]
    vod = s._get_vod_id(uid)
    started = l["stream_info"]["started_at"]
    print(f"{l['name']} user_id={uid} vod_id={vod} started_at={started}")
