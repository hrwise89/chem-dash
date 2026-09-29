import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from economy import (
    HOURS_PER_DAY,
    REJECTED_RECOVERY_HOURS,
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
        # Game-start time context (hour 0, day 1's boundary, day 1) -- most
        # tests don't care about the exact values, just that offer/accept/
        # reject take them consistently.
        self.now = 0.0
        self.day_start = 0.0
        self.day = 1

    def offer(self, subject="Test job", sender="Test Sender", message="Test message",
              product="ethyl bromide", product_short_name="EtBr", amount=1.0, reward=20.0,
              now=None, day_start=None, day=None, **kwargs):
        return self.board.offer(subject, sender, message, product, product_short_name, amount, reward,
                                 self.now if now is None else now,
                                 self.day_start if day_start is None else day_start,
                                 self.day if day is None else day, **kwargs)

    def test_offer_adds_to_available(self):
        contract = self.offer()
        self.assertIn(contract, self.board.available)
        self.assertIsInstance(contract, Contract)
        self.assertFalse(contract.requires_purity)

    def test_offer_rejects_invalid_days_to_complete(self):
        with self.assertRaises(ValueError):
            self.offer(days_to_complete=3)

    def test_display_name_falls_back_to_subject_without_a_short_name(self):
        contract = self.offer(subject="Test job")
        self.assertEqual(contract.display_name, "Test job")

    def test_display_name_prefers_short_name_when_set(self):
        contract = self.offer(short_name="EtBr Order")
        self.assertEqual(contract.display_name, "EtBr Order")

    def test_order_type_defaults_to_synthesis_and_letter_is_its_first_char(self):
        contract = self.offer()
        self.assertEqual(contract.order_type, "Synthesis")
        self.assertEqual(contract.order_type_letter, "S")

    def test_accept_moves_from_available_to_accepted(self):
        contract = self.offer()
        accepted = self.board.accept(contract.contract_id, self.day_start)
        self.assertEqual(accepted, contract)
        self.assertNotIn(contract, self.board.available)
        self.assertIn(contract, self.board.accepted)

    def test_reject_moves_to_rejected_not_accepted(self):
        contract = self.offer()
        self.board.reject(contract.contract_id, self.now, self.day)
        self.assertNotIn(contract, self.board.available)
        self.assertNotIn(contract, self.board.accepted)
        self.assertIn(contract, self.board.rejected)

    def test_accept_unknown_id_raises(self):
        with self.assertRaises(ValueError):
            self.board.accept("nope", self.day_start)

    # --- Rush vs normal acceptance windows ---

    def test_normal_offer_accept_deadline_is_end_of_next_day(self):
        contract = self.offer(days_to_complete=5)
        self.assertEqual(contract.accept_deadline, 2 * HOURS_PER_DAY)

    def test_rush_offer_accept_deadline_is_end_of_same_day(self):
        contract = self.offer(days_to_complete=0)
        self.assertEqual(contract.accept_deadline, 1 * HOURS_PER_DAY)
        self.assertTrue(contract.is_rush)

    def test_open_ended_offer_uses_normal_accept_window_and_never_has_a_due_date(self):
        contract = self.offer(days_to_complete=None)
        self.assertEqual(contract.accept_deadline, 2 * HOURS_PER_DAY)
        self.board.accept(contract.contract_id, self.day_start)
        self.assertIsNone(contract.due_date)

    def test_accept_sets_due_date_from_days_to_complete(self):
        contract = self.offer(days_to_complete=2)
        self.board.accept(contract.contract_id, self.day_start)
        self.assertEqual(contract.due_date, 3 * HOURS_PER_DAY)

    # --- Rejection recovery / expiration sweeping ---

    def test_retrieve_moves_rejected_back_to_available(self):
        contract = self.offer()
        self.board.reject(contract.contract_id, self.now, self.day)
        retrieved = self.board.retrieve(contract.contract_id)
        self.assertEqual(retrieved, contract)
        self.assertIn(contract, self.board.available)
        self.assertNotIn(contract, self.board.rejected)
        self.assertIsNone(contract.rejected_at)

    def test_retrieve_unknown_id_raises(self):
        with self.assertRaises(ValueError):
            self.board.retrieve("nope")

    def test_sweep_expires_rejected_offer_past_recovery_window(self):
        contract = self.offer()
        self.board.reject(contract.contract_id, now=0.0, current_day=self.day)
        self.board.sweep_expirations(now=REJECTED_RECOVERY_HOURS + 0.1)
        self.assertNotIn(contract, self.board.rejected)
        self.assertIn(contract, self.board.expired)

    def test_sweep_leaves_rejected_offer_within_recovery_window(self):
        contract = self.offer()
        self.board.reject(contract.contract_id, now=0.0, current_day=self.day)
        self.board.sweep_expirations(now=REJECTED_RECOVERY_HOURS - 0.1)
        self.assertIn(contract, self.board.rejected)

    def test_sweep_expires_unaccepted_offer_past_its_accept_deadline(self):
        contract = self.offer(days_to_complete=0)  # Rush -- deadline at end of day 1
        self.board.sweep_expirations(now=HOURS_PER_DAY + 0.1)
        self.assertNotIn(contract, self.board.available)
        self.assertIn(contract, self.board.expired)

    def test_sweep_flags_overdue_accepted_contract_unfulfilled_once(self):
        contract = self.offer(days_to_complete=0)
        self.board.accept(contract.contract_id, self.day_start)  # due_date = HOURS_PER_DAY
        self.board.sweep_expirations(now=HOURS_PER_DAY + 0.1)
        self.assertIn(contract, self.board.accepted)  # still shippable -- no penalty yet
        self.assertTrue(contract.unfulfilled_recorded)
        stats = self.board.sender_stats[contract.sender]
        self.assertEqual(stats.offer_unfulfilled, 1)

        self.board.sweep_expirations(now=HOURS_PER_DAY + 10.0)
        self.assertEqual(stats.offer_unfulfilled, 1)  # not double-counted on a later sweep

    # --- Per-sender stats ---

    def test_reject_same_day_vs_next_day_tracked_separately(self):
        same_day = self.offer(sender="A")
        self.board.reject(same_day.contract_id, now=1.0, current_day=1)
        next_day = self.offer(sender="A")
        self.board.reject(next_day.contract_id, now=30.0, current_day=2)

        stats = self.board.sender_stats["A"]
        self.assertEqual(stats.rejected_same_day, 1)
        self.assertEqual(stats.rejected_next_day, 1)

    def test_ship_records_offer_fulfilled_for_sender(self):
        contract = self.offer(sender="A")
        self.board.accept(contract.contract_id, self.day_start)
        self.inventory.add_moles("ethyl bromide", 1.0)
        self.board.ship(contract.contract_id, self.inventory)
        self.assertEqual(self.board.sender_stats["A"].offer_fulfilled, 1)

    # --- Shipping (consumes product immediately, payment deferred) ---

    def test_ship_moves_to_in_transit_and_consumes_product_but_does_not_pay(self):
        contract = self.offer()
        self.board.accept(contract.contract_id, self.day_start)
        self.inventory.add_moles("ethyl bromide", 2.0)

        shipped = self.board.ship(contract.contract_id, self.inventory)
        self.assertEqual(shipped, contract)
        self.assertNotIn(contract, self.board.accepted)
        self.assertIn(contract, self.board.in_transit)
        self.assertEqual(self.wallet.balance, 0.0)  # not paid yet
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide"), 1.0, places=6)

    def test_ship_without_enough_product_raises_and_changes_nothing(self):
        contract = self.offer()
        self.board.accept(contract.contract_id, self.day_start)
        self.inventory.add_moles("ethyl bromide", 0.2)

        with self.assertRaises(ValueError):
            self.board.ship(contract.contract_id, self.inventory)
        self.assertIn(contract, self.board.accepted)
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide"), 0.2, places=6)

    def test_ship_not_accepted_raises(self):
        contract = self.offer()
        with self.assertRaises(ValueError):
            self.board.ship(contract.contract_id, self.inventory)

    def test_crude_order_accepts_crude_product(self):
        contract = self.offer(subject="Crude order", requires_purity=False)
        self.board.accept(contract.contract_id, self.day_start)
        self.inventory.add_moles("ethyl bromide (crude)", 1.0)

        self.board.ship(contract.contract_id, self.inventory)
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide (crude)"), 0.0, places=6)

    def test_crude_order_spends_crude_before_pure(self):
        contract = self.offer(subject="Crude order", requires_purity=False)
        self.board.accept(contract.contract_id, self.day_start)
        self.inventory.add_moles("ethyl bromide (crude)", 0.4)
        self.inventory.add_moles("ethyl bromide", 1.0)

        self.board.ship(contract.contract_id, self.inventory)
        # Crude fully spent first, then only the remaining 0.6 mol taken from pure.
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide (crude)"), 0.0, places=6)
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide"), 0.4, places=6)

    def test_pure_order_rejects_crude_only_stock(self):
        contract = self.offer(subject="Pure order", requires_purity=True)
        self.board.accept(contract.contract_id, self.day_start)
        self.inventory.add_moles("ethyl bromide (crude)", 5.0)  # plenty of crude, but it doesn't count

        with self.assertRaises(ValueError):
            self.board.ship(contract.contract_id, self.inventory)
        self.assertIn(contract, self.board.accepted)

    def test_pure_order_accepts_pure_stock(self):
        contract = self.offer(subject="Pure order", requires_purity=True)
        self.board.accept(contract.contract_id, self.day_start)
        self.inventory.add_moles("ethyl bromide", 1.0)

        self.board.ship(contract.contract_id, self.inventory)
        self.assertIn(contract, self.board.in_transit)

    # --- Overnight payment ---

    def test_process_overnight_pays_and_moves_to_history(self):
        contract = self.offer()
        self.board.accept(contract.contract_id, self.day_start)
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
            self.assertIn(contract.days_to_complete, {0, 2, 5, 10, None})


if __name__ == "__main__":
    unittest.main()
