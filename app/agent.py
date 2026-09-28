# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
import google.auth
import google.auth.transport.requests
import requests
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from app.a2ui_utils import a2ui_callback

# Hardcode project ID, Cloud Storage bucket, and Memory Bank ID as strings
PROJECT_ID = "qwiklabs-gcp-02-563af7ba3456"
BUCKET_NAME = "smart-recipe-concierge-images-563a"
MEMORY_BANK_ID = "2695815594330030080"

# Read Agent Engine resource name from deployment_metadata.json
METADATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deployment_metadata.json")
agent_engine_resource_name = "projects/654252928124/locations/us-east1/reasoningEngines/2695815594330030080"
if os.path.exists(METADATA_FILE):
    try:
        with open(METADATA_FILE, "r") as f:
            meta = json.load(f)
            agent_engine_resource_name = meta.get("remote_agent_runtime_id", agent_engine_resource_name)
    except Exception:
        pass

code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=agent_engine_resource_name
)


def get_memory_service() -> VertexAiMemoryBankService:
    """Returns initialized VertexAiMemoryBankService for Memory Bank cross-session memory."""
    return VertexAiMemoryBankService(
        project=PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


async def generate_memories_callback(callback_context: CallbackContext):
    """Callback triggered after each agent turn to extract and persist durable facts to Memory Bank."""
    try:
        await callback_context.add_session_to_memory()
    except Exception:
        pass
    return None

_db = None
_storage_client = None


def get_firestore_client() -> firestore.Client:
    """Returns initialized Firestore client with hardcoded project ID."""
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID)
    return _db


def get_storage_client() -> storage.Client:
    """Returns initialized Cloud Storage client with hardcoded project ID."""
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client(project=PROJECT_ID)
    return _storage_client


def search_recipes(dietary_tag: str = "", keyword: str = "", max_calories: int = 0) -> str:
    """Search recipes in the Firestore database by dietary tag, keyword, or maximum calories.

    Args:
        dietary_tag: Optional tag to filter by (e.g. 'vegan', 'keto', 'gluten-free', 'vegetarian', 'dairy-free').
        keyword: Optional search term to match in recipe title or description (e.g. 'chicken', 'pasta', 'avocado').
        max_calories: Optional maximum calories per serving limit (e.g. 400). Set to 0 for no limit.

    Returns:
        JSON string list of matching recipe summaries.
    """
    db = get_firestore_client()
    docs = db.collection("recipes").stream()
    matches = []

    clean_tag = dietary_tag.strip().lower()
    clean_keyword = keyword.strip().lower()

    for doc in docs:
        data = doc.to_dict()
        doc_id = doc.id
        title = data.get("title", "")
        desc = data.get("description", "")
        tags = [t.lower() for t in data.get("dietary_tags", [])]
        cals = data.get("calories_per_serving", 0)

        # Filter by dietary tag
        if clean_tag and clean_tag not in tags:
            continue

        # Filter by keyword
        if clean_keyword and (clean_keyword not in title.lower() and clean_keyword not in desc.lower()):
            continue

        # Filter by max calories
        if max_calories > 0 and cals > max_calories:
            continue

        matches.append({
            "recipe_id": doc_id,
            "title": title,
            "description": desc,
            "calories_per_serving": cals,
            "prep_time_minutes": data.get("prep_time_minutes", 0),
            "cook_time_minutes": data.get("cook_time_minutes", 0),
            "servings": data.get("servings", 0),
            "dietary_tags": data.get("dietary_tags", []),
        })

    if not matches:
        return f"No recipes found matching query (tag='{dietary_tag}', keyword='{keyword}', max_calories={max_calories})."

    return json.dumps(matches, indent=2)


def get_recipe_details(recipe_id: str) -> str:
    """Get complete recipe details from Firestore, including ingredients and instructions.

    Args:
        recipe_id: The unique document ID of the recipe (e.g. 'recipe-001', 'recipe-002').

    Returns:
        JSON string with full recipe details, ingredients list, and step-by-step instructions.
    """
    db = get_firestore_client()
    doc_ref = db.collection("recipes").document(recipe_id.strip())
    doc = doc_ref.get()

    if not doc.exists:
        # Search by title match if exact ID is not provided
        docs = db.collection("recipes").stream()
        for d in docs:
            data = d.to_dict()
            if recipe_id.strip().lower() in data.get("title", "").lower():
                return json.dumps(data, indent=2)
        return f"Error: Recipe with ID or title '{recipe_id}' was not found in Firestore."

    return json.dumps(doc.to_dict(), indent=2)


def add_recipe(
    title: str,
    description: str,
    prep_time_minutes: int,
    cook_time_minutes: int,
    servings: int,
    calories_per_serving: int,
    dietary_tags: str,
    ingredients: str,
    instructions: str,
) -> str:
    """Add a new custom recipe document to the Firestore database.

    Args:
        title: Recipe title (e.g. 'Berry Almond Oatmeal').
        description: Short description of the dish.
        prep_time_minutes: Preparation time in minutes.
        cook_time_minutes: Cooking time in minutes.
        servings: Number of servings.
        calories_per_serving: Estimated calories per serving.
        dietary_tags: Comma-separated list of dietary tags (e.g. 'vegan, gluten-free, healthy').
        ingredients: Comma or pipe-separated list of ingredients.
        instructions: Comma or pipe-separated step-by-step instructions.

    Returns:
        Confirmation message with the created recipe document ID.
    """
    db = get_firestore_client()
    recipe_id = f"recipe-{uuid.uuid4().hex[:6]}"

    tags_list = [t.strip().lower() for t in dietary_tags.split(",") if t.strip()]
    ingredients_list = [i.strip() for i in ingredients.replace("|", "\n").split(",") if i.strip()]
    instructions_list = [s.strip() for s in instructions.replace("|", "\n").split(",") if s.strip()]

    recipe_doc = {
        "recipe_id": recipe_id,
        "title": title.strip(),
        "description": description.strip(),
        "prep_time_minutes": prep_time_minutes,
        "cook_time_minutes": cook_time_minutes,
        "servings": servings,
        "calories_per_serving": calories_per_serving,
        "dietary_tags": tags_list,
        "ingredients": ingredients_list,
        "instructions": instructions_list,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    db.collection("recipes").document(recipe_id).set(recipe_doc)
    return f"Successfully added new recipe '{title}' to Firestore with ID: {recipe_id}."


def scale_ingredients(recipe_id: str, target_servings: int) -> str:
    """Scale ingredient quantities of a recipe to match desired target servings.

    Args:
        recipe_id: The unique document ID or title of the recipe (e.g. 'recipe-001', 'Quinoa Mediterranean Power Bowl').
        target_servings: The desired target number of servings (e.g. 6).

    Returns:
        JSON string containing original servings, target servings, scale ratio, and scaled ingredients.
    """
    if target_servings <= 0:
        return "Error: target_servings must be a positive integer greater than 0."

    db = get_firestore_client()
    doc_ref = db.collection("recipes").document(recipe_id.strip())
    doc = doc_ref.get()

    data = None
    if doc.exists:
        data = doc.to_dict()
    else:
        docs = db.collection("recipes").stream()
        for d in docs:
            d_dict = d.to_dict()
            if recipe_id.strip().lower() in d_dict.get("title", "").lower():
                data = d_dict
                break

    if not data:
        return f"Error: Recipe '{recipe_id}' was not found in Firestore."

    original_servings = data.get("servings", 1)
    if original_servings <= 0:
        original_servings = 1

    ratio = target_servings / original_servings
    ingredients = data.get("ingredients", [])

    scaled_ingredients = []
    for item in ingredients:
        parts = item.split()
        if parts:
            try:
                first = parts[0]
                if "/" in first:
                    num, den = first.split("/")
                    val = float(num) / float(den)
                else:
                    val = float(first)
                scaled_val = round(val * ratio, 2)
                if scaled_val.is_integer():
                    scaled_val = int(scaled_val)
                item_str = f"{scaled_val} {' '.join(parts[1:])}"
            except ValueError:
                item_str = f"{item} (scaled x{round(ratio, 2)})"
        else:
            item_str = item
        scaled_ingredients.append(item_str)

    result = {
        "title": data.get("title"),
        "recipe_id": data.get("recipe_id"),
        "original_servings": original_servings,
        "target_servings": target_servings,
        "scale_ratio": round(ratio, 2),
        "scaled_ingredients": scaled_ingredients,
    }
    return json.dumps(result, indent=2)


def fetch_external_recipes(query: str = "") -> str:
    """Fetch real-world meal recipes from TheMealDB open public API.

    Args:
        query: Optional search term for a meal or ingredient (e.g. 'pasta', 'chicken', 'tacos', 'salad'). Reads optional API key from THEMEALDB_API_KEY environment variable.

    Returns:
        JSON string containing matching meal details, category, cuisine area, ingredients, and instructions.
    """
    api_key = os.getenv("THEMEALDB_API_KEY", "1")
    clean_query = query.strip()
    if clean_query:
        url = f"https://www.themealdb.com/api/json/v1/{api_key}/search.php?s={urllib.parse.quote(clean_query)}"
    else:
        url = f"https://www.themealdb.com/api/json/v1/{api_key}/random.php"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SmartRecipeConcierge/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))

        meals = data.get("meals")
        if not meals:
            return f"No external recipes found matching '{query}' on TheMealDB."

        results = []
        for m in meals[:3]:
            ingredients = []
            for i in range(1, 21):
                ing = m.get(f"strIngredient{i}")
                meas = m.get(f"strMeasure{i}")
                if ing and ing.strip():
                    measure_str = f" ({meas.strip()})" if meas and meas.strip() else ""
                    ingredients.append(f"{ing.strip()}{measure_str}")

            results.append({
                "meal_id": m.get("idMeal"),
                "name": m.get("strMeal"),
                "category": m.get("strCategory"),
                "cuisine": m.get("strArea"),
                "instructions": m.get("strInstructions", "")[:350] + "...",
                "ingredients": ingredients,
                "youtube_video": m.get("strYoutube"),
                "image_url": m.get("strMealThumb"),
            })

        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error fetching external recipe data from TheMealDB API: {str(e)}"


def generate_recipe_image(prompt: str, tool_context: ToolContext) -> str:
    """Generate an image of a recipe dish or food item using the gemini-3.1-flash-lite-image model in global region.

    Saves the image as a Playground artifact and uploads it to public Cloud Storage, returning its public HTTPS URL.

    Args:
        prompt: Description of the dish or food presentation to generate (e.g. 'Fresh avocado guacamole in a bowl').
        tool_context: ADK ToolContext for saving the artifact.

    Returns:
        Public HTTPS URL of the uploaded image (https://storage.googleapis.com/<bucket>/<filename>).
    """
    client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=f"High quality food photography of: {prompt}",
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )

    image_bytes = None
    mime_type = "image/jpeg"

    if response.candidates and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                mime_type = part.inline_data.mime_type or "image/jpeg"
                break

    if not image_bytes:
        return f"Error: Failed to generate image for prompt '{prompt}'."

    ext = "jpg" if "jpeg" in mime_type else "png"
    filename = f"recipe_image_{uuid.uuid4().hex[:8]}.{ext}"

    # 1. Save artifact for Playground Artifacts panel
    artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload image bytes directly to public GCS bucket (no local file write)
    gcs_client = get_storage_client()
    bucket = gcs_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    return f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"


def generate_recipe_video(prompt: str, tool_context: ToolContext) -> str:
    """Generate a short video of a recipe dish or food item using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Saves the video as a Playground artifact and uploads it to public Cloud Storage, returning its public HTTPS URL.

    Args:
        prompt: Description of the food dish or recipe item video to generate (e.g. 'Sizzling garlic butter shrimp in a pan').
        tool_context: ADK ToolContext for saving the artifact.

    Returns:
        Public HTTPS URL of the uploaded video (https://storage.googleapis.com/<bucket>/<filename>).
    """
    credentials, _ = google.auth.default()
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    token = credentials.token

    url = f"https://aiplatform.googleapis.com/v1beta1/projects/{PROJECT_ID}/locations/global/interactions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "model": "gemini-omni-flash-preview",
        "input": [
            {
                "type": "text",
                "text": f"High quality video of food preparation or dish: {prompt}"
            }
        ],
        "generation_config": {
            "video_config": {
                "task": "text_to_video"
            }
        }
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=120)
        if res.status_code != 200:
            return f"Error: Failed to generate video from API (HTTP {res.status_code}): {res.text[:300]}"

        data = res.json()
        video_bytes = None
        mime_type = "video/mp4"

        for step in data.get("steps", []):
            if step.get("type") == "model_output":
                for item in step.get("content", []):
                    if item.get("type") == "video" and "data" in item:
                        video_bytes = base64.b64decode(item["data"])
                        mime_type = item.get("mime_type", "video/mp4")
                        break

        if not video_bytes:
            return f"Error: No video data returned for prompt '{prompt}'."

        filename = f"recipe_video_{uuid.uuid4().hex[:8]}.mp4"

        # 1. Save artifact for Playground Artifacts panel
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload video bytes directly to public GCS bucket (no local file write)
        gcs_client = get_storage_client()
        bucket = gcs_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        return f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
    except Exception as e:
        return f"Error generating recipe video: {str(e)}"


def get_weather(query: str) -> str:
    """Simulates a web search for weather.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with weather information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting current time for a city.

    Args:
        query: The name of the city to get current time for.

    Returns:
        A string with current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are the Smart Recipe Concierge, an expert culinary AI assistant. "
        "CRITICAL MEMORY REQUIREMENT: You MUST pay strict attention to and remember all user food allergies, sensitivities, intolerances, and dietary restrictions stated across conversations. "
        "Always check preloaded user memories for allergies before suggesting recipes, meal plans, or ingredient substitutes, and NEVER recommend any recipe or ingredient containing a known user allergen. "
        "You help users discover recipes based on dietary preferences and available ingredients, "
        "fetch real-world global recipes from external public recipe APIs (TheMealDB), "
        "provide detailed ingredient lists and instructions from Firestore database, "
        "scale recipe ingredient amounts dynamically for any number of servings, "
        "generate AI food photography using gemini-3.1-flash-lite-image, "
        "generate short food presentation videos using Google's Omni model (gemini-omni-flash-preview) in the global region, "
        "execute Python code safely in a sandbox using AgentEngineSandboxCodeExecutor to calculate complex ratios, macros, or nutrition math, "
        "and save new custom recipes to the database."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="smart_recipe_concierge",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=a2ui_instruction,
    code_executor=code_executor,
    tools=[
        PreloadMemoryTool(),
        search_recipes,
        get_recipe_details,
        scale_ingredients,
        add_recipe,
        fetch_external_recipes,
        generate_recipe_image,
        generate_recipe_video,
        get_weather,
        get_current_time,
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)




