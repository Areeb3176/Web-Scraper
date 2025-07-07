# api_management.py
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from assets import MODELS_USED

load_dotenv() # Ensures .env is loaded when this module is imported

def get_api_key(model: str) -> str | None:
    if model not in MODELS_USED:
        print(f"WARNING: Model '{model}' not found in MODELS_USED configuration (api_management.py).")
        return None
    env_var_name_set = MODELS_USED[model]
    if not env_var_name_set:
        print(f"WARNING: No API key environment variable name configured for model '{model}' in MODELS_USED (api_management.py).")
        return None
    env_var_name = list(env_var_name_set)[0]
    api_key = os.getenv(env_var_name)
    if not api_key:
        print(f"WARNING: Environment variable '{env_var_name}' for model '{model}' not found or is empty (api_management.py).")
    # else:
        # print(f"DEBUG: Found API key for model '{model}' in env var '{env_var_name}'.") # Avoid printing this too often
    return api_key

def get_supabase_client() -> Client | None:
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_ANON_KEY')

    if not supabase_url:
        print("ERROR: SUPABASE_URL not configured properly or uses placeholder value (api_management.py).")
        return None
    if not supabase_key:
        print("ERROR: SUPABASE_ANON_KEY not configured properly or uses placeholder value (api_management.py).")
        return None
    
    print("DEBUG: Attempting to create Supabase client with provided URL and Key (api_management.py).")
    try:
        client = create_client(supabase_url, supabase_key)
        print("INFO: Supabase client created successfully (api_management.py).")
        return client
    except Exception as e:
        print(f"CRITICAL ERROR creating Supabase client: {e} (api_management.py)")
        return None

supabase_client_instance = get_supabase_client()