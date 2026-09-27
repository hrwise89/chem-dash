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
    load_contract_offers,
)
from inventory import ChemicalInventory, ChemicalSpecies

SPECIES_CATALOG = {
    "ethanol": ChemicalSpecies(name="ethanol", state="liquid", molarity=1000.0, price_per_unit=0.03),
    "ethyl bromide": ChemicalSpecies(name="ethyl bromide", state="liquid", molarity=1000.0),  # not for sale
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


class TestContractBoard(unittest.TestCase):
    def setUp(self):
        self.board = ContractBoard()
        self.inventory = ChemicalInventory(species_catalog=SPECIES_CATALOG)
        self.wallet = Wallet(0.0)

    def test_offer_adds_to_available(self):
        contract = self.board.offer("Test job", "ethyl bromide", 1.0, 20.0)
        self.assertIn(contract, self.board.available)
        self.assertIsInstance(contract, Contract)

    def test_accept_moves_from_available_to_accepted(self):
        contract = self.board.offer("Test job", "ethyl bromide", 1.0, 20.0)
        accepted = self.board.accept(contract.contract_id)
        self.assertEqual(accepted, contract)
        self.assertNotIn(contract, self.board.available)
        self.assertIn(contract, self.board.accepted)

    def test_reject_discards_without_accepting(self):
        contract = self.board.offer("Test job", "ethyl bromide", 1.0, 20.0)
        self.board.reject(contract.contract_id)
        self.assertNotIn(contract, self.board.available)
        self.assertNotIn(contract, self.board.accepted)

    def test_accept_unknown_id_raises(self):
        with self.assertRaises(ValueError):
            self.board.accept("nope")

    def test_fulfill_pays_and_consumes_product(self):
        contract = self.board.offer("Test job", "ethyl bromide", 1.0, 20.0)
        self.board.accept(contract.contract_id)
        self.inventory.add_moles("ethyl bromide", 2.0)

        fulfilled = self.board.fulfill(contract.contract_id, self.inventory, self.wallet)
        self.assertEqual(fulfilled, contract)
        self.assertNotIn(contract, self.board.accepted)
        self.assertEqual(self.wallet.balance, 20.0)
        self.assertAlmostEqual(self.inventory.moles_of("ethyl bromide"), 1.0, places=6)

    def test_fulfill_without_enough_product_raises_and_changes_nothing(self):
        contract = self.board.offer("Test job", "ethyl bromide", 1.0, 20.0)
        self.board.accept(contract.contract_id)
        self.inventory.add_moles("ethyl bromide", 0.2)

        with self.assertRaises(ValueError):
            self.board.fulfill(contract.contract_id, self.inventory, self.wallet)
        self.assertIn(contract, self.board.accepted)
        self.assertEqual(self.wallet.balance, 0.0)

    def test_fulfill_not_accepted_raises(self):
        contract = self.board.offer("Test job", "ethyl bromide", 1.0, 20.0)
        with self.assertRaises(ValueError):
            self.board.fulfill(contract.contract_id, self.inventory, self.wallet)


class TestLoadContractOffers(unittest.TestCase):
    def test_loads_starter_contracts_json(self):
        board = ContractBoard()
        load_contract_offers(board, "src/data/contracts.json")
        self.assertGreater(len(board.available), 0)
        for contract in board.available:
            self.assertTrue(contract.product)
            self.assertGreater(contract.amount, 0)
            self.assertGreater(contract.reward, 0)


if __name__ == "__main__":
    unittest.main()
