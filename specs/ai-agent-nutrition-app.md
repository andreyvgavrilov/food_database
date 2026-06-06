# AI Nutrition Agent Web App Specification

## Overview

Build a Python web application with a SQLite database and an AI chat agent that helps users analyze the nutrition of food recipes.

The agent must use Ollama for LLM inference, with local and cloud-compatible settings controlled through a `.env` file. The agent orchestration layer must use Deepagent as the core engine. The app must use USDA FoodData Central JSON dump data as its nutrition source, populate SQLite automatically on first run, and expose a UI button to refresh the imported nutrition database later.

## Goals

- Let users chat with an AI nutrition assistant about recipes and ingredients.
- Normalize ingredient names into standard English before nutrition lookup.
- Retrieve nutrition data for individual ingredients from the local SQLite copy of USDA FoodData Central data.
- Calculate per-ingredient and total recipe nutrition after converting ingredient measures to grams.
- Keep the nutrition database available offline after the initial import.
- Allow the app operator to configure Ollama local or cloud endpoints without code changes.

## Non-Goals

- Medical diagnosis or treatment advice.
- Personalized meal plans based on protected health data unless added in a later privacy-reviewed scope.
- Replacing professional dietary guidance.
- Real-time calls to the USDA API for every recipe analysis. The primary source is the local database imported from the USDA JSON dump.

## Technology Stack

- Language: Python
- Web framework: FastAPI or Flask. FastAPI is preferred for typed request/response models and clean async support.
- Database: SQLite
- ORM/query layer: SQLAlchemy or SQLModel
- LLM provider: Ollama
- Agent engine: Deepagent
- Configuration: `.env` loaded through `python-dotenv` or framework-native settings
- Frontend: Server-rendered templates or a lightweight SPA. The first implementation should keep the UI simple and functional.

## Configuration

The app must read configuration from `.env`.

Required settings:

```env
APP_ENV=development
DATABASE_URL=sqlite:///./data/nutrition.sqlite

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
OLLAMA_API_KEY=
OLLAMA_TIMEOUT_SECONDS=120

USDA_JSON_DUMP_PATH=./data/usda-fooddata-central
AUTO_IMPORT_USDA_ON_FIRST_RUN=true
```

Cloud Ollama-compatible deployments should be supported by changing `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and optionally `OLLAMA_API_KEY`.

## Application Structure

Suggested layout:

```text
app/
  main.py
  config.py
  db.py
  models.py
  schemas.py
  agent/
    engine.py
    prompts.py
    tools.py
  usda/
    importer.py
    lookup.py
    units.py
  nutrition/
    calculator.py
  web/
    routes.py
    templates/
data/
  nutrition.sqlite
  usda-fooddata-central/
specs/
```

## Database Requirements

SQLite must store imported USDA nutrition data in queryable tables. The schema should preserve enough original data to support accurate lookup, serving conversion, and future re-imports.

Recommended tables:

- `import_status`
  - `id`
  - `source_name`
  - `source_path`
  - `source_version`
  - `started_at`
  - `completed_at`
  - `status`
  - `error_message`

- `foods`
  - `fdc_id`
  - `description`
  - `data_type`
  - `food_category_id`
  - `publication_date`
  - `search_name`
  - `raw_json`

- `food_categories`
  - `id`
  - `description`

- `nutrients`
  - `id`
  - `number`
  - `name`
  - `unit_name`

- `food_nutrients`
  - `id`
  - `fdc_id`
  - `nutrient_id`
  - `amount`
  - `derivation_code`

- `food_portions`
  - `id`
  - `fdc_id`
  - `amount`
  - `measure_unit_name`
  - `modifier`
  - `gram_weight`

- `ingredient_aliases`
  - `id`
  - `original_name`
  - `normalized_name`
  - `fdc_id`
  - `confidence`
  - `created_at`
  - `updated_at`

The app should keep `raw_json` for traceability, but nutrition lookup should use indexed relational columns instead of scanning raw JSON.

## First-Run USDA Import

On application startup:

1. Check whether the SQLite database exists and whether `import_status` has a successful USDA import.
2. If no successful import exists and `AUTO_IMPORT_USDA_ON_FIRST_RUN=true`, run the USDA importer.
3. If the JSON dump path is missing, show an admin-visible warning and keep the app running in degraded mode.
4. Store import progress and errors in `import_status`.
5. Do not block the web server indefinitely. Long imports should run as a background task with a visible status page.

The importer must:

- Read the USDA FoodData Central JSON dump from `USDA_JSON_DUMP_PATH`.
- Import food records, categories, nutrients, food nutrient amounts, and food portion/measure data.
- Build normalized search columns, such as lowercase ASCII names with punctuation collapsed.
- Create indexes for ingredient lookup:
  - `foods.search_name`
  - `foods.description`
  - `food_nutrients.fdc_id`
  - `food_portions.fdc_id`
  - `ingredient_aliases.original_name`
  - `ingredient_aliases.normalized_name`

## Manual Database Update

The web UI must include a button for updating USDA data later.

Expected behavior:

- Button label: `Update nutrition database`
- Available from an admin/settings page.
- Starts a background import job.
- Shows import status: idle, running, completed, failed.
- Prevents duplicate imports from running at the same time.
- Uses an atomic refresh strategy:
  - Import into staging tables or a temporary database.
  - Validate required table counts and indexes.
  - Swap into active database only after success.
- Keeps the previous successful dataset active if the update fails.

## Agent Requirements

The chat agent must be built around Deepagent and expose nutrition tools to the LLM.

The agent should:

- Accept recipe text, ingredient lists, and follow-up questions.
- Ask clarifying questions when quantity, unit, or ingredient identity is ambiguous.
- Use tools for nutrition lookup and calculation instead of inventing nutrition values.
- Explain uncertainty when an ingredient match is approximate.
- Return concise, readable nutrition summaries.

The agent should not:
- Include a safety disclaimer for medical or disease-specific advice.

## Ollama Integration

The Ollama client must:

- Read endpoint/model/API key from `.env`.
- Support local Ollama without an API key.
- Support cloud or proxy endpoints with an API key.
- Use request timeouts.
- Surface model connection failures clearly in the UI.

## Ingredient Normalization Flow

Before querying the database, ingredient names must be converted into standard English names by the LLM.

Example input:

```text
2 tomates
1 tbsp huile d'olive
200g kurinaya grudka
```

Expected normalized output:

```json
[
  {
    "original_name": "tomates",
    "standard_english_name": "tomato",
    "quantity": 2,
    "unit": "item"
  },
  {
    "original_name": "huile d'olive",
    "standard_english_name": "olive oil",
    "quantity": 1,
    "unit": "tablespoon"
  },
  {
    "original_name": "kurinaya grudka",
    "standard_english_name": "chicken breast",
    "quantity": 200,
    "unit": "gram"
  }
]
```

The normalized result should be cached in `ingredient_aliases` when the app can confidently associate it with a USDA food record.

## Tool 1: Ingredient Nutrition Lookup

Tool name: `get_ingredient_nutrition`

Purpose:

Get nutrition data for one ingredient using the local USDA FoodData Central SQLite database.

Input:

```json
{
  "ingredient_name": "olive oil",
  "preferred_food_category": "Fats and Oils",
  "max_results": 5
}
```

Behavior:

1. Receive a standard English ingredient name.
2. Search `ingredient_aliases` for a known mapping.
3. Search `foods.search_name` and `foods.description`.
4. Prefer exact matches, common foods, and category matches.
5. Return top candidates when confidence is not high enough.
6. Include nutrient data and available portion conversions for each candidate.

Output:

```json
{
  "ingredient_name": "olive oil",
  "matches": [
    {
      "fdc_id": 123456,
      "description": "Oil, olive, salad or cooking",
      "confidence": 0.95,
      "nutrients_per_100g": {
        "Energy": { "amount": 884, "unit": "kcal" },
        "Protein": { "amount": 0, "unit": "g" },
        "Total lipid (fat)": { "amount": 100, "unit": "g" }
      },
      "portion_conversions": [
        {
          "amount": 1,
          "unit": "tablespoon",
          "gram_weight": 13.5
        }
      ]
    }
  ]
}
```

## Tool 2: Total Nutrition Calculator

Tool name: `calculate_total_nutrition`

Purpose:

Calculate nutrition for a full recipe, including per-ingredient rows and total nutrition.

Input:

```json
{
  "ingredients": [
    {
      "name": "olive oil",
      "quantity": 1,
      "unit": "tablespoon"
    },
    {
      "name": "chicken breast",
      "quantity": 200,
      "unit": "gram"
    }
  ],
  "servings": 2
}
```

Behavior:

1. Normalize all ingredient names into standard English if needed.
2. Resolve each ingredient to a USDA food record.
3. Convert ingredient quantities to grams.
4. Use USDA portion data where available, such as tablespoon, cup, piece, slice, or serving.
5. Use direct conversion for metric units:
   - `gram`
   - `kilogram`
   - `milligram`
6. Use volume-to-weight conversion only when USDA portion data or ingredient-specific density data exists.
7. If a conversion is ambiguous, ask the agent to request clarification or return an explicit warning.
8. Calculate nutrient amounts from per-100g data:

```text
ingredient_nutrient_amount = nutrient_per_100g * ingredient_grams / 100
```

9. Return a table with one row per ingredient and one total row.
10. If `servings` is provided, also return per-serving totals.

Output:

```json
{
  "ingredients": [
    {
      "input_name": "olive oil",
      "resolved_name": "Oil, olive, salad or cooking",
      "fdc_id": 123456,
      "quantity": 1,
      "unit": "tablespoon",
      "grams": 13.5,
      "nutrition": {
        "Energy": { "amount": 119.34, "unit": "kcal" },
        "Protein": { "amount": 0, "unit": "g" },
        "Total lipid (fat)": { "amount": 13.5, "unit": "g" }
      },
      "warnings": []
    }
  ],
  "total": {
    "Energy": { "amount": 119.34, "unit": "kcal" },
    "Protein": { "amount": 0, "unit": "g" },
    "Total lipid (fat)": { "amount": 13.5, "unit": "g" }
  },
  "per_serving": {
    "Energy": { "amount": 59.67, "unit": "kcal" },
    "Protein": { "amount": 0, "unit": "g" },
    "Total lipid (fat)": { "amount": 6.75, "unit": "g" }
  },
  "warnings": []
}
```

## Nutrition Fields

The first implementation should prioritize:

- Calories / energy
- Protein
- Total fat
- Saturated fat
- Carbohydrates
- Total sugars
- Fiber
- Sodium
- Cholesterol
- Potassium
- Calcium
- Iron

The database should store all imported USDA nutrients even if the UI initially displays only the priority set.

## Chat UI Requirements

The web interface should include:

- Chat panel for recipe and nutrition questions.
- Recipe ingredient input support, including pasted multiline recipes.
- Nutrition result table.
- Warnings for ambiguous ingredient matches or unit conversions.
- Admin/settings section with:
  - USDA import status
  - `Update nutrition database` button
  - Ollama connection status

The chat response should avoid pretending uncertain calculations are exact. If a result depends on a guessed ingredient match or portion conversion, it must show that clearly.

## API Endpoints

Suggested endpoints:

- `GET /`
  - Main chat UI.

- `POST /api/chat`
  - Sends a user message to the Deepagent-powered chat agent.

- `POST /api/nutrition/lookup`
  - Direct ingredient lookup endpoint for Tool 1.

- `POST /api/nutrition/calculate`
  - Direct recipe calculation endpoint for Tool 2.

- `GET /api/usda/import/status`
  - Returns current import status.

- `POST /api/usda/import`
  - Starts manual USDA import/update.

- `GET /settings`
  - Admin/settings page.

## Error Handling

The app must handle:

- Missing USDA JSON dump path.
- Failed USDA import.
- Empty or corrupted SQLite database.
- Ollama endpoint unavailable.
- LLM normalization returning invalid JSON.
- Ingredient not found.
- Multiple likely USDA matches.
- Unit conversion unavailable.
- Long-running imports.

Errors shown to users should be readable and actionable. Internal logs should preserve technical details.

## Testing Requirements

Add automated tests for:

- `.env` configuration loading.
- First-run import detection.
- USDA importer parsing representative JSON records.
- Ingredient lookup exact match.
- Ingredient lookup approximate match.
- LLM normalization response parsing.
- Gram conversion from metric units.
- Gram conversion from USDA portion data.
- Calculator totals and per-serving totals.
- Ambiguous conversion warning behavior.
- Manual import endpoint preventing duplicate jobs.

## Acceptance Criteria

The app is ready for first release when:

- A fresh startup with a valid USDA JSON dump populates SQLite automatically.
- The settings page shows import status and can trigger an update.
- Ollama local endpoint can be configured through `.env`.
- Ollama cloud/proxy endpoint can be configured through `.env`.
- The Deepagent chat agent can call both nutrition tools.
- Ingredient names in other languages are normalized to standard English before database lookup.
- A recipe can be analyzed into per-ingredient nutrition rows and total nutrition.
- The calculator converts known measures to grams using USDA data where available.
- Ambiguous or unavailable conversions produce warnings instead of fabricated precision.
- Automated tests cover importer, lookup, normalization parsing, and calculation behavior.
