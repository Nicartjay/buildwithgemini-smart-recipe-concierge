import os
from google.cloud import firestore

# Hardcode project ID as string for Firestore client (do NOT use GOOGLE_CLOUD_PROJECT or google.auth.default())
PROJECT_ID = "qwiklabs-gcp-02-563af7ba3456"

SEED_RECIPES = [
    {
        "recipe_id": "recipe-001",
        "title": "Avocado Lime Guacamole",
        "description": "Fresh and creamy homemade guacamole with fresh lime juice, coriander, and diced tomatoes.",
        "prep_time_minutes": 10,
        "cook_time_minutes": 0,
        "servings": 4,
        "calories_per_serving": 150,
        "dietary_tags": ["vegan", "gluten-free", "keto", "dairy-free"],
        "ingredients": [
            "3 ripe avocados",
            "1 lime, juiced",
            "1/2 tsp salt",
            "1/2 cup diced tomato",
            "1/4 cup finely chopped red onion",
            "2 tbsp fresh cilantro, chopped"
        ],
        "instructions": [
            "Cut avocados in half, remove pit, and scoop flesh into a bowl.",
            "Mash avocado coarsely with a fork.",
            "Stir in lime juice, salt, red onion, tomato, and cilantro.",
            "Serve immediately with fresh vegetable sticks or corn chips."
        ]
    },
    {
        "recipe_id": "recipe-002",
        "title": "Quinoa Mediterranean Power Bowl",
        "description": "Nutritious power bowl featuring fluffy quinoa, roasted chickpeas, cucumber, Kalamata olives, and creamy tahini dressing.",
        "prep_time_minutes": 15,
        "cook_time_minutes": 20,
        "servings": 2,
        "calories_per_serving": 420,
        "dietary_tags": ["vegetarian", "gluten-free", "vegan", "high-fiber"],
        "ingredients": [
            "1 cup cooked quinoa",
            "1 cup canned chickpeas, rinsed and drained",
            "1/2 cup diced cucumber",
            "1/2 cup cherry tomatoes, halved",
            "1/4 cup Kalamata olives",
            "2 tbsp tahini dressing"
        ],
        "instructions": [
            "Cook quinoa according to package directions and let cool slightly.",
            "Arrange quinoa, chickpeas, cucumber, tomatoes, and olives in serving bowls.",
            "Drizzle with tahini dressing before serving."
        ]
    },
    {
        "recipe_id": "recipe-003",
        "title": "Grilled Lemon Herb Chicken",
        "description": "Juicy chicken breast marinated in garlic, olive oil, lemon zest, and fresh rosemary.",
        "prep_time_minutes": 15,
        "cook_time_minutes": 20,
        "servings": 4,
        "calories_per_serving": 380,
        "dietary_tags": ["keto", "dairy-free", "high-protein", "gluten-free"],
        "ingredients": [
            "4 boneless skinless chicken breasts",
            "3 tbsp olive oil",
            "2 cloves garlic, minced",
            "1 lemon, zested and juiced",
            "1 tbsp fresh rosemary, chopped",
            "1 tsp salt and pepper"
        ],
        "instructions": [
            "In a bowl, mix olive oil, garlic, lemon juice, zest, rosemary, salt, and pepper.",
            "Coat chicken breasts in marinade and refrigerate for at least 15 minutes.",
            "Grill over medium-high heat for 6-8 minutes per side until internal temperature reaches 165°F (74°C).",
            "Rest for 5 minutes before slicing and serving."
        ]
    },
    {
        "recipe_id": "recipe-004",
        "title": "Creamy Wild Mushroom Pasta",
        "description": "Savory tagliatelle pasta with sautéed cremini and shiitake mushrooms in garlic-parmesan cream sauce.",
        "prep_time_minutes": 10,
        "cook_time_minutes": 15,
        "servings": 3,
        "calories_per_serving": 510,
        "dietary_tags": ["vegetarian"],
        "ingredients": [
            "250g tagliatelle or fettuccine pasta",
            "200g mixed mushrooms (cremini & shiitake), sliced",
            "2 tbsp butter",
            "2 cloves garlic, minced",
            "1/2 cup heavy cream",
            "1/3 cup grated parmesan cheese",
            "Fresh parsley for garnish"
        ],
        "instructions": [
            "Boil pasta in salted water according to package instructions until al dente.",
            "Melt butter in a skillet over medium heat and sauté mushrooms until golden brown.",
            "Add minced garlic and cook for 1 minute until fragrant.",
            "Pour in heavy cream and bring to a simmer; stir in parmesan cheese until melted.",
            "Toss cooked pasta with sauce and garnish with fresh parsley."
        ]
    },
    {
        "recipe_id": "recipe-005",
        "title": "Berry Chia Smoothie Bowl",
        "description": "Refreshing thick smoothie bowl made with blended berries, banana, almond milk, topped with chia seeds and granola.",
        "prep_time_minutes": 5,
        "cook_time_minutes": 0,
        "servings": 1,
        "calories_per_serving": 220,
        "dietary_tags": ["vegan", "gluten-free", "dairy-free"],
        "ingredients": [
            "1 cup frozen mixed berries",
            "1 frozen banana",
            "1/2 cup unsweetened almond milk",
            "1 tbsp chia seeds",
            "2 tbsp gluten-free granola"
        ],
        "instructions": [
            "Blend frozen berries, banana, and almond milk until thick and smooth.",
            "Pour into a bowl and top with chia seeds and granola.",
            "Enjoy immediately with a spoon."
        ]
    }
]

def seed_recipes():
    print(f"Connecting to Firestore for project: {PROJECT_ID}...")
    db = firestore.Client(project=PROJECT_ID)
    collection_ref = db.collection("recipes")
    
    for recipe in SEED_RECIPES:
        doc_id = recipe["recipe_id"]
        collection_ref.document(doc_id).set(recipe)
        print(f"  ✓ Seeded recipe '{doc_id}': {recipe['title']}")

    print("\nFirestore seeding complete!")

if __name__ == "__main__":
    seed_recipes()
