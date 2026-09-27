"""
Money and contracts ("orders") -- the computer bench's two functions per
the design doc: buying chemicals from a catalogue, and accepting/
fulfilling contracts for products the player can already make. Kept
arcade-free so it stays headless-testable, like reaction_engine.py/
inventory.py.
"""

import itertools
import json
from dataclasses import dataclass

from inventory import ChemicalInventory


class InsufficientFundsError(Exception):
    """Raised when a purchase or other spend exceeds the current balance."""


class Wallet:
    """Tracks the player's cash on hand."""

    def __init__(self, balance: float = 0.0):
        self.balance = balance

    def deposit(self, amount: float):
        if amount < 0:
            raise ValueError("Cannot deposit a negative amount")
        self.balance += amount

    def spend(self, amount: float):
        if amount < 0:
            raise ValueError("Cannot spend a negative amount")
        if amount > self.balance:
            raise InsufficientFundsError(
                f"Not enough money: need ${amount:.2f}, have ${self.balance:.2f}"
            )
        self.balance -= amount


def buy_chemical(inventory: ChemicalInventory, wallet: Wallet, name: str, amount: float) -> float:
    """
    Buy `amount` (native units -- mL or g) of `name` from the catalogue, at
    its species' price_per_unit. Returns the cost. Raises KeyError if the
    species isn't sold in the catalogue (no price_per_unit), and
    InsufficientFundsError if the wallet can't cover it -- either way,
    nothing is added to inventory or spent.
    """
    species = inventory.species_for(name)
    if species.price_per_unit is None:
        raise KeyError(f"'{name}' isn't sold in the catalogue")
    cost = amount * species.price_per_unit
    wallet.spend(cost)          # raises (and leaves inventory untouched) if unaffordable
    inventory.add(name, amount)
    return cost


@dataclass
class Contract:
    """A job offered on the computer bench: deliver `amount` moles of
    `product` (a reaction output the player can already make) for
    `reward` money."""
    contract_id: str
    title: str
    product: str
    amount: float
    reward: float


class ContractBoard:
    """Tracks contracts available to accept and contracts already accepted.
    Fulfilling one consumes the product (in moles, matching how
    reaction_engine.py adds crude products to inventory) and pays the
    reward."""

    def __init__(self):
        self.available: list[Contract] = []
        self.accepted: list[Contract] = []
        self._id_counter = itertools.count(1)

    def offer(self, title: str, product: str, amount: float, reward: float) -> Contract:
        contract = Contract(f"contract_{next(self._id_counter)}", title, product, amount, reward)
        self.available.append(contract)
        return contract

    def accept(self, contract_id: str) -> Contract:
        contract = self._remove(self.available, contract_id, "available")
        self.accepted.append(contract)
        return contract

    def reject(self, contract_id: str) -> Contract:
        return self._remove(self.available, contract_id, "available")

    def fulfill(self, contract_id: str, inventory: ChemicalInventory, wallet: Wallet) -> Contract:
        contract = self._find(self.accepted, contract_id)
        if contract is None:
            raise ValueError(f"No accepted contract with id '{contract_id}'")
        if not inventory.has_moles(contract.product, contract.amount):
            have = inventory.available_moles(contract.product)
            raise ValueError(
                f"Not enough {contract.product} to fulfill this contract "
                f"(need {contract.amount:.2f} mol, have {have:.2f} mol)"
            )
        inventory.remove_moles(contract.product, contract.amount)
        wallet.deposit(contract.reward)
        self.accepted.remove(contract)
        return contract

    def _find(self, pool: list[Contract], contract_id: str) -> Contract | None:
        return next((c for c in pool if c.contract_id == contract_id), None)

    def _remove(self, pool: list[Contract], contract_id: str, pool_name: str) -> Contract:
        contract = self._find(pool, contract_id)
        if contract is None:
            raise ValueError(f"No {pool_name} contract with id '{contract_id}'")
        pool.remove(contract)
        return contract


def load_contract_offers(board: ContractBoard, path: str) -> None:
    """Seed `board` with the starter contract offers from a JSON file of
    {title: {product, amount, reward}} -- see src/data/contracts.json."""
    with open(path, "r") as f:
        data = json.load(f)
    for title, spec in data.items():
        board.offer(title, spec["product"], spec["amount"], spec["reward"])
