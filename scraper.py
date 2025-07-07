# scraper.py

import json
from typing import List
from pydantic import BaseModel, create_model # Removed Field as it's not used here
from assets import (OPENAI_MODEL_FULLNAME,GEMINI_MODEL_FULLNAME,SYSTEM_MESSAGE) # Removed DEEPSEEK_MODEL_FULLNAME, not used
from llm_calls import (call_llm_model)
from markdown import read_raw_data
from api_management import get_supabase_client
# from utils import generate_unique_name # Not used in this file

supabase = get_supabase_client()

def create_dynamic_listing_model(field_names: List[str]):
    field_definitions = {field: (str, ...) for field in field_names}
    return create_model('DynamicListingModel', **field_definitions)

def create_listings_container_model(listing_model: BaseModel):
    return create_model('DynamicListingsContainer', listings=(List[listing_model], ...))

def generate_system_message(listing_model: BaseModel) -> str:
    schema_info = listing_model.model_json_schema()
    field_descriptions = []
    # Ensure properties exist before iterating
    if "properties" in schema_info:
        for field_name, field_info in schema_info["properties"].items():
            # Ensure field_info is a dict and "type" exists
            field_type = field_info.get("type", "string") if isinstance(field_info, dict) else "string"
            field_descriptions.append(f'"{field_name}": "{field_type}"')
    else: # Handle cases where model might have no properties (e.g. empty fields list passed - though app.py should prevent this)
        print("WARNING: DynamicListingModel has no properties in its schema.")


    schema_structure = ",\n".join(field_descriptions)
    if not schema_structure: # If no fields, provide a generic placeholder
        schema_structure = '"field_name": "type"'


    final_prompt= SYSTEM_MESSAGE+"\n"+f"""strictly follows this schema:
    {{
       "listings": [
         {{
           {schema_structure}
         }}
       ]
    }}
    """
    return final_prompt


def save_formatted_data(unique_name: str, formatted_data_dict: dict):
    # formatted_data_dict is already expected to be a dictionary,
    # typically like {"listings": [...]} or {"raw_text_from_llm": "..."}
    supabase.table("scraped_data").update({
        "formatted_data": formatted_data_dict 
    }).eq("unique_name", unique_name).execute()
    MAGENTA = "\033[35m"
    RESET = "\033[0m"  # Reset color to default
    print(f"{MAGENTA}INFO:Scraped data saved for {unique_name}{RESET}")

def scrape_urls(unique_names: List[str], fields: List[str], selected_model: str):
    """
    For each unique_name:
      1) read raw_data from supabase
      2) parse with selected LLM using a schema-specific system message
      3) extract item dictionaries from the parsed response
      4) save the original parsed LLM response (container format) to Supabase
      5) accumulate cost
    Return total usage + list of {"unique_name": str, "items": List[Dict]}
    """
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0
    # parsed_results will store {"unique_name": name, "items": list_of_item_dicts}
    parsed_results = [] 

    if not fields: # Should be caught by app.py, but as a safeguard
        print("WARNING: scrape_urls called with empty fields list.")
        return total_input_tokens, total_output_tokens, total_cost, parsed_results

    DynamicListingModel = create_dynamic_listing_model(fields)
    DynamicListingsContainer = create_listings_container_model(DynamicListingModel)
    specific_system_message = generate_system_message(DynamicListingModel)

    for uniq in unique_names:
        raw_data = read_raw_data(uniq)
        if not raw_data:
            BLUE = "\033[34m"
            RESET = "\033[0m"
            print(f"{BLUE}No raw_data found for {uniq}, skipping.{RESET}")
            parsed_results.append({"unique_name": uniq, "items": []})
            continue

        # 'parsed_llm_response' can be Pydantic model, dict, or string
        parsed_llm_response, token_counts, cost = call_llm_model(
            raw_data, 
            DynamicListingsContainer, # Desired Pydantic response_format for LiteLLM
            selected_model, 
            specific_system_message # System message with schema
        )

        current_items_list = [] # List of item dictionaries for this unique_name
        data_to_save_in_db = {} # Data structure to save in Supabase

        if parsed_llm_response:
            # Case 1: LLM returned the Pydantic model instance (ideal)
            if hasattr(parsed_llm_response, 'listings') and isinstance(parsed_llm_response.listings, list):
                for item_model in parsed_llm_response.listings:
                    if hasattr(item_model, 'model_dump'): # Pydantic v2
                        current_items_list.append(item_model.model_dump())
                    elif hasattr(item_model, 'dict'): # Pydantic v1
                        current_items_list.append(item_model.dict())
                    else: # Fallback if item_model is not a Pydantic model as expected
                        current_items_list.append(dict(item_model) if not isinstance(item_model, dict) else item_model)
                
                if hasattr(parsed_llm_response, 'model_dump'): # Pydantic v2
                    data_to_save_in_db = parsed_llm_response.model_dump()
                elif hasattr(parsed_llm_response, 'dict'): # Pydantic v1
                    data_to_save_in_db = parsed_llm_response.dict()

            # Case 2: LLM returned a dictionary (e.g. from LiteLLM fallback or manual parsing)
            elif isinstance(parsed_llm_response, dict) and "listings" in parsed_llm_response and isinstance(parsed_llm_response["listings"], list):
                current_items_list = parsed_llm_response["listings"] # Assuming items are already dicts
                data_to_save_in_db = parsed_llm_response
            
            # Case 3: LLM returned a JSON string
            elif isinstance(parsed_llm_response, str):
                try:
                    parsed_dict_from_string = json.loads(parsed_llm_response)
                    if "listings" in parsed_dict_from_string and isinstance(parsed_dict_from_string["listings"], list):
                        current_items_list = parsed_dict_from_string["listings"]
                        data_to_save_in_db = parsed_dict_from_string
                    else: # String is JSON but not the expected listings structure
                        print(f"WARNING: LLM returned JSON string without 'listings' for {uniq}: {parsed_llm_response[:100]}")
                        data_to_save_in_db = {"raw_text_from_llm": parsed_llm_response, "listings": []}
                except json.JSONDecodeError: # String is not valid JSON
                    print(f"WARNING: LLM returned non-JSON string for {uniq}: {parsed_llm_response[:100]}")
                    data_to_save_in_db = {"raw_text_from_llm": parsed_llm_response, "listings": []}
            else:
                print(f"WARNING: Unexpected type for parsed_llm_response for {uniq}: {type(parsed_llm_response)}")
                data_to_save_in_db = {"error": "Unknown LLM response type", "listings": []}
        
        if not data_to_save_in_db: # Ensure there's always something to save if parsing failed early
            data_to_save_in_db = {"listings": [], "parsing_error": "Initial parsing failed or empty response"}
            if isinstance(parsed_llm_response, str) and "raw_text_from_llm" not in data_to_save_in_db : # if original was string
                 data_to_save_in_db["raw_text_from_llm"] = parsed_llm_response


        save_formatted_data(uniq, data_to_save_in_db)

        parsed_results.append({
            "unique_name": uniq,
            "items": current_items_list # This is List[Dict]
        })

        total_input_tokens += token_counts.get("input_tokens", 0)
        total_output_tokens += token_counts.get("output_tokens", 0)
        total_cost += cost if cost is not None else 0

    return total_input_tokens, total_output_tokens, total_cost, parsed_results