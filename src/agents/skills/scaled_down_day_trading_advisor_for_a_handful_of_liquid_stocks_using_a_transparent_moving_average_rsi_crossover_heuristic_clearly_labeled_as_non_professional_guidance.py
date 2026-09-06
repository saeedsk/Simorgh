"""
Day-trading advisor heuristic skill.

NON-PROFESSIONAL GUIDANCE ONLY. This module implements a simple, fully
transparent moving-average / RSI crossover heuristic over historical price
bars supplied by the caller. It does NOT fetch market data itself (no
network access is available to this skill), does NOT constitute financial
advice, and should not be relied upon for real trading decisions. Always
consult a licensed financial professional before making investment
decisions.
"""

from statistics import mean


def _simple_moving_average(closes, window):
    if len(closes) < window:
        return None
    return mean(closes[-window:])


def _relative_strength_index(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(-period, 0):
        change = closes[i] - closes[i - 1]
        if change >= 0:
            gains.append(change)
        else:
            losses.append(-change)

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def analyze_symbol(
    symbol,
    closes,
    short_window=5,
    long_window=20,
    rsi_period=14,
    rsi_overbought=70.0,
    rsi_oversold=30.0,
):
    """
    Produce a transparent BUY/SELL/HOLD heuristic signal for one symbol.

    Parameters
    ----------
    symbol : str
        Ticker symbol, for labeling only (not looked up or validated).
    closes : list[float]
        Historical closing prices in chronological order (oldest first).
        Caller is responsible for supplying this data; this skill has no
        network access and cannot fetch prices itself.
    short_window, long_window : int
        Periods (in bars) for the fast and slow simple moving averages.
    rsi_period : int
        Lookback period for the RSI calculation.
    rsi_overbought, rsi_oversold : float
        RSI thresholds used to flag overbought/oversold conditions.

    Returns
    -------
    dict with keys:
        symbol, signal ("BUY"/"SELL"/"HOLD"), reason (str explanation),
        short_ma, long_ma, rsi, disclaimer (str)

    Raises
    ------
    ValueError
        If not enough price data is supplied to compute the indicators.
    """
    disclaimer = (
        "This is an automated heuristic for educational purposes only, "
        "not professional financial advice. Trading involves risk of loss."
    )

    if not isinstance(closes, list) or len(closes) < 2:
        raise ValueError("closes must be a list with at least 2 price points")

    required = max(short_window, long_window, rsi_period + 1)
    if len(closes) < required:
        raise ValueError(
            f"need at least {required} closing prices, got {len(closes)}"
        )

    short_ma = _simple_moving_average(closes, short_window)
    long_ma = _simple_moving_average(closes, long_window)
    rsi = _relative_strength_index(closes, rsi_period)

    prev_short_ma = _simple_moving_average(closes[:-1], short_window)
    prev_long_ma = _simple_moving_average(closes[:-1], long_window)

    bullish_cross = (
        prev_short_ma is not None
        and prev_long_ma is not None
        and prev_short_ma <= prev_long_ma
        and short_ma > long_ma
    )
    bearish_cross = (
        prev_short_ma is not None
        and prev_long_ma is not None
        and prev_short_ma >= prev_long_ma
        and short_ma < long_ma
    )

    signal = "HOLD"
    reasons = []

    if bullish_cross and rsi is not None and rsi < rsi_overbought:
        signal = "BUY"
        reasons.append(
            f"short MA ({short_ma:.2f}) crossed above long MA "
            f"({long_ma:.2f}) with RSI {rsi:.1f} not overbought"
        )
    elif bearish_cross and rsi is not None and rsi > rsi_oversold:
        signal = "SELL"
        reasons.append(
            f"short MA ({short_ma:.2f}) crossed below long MA "
            f"({long_ma:.2f}) with RSI {rsi:.1f} not oversold"
        )
    elif rsi is not None and rsi >= rsi_overbought:
        signal = "SELL"
        reasons.append(f"RSI {rsi:.1f} indicates overbought conditions")
    elif rsi is not None and rsi <= rsi_oversold:
        signal = "BUY"
        reasons.append(f"RSI {rsi:.1f} indicates oversold conditions")
    else:
        reasons.append(
            f"no crossover and RSI {rsi:.1f} in neutral range "
            f"({rsi_oversold}-{rsi_overbought})"
            if rsi is not None
            else "insufficient signal strength for a directional call"
        )

    return {
        "symbol": symbol,
        "signal": signal,
        "reason": "; ".join(reasons),
        "short_ma": short_ma,
        "long_ma": long_ma,
        "rsi": rsi,
        "disclaimer": disclaimer,
    }


def analyze_watchlist(price_history_by_symbol, **kwargs):
    """
    Run analyze_symbol over a dict of {symbol: closes_list} and return a
    list of result dicts, skipping symbols with insufficient data (their
    error is included instead of raising, so one bad symbol doesn't stop
    the whole watchlist).
    """
    results = []
    for symbol, closes in price_history_by_symbol.items():
        try:
            results.append(analyze_symbol(symbol, closes, **kwargs))
        except ValueError as exc:
            results.append(
                {
                    "symbol": symbol,
                    "signal": "HOLD",
                    "reason": f"could not analyze: {exc}",
                    "short_ma": None,
                    "long_ma": None,
                    "rsi": None,
                    "disclaimer": (
                        "This is an automated heuristic for educational "
                        "purposes only, not professional financial advice."
                    ),
                }
            )
    return results