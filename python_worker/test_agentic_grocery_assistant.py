import unittest
from python_worker.agentic_grocery_assistant import (
    GroceryItem,
    HouseholdProfile,
    AgenticGroceryAssistant,
)

class TestAgenticGroceryAssistant(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            GroceryItem("item_1", "Organic Oat Milk 1L", "beverages", 249, in_stock=True, tags={"vegan"}),
            GroceryItem("item_2", "Whole Cow Milk 1L", "beverages", 179, in_stock=True, allergens={"dairy"}),
            GroceryItem("item_3", "Sourdough Bread 500g", "bakery", 299, in_stock=True, allergens={"gluten"}),
            GroceryItem("item_4", "Gluten-Free Rice Loaf 400g", "bakery", 349, in_stock=True, tags={"vegan"}),
            GroceryItem("item_5", "Peanut Butter 350g", "spreads", 319, in_stock=True, allergens={"nuts"}, tags={"vegan"}),
            GroceryItem("item_6", "Sunflower Seed Butter 350g", "spreads", 369, in_stock=True, tags={"vegan"}),
            GroceryItem("item_7", "Organic Tofu 400g", "plant_protein", 229, in_stock=False, tags={"vegan"}),
            GroceryItem("item_8", "Tempeh 250g", "plant_protein", 259, in_stock=True, tags={"vegan"}),
            GroceryItem("item_9", "Fresh Organic Spinach 200g", "produce", 189, in_stock=True, tags={"vegan"}),
        ]
        self.assistant = AgenticGroceryAssistant(self.catalog)

    def test_synthesize_basket_respects_allergies(self):
        household = HouseholdProfile(
            household_id="hh_101",
            allergies={"nuts", "dairy"},
            weekly_budget_cents=5000
        )
        # item_2 (Cow milk) has dairy allergen; item_1 (Oat milk) is safe.
        # item_5 (Peanut butter) has nuts allergen and has no safe substitution with 'peanut butter' in name.
        basket = self.assistant.synthesize_basket("b_001", household, ["milk", "peanut butter"])
        self.assertEqual(len(basket.items), 1)
        self.assertEqual(basket.items[0].name, "Organic Oat Milk 1L")
        eval_metrics = self.assistant.evaluate_basket_safety(basket, household)
        self.assertEqual(eval_metrics["allergy_safety_rate"], 1.0)

    def test_synthesize_basket_out_of_stock_substitution(self):
        household = HouseholdProfile(
            household_id="hh_102",
            dietary_preferences={"vegan"},
            weekly_budget_cents=5000
        )
        # item_7 (Tofu) is out of stock, should substitute with Tempeh
        basket = self.assistant.synthesize_basket("b_002", household, ["tofu"])
        self.assertEqual(len(basket.items), 1)
        self.assertEqual(basket.items[0].item_id, "item_8")
        self.assertEqual(len(basket.substitutions), 1)
        self.assertEqual(basket.substitutions[0]["original"], "Organic Tofu 400g")
        self.assertEqual(basket.substitutions[0]["replacement"], "Tempeh 250g")

    def test_budget_guardrail_capping(self):
        household = HouseholdProfile(
            household_id="hh_103",
            weekly_budget_cents=500  # only 5.00 EUR
        )
        # Milk (2.49) + Bread (2.99) would be 5.48 EUR > 5.00 EUR
        basket = self.assistant.synthesize_basket("b_003", household, ["oat milk", "sourdough"])
        self.assertLessEqual(basket.total_cost_cents, 500)
        self.assertEqual(len(basket.items), 1)
        self.assertEqual(basket.items[0].price_cents, 249)

    def test_empty_query_returns_valid_structure(self):
        household = HouseholdProfile(household_id="hh_104")
        basket = self.assistant.synthesize_basket("b_004", household, [])
        self.assertEqual(basket.items, [])
        self.assertEqual(basket.total_cost_cents, 0)
        eval_metrics = self.assistant.evaluate_basket_safety(basket, household)
        self.assertEqual(eval_metrics["allergy_safety_rate"], 1.0)

if __name__ == "__main__":
    unittest.main()
