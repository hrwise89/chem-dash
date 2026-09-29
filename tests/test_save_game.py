import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from day_manager import DayManager
from economy import ContractBoard, Wallet, load_contract_offers
from game_clock import GameClock
from inventory import ChemicalInventory, ConsumableInventory, EquipmentInventory
from reaction_engine import ReactionEngine
from save_game import build_save_data, load_game, save_game
from skills import PlayerSkills

SPECIES_CATALOG_PATH = "src/data/chemicals.json"
REACTIONS_PATH = "src/data/reactions.json"
CONTRACTS_PATH = "src/data/contracts.json"


def make_window(**overrides) -> SimpleNamespace:
    from inventory import load_species_catalog

    window = SimpleNamespace(
        wallet=Wallet(150.0),
        day_manager=DayManager(),
        game_clock=GameClock(),
        player_skills=PlayerSkills(),
        chemical_inventory=ChemicalInventory(species_catalog=load_species_catalog(SPECIES_CATALOG_PATH)),
        consumables=ConsumableInventory(),
        equipment_inventory=EquipmentInventory(),
        contract_board=ContractBoard(),
        reaction_engine=ReactionEngine(REACTIONS_PATH),
    )
    for key, value in overrides.items():
        setattr(window, key, value)
    return window


class TestBuildAndApplySaveData(unittest.TestCase):

    def setUp(self):
        self.window = make_window()

    def test_round_trips_wallet_day_clock_and_skills(self):
        self.window.wallet.balance = 321.5
        self.window.day_manager.current_day = 4
        self.window.day_manager.day_start_time = 12.0
        self.window.game_clock.advance(12.0)
        self.window.player_skills.levels["synthesis"] = 3

        data = build_save_data(self.window, player_row=5, player_col=7)

        fresh = make_window()
        row, col = _apply(fresh, data)

        self.assertEqual(fresh.wallet.balance, 321.5)
        self.assertEqual(fresh.day_manager.current_day, 4)
        self.assertEqual(fresh.day_manager.day_start_time, 12.0)
        self.assertEqual(fresh.game_clock.now(), 12.0)
        self.assertEqual(fresh.player_skills.levels["synthesis"], 3)
        self.assertEqual((row, col), (5, 7))

    def test_round_trips_chemical_and_consumable_contents(self):
        self.window.chemical_inventory.add("ethanol", 250.0)
        self.window.consumables.add("Silica Gel", 40.0)

        data = build_save_data(self.window, 0, 0)
        fresh = make_window()
        _apply(fresh, data)

        self.assertEqual(fresh.chemical_inventory.contents["ethanol"], 250.0)
        self.assertEqual(fresh.consumables.contents["Silica Gel"], 40.0)

    def test_round_trips_equipment_and_resumes_id_counter_above_restored_ids(self):
        self.window.equipment_inventory.add_item("rb_flask", "RB Flask 250 mL", capacity=250.0)
        item = self.window.equipment_inventory.add_item("rb_flask", "RB Flask 500 mL", capacity=500.0)
        item.in_use = True

        data = build_save_data(self.window, 0, 0)
        fresh = make_window()
        _apply(fresh, data)

        self.assertEqual(len(fresh.equipment_inventory.items), 2)
        restored = fresh.equipment_inventory.items[item.id]
        self.assertTrue(restored.in_use)
        self.assertEqual(restored.capacity, 500.0)

        # A newly bought item after loading must not collide with a
        # restored id.
        new_item = fresh.equipment_inventory.add_item("rb_flask", "RB Flask 1 L", capacity=1000.0)
        self.assertNotEqual(new_item.id, item.id)
        self.assertEqual(len(fresh.equipment_inventory.items), 3)

    def test_round_trips_contract_board_across_all_four_pools(self):
        load_contract_offers(self.window.contract_board, CONTRACTS_PATH)
        contract = self.window.contract_board.available[0]
        self.window.contract_board.accept(contract.contract_id, day_start_time=0.0)

        data = build_save_data(self.window, 0, 0)
        fresh = make_window()
        _apply(fresh, data)

        self.assertEqual(len(fresh.contract_board.accepted), 1)
        self.assertEqual(fresh.contract_board.accepted[0].contract_id, contract.contract_id)
        self.assertEqual(fresh.contract_board.accepted[0].subject, contract.subject)

        # A fresh offer after loading must not collide with a restored id.
        new_contract = fresh.contract_board.offer("New job", "Test Sender", "Test message", "ethanol", "EtOH",
                                                    1.0, 10.0, now=0.0, day_start_time=0.0, current_day=1)
        self.assertNotEqual(new_contract.contract_id, contract.contract_id)

    def test_round_trips_rejected_expired_pools_and_sender_stats(self):
        load_contract_offers(self.window.contract_board, CONTRACTS_PATH)
        board = self.window.contract_board
        expired = board.available[0]
        later = max(c.accept_deadline for c in board.available) + 1.0
        board.sweep_expirations(now=later)  # expires every starter offer's accept window

        rejected = board.offer("Test job", "Test Sender", "Test message", "ethanol", "EtOH", 1.0, 10.0,
                                now=later, day_start_time=later, current_day=2)
        board.reject(rejected.contract_id, now=later, current_day=2)  # within its own recovery window

        data = build_save_data(self.window, 0, 0)
        fresh = make_window()
        _apply(fresh, data)

        self.assertEqual([c.contract_id for c in fresh.contract_board.rejected], [rejected.contract_id])
        self.assertIn(expired.contract_id, [c.contract_id for c in fresh.contract_board.expired])
        stats = fresh.contract_board.sender_stats
        self.assertEqual(stats[rejected.sender].rejected_same_day, 1)
        self.assertEqual(stats[expired.sender].offer_expired, 1)

    def test_round_trips_an_in_progress_reaction(self):
        inventory = self.window.chemical_inventory
        inventory.add("ethanol", 200.0)
        inventory.add("48% hydrobromic acid", 200.0)
        equipment = self.window.equipment_inventory
        equipment.add_item("rb_flask", "RB Flask 250 mL", capacity=250.0)

        process = self.window.reaction_engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.window.game_clock,
        )

        data = build_save_data(self.window, 0, 0)
        fresh = make_window()
        # Equipment must be restored before the reaction engine so the
        # process's reserved equipment ids still exist for collection.
        _apply(fresh, data)

        restored = fresh.reaction_engine.active_processes[process.process_id]
        self.assertEqual(restored.reaction_name, process.reaction_name)
        self.assertEqual(restored.end_time, process.end_time)
        self.assertIs(restored.definition, fresh.reaction_engine.reaction_db[process.reaction_name])

        # Collecting the restored process should work exactly like the
        # original would have.
        fresh.game_clock.advance_to(restored.end_time)
        products = fresh.reaction_engine.collect_reaction(
            process.process_id, fresh.chemical_inventory, fresh.equipment_inventory, fresh.game_clock,
        )
        self.assertIn("ethyl bromide (crude)", products)

    def test_round_trips_reaction_history(self):
        inventory = self.window.chemical_inventory
        inventory.add("ethanol", 200.0)
        inventory.add("48% hydrobromic acid", 200.0)
        equipment = self.window.equipment_inventory
        equipment.add_item("rb_flask", "RB Flask 250 mL", capacity=250.0)
        clock = self.window.game_clock

        process = self.window.reaction_engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, clock,
        )
        clock.advance_to(process.end_time)
        self.window.reaction_engine.collect_reaction(process.process_id, inventory, equipment, clock)

        data = build_save_data(self.window, 0, 0)
        fresh = make_window()
        _apply(fresh, data)

        self.assertEqual(len(fresh.reaction_engine.history), 1)
        self.assertEqual(fresh.reaction_engine.history[0].reaction_name,
                          self.window.reaction_engine.history[0].reaction_name)


class TestSaveGameFileRoundTrip(unittest.TestCase):

    def test_save_then_load_restores_state_from_disk(self):
        window = make_window()
        window.wallet.balance = 99.0
        window.chemical_inventory.add("ethanol", 10.0)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "save.json")
            save_game(window, player_row=3, player_col=9, path=path)

            fresh = make_window()
            position = load_game(fresh, path=path)

            self.assertEqual(position, (3, 9))
            self.assertEqual(fresh.wallet.balance, 99.0)
            self.assertEqual(fresh.chemical_inventory.contents["ethanol"], 10.0)

    def test_load_game_with_no_file_returns_none_and_changes_nothing(self):
        window = make_window()
        window.wallet.balance = 42.0

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "does_not_exist.json")
            result = load_game(window, path=path)

        self.assertIsNone(result)
        self.assertEqual(window.wallet.balance, 42.0)


def _apply(window, data):
    from save_game import apply_save_data
    return apply_save_data(window, data)


if __name__ == "__main__":
    unittest.main()
