# pagination.py
import json
from typing import List, Dict
from assets import PROMPT_PAGINATION
from markdown import read_raw_data
from api_management import supabase_client_instance as supabase
from pydantic import BaseModel, Field, create_model, ValidationError
from llm_calls import call_llm_model
import traceback # For detailed error logging

class PaginationModel(BaseModel):
    page_urls: List[str] = Field(default_factory=list)

def get_pagination_response_format() -> type[BaseModel]:
    return PaginationModel

def build_pagination_prompt(indications: str, url: str) -> str:
    prompt = PROMPT_PAGINATION + f"\nThe page being analyzed is: {url}\n"
    if indications and indications.strip():
        prompt += (
            "These are the user's indications. Pay attention:\n"
            f"{indications}\n\n"
        )
    else:
        prompt += (
            "No special user indications. Just apply the pagination logic.\n\n"
        )
    return prompt

def save_pagination_data(unique_name: str, pagination_data_obj) -> bool:
    print(f"DEBUG: save_pagination_data called for unique_name: {unique_name}")
    if not supabase:
        print("ERROR: Supabase client not initialized in pagination.py. Cannot save pagination data.")
        return False

    data_to_save = {}
    if isinstance(pagination_data_obj, BaseModel):
        data_to_save = pagination_data_obj.model_dump()
    elif isinstance(pagination_data_obj, dict):
        data_to_save = pagination_data_obj
    elif isinstance(pagination_data_obj, str):
        try:
            data_to_save = json.loads(pagination_data_obj)
        except json.JSONDecodeError:
            print(f"WARNING: Pagination data for {unique_name} is a string but not valid JSON: {pagination_data_obj}")
            data_to_save = {"raw_text_unparsed": pagination_data_obj}
    else:
        print(f"WARNING: Unknown pagination data type for {unique_name}: {type(pagination_data_obj)}. Not saving.")
        return False
        
    try:
        print(f"DEBUG: Saving pagination data to Supabase for {unique_name}: {str(data_to_save)[:200]}...")
        supabase.table("scraped_data").update({
            "pagination_data": data_to_save
        }).eq("unique_name", unique_name).execute()
        MAGENTA = "\033[35m"
        RESET = "\033[0m" 
        print(f"{MAGENTA}INFO: Pagination data saved for {unique_name}{RESET}")
        return True
    except Exception as e:
        print(f"CRITICAL ERROR saving pagination data for {unique_name} to Supabase: {e}")
        traceback.print_exc()
        return False

def paginate_urls(unique_names: List[str], selected_model: str, indication: str, source_urls:List[str]):
    print(f"DEBUG: paginate_urls called. Unique names: {unique_names}, Model: {selected_model}, Source URLs: {source_urls}")
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    pagination_results_for_response = []

    if len(unique_names) != len(source_urls):
        print(f"CRITICAL ERROR: Mismatch length of unique_names ({len(unique_names)}) and source_urls ({len(source_urls)}) in paginate_urls.")
        return total_input_tokens, total_output_tokens, total_cost, pagination_results_for_response

    for uniq_name, current_url in zip(unique_names, source_urls):
        print(f"DEBUG: Processing pagination for unique_name: {uniq_name}, URL: {current_url}")
        raw_data = read_raw_data(uniq_name)
        if not raw_data:
            print(f"WARNING: No raw_data found for {uniq_name} in paginate_urls, skipping pagination for this item.")
            continue
        
        response_pydantic_model = get_pagination_response_format()
        system_prompt_for_pagination = build_pagination_prompt(indication, current_url)

        try:
            print(f"DEBUG: Calling LLM for pagination for {uniq_name}.")
            # --- START OF FIX ---
            # We are now forcing JSON object mode and will parse the string ourselves.
            pag_data_obj, token_counts, cost = call_llm_model(
                data=raw_data,
                response_format={"type": "json_object"}, # More reliable way to request JSON
                model=selected_model,
                system_message=system_prompt_for_pagination,
            )
            # --- END OF FIX ---
            
            print(f"DEBUG: LLM call for pagination {uniq_name} successful. Tokens: {token_counts}, Cost: {cost}")
            
            save_pagination_data(uniq_name, pag_data_obj)

            total_input_tokens += token_counts.get("input_tokens", 0)
            total_output_tokens += token_counts.get("output_tokens", 0)
            total_cost += cost

            # --- START OF FIX: LOGIC RESTRUCTURE ---
            # This new block robustly handles string, dict, or pydantic model responses.
            validated_model = None
            try:
                if isinstance(pag_data_obj, str):
                    # This is the case from your logs. Parse the string into a dict.
                    data_dict = json.loads(pag_data_obj)
                    validated_model = PaginationModel.model_validate(data_dict)
                    print(f"DEBUG: Successfully parsed string response into Pydantic model for {uniq_name}.")
                elif isinstance(pag_data_obj, dict):
                    # Handle if the LLM returns a dict directly.
                    validated_model = PaginationModel.model_validate(pag_data_obj)
                elif isinstance(pag_data_obj, PaginationModel):
                    # Handle if the LLM returns a Pydantic object directly.
                    validated_model = pag_data_obj
                else:
                    print(f"WARNING: LLM response for {uniq_name} pagination was of unhandled type: {type(pag_data_obj)}. Content: {str(pag_data_obj)[:200]}...")

                if validated_model and validated_model.page_urls:
                    for p_url in validated_model.page_urls:
                        # Add the source_url as identified in the previous step
                        pagination_results_for_response.append({"page_url": p_url, "source_url": current_url})
                    print(f"DEBUG: Extracted {len(validated_model.page_urls)} pagination URLs for {uniq_name}.")
                else:
                    print(f"WARNING: 'page_urls' attribute was empty or model was invalid for {uniq_name}.")

            except (json.JSONDecodeError, ValidationError) as e:
                 print(f"WARNING: Could not parse or validate LLM response for {uniq_name}. Error: {e}. Raw content: {str(pag_data_obj)[:200]}...")
            # --- END OF FIX: LOGIC RESTRUCTURE ---

        except Exception as e:
            print(f"CRITICAL ERROR processing pagination for {uniq_name}: {e}")
            traceback.print_exc()
    
    print(f"DEBUG: paginate_urls finished. Total tokens: In={total_input_tokens}, Out={total_output_tokens}. Total cost: ${total_cost:.6f}. Results count: {len(pagination_results_for_response)}")
    return total_input_tokens, total_output_tokens, total_cost, pagination_results_for_response