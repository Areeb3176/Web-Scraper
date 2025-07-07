# app.py
from flask import Flask, request, jsonify, send_from_directory, Blueprint, redirect # <--- Add Blueprint and redirect
from flask_cors import CORS
import os
from dotenv import load_dotenv
import re # For URL validation
import traceback # For detailed error logging

# Load environment variables from .env file
load_dotenv()
print("DEBUG: .env file loaded (or attempted to load).")

# Import your backend modules
from api_management import supabase_client_instance as supabase
from assets import OPENAI_MODEL_FULLNAME, GEMINI_MODEL_FULLNAME, DEEPSEEK_MODEL_FULLNAME
from markdown import fetch_and_store_markdowns
from scraper import scrape_urls
from pagination import paginate_urls

# By default, Flask looks for a 'static' folder at the same level as app.py
app = Flask(__name__)
CORS(app)

if not supabase:
    print("CRITICAL: Supabase client could not be initialized. Check .env variables (SUPABASE_URL, SUPABASE_ANON_KEY) and Supabase status.")
else:
    print("INFO: Supabase client initialized successfully.")

# --- YOUR API ROUTES ---
# These remain unchanged as they are correctly prefixed with /api
@app.route('/api/health', methods=['GET'])
def health_check():
    db_status = "connected" if supabase else "disconnected"
    print(f"DEBUG: Health check called. DB status: {db_status}")
    return jsonify({"status": "healthy", "database": db_status})

@app.route('/api/models', methods=['GET'])
def get_models():
    available_models = [
        OPENAI_MODEL_FULLNAME,
        GEMINI_MODEL_FULLNAME,
        DEEPSEEK_MODEL_FULLNAME
    ]
    default_model = OPENAI_MODEL_FULLNAME
    print(f"DEBUG: Models endpoint called. Models: {available_models}, Default: {default_model}")
    return jsonify({
        "models": available_models,
        "default": default_model
    })

@app.route('/api/validate-urls', methods=['POST'])
def validate_urls_route():
    print("DEBUG: /api/validate-urls endpoint called.")
    data = request.get_json()
    urls_to_validate = data.get('urls', [])
    if not isinstance(urls_to_validate, list):
        print("ERROR: /api/validate-urls - URLs not a list.")
        return jsonify({"success": False, "error": "URLs must be a list"}), 400

    invalid_urls = []
    url_pattern = re.compile(
        r'^(?:http|ftp)s?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    for u in urls_to_validate:
        if not (isinstance(u, str) and re.match(url_pattern, u)):
            invalid_urls.append(u)
    
    if invalid_urls:
        print(f"DEBUG: /api/validate-urls - Invalid URLs found: {invalid_urls}")
        return jsonify({"success": False, "invalid_urls": invalid_urls, "message": "Some URLs are invalid."})
    print("DEBUG: /api/validate-urls - All URLs seem valid.")
    return jsonify({"success": True, "message": "All URLs seem valid."})


@app.route('/api/scrape', methods=['POST'])
def handle_scrape():
    print("DEBUG: /api/scrape endpoint called.")
    if not supabase:
        print("ERROR: /api/scrape - Supabase client not initialized.")
        return jsonify({"success": False, "error": "Supabase client not initialized. Cannot process request."}), 500

    try:
        data = request.get_json()
        if not data:
            print("ERROR: /api/scrape - No JSON data received.")
            return jsonify({"success": False, "error": "No JSON data received"}), 400
        
        print(f"DEBUG: /api/scrape - Received data: {data}")

        urls_to_process = data.get('urls', [])
        fields_to_extract = data.get('fields', [])
        selected_model = data.get('model')
        enable_pagination = data.get('use_pagination', False)
        enable_scraping = data.get('enable_scraping', False)

        if not urls_to_process or not isinstance(urls_to_process, list):
            print("ERROR: /api/scrape - URLs list is required and must be a list.")
            return jsonify({"success": False, "error": "URLs list is required and must be a list."}), 400
        if not selected_model:
            print("ERROR: /api/scrape - Model selection is required.")
            return jsonify({"success": False, "error": "Model selection is required."}), 400
        if enable_scraping and (not fields_to_extract or not isinstance(fields_to_extract, list) or not fields_to_extract):
            print("ERROR: /api/scrape - Non-empty Fields list is required for scraping.")
            return jsonify({"success": False, "error": "Non-empty Fields list is required for scraping."}), 400

        print(f"DEBUG: /api/scrape - Fetching markdowns for: {urls_to_process}")
        unique_names = fetch_and_store_markdowns(urls_to_process)
        print(f"DEBUG: /api/scrape - unique_names from fetch_and_store_markdowns: {unique_names}")
        
        if not unique_names:
            print("WARNING: /api/scrape - No unique names generated, possibly all markdown fetches failed or URLs were invalid.")
            return jsonify({
                "success": True, 
                "data": {
                    "scraping_data": [],
                    "pagination_data": [],
                    "statistics": {
                        "urls_processed": 0,
                        "fields_extracted": 0,
                        "total_input_tokens": 0,
                        "total_output_tokens": 0,
                        "total_cost": "$0.000000",
                        "pagination_urls_found": 0
                    }
                },
                "message": "No valid URLs could be processed for markdown."
            })

        total_input_tokens = 0
        total_output_tokens = 0
        total_combined_cost = 0.0
        # scraped_data_results will store the direct output from scrape_urls
        scraped_data_from_urls = [] 
        all_scraped_rows_for_table = [] # This will be the flattened list for the frontend table
        pagination_data_results = []
        urls_actually_processed_count = len(unique_names)
        fields_extracted_overall_count = 0
        pagination_urls_found_count = 0

        if enable_scraping and unique_names and fields_to_extract:
            print(f"DEBUG: /api/scrape - Calling scrape_urls with unique_names: {unique_names}, fields: {fields_to_extract}, model: {selected_model}")
            s_in_tokens, s_out_tokens, s_cost, scraped_items_structured = scrape_urls(
                unique_names, fields_to_extract, selected_model
            )
            # scraped_items_structured is: [{"unique_name": str, "items": List[Dict]}, ...]
            print(f"DEBUG: /api/scrape - scrape_urls returned: tokens_in={s_in_tokens}, tokens_out={s_out_tokens}, cost={s_cost}, groups_count={len(scraped_items_structured)}")
            
            if scraped_items_structured:
                scraped_data_from_urls.extend(scraped_items_structured)
                # Flatten the items for the table view
                for group in scraped_items_structured:
                    if group and "items" in group and isinstance(group["items"], list):
                        all_scraped_rows_for_table.extend(group["items"])
                
                if all_scraped_rows_for_table:
                     print(f"DEBUG: /api/scrape - First processed row for table (if any): {all_scraped_rows_for_table[0]}")
                else:
                    print(f"DEBUG: /api/scrape - No rows processed for table from scrape_urls output.")

            total_input_tokens += s_in_tokens
            total_output_tokens += s_out_tokens
            total_combined_cost += s_cost
            
            # Calculate fields_extracted based on the flattened list and requested fields
            if fields_to_extract and all_scraped_rows_for_table:
                # More accurate count (actual fields present):
                for row in all_scraped_rows_for_table:
                    for field_name in fields_to_extract:
                        if field_name in row and row[field_name] is not None and str(row[field_name]).strip() != "":
                            fields_extracted_overall_count +=1


        if enable_pagination and unique_names:
            print(f"DEBUG: /api/scrape - Calling paginate_urls for unique_names: {unique_names}, model: {selected_model}")
            source_urls_for_pagination = urls_to_process[:len(unique_names)]
            print(f"DEBUG: /api/scrape - Source URLs for pagination: {source_urls_for_pagination}")

            p_in_tokens, p_out_tokens, p_cost, pag_urls_found_list = paginate_urls(
                unique_names, selected_model, indication="", source_urls=source_urls_for_pagination
            )
            print(f"DEBUG: /api/scrape - paginate_urls returned: tokens_in={p_in_tokens}, tokens_out={p_out_tokens}, cost={p_cost}, urls_found_count={len(pag_urls_found_list)}")
            if pag_urls_found_list:
                print(f"DEBUG: /api/scrape - First pagination URL item (if any): {pag_urls_found_list[0]}")

            total_input_tokens += p_in_tokens
            total_output_tokens += p_out_tokens
            total_combined_cost += p_cost
            pagination_data_results.extend(pag_urls_found_list)
            pagination_urls_found_count = len(pag_urls_found_list)

        response_payload = {
            "success": True,
            "data": {
                "scraping_data": all_scraped_rows_for_table, # This is List[Dict]
                "pagination_data": pagination_data_results,
                "statistics": {
                    "urls_processed": urls_actually_processed_count,
                    "fields_extracted": fields_extracted_overall_count,
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                    "total_cost": f"${total_combined_cost:.6f}",
                    "pagination_urls_found": pagination_urls_found_count
                }
            }
        }
        print(f"DEBUG: /api/scrape - Final response_payload being sent (first 200 chars of data): {str(response_payload)[:200]}...")
        return jsonify(response_payload)

    except Exception as e:
        print(f"CRITICAL ERROR in /api/scrape: {e}")
        traceback.print_exc() 
        return jsonify({"success": False, "error": str(e), "trace": traceback.format_exc()}), 500

# --- NEW: SCRAPER APP & STATIC FILE SERVING via Blueprint ---

# Create a Blueprint to encapsulate the frontend application.
# This allows us to mount the entire app under the '/scraper' prefix.
scraper_bp = Blueprint(
    'scraper_app',
    __name__,
    static_folder='static',
    # The static_url_path is relative to the blueprint's URL prefix.
    # When registered, requests to '/scraper/static/...' will be served from the 'static' folder.
    static_url_path='/static'
)

# This route serves the main 'index.html' at the root of the blueprint.
# When registered, it will be accessible at http://127.0.0.1:5000/scraper
@scraper_bp.route('/')
def serve_scraper_index():
    print(f"DEBUG: Serving index.html for /scraper route from: {scraper_bp.static_folder}")
    return send_from_directory(scraper_bp.static_folder, 'index.html')

# This is a catch-all route for the blueprint. It handles two cases:
# 1. Serving other assets from the static folder (e.g., manifest.json, favicon.ico).
# 2. Handling client-side routing (e.g., if you had /scraper/results). It serves
#    index.html, and the frontend router takes over.
@scraper_bp.route('/<path:path>')
def serve_scraper_assets(path):
    if os.path.exists(os.path.join(scraper_bp.static_folder, path)):
        print(f"DEBUG: Serving static asset for blueprint: {path}")
        return send_from_directory(scraper_bp.static_folder, path)
    else:
        print(f"DEBUG: Path '{path}' not found in static, serving index.html for client-side routing.")
        return send_from_directory(scraper_bp.static_folder, 'index.html')

# Register the blueprint on the main app, mounting it at the '/scraper' prefix.
app.register_blueprint(scraper_bp, url_prefix='/scraper')

# --- NEW: ROOT REDIRECT ---
# Redirect the root URL http://127.0.0.1:5000/ to the scraper app.
@app.route('/')
def index_redirect():
    print("DEBUG: Redirecting from '/' to '/scraper/'")
    return redirect('/scraper/')


if __name__ == '__main__':
    print("DEBUG: Starting Flask application...")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=True)