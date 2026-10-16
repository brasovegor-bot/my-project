"""Conservative mapping of the documented GMGN activity schema.

Unknown quote denomination or historical cap stays unavailable. A stable
record identity is required: transaction hash alone cannot distinguish swaps.
"""
from datetime import datetime, timezone
from .core import Trade, address_key


class SourceSchemaError(ValueError):
    pass


def normalize(row, chain, wallet):
    side = row.get('event_type')
    if side is None:
        side = row.get('type')
    if side not in ('buy', 'sell'):
        return None
    try:
        if row.get('maker') is not None and address_key(chain, row['maker']) != address_key(chain, wallet):
            raise ValueError('Source wallet mismatch')
        if row.get('chain') is not None and row['chain'] != ('sol' if chain == 'solana' else chain):
            raise ValueError('Source chain mismatch')
        token = row['token']
        # Documentation does not guarantee activity ID availability. Fail visibly
        # until a successful live response provides an unambiguous swap identity.
        identity = row.get('id')
        if not isinstance(identity, (str, int)) or isinstance(identity, bool) or not str(identity):
            raise ValueError('Missing stable GMGN activity identity')
        stamp = row['timestamp']
        if isinstance(stamp, bool):
            raise ValueError('Invalid timestamp')
        when = datetime.fromtimestamp(float(stamp), timezone.utc).isoformat()
        # quote_amount alone is not enough: its historical denomination has not
        # yet been verified in a successful live response. No chain-native guess.
        return Trade.from_record(dict(
            event_id=str(identity), chain=chain, wallet=wallet, side=side,
            token_address=token['address'], token_symbol=token['symbol'],
            token_amount=row['token_amount'], quote_symbol=None, quote_amount=None,
            usd_amount=row.get('cost_usd'), timestamp=when, tx_hash=row['tx_hash'],
        ))
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise SourceSchemaError('GMGN activity schema or units require verification; cursor not advanced') from None
