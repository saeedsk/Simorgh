"""Financial asset and portfolio value tracking module."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple


@dataclass
class AssetHolding:
    """Represents a financial asset holding."""

    symbol: str
    asset_type: str
    quantity: float
    cost_basis: float
    current_price: float
    currency: str = "USD"
    last_updated: Optional[datetime] = None

    @property
    def total_cost(self) -> float:
        """Total cost basis for the holding."""
        return self.quantity * self.cost_basis

    @property
    def market_value(self) -> float:
        """Current market value of the holding."""
        return self.quantity * self.current_price

    @property
    def unrealized_gain_loss(self) -> float:
        """Absolute unrealized gain or loss."""
        return self.market_value - self.total_cost

    @property
    def return_on_investment(self) -> float:
        """Percentage return on investment."""
        if self.total_cost == 0:
            return 0.0
        return (self.unrealized_gain_loss / self.total_cost) * 100.0


@dataclass
class PortfolioSnapshot:
    """Historical snapshot of portfolio value."""

    timestamp: datetime
    total_value: float
    total_cost: float
    holdings_count: int


class AssetTracker:
    """Tracks financial assets, portfolio valuation, and performance metrics."""

    def __init__(self, base_currency: str = "USD") -> None:
        self.base_currency: str = base_currency
        self.holdings: Dict[str, AssetHolding] = {}
        self.history: List[PortfolioSnapshot] = []

    def record_asset(
        self,
        symbol: str,
        asset_type: str,
        quantity: float,
        cost_basis: float,
        current_price: Optional[float] = None,
        currency: Optional[str] = None,
    ) -> AssetHolding:
        """Add or update an asset holding."""
        if quantity < 0:
            raise ValueError("Quantity cannot be negative.")
        if cost_basis < 0:
            raise ValueError("Cost basis cannot be negative.")

        price = current_price if current_price is not None else cost_basis
        if price < 0:
            raise ValueError("Current price cannot be negative.")

        holding = AssetHolding(
            symbol=symbol.upper(),
            asset_type=asset_type.lower(),
            quantity=quantity,
            cost_basis=cost_basis,
            current_price=price,
            currency=(currency or self.base_currency).upper(),
            last_updated=datetime.now(),
        )
        self.holdings[symbol.upper()] = holding
        return holding

    def update_price(self, symbol: str, new_price: float) -> Optional[AssetHolding]:
        """Update market price for an existing asset."""
        sym = symbol.upper()
        if sym not in self.holdings:
            return None
        if new_price < 0:
            raise ValueError("Price cannot be negative.")
        holding = self.holdings[sym]
        holding.current_price = new_price
        holding.last_updated = datetime.now()
        return holding

    def add_transaction(
        self, symbol: str, quantity_delta: float, transaction_price: float, asset_type: str = "equity"
    ) -> AssetHolding:
        """Record buy (positive quantity) or sell (negative quantity) transaction."""
        sym = symbol.upper()
        if transaction_price < 0:
            raise ValueError("Transaction price cannot be negative.")

        if sym not in self.holdings:
            if quantity_delta <= 0:
                raise ValueError("Cannot initiate holding with negative quantity.")
            return self.record_asset(
                symbol=sym,
                asset_type=asset_type,
                quantity=quantity_delta,
                cost_basis=transaction_price,
                current_price=transaction_price,
            )

        holding = self.holdings[sym]
        new_quantity = holding.quantity + quantity_delta
        if new_quantity < 0:
            raise ValueError(f"Cannot sell more than owned quantity ({holding.quantity}).")

        if new_quantity == 0:
            holding.quantity = 0.0
            holding.cost_basis = 0.0
            holding.current_price = transaction_price
        elif quantity_delta > 0:
            # Weighted average cost basis for buys
            total_cost = (holding.quantity * holding.cost_basis) + (quantity_delta * transaction_price)
            holding.cost_basis = total_cost / new_quantity
            holding.quantity = new_quantity
            holding.current_price = transaction_price
        else:
            # Selling reduces quantity; cost basis per unit remains unchanged
            holding.quantity = new_quantity
            holding.current_price = transaction_price

        holding.last_updated = datetime.now()
        return holding

    def get_total_value(self) -> float:
        """Calculate aggregate market value across all holdings."""
        return sum(h.market_value for h in self.holdings.values())

    def get_total_cost(self) -> float:
        """Calculate total acquisition cost across all holdings."""
        return sum(h.total_cost for h in self.holdings.values())

    def get_total_gain_loss(self) -> Tuple[float, float]:
        """Return (unrealized_gain_loss, percentage_return) for the portfolio."""
        total_value = self.get_total_value()
        total_cost = self.get_total_cost()
        gain_loss = total_value - total_cost
        pct_return = (gain_loss / total_cost * 100.0) if total_cost > 0 else 0.0
        return round(gain_loss, 4), round(pct_return, 4)

    def get_allocation_by_type(self) -> Dict[str, float]:
        """Compute portfolio allocation percentage grouped by asset type."""
        total_value = self.get_total_value()
        if total_value == 0:
            return {}

        allocations: Dict[str, float] = {}
        for h in self.holdings.values():
            allocations[h.asset_type] = allocations.get(h.asset_type, 0.0) + h.market_value

        return {k: round((v / total_value) * 100.0, 2) for k, v in allocations.items()}

    def take_snapshot(self) -> PortfolioSnapshot:
        """Capture and record the current portfolio valuation snapshot."""
        snapshot = PortfolioSnapshot(
            timestamp=datetime.now(),
            total_value=self.get_total_value(),
            total_cost=self.get_total_cost(),
            holdings_count=len(self.holdings),
        )
        self.history.append(snapshot)
        return snapshot

    def portfolio_summary(self) -> Dict[str, object]:
        """Generate a complete structured portfolio summary."""
        gain_loss, roi = self.get_total_gain_loss()
        return {
            "base_currency": self.base_currency,
            "total_value": round(self.get_total_value(), 2),
            "total_cost": round(self.get_total_cost(), 2),
            "unrealized_gain_loss": gain_loss,
            "return_percentage": roi,
            "asset_count": len(self.holdings),
            "allocation_by_type": self.get_allocation_by_type(),
            "holdings": [
                {
                    "symbol": h.symbol,
                    "type": h.asset_type,
                    "quantity": h.quantity,
                    "cost_basis": round(h.cost_basis, 2),
                    "current_price": round(h.current_price, 2),
                    "market_value": round(h.market_value, 2),
                    "gain_loss": round(h.unrealized_gain_loss, 2),
                    "roi_pct": round(h.return_on_investment, 2),
                }
                for h in self.holdings.values()
            ],
        }


def track_portfolio(
    transactions: List[Dict[str, object]], base_currency: str = "USD"
) -> Dict[str, object]:
    """
    Process a series of transactions and return current portfolio valuation.

    Each transaction item format:
    {
        "symbol": "AAPL",
        "action": "buy" | "sell",
        "quantity": float,
        "price": float,
        "asset_type": "equity" (optional)
    }
    """
    tracker = AssetTracker(base_currency=base_currency)
    for txn in transactions:
        symbol = str(txn["symbol"])
        action = str(txn.get("action", "buy")).lower()
        qty = float(txn["quantity"])
        price = float(txn["price"])
        asset_type = str(txn.get("asset_type", "equity"))

        delta = qty if action == "buy" else -qty
        tracker.add_transaction(symbol, delta, price, asset_type=asset_type)

    tracker.take_snapshot()
    return tracker.portfolio_summary()