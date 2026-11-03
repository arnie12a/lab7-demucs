import json
import redis

r = redis.Redis(host="localhost", port=6379)

job = {
    "song_id": "test123",
    "object_name": "test123.mp3",
    "callback": None
}

r.lpush("toWorkers", json.dumps(job))
print("Job submitted")
