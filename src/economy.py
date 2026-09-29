"""
Money and contracts ("orders") -- the computer bench's contract inbox/
catalogue functions, plus the shipping bench's overnight-fulfillment
mechanic. Kept arcade-free (and DayManager-free -- times/days are passed
in as plain floats/ints) so it stays headless-testable, like
reaction_engine.py/inventory.py.

A contract's lifecycle:
  available -> accepted -> in_transit -> history
      |    \\                (shipping bench:   (paid out
      |     \\-> rejected     product consumed   the following
      |          |    \\      from inventory,    morning --
      |          |     \\--> expired  payment      see process_overnight)
      |          \\-------->  ^        deferred)
      \\------------------->  |
       (unaccepted past      (rejected past its 1-hour
        its accept_deadline,  recovery window -- see
        or rejected past      ContractBoard.retrieve)
        recovery)

`available` = the contract inbox's Inbox tab (accept/reject); `rejected`
is its Rejected tab (retrieve, within the recovery window, or let it
expire); `expired` is terminal -- nothing leaves it. sweep_expirations()
drives the available->expired, rejected->expired, and the
accepted-but-overdue bookkeeping (see ContractBoard.sweep_expirations);
call it before reading any of these pools for display, since none of
these transitions happen on their own between calls.
"""

import itertools
import json
from dataclasses import dataclass

from inventory import (
    ChemicalInventory,
    ConsumableCatalogEntry,
    ConsumableInventory,
    EquipmentCatalogEntry,
    EquipmentInventory,
    crude_name_for,
)


# A contract's days_to_complete: 0 is "Rush" (due the same day it's
# accepted), 2/5/10 are normal windows, None is "Open Ended" (never
# expires once accepted). Matches day_manager.HOURS_PER_CALENDAR_DAY, but
# duplicated as a plain float here rather than importing day_manager --
# this module stays arcade/DayManager-free so it's headless-testable.
ALLOWED_DAYS_TO_COMPLETE = {0, 2, 5, 10, None}
HOURS_PER_DAY = 24.0

# How long a rejected offer stays recoverable (ContractBoard.retrieve())
# before ContractBoard.sweep_expirations() moves it to `expired` for good.
REJECTED_RECOVERY_HOURS = 1.0


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


def buy_equipment(equipment_inventory: EquipmentInventory, wallet: Wallet,
                   catalog_entry: EquipmentCatalogEntry) -> float:
    """
    Buy one unit of `catalog_entry` (an inventory.EquipmentCatalogEntry --
    see src/data/equipment.json) from the catalogue, adding a new
    EquipmentItem to equipment_inventory. Returns the cost. Raises KeyError
    if the entry has no price (not sold), and InsufficientFundsError if the
    wallet can't cover it -- either way, nothing is added.
    """
    if catalog_entry.price is None:
        raise KeyError(f"'{catalog_entry.name}' isn't sold in the catalogue")
    wallet.spend(catalog_entry.price)          # raises (and leaves inventory untouched) if unaffordable
    equipment_inventory.add_item(catalog_entry.type, catalog_entry.name, capacity=catalog_entry.capacity)
    return catalog_entry.price


def buy_consumable(consumables: ConsumableInventory, wallet: Wallet,
                    catalog_entry: ConsumableCatalogEntry, amount: float) -> float:
    """
    Buy `amount` (native units, e.g. mL or g) of `catalog_entry` (an
    inventory.ConsumableCatalogEntry -- see src/data/consumables.json) from
    the catalogue. Returns the cost. Raises KeyError if the entry has no
    price, and InsufficientFundsError if the wallet can't cover it --
    either way, nothing is added.
    """
    if catalog_entry.price is None:
        raise KeyError(f"'{catalog_entry.name}' isn't sold in the catalogue")
    cost = amount * catalog_entry.price
    wallet.spend(cost)                          # raises (and leaves inventory untouched) if unaffordable
    consumables.add(catalog_entry.name, amount)
    return cost


@dataclass
class Contract:
    """
    A job offered on the computer bench: deliver `amount` moles of
    `product` (a reaction output the player can already make) for
    `reward` money.

    `sender`/`subject`/`message` are the incoming-order framing (an
    in-game email: who sent it, its subject line, its full body) --
    `subject` is the short line a list row shows, `message` is the full
    text a detail view shows in full rather than truncating.

    `order_type` (e.g. "Synthesis", "Purification", "Analysis",
    "Research") categorizes what kind of job this is -- every contract
    today is "Synthesis"; `order_type_letter` is its single-letter list
    indicator until sprites.py grows a per-type icon.

    `product` is always the substance's pure name (e.g. "ethyl bromide"),
    never the "(crude)" form -- `requires_purity` says whether the crude
    form is also acceptable:
      - requires_purity=False ("orders for crude product"): either the
        crude or the pure form counts, crude spent first (see
        ContractBoard.ship) so pure stock is saved for orders that need it.
      - requires_purity=True ("orders for pure product"): only the pure
        form counts.

    `purity` is a target percentage (e.g. 95.0) alongside requires_purity
    -- a placeholder for a future "not just pure, but *this* pure" check;
    nothing reads it yet, so any value is a no-op today.

    `product_short_name` is the compact chemical name a fixed-width list
    row shows (e.g. "EtBr" for "ethyl bromide") -- separate from
    `short_name`, which is the whole *order's* compact label as shown by
    other benches (computer bench's offer list, the reaction bench
    notebook), not just the chemical.

    `days_to_complete` is one of ALLOWED_DAYS_TO_COMPLETE: 0 ("Rush"),
    2/5/10, or None ("Open Ended", never expires once accepted).
    `offered_at`/`offered_day` are the game_clock hour and calendar day
    ContractBoard.offer() created this contract on -- used to compute
    `accept_deadline` (see offer()) and, at accept() time, `due_date` (the
    hour by which it must be shipped; None until accepted, and always
    None for an Open Ended contract). `rejected_at` is the game_clock
    hour of the most recent reject() (None if never rejected, or after a
    retrieve()) -- ContractBoard.sweep_expirations() reads it against
    REJECTED_RECOVERY_HOURS. `unfulfilled_recorded` guards against
    double-counting a sender's offer_unfulfilled stat across repeated
    sweeps once a contract has gone overdue.
    """
    contract_id: str
    subject: str
    sender: str
    message: str
    product: str
    product_short_name: str
    amount: float
    reward: float
    requires_purity: bool = False
    purity: float = 100.0
    order_type: str = "Synthesis"
    short_name: str | None = None   # what a fixed-width list row shows; None falls back to `subject`
    days_to_complete: int | None = None
    offered_at: float = 0.0
    offered_day: int = 1
    accept_deadline: float = 0.0
    due_date: float | None = None
    rejected_at: float | None = None
    unfulfilled_recorded: bool = False

    @property
    def display_name(self) -> str:
        return self.short_name or self.subject

    @property
    def order_type_letter(self) -> str:
        return self.order_type[0].upper() if self.order_type else "?"

    @property
    def is_rush(self) -> bool:
        return self.days_to_complete == 0

    @property
    def due_date_label(self) -> str:
        """A short label for a list row -- "Rush", "Open Ended", or the
        calendar day number it's due (see day_manager.day_number_for)."""
        if self.is_rush:
            return "Rush"
        if self.days_to_complete is None:
            return "Open Ended"
        if self.due_date is None:
            return f"{self.days_to_complete}d"  # not yet accepted -- no due_date to show a day for
        return f"Day {int(self.due_date // HOURS_PER_DAY) + 1}"


@dataclass
class SenderStats:
    """Per-sender/company bookkeeping ContractBoard keeps across every
    contract that sender has ever offered -- no gameplay penalties read
    these yet, they're purely tracked data (see module docstring)."""
    rejected_same_day: int = 0
    rejected_next_day: int = 0
    offer_expired: int = 0
    offer_fulfilled: int = 0
    offer_unfulfilled: int = 0


class ContractBoard:
    """Tracks a contract through available -> accepted -> in_transit ->
    history. Shipping consumes the product from inventory immediately
    (crude/pure rules per Contract.requires_purity); payment is deferred
    until process_overnight() runs (see the shipping bench / day-start
    hook), giving a one-day delay between fulfillment and payment."""

    def __init__(self):
        self.available: list[Contract] = []
        self.accepted: list[Contract] = []
        self.rejected: list[Contract] = []
        self.expired: list[Contract] = []
        self.in_transit: list[Contract] = []
        self.history: list[Contract] = []
        self.sender_stats: dict[str, SenderStats] = {}
        self._id_counter = itertools.count(1)

    def _stats_for(self, sender: str) -> SenderStats:
        return self.sender_stats.setdefault(sender, SenderStats())

    def offer(self, subject: str, sender: str, message: str, product: str, product_short_name: str,
              amount: float, reward: float, now: float, day_start_time: float, current_day: int,
              requires_purity: bool = False, purity: float = 100.0, order_type: str = "Synthesis",
              short_name: str | None = None, days_to_complete: int | None = None) -> Contract:
        """`now`/`day_start_time`/`current_day` are the caller's current
        game_clock hour, the hour the *current* calendar day started, and
        that day's number (see day_manager.DayManager) -- used to compute
        accept_deadline: end of `day_start_time`'s day for a Rush offer
        (days_to_complete == 0), end of the day after for every other
        offer (2/5/10/Open Ended alike)."""
        if days_to_complete not in ALLOWED_DAYS_TO_COMPLETE:
            raise ValueError(f"days_to_complete must be one of {ALLOWED_DAYS_TO_COMPLETE}, got {days_to_complete!r}")
        deadline_days = 1 if days_to_complete == 0 else 2
        accept_deadline = day_start_time + deadline_days * HOURS_PER_DAY
        contract = Contract(f"contract_{next(self._id_counter)}", subject, sender, message, product,
                             product_short_name, amount, reward, requires_purity, purity, order_type,
                             short_name, days_to_complete, now, current_day, accept_deadline)
        self.available.append(contract)
        return contract

    def accept(self, contract_id: str, day_start_time: float) -> Contract:
        """day_start_time is the hour the *current* calendar day started
        -- due_date (None for an Open Ended contract) is the end of the
        day `days_to_complete` days out from today, e.g. accepting a Rush
        (0) order due-dates it today; a 2-day order, two days from now."""
        contract = self._remove(self.available, contract_id, "available")
        if contract.days_to_complete is not None:
            contract.due_date = day_start_time + (contract.days_to_complete + 1) * HOURS_PER_DAY
        self.accepted.append(contract)
        return contract

    def reject(self, contract_id: str, now: float, current_day: int) -> Contract:
        """Moves the offer to `rejected` (recoverable via retrieve() for
        REJECTED_RECOVERY_HOURS -- see sweep_expirations()) rather than
        discarding it outright, and records whether this was a same-day
        or next-day reject against the sender's stats."""
        contract = self._remove(self.available, contract_id, "available")
        contract.rejected_at = now
        self.rejected.append(contract)
        stats = self._stats_for(contract.sender)
        if current_day == contract.offered_day:
            stats.rejected_same_day += 1
        else:
            stats.rejected_next_day += 1
        return contract

    def retrieve(self, contract_id: str) -> Contract:
        """Moves a still-recoverable rejected offer back to `available`.
        Raises ValueError if it's not in `rejected` -- including if
        sweep_expirations() already moved it to `expired`, since a caller
        should sweep before offering a Retrieve action in the first
        place."""
        contract = self._remove(self.rejected, contract_id, "rejected")
        contract.rejected_at = None
        self.available.append(contract)
        return contract

    def sweep_expirations(self, now: float) -> None:
        """Moves any available offer past its accept_deadline, and any
        rejected offer past its REJECTED_RECOVERY_HOURS window, to
        `expired` (incrementing the sender's offer_expired stat either
        way); also flags any accepted-but-overdue contract's sender stats
        with offer_unfulfilled, once, the first sweep after its due_date
        passes -- the contract itself stays in `accepted` and can still
        be shipped (no gameplay penalty yet, see module docstring). Call
        this before reading available/rejected/accepted for display --
        none of these transitions happen on their own between calls."""
        for contract in list(self.available):
            if now >= contract.accept_deadline:
                self.available.remove(contract)
                self.expired.append(contract)
                self._stats_for(contract.sender).offer_expired += 1
        for contract in list(self.rejected):
            if contract.rejected_at is not None and now - contract.rejected_at >= REJECTED_RECOVERY_HOURS:
                self.rejected.remove(contract)
                self.expired.append(contract)
                self._stats_for(contract.sender).offer_expired += 1
        for contract in self.accepted:
            if (contract.due_date is not None and now >= contract.due_date
                    and not contract.unfulfilled_recorded):
                contract.unfulfilled_recorded = True
                self._stats_for(contract.sender).offer_unfulfilled += 1

    def available_product_moles(self, contract: Contract, inventory: ChemicalInventory) -> float:
        """How much of `contract`'s product is currently on hand and
        eligible to ship -- just the pure form if requires_purity,
        otherwise pure + crude combined."""
        moles = inventory.moles_of(contract.product)
        if not contract.requires_purity:
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
        if not contract.requires_purity:
            crude_name = crude_name_for(contract.product)
            use_crude = min(inventory.moles_of(crude_name), remaining)
            if use_crude > 1e-9:
                inventory.remove_moles(crude_name, use_crude)
                remaining -= use_crude
        if remaining > 1e-9:
            inventory.remove_moles(contract.product, remaining)

        self.accepted.remove(contract)
        self.in_transit.append(contract)
        self._stats_for(contract.sender).offer_fulfilled += 1
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


def load_contract_offers(board: ContractBoard, path: str, now: float = 0.0,
                          day_start_time: float = 0.0, current_day: int = 1) -> None:
    """Seed `board` with the starter contract offers from a JSON file of
    {order_id: {subject, sender, message, product, product_short_name,
    amount, reward, requires_purity?, purity?, order_type?, short_name?,
    days_to_complete?}} -- see src/data/contracts.json. `now`/
    `day_start_time`/`current_day` default to game-start values (hour 0,
    day 1) since this is normally called right after creating a fresh
    GameClock/DayManager, before any time has passed -- pass the real
    current ones if seeding offers later into an already-running game."""
    with open(path, "r") as f:
        data = json.load(f)
    for spec in data.values():
        board.offer(spec["subject"], spec["sender"], spec["message"], spec["product"],
                    spec["product_short_name"], spec["amount"], spec["reward"], now, day_start_time,
                    current_day, spec.get("requires_purity", False), spec.get("purity", 100.0),
                    spec.get("order_type", "Synthesis"), spec.get("short_name"),
                    spec.get("days_to_complete"))
