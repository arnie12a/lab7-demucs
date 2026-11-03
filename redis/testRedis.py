import redis

r = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True
)

r.lpush("toWorkers", "test_song")

print(r.blpop("toWorkers", timeout=5))
