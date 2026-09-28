import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from economy import (
    Contract,
    ContractBoard,
    InsufficientFundsError,
    Wallet,
    buy_chemical,
    buy_consumable,
    buy_equipment,
    load_contract_offers,
)
from inventory import (
    ChemicalInventory,
    ChemicalSpecies,
    ConsumableCatalogEntry,
    ConsumableInventory,
    EquipmentCatalogEntry,
    EquipmentInventory,
)

SPECIES_CATALOG = {
    "ethanol": ChemicalSpecies(name="ethanol", state="liquid", molarity=1000.0, density=1.0, price_per_unit=0.03),
    "ethyl bromide": ChemicalSpecies(name="ethyl bromide", state="liquid", molarity=1000.0, density=1.0),  # not for sale
}


class TestWallet(unittest.TestCase):
    def test_deposit_and_spend(self):
        wallet = Wallet(10.0)
        wallet.deposit(5.0)
        self.assertEqual(wallet.balance, 15.0)
        wallet.spend(4.0)
        self.assertEqual(wallet.balance, 11.0)

    def test_spend_more_than_balance_raises_and_leaves_balance_untouched(self):
        wallet = Wallet(10.0)
        with self.assertRaises(InsufficientFundsError):
            wallet.spend(11.0)
        self.assertEqual(wallet.balance, 10.0)

    def test_negative_deposit_or_spend_rejected(self):
        wallet = Wallet(10.0)
        with self.assertRaises(ValueError):
            wallet.deposit(-1.0)
        with self.assertRaises(ValueError):
            wallet.spend(-1.0)


class TestBuyChemical(unittest.TestCase):
    def setUp(self):
        self.inventory = ChemicalInventory(species_catalog=SPECIES_CATALOG)
        self.wallet = Wallet(100.0)

    def test_buy_deducts_cost_and_adds_to_inventory(self):
        cost = buy_chemical(self.inventory, self.wallet, "ethanol", 50.0)
        self.assertAlmostEqual(cost, 1.5, places=6)
        self.assertAlmostEqual(self.wallet.balance, 98.5, places=6)
        self.assertTrue(self.inventory.has("ethanol", 50.0))

    def test_buy_unaffordable_amount_raises_and_changes_nothing(self):
        with self.assertRaises(InsufficientFundsError):
            buy_chemical(self.inventory, self.wallet, "ethanol", 100_000.0)
        self.assertEqual(self.wallet.balance, 100.0)
        self.assertFalse(self.inventory.has("ethanol", 1.0))

    def test_buy_chemical_not_for_sale_raises(self):
        with self.assertRaises(KeyError):
            buy_chemical(self.inventory, self.wallet, "ethyl bromide", 10.0)
        self.assertEqual(self.wallet.balance, 100.0)


class TestBuyEquipment(unittest.TestCase):
    def setUp(self):
        self.equipment = EquipmentInventory()
        self.wallet = Wallet(100.0)

    def test_buy_adds_item_and_deducts_cost(self):
        entry = EquipmentCatalogEntry(name="RB Flask 250 mL", type="rb_flask", bench="reaction",
                                       price=40.0, capacity=250.0)
        cost = buy_equipment(self.equipment, self.wallet, entry)
        self.assertEqual(cost, 40.0)
        self.assertEqual(self.wallet.balance, 60.0)
        items = self.equipment.available_items("rb_flask")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].capacity, 250.0)
        self.assertEqual(items[0].name, "RB Flask 250 mL")

    def test_buy_unaffordable_raises_and_adds_nothing(self):
        entry = EquipmentCatalogEntry(name="Distillation Column (Bench)", type="distill_column_bench",
                                       bench="purify", price=200.0)
        with self.assertRaises(InsufficientFundsError):
            buy_equipment(self.equipment, Wallet(10.0), entry)
        self.assertEqual(self.equipment.available_items("distill_column_bench"), [])

    def test_buy_entry_without_price_raises(self):
        entry = EquipmentCatalogEntry(name="Mystery Item", type="mystery", bench="reaction", price=None)
        with self.assertRaises(KeyError):
            buy_equipment(self.equipment, self.wallet, entry)
        self.assertEqual(self.wallet.balance, 100.0)


class TestBuyConsumable(unittest.TestCase):
    def setUp(self):
        self.consumables = ConsumableInventory()
        self.wallet = Wallet(100.0)

    def test_buy_adds_amount_and_deducts_cost(self):
        entry = ConsumableCatalogEntry(name="Silica Gel", bench=["purify"], price=0.08, unit="g")
        cost = buy_consumable(self.consumables, self.wallet, entry, 100.0)
        self.assertAlmostEqual(cost, 8.0, places=6)
        self.assertAlmostEqual(self.wallet.balance, 92.0, places=6)
        self.assertTrue(self.consumables.has("Silica Gel", 100.0))

    def test_buy_unaffordable_raises_and_adds_nothing(self):
        entry = ConsumableCatalogEntry(name="Silica Gel", bench=["purify"], price=0.08, unit="g")
        with self.assertRaises(InsufficientFundsError):
            buy_consumable(self.consumables, Wallet(1.0), entry, 1000.0)
        self.assertFalse(self.consumables.has("Silica Gel", 1.0))

    def test_buy_entry_without_price_raises(self):
        entry = ConsumableCatalogEntry(name="Mystery Stuff", bench=["purify"], price=None)
        with self.assertRaises(KeyError):
            buy_consumable(self.consumables, self.wallet, entry, 10.0)
        self.assertEqual(self.wallet.balance, 100.0)


class TestContractBoard(unittest.TestCase):
    def setUp(self):
        self.board = ContractBoard()
        self.inventory = ChemicalInventory(species_catalog=SPECIES_CATALOG)
        self.wallet = Wallet(0.0)

    def test_offer_adds_to_available(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0)
        self.assertIn(contract, self.board.available)
        self.assertIsInstance(contract, Contract)
        self.assertFalse(contract.requires_purity)

    def test_display_name_falls_back_to_subject_without_a_short_name(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0)
        self.assertEqual(contract.display_name, "Test job")

    def test_display_name_prefers_short_name_when_set(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0,
                                     short_name="EtBr Order")
        self.assertEqual(contract.display_name, "EtBr Order")

    def test_order_type_defaults_to_synthesis_and_letter_is_its_first_char(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0)
        self.assertEqual(contract.order_type, "Synthesis")
        self.assertEqual(contract.order_type_letter, "S")

    def test_accept_moves_from_available_to_accepted(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0)
        accepted = self.board.accept(contract.contract_id)
        self.assertEqual(accepted, contract)
        self.assertNotIn(contract, self.board.available)
        self.assertIn(contract, self.board.accepted)

    def test_reject_discards_without_accepting(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0)
        self.board.reject(contract.contract_id)
        self.assertNotIn(contract, self.board.available)
        self.assertNotIn(contract, self.board.accepted)

    def test_accept_unknown_id_raises(self):
        with self.assertRaises(ValueError):
            self.board.accept("nope")

    # --- Shipping (consumes product immediately, payment deferred) ---

    def test_ship_moves_to_in_transit_and_consumes_product_but_does_not_pay(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0)
        self.board.accept(contract.contract_id)
        self.inventory.add_moles("ethyl bromide", 2.0)

        shipped = self.board.ship(contract.contract_id, self.inventory)
        self.assertEqual(shipped, contract)
        self.assertNotIn(contract, self.board.accepted)
        self.assertIn(contract, self.board.in_transit)
        self.assertEqual(self.wallet.balance, 0.0)  # not paid yet
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide"), 1.0, places=6)

    def test_ship_without_enough_product_raises_and_changes_nothing(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0)
        self.board.accept(contract.contract_id)
        self.inventory.add_moles("ethyl bromide", 0.2)

        with self.assertRaises(ValueError):
            self.board.ship(contract.contract_id, self.inventory)
        self.assertIn(contract, self.board.accepted)
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide"), 0.2, places=6)

    def test_ship_not_accepted_raises(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0)
        with self.assertRaises(ValueError):
            self.board.ship(contract.contract_id, self.inventory)

    def test_crude_order_accepts_crude_product(self):
        contract = self.board.offer("Crude order", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0, requires_purity=False)
        self.board.accept(contract.contract_id)
        self.inventory.add_moles("ethyl bromide (crude)", 1.0)

        self.board.ship(contract.contract_id, self.inventory)
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide (crude)"), 0.0, places=6)

    def test_crude_order_spends_crude_before_pure(self):
        contract = self.board.offer("Crude order", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0, requires_purity=False)
        self.board.accept(contract.contract_id)
        self.inventory.add_moles("ethyl bromide (crude)", 0.4)
        self.inventory.add_moles("ethyl bromide", 1.0)

        self.board.ship(contract.contract_id, self.inventory)
        # Crude fully spent first, then only the remaining 0.6 mol taken from pure.
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide (crude)"), 0.0, places=6)
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide"), 0.4, places=6)

    def test_pure_order_rejects_crude_only_stock(self):
        contract = self.board.offer("Pure order", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0, requires_purity=True)
        self.board.accept(contract.contract_id)
        self.inventory.add_moles("ethyl bromide (crude)", 5.0)  # plenty of crude, but it doesn't count

        with self.assertRaises(ValueError):
            self.board.ship(contract.contract_id, self.inventory)
        self.assertIn(contract, self.board.accepted)

    def test_pure_order_accepts_pure_stock(self):
        contract = self.board.offer("Pure order", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0, requires_purity=True)
        self.board.accept(contract.contract_id)
        self.inventory.add_moles("ethyl bromide", 1.0)

        self.board.ship(contract.contract_id, self.inventory)
        self.assertIn(contract, self.board.in_transit)

    # --- Overnight payment ---

    def test_process_overnight_pays_and_moves_to_history(self):
        contract = self.board.offer("Test job", "Test Sender", "Test message", "ethyl bromide", "EtBr", 1.0, 20.0)
        self.board.accept(contract.contract_id)
        self.inventory.add_moles("ethyl bromide", 1.0)
        self.board.ship(contract.contract_id, self.inventory)

        paid = self.board.process_overnight(self.wallet)
        self.assertEqual(paid, [contract])
        self.assertEqual(self.wallet.balance, 20.0)
        self.assertEqual(self.board.in_transit, [])
        self.assertIn(contract, self.board.history)

    def test_process_overnight_with_nothing_in_transit_is_a_no_op(self):
        paid = self.board.process_overnight(self.wallet)
        self.assertEqual(paid, [])
        self.assertEqual(self.wallet.balance, 0.0)


class TestLoadContractOffers(unittest.TestCase):
    def test_loads_starter_contracts_json(self):
        board = ContractBoard()
        load_contract_offers(board, "src/data/contracts.json")
        self.assertGreater(len(board.available), 0)
        for contract in board.available:
            self.assertTrue(contract.product)
            self.assertGreater(contract.amount, 0)
            self.assertGreater(contract.reward, 0)
            self.assertTrue(contract.display_name)  # every starter contract has a short_name


if __name__ == "__main__":
    unittest.main()
