"""Poll selected wallets through read-only GMGN activity and deliver Telegram alerts.

Stops on access denial, unknown schema, incomplete pagination or a second runner.
This development process does not establish an always-on deployment.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import subprocess
import time

from .activity import SourceSchemaError, normalize
from .core import EVM_CHAINS, Outbox, Telegram, DeliveryError, load_priorities


class SourceError(Exception):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail.get('kind', 'source_error'))


class GMGN:
    def __init__(self, interval=3):
        self.interval, self.last_request = interval, 0

    def fetch(self, chain, wallet, cursor):
        time.sleep(max(0, self.interval-(time.monotonic()-self.last_request)))
        self.last_request = time.monotonic()
        try:
            result = subprocess.run(['node', str(Path(__file__).with_name('gmgn_bridge.mjs'))],
                input=json.dumps(dict(chain='sol' if chain=='solana' else chain, wallet=wallet, cursor=cursor)),
                capture_output=True, text=True, timeout=40)
            payload = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise SourceError(dict(kind='transport_process_failed')) from None
        if not payload.get('ok'):
            raise SourceError({key:payload[key] for key in ('kind','http_status','cf_ray','retry_at','api_error') if key in payload})
        if result.returncode != 0 or not isinstance(payload.get('data'), dict):
            raise SourceError(dict(kind='invalid_source_response'))
        return payload['data']


def feeds(wallets, chains):
    result = set()
    for wallet in wallets.values():
        if wallet.priority:
            for chain in chains if wallet.chain=='evm' else [wallet.chain]:
                result.add((chain, wallet.address))
    return sorted(result)


def poll_feed(source, box, wallets, chain, wallet, since, max_pages=100):
    name = f'gmgn-activity:{chain}:{wallet}'
    state = box.cursor(name)
    cutoff = float(state) if state is not None else since
    cursor, seen, pending, newest = None, set(), {}, cutoff
    for _ in range(max_pages):
        page = source.fetch(chain, wallet, cursor)
        rows = page.get('activities')
        if not isinstance(rows, list):
            raise SourceSchemaError('Expected GMGN activities array')
        for row in rows:
            try:
                if not isinstance(row,dict) or isinstance(row.get('timestamp'),bool):raise ValueError()
                stamp = float(row['timestamp'])
                if not 0 <= stamp <= time.time()+300:raise ValueError()
            except (KeyError,ValueError,TypeError):
                raise SourceSchemaError('Invalid GMGN timestamp') from None
            if stamp < cutoff:
                continue
            trade = normalize(row, chain, wallet)
            if trade is not None:
                previous = pending.get(trade.key)
                if previous is not None and previous != trade:
                    raise SourceSchemaError('Conflicting GMGN activity identity')
                pending[trade.key] = trade
            newest = max(newest, stamp)
        next_cursor = page.get('next')
        if not next_cursor:
            break
        if not rows:
            raise SourceSchemaError('Empty GMGN page has a continuation; completeness is unverified')
        if not isinstance(next_cursor, str) or next_cursor in seen:
            raise SourceSchemaError('Invalid or repeated GMGN pagination cursor')
        seen.add(next_cursor)
        cursor = next_cursor
    else:
        raise SourceSchemaError('GMGN catch-up exceeds page bound; watermark not advanced')
    for trade in pending.values():
        box.enqueue(trade, wallets)
    # All rows were validated first; failed catch-up never moves past unseen data.
    box.save_cursor(name, str(max(cutoff,newest-5)))
    return len(pending)


def write_status(directory, state, **extra):
    record=dict(state=state,checked_at=datetime.now(timezone.utc).isoformat(),**extra)
    path=directory/'monitor_status.json'
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path('data/gmgn'))
    parser.add_argument('--chains',nargs='+',choices=sorted(EVM_CHAINS),default=sorted(EVM_CHAINS))
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--request-interval',type=float,default=3)
    parser.add_argument('--poll-interval',type=float,default=15)
    args=parser.parse_args()
    if args.request_interval<1 or args.poll_interval<1:parser.error('Intervals must be at least one second')
    directory=args.directory
    directory.mkdir(parents=True,exist_ok=True)
    lock=(directory/'monitor.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:parser.exit(1,'A monitor already holds the process lock.\n')
    box=None
    try:
        wallets=load_priorities(directory/'priorities.json')
        client=Telegram.from_saved_recipient(directory/'telegram_recipient.json')
        box=Outbox(directory/'alerts.sqlite')
        state=box.cursor('monitor_started_at')
        since=float(state) if state else time.time()
        if state is None:box.save_cursor('monitor_started_at',str(since))
        source=GMGN(args.request_interval)
        targets=feeds(wallets,args.chains)
        if not targets:raise ValueError('No selected feeds')
        print(f'{len(wallets)} selected wallets; {len(targets)} feeds; full sweep needs at least {len(targets)*args.request_interval:.0f}s plus network time.',flush=True)
        while True:
            write_status(directory,'checking_source',feed_count=len(targets))
            while box.deliver_one(client):pass
            for chain,wallet in targets:
                poll_feed(source,box,wallets,chain,wallet,since)
                while box.deliver_one(client):pass
            write_status(directory,'polling',feed_count=len(targets),outbox=box.counts())
            print('Completed source sweep; accepted rows delivered or durably queued.',flush=True)
            if args.once:break
            time.sleep(args.poll_interval)
    except SourceError as exc:
        write_status(directory,'blocked_source',**exc.detail)
        parser.exit(2,'GMGN request failed: '+json.dumps(exc.detail)+'; monitor stopped, no retry loop.\n')
    except SourceSchemaError:
        write_status(directory,'source_schema_unverified')
        parser.exit(3,'GMGN returned an unverified schema; monitor stopped before advancing the affected feed.\n')
    except DeliveryError as exc:
        write_status(directory,'telegram_error',error_code=str(exc.code))
        parser.exit(4,'Telegram operation failed; queued alerts retained.\n')
    except (OSError,ValueError,KeyError):
        write_status(directory,'configuration_error')
        parser.exit(5,'Monitor configuration failed; no secrets logged.\n')
    except KeyboardInterrupt:
        write_status(directory,'stopped')
    finally:
        if box is not None:box.close()
        lock.close()


if __name__=='__main__':main()
