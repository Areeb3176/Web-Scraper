# utils.py
from datetime import datetime
import re

def generate_unique_name(url: str) -> str:
    """
    Generate a unique name for the folder based on the URL.
    """
    timestamp = datetime.now().strftime('%Y_%m_%d__%H_%M_%S_%f')
    # Sanitize domain: replace non-alphanumeric with underscore, ensure it's not too long
    domain_part = url.split('//')[-1].split('/')[0]
    sanitized_domain = re.sub(r'\W+', '_', domain_part)
    sanitized_domain = (sanitized_domain[:50]) if len(sanitized_domain) > 50 else sanitized_domain # Limit length
    return f"{sanitized_domain}_{timestamp}"

# The calculate_price function was commented out in your original file, so I'll keep it that way.
# If you need it, LiteLLM's completion_cost usually handles this.
# def calculate_price(token_counts, model):
#     """
#     Calculate the cost based on input/output tokens and model pricing.
#     """
#     # ...