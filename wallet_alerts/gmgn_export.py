"""Import the observed GMGN Wallet Tracker export for priority selection.

This export has addresses and names, but no chain. ``evm`` is an address
family, never a claim that these wallets belong to Ethereum. This inventory
is for selection only; the event adapter must resolve actual GMGN chains.
"""
import argparse
import json
from pathlib import Path

from .core import Wallet, address_key
from .selector import render


def parse_export(records):
    if not isinstance(records, list):
        raise ValueError('GMGN export must be a JSON array')
    wallets = {}
    for index, row in enumerate(records, 1):
        if not isinstance(row, dict):
            raise ValueError(f'Entry {index}: expected an object')
        # Validation of EVM address syntax only; this does not assign a chain.
        address = address_key('eth', row.get('address'))
        name = row.get('name')
        if not isinstance(name, str) or len(name) > 1000:
            raise ValueError(f'Entry {index}: invalid name')
        if row.get('chain') or row.get('network'):
            raise ValueError(f'Entry {index}: unexpected network metadata; review before import')
        key = ('evm', address)
        if key in wallets:
            raise ValueError(f'Entry {index}: duplicate address; review before import')
        # GMGN toast/feed/sound flags are not Telegram priority selections.
        wallets[key] = Wallet('evm', address, name.strip() or address, False)
    return wallets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('--output', type=Path, default=Path('data/gmgn/wallet_selector.html'))
    args = parser.parse_args()
    wallets = parse_export(json.loads(args.export.read_text(encoding='utf-8-sig')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(
        wallets, 'Твой экспорт Wallet Tracker GMGN', complete=True,
        note='Все адреса и имена взяты из присланного экспорта. Сети в нём не указаны. '
             'Поставь галочки только у тех, чьи сделки хочешь получать. '
             'Уведомления начнут работать после подключения GMGN и Telegram.'
    ), encoding='utf-8')
    print(f'Created selector with {len(wallets)} unique wallets: {args.output}')


if __name__ == '__main__':
    main()
