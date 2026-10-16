"""Apply the user's returned checklist, verifying it against their GMGN export."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .core import load_priorities
from .gmgn_export import parse_export


def apply_selection(selection, inventory, output):
    wallets = load_priorities(selection)
    if not wallets or any(not w.priority for w in wallets.values()):
        raise ValueError('Selection must contain selected priority wallets only')
    original = parse_export(json.loads(Path(inventory).read_text(encoding='utf-8-sig')))
    for key, wallet in wallets.items():
        if key not in original or wallet.label != original[key].label:
            raise ValueError('Selection does not match the provided GMGN inventory')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'priorities.json').write_text(
        json.dumps([asdict(w) for w in wallets.values()], ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    settings = {
        'provider': 'GMGN', 'feed': 'follow-wallet', 'delivery': 'Telegram',
        'gmgn_access': 'read_only',
        'preserve_all_gmgn_follows': True,
        'selection_applies_to': 'Telegram notifications only',
        'selected_wallet_count': len(wallets),
        'applied_at': datetime.now(timezone.utc).isoformat(),
        'selection_sha256': hashlib.sha256(Path(selection).read_bytes()).hexdigest(),
        'scope': 'Selected EVM addresses on supported GMGN chains; no ETH-only assumption',
        'sides': ['buy', 'sell'],
        'fields': ['wallet_label', 'chain', 'token_symbol', 'token_address',
                   'token_amount', 'quote_amount', 'quote_symbol', 'capitalization', 'timestamp'],
        'capitalization_policy': {
            'preferred': 'GMGN value at trade time',
            'missing': 'Show no data; never substitute zero or current cap',
            'fdv': 'Label separately from circulating market capitalization',
            'estimates': 'Require verified units, supply timestamp and explicit estimate label',
        },
        'monitoring_status': 'not_started',
    }
    (output / 'settings.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return wallets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('selection', type=Path)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('data/gmgn'))
    args = parser.parse_args()
    wallets = apply_selection(args.selection, args.inventory, args.output)
    print(f'Saved {len(wallets)} selected wallets; monitoring has not started.')


if __name__ == '__main__':
    main()
