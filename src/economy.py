"""
Money and contracts ("orders") -- the computer bench's catalogue/contracts
functions, plus the shipping bench's overnight-fulfillment mechanic. Kept
arcade-free so it stays headless-testable, like reaction_engine.py/
inventory.py.

A contract's lifecycle:
  available -> accepted -> in_transit -> history
  (computer bench)  (open order,   (shipping bench:  (paid out
                      awaiting      product consumed  the following
                      shipment)     from inventory,   morning --
                                    payment deferred) see process_overnight)
"""

import itertools
import json
from dataclasses import dataclass

from inventory import ChemicalInventory, crude_name_for


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
    """
    A job offered on the computer bench: deliver `amount` moles of
    `product` (a reaction output the player can already make) for
    `reward` money.

    `product` is always the substance's pure name (e.g. "ethyl bromide"),
    never the "(crude)" form -- `requires_pure` says whether the crude form
    is also acceptable:
      - requires_pure=False ("orders for crude product"): either the crude
        or the pure form counts, crude spent first (see
        ContractBoard.ship) so pure stock is saved for orders that need it.
      - requires_pure=True ("orders for pure product"): only the pure form
        counts.
    """
    contract_id: str
    title: str
    product: str
    amount: float
    reward: float
    requires_pure: bool = False


class ContractBoard:
    """Tracks a contract through available -> accepted -> in_transit ->
    history. Shipping consumes the product from inventory immediately
    (crude/pure rules per Contract.requires_pure); payment is deferred
    until process_overnight() runs (see the shipping bench / day-start
    hook), giving a one-day delay between fulfillment and payment."""

    def __init__(self):
        self.available: list[Contract] = []
        self.accepted: list[Contract] = []
        self.in_transit: list[Contract] = []
        self.history: list[Contract] = []
        self._id_counter = itertools.count(1)

    def offer(self, title: str, product: str, amount: float, reward: float,
              requires_pure: bool = False) -> Contract:
        contract = Contract(f"contract_{next(self._id_counter)}", title, product, amount, reward, requires_pure)
        self.available.append(contract)
        return contract

    def accept(self, contract_id: str) -> Contract:
        contract = self._remove(self.available, contract_id, "available")
        self.accepted.append(contract)
        return contract

    def reject(self, contract_id: str) -> Contract:
        return self._remove(self.available, contract_id, "available")

    def available_product_moles(self, contract: Contract, inventory: ChemicalInventory) -> float:
        """How much of `contract`'s product is currently on hand and
        eligible to ship -- just the pure form if requires_pure, otherwise
        pure + crude combined."""
        moles = inventory.moles_of(contract.product)
        if not contract.requires_pure:
            moles += inventory.moles_of(crude_name_for(contract.product))
        return moles

    def ship(self, contract_id: str, inventory: ChemicalInventory) -> Contract:
        """
        Move an accepted (open) order to in_transit, consuming its product
        from inventory right away -- crude first when the crude form is
        acceptable, so pure stock is saved for orders that need it.
        Payment is NOT applied here; see process_overnight(). Raises
        ValueError (leaving both the contract and inventory untouched) if
        there isn't enough eligible product on hand yet.
        """
        contract = self._find(self.accepted, contract_id)
        if contract is None:
            raise ValueError(f"No open order with id '{contract_id}'")

        have = self.available_product_moles(contract, inventory)
        if have + 1e-9 < contract.amount:
            raise ValueError(
                f"Not enough {contract.product} to ship this order "
                f"(need {contract.amount:.2f} mol, have {have:.2f} mol)"
            )

        remaining = contract.amount
        if not contract.requires_pure:
            crude_name = crude_name_for(contract.product)
            use_crude = min(inventory.moles_of(crude_name), remaining)
            if use_crude > 1e-9:
                inventory.remove_moles(crude_name, use_crude)
                remaining -= use_crude
        if remaining > 1e-9:
            inventory.remove_moles(contract.product, remaining)

        self.accepted.remove(contract)
        self.in_transit.append(contract)
        return contract

    def process_overnight(self, wallet: Wallet) -> list[Contract]:
        """Pay out every shipment currently in transit -- call once when a
        new day begins (going home, or passing out). Returns the contracts
        paid, which also move into `history`."""
        paid = list(self.in_transit)
        for contract in paid:
            wallet.deposit(contract.reward)
        self.history.extend(paid)
        self.in_transit.clear()
        return paid

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
    {title: {product, amount, reward, requires_pure?}} -- see
    src/data/contracts.json."""
    with open(path, "r") as f:
        data = json.load(f)
    for title, spec in data.items():
        board.offer(title, spec["product"], spec["amount"], spec["reward"],
                    spec.get("requires_pure", False))
