import os

def get_headers():
    return {
        "Content-Type": "application/json",
        "accept": "*/*",
        "Cookie": os.getenv("COOKIE"),
        "x-crypto-token": os.getenv("XCRYPTO"),
        "User-Agent": "Python/requests",
    }
