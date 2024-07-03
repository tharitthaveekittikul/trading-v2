import logging
import time
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd

from config import MT5_ACCOUNT, MT5_PASSWORD, MT5_SERVER, STOP_LOSS_PIPS, TAKE_PROFIT_PIPS, LOT_SIZE, LOG_FILE, \
    CHECK_INTERVAL

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

FIXED_MIN_STOP_DISTANCE = 100 * 0.01  # 100 pips as a fallback minimum stop distance


def connect_to_mt5() -> bool:
    """
    Initializes the connection to MT5 and logs in with the provided account credentials.
    """
    print("MetaTrader5 package author: ", mt5.__author__)
    print("MetaTrader5 package version: ", mt5.__version__)
    logging.info("MetaTrader5 package author: %s, version: %s", mt5.__author__, mt5.__version__)

    # Connect to the account
    account = MT5_ACCOUNT
    password = MT5_PASSWORD
    server = MT5_SERVER

    # Initialize MT5 connection
    if not mt5.initialize(login=account, server=server, password=password):
        print("Initialize failed, error code =", mt5.last_error())
        logging.error("Initialize failed, error code = %s", mt5.last_error())
        return False

    print(f"Initialize version: {mt5.version()}")
    authorized = mt5.login(account, password=password, server=server)
    if not authorized:
        print(f"Failed to connect at account #{account}, error code: {mt5.last_error()}")
        logging.error("Login failed, error code = %s", mt5.last_error())
        return False

    print(mt5.account_info())
    print("Show account_info()._asdict():")
    account_info_dict = mt5.account_info()._asdict()
    for prop in account_info_dict:
        print(f"  {prop} = {account_info_dict[prop]}")

    logging.info("Connected to MT5 Account")
    return True


def get_data(symbol, timeframe, n):
    print(f"Fetching data for {symbol}")
    logging.info(f"Fetching data for {symbol}")
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    data = pd.DataFrame(rates)
    data['time'] = pd.to_datetime(data['time'], unit='s')
    data.set_index('time', inplace=True)
    return data


def calculate_pips(pips):
    return pips * 0.01


def find_key_levels(data):
    """
    Finds key levels using recent highs and lows.
    """
    recent_high = data['high'].max()
    recent_low = data['low'].min()
    key_level = (recent_high + recent_low) / 2  # Example: mid-point between high and low
    return recent_high, recent_low, key_level


def turtle_soup_signal(data, key_level, direction='buy'):
    signals = []
    print(f"Generating {direction} signals based on key level {key_level}")
    logging.info(f"Generating {direction} signals based on key level {key_level}")

    for i in range(1, len(data)):
        if direction == 'buy' and data['low'].iloc[i] < key_level and data['close'].iloc[i] > key_level:
            signals.append({'time': data.index[i], 'type': 'buy', 'price': data['close'].iloc[i]})
        if direction == 'sell' and data['high'].iloc[i] > key_level and data['close'].iloc[i] < key_level:
            signals.append({'time': data.index[i], 'type': 'sell', 'price': data['close'].iloc[i]})

    print(f"Generated {len(signals)} signals")
    logging.info(f"Generated {len(signals)} signals")
    return signals


def place_order(symbol, order_type, lot, stop_loss_pips, take_profit_pips):
    order_type_dict = {
        'buy': mt5.ORDER_TYPE_BUY,
        'sell': mt5.ORDER_TYPE_SELL
    }

    deviation = 20
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"Failed to get symbol info for {symbol}")
        logging.error(f"Failed to get symbol info for {symbol}")
        return None

    current_price = mt5.symbol_info_tick(symbol).ask if order_type == 'buy' else mt5.symbol_info_tick(symbol).bid
    point = symbol_info.point
    min_stop_distance = symbol_info.trade_stops_level * point

    if min_stop_distance == 0.0:
        min_stop_distance = FIXED_MIN_STOP_DISTANCE

    print(f"Minimum stop distance for {symbol}: {min_stop_distance}")
    logging.info(f"Minimum stop distance for {symbol}: {min_stop_distance}")

    # Add a substantial buffer to the minimum stop distance to ensure it's not too close
    buffer = 5 * min_stop_distance

    # Ensure stops are adjusted to meet the minimum distance requirements plus the buffer
    stop_loss_distance = max(stop_loss_pips * point, min_stop_distance + buffer)
    take_profit_distance = max(take_profit_pips * point, min_stop_distance + buffer)

    if order_type == 'buy':
        stop_loss = current_price - stop_loss_distance
        take_profit = current_price + take_profit_distance
    else:
        stop_loss = current_price + stop_loss_distance
        take_profit = current_price - take_profit_distance

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type_dict[order_type],
        "price": current_price,
        "sl": stop_loss,
        "tp": take_profit,
        "deviation": deviation,
        "magic": 234000,
        "comment": "Turtle Soup Strategy",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    print(
        f"Placing {order_type} order for {symbol} at price {request['price']} with SL: {stop_loss} and TP: {take_profit}")
    logging.info(
        f"Placing {order_type} order for {symbol} at price {request['price']} with SL: {stop_loss} and TP: {take_profit}")
    result = mt5.order_send(request)

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order failed: {result.comment}")
        logging.error(f"Order failed: {result.comment}")
    else:
        print(f"Order placed successfully: {result}")
        logging.info(f"Order placed successfully: {result}")

    return result


def main():
    if not connect_to_mt5():
        return

    SYMBOL = "GOLD"
    TIMEFRAME = mt5.TIMEFRAME_M5  # 5 minute timeframe

    print("Starting trading bot")
    logging.info("Starting trading bot")

    while True:
        data = get_data(SYMBOL, TIMEFRAME, 100)
        recent_high, recent_low, key_level = find_key_levels(data)

        print(f"Recent High: {recent_high}, Recent Low: {recent_low}, Key Level: {key_level}")
        logging.info(f"Recent High: {recent_high}, Recent Low: {recent_low}, Key Level: {key_level}")

        # Check for buy and sell signals
        buy_signals = turtle_soup_signal(data, key_level, 'buy')
        sell_signals = turtle_soup_signal(data, key_level, 'sell')

        for signal in buy_signals:
            price = signal['price']
            stop_loss_pips = STOP_LOSS_PIPS
            take_profit_pips = TAKE_PROFIT_PIPS
            result = place_order(SYMBOL, 'buy', LOT_SIZE, stop_loss_pips, take_profit_pips)
            print(f"Buy Order: {result}")
            logging.info(f"Buy Order: {result}")

        for signal in sell_signals:
            price = signal['price']
            stop_loss_pips = STOP_LOSS_PIPS
            take_profit_pips = TAKE_PROFIT_PIPS
            result = place_order(SYMBOL, 'sell', LOT_SIZE, stop_loss_pips, take_profit_pips)
            print(f"Sell Order: {result}")
            logging.info(f"Sell Order: {result}")

        print(f"{datetime.now()} - Waiting for {CHECK_INTERVAL} seconds before next check")
        logging.info(f"{datetime.now()} - Waiting for {CHECK_INTERVAL} seconds before next check")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
