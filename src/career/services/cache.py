import hashlib
import json
import time
from django.core.cache import cache

def get_applications_cache_version(user_id):
    if not user_id:
        return "anonymous"
    key = f"user_applications_version:{user_id}"
    version = cache.get(key)
    if not version:
        version = str(time.time())
        cache.set(key, version, timeout=86400)  # expires in 24 hours
    return version

def get_applications_cache_key(user_id, action_name, query_params):
    version = get_applications_cache_version(user_id)
    params_dict = {}
    if query_params:
        for k, v in query_params.items():
            params_dict[k] = v
            
    sorted_params = sorted(params_dict.items())
    params_str = json.dumps(sorted_params)
    params_hash = hashlib.md5(params_str.encode('utf-8')).hexdigest()
    return f"user_applications:{user_id}:v{version}:{action_name}:{params_hash}"

def invalidate_applications_cache(user_id):
    if user_id:
        key = f"user_applications_version:{user_id}"
        cache.delete(key)

def get_experiences_cache_version(user_id):
    if not user_id:
        return "anonymous"
    key = f"user_experiences_version:{user_id}"
    version = cache.get(key)
    if not version:
        version = str(time.time())
        cache.set(key, version, timeout=86400)  # expires in 24 hours
    return version

def get_experiences_cache_key(user_id, action_name, query_params):
    version = get_experiences_cache_version(user_id)
    params_dict = {}
    if query_params:
        for k, v in query_params.items():
            params_dict[k] = v
            
    sorted_params = sorted(params_dict.items())
    params_str = json.dumps(sorted_params)
    params_hash = hashlib.md5(params_str.encode('utf-8')).hexdigest()
    return f"user_experiences:{user_id}:v{version}:{action_name}:{params_hash}"

def invalidate_experiences_cache(user_id):
    if user_id:
        key = f"user_experiences_version:{user_id}"
        cache.delete(key)

def get_tasks_cache_version(user_id):
    if not user_id:
        return "anonymous"
    key = f"user_tasks_version:{user_id}"
    version = cache.get(key)
    if not version:
        version = str(time.time())
        cache.set(key, version, timeout=86400)  # expires in 24 hours
    return version

def get_tasks_cache_key(user_id, action_name, query_params):
    version = get_tasks_cache_version(user_id)
    params_dict = {}
    if query_params:
        for k, v in query_params.items():
            params_dict[k] = v
            
    sorted_params = sorted(params_dict.items())
    params_str = json.dumps(sorted_params)
    params_hash = hashlib.md5(params_str.encode('utf-8')).hexdigest()
    return f"user_tasks:{user_id}:v{version}:{action_name}:{params_hash}"

def invalidate_tasks_cache(user_id):
    if user_id:
        key = f"user_tasks_version:{user_id}"
        cache.delete(key)

def get_ai_artifacts_cache_version(user_id):
    if not user_id:
        return "anonymous"
    key = f"user_ai_artifacts_version:{user_id}"
    version = cache.get(key)
    if not version:
        version = str(time.time())
        cache.set(key, version, timeout=86400)  # expires in 24 hours
    return version

def get_ai_artifacts_cache_key(user_id, action_name, query_params):
    version = get_ai_artifacts_cache_version(user_id)
    params_dict = {}
    if query_params:
        for k, v in query_params.items():
            params_dict[k] = v
            
    sorted_params = sorted(params_dict.items())
    params_str = json.dumps(sorted_params)
    params_hash = hashlib.md5(params_str.encode('utf-8')).hexdigest()
    return f"user_ai_artifacts:{user_id}:v{version}:{action_name}:{params_hash}"

def invalidate_ai_artifacts_cache(user_id):
    if user_id:
        key = f"user_ai_artifacts_version:{user_id}"
        cache.delete(key)
