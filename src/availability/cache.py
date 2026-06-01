import hashlib
import json
import time
from django.core.cache import cache

def get_events_cache_version(user_id):
    if not user_id:
        return "anonymous"
    key = f"user_events_version:{user_id}"
    version = cache.get(key)
    if not version:
        version = str(time.time())
        cache.set(key, version, timeout=86400)  # expires in 24 hours
    return version

def get_events_cache_key(user_id, action_name, query_params):
    version = get_events_cache_version(user_id)
    params_dict = {}
    if query_params:
        for k, v in query_params.items():
            params_dict[k] = v
            
    sorted_params = sorted(params_dict.items())
    params_str = json.dumps(sorted_params)
    params_hash = hashlib.md5(params_str.encode('utf-8')).hexdigest()
    return f"user_events:{user_id}:v{version}:{action_name}:{params_hash}"

def invalidate_events_cache(user_id):
    if user_id:
        key = f"user_events_version:{user_id}"
        cache.delete(key)

def get_holidays_cache_version(user_id):
    if not user_id:
        return "anonymous"
    key = f"user_holidays_version:{user_id}"
    version = cache.get(key)
    if not version:
        version = str(time.time())
        cache.set(key, version, timeout=86400)  # expires in 24 hours
    return version

def get_holidays_cache_key(user_id, action_name, query_params):
    version = get_holidays_cache_version(user_id)
    params_dict = {}
    if query_params:
        for k, v in query_params.items():
            params_dict[k] = v
            
    sorted_params = sorted(params_dict.items())
    params_str = json.dumps(sorted_params)
    params_hash = hashlib.md5(params_str.encode('utf-8')).hexdigest()
    return f"user_holidays:{user_id}:v{version}:{action_name}:{params_hash}"

def invalidate_holidays_cache(user_id):
    if user_id:
        key = f"user_holidays_version:{user_id}"
        cache.delete(key)
