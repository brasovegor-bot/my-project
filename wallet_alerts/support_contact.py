"""One permitted GMGN support case via our bot, with receipts and bounded reads.

The user authorized support correspondence. Group membership and messaging
permissions must be established separately; this helper cannot join a group.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re

from .core import Telegram, DeliveryError

TARGET = '@gmgnagentapi'


def write_case(path, case):
    case['updated_at'] = datetime.now(timezone.utc).isoformat()
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def support_access(client):
    me = client.call('getMe', {})
    chat = client.call('getChat', {'chat_id': TARGET})
    if chat.get('type') != 'supergroup' or str(chat.get('username', '')).lower() != TARGET[1:]:
        raise ValueError('Unexpected support target')
    member = client.call('getChatMember', {'chat_id': chat['id'], 'user_id': me['id']})
    status = member.get('status')
    allowed = status in ('administrator', 'creator') or (
        status == 'member' and chat.get('permissions', {}).get('can_send_messages', True)) or (
        status == 'restricted' and member.get('is_member') is True and member.get('can_send_messages') is True)
    return chat['id'], bool(allowed), status


def send_case(client, directory, case, chat_id, allowed):
    path = directory / 'support_resolution_case.json'
    if case.get('delivery', {}).get('sent') is True:
        return 'already_sent'
    attempt = directory / 'support_send_attempt.json'
    if attempt.exists():
        return 'previous_attempt_requires_review'
    if not allowed:
        case['status'] = 'awaiting_group_membership_or_permission'
        case['delivery'] = dict(sent=False, receipt=None, reason='Bot lacks group membership or sending permission')
        write_case(path, case)
        return 'not_permitted'
    body = (directory / 'GMGN_SUPPORT_REQUEST.txt').read_text(encoding='utf-8')
    if not 1 <= len(body) <= 3900 or re.search(r'-----BEGIN .*PRIVATE KEY-----|\b\d{6,}:[A-Za-z0-9_-]{25,}|\bgmg[a-zA-Z0-9]{20,}|\b0x[a-fA-F0-9]{40}\b', body):
        raise ValueError('Support text size or sensitive-content check failed')
    attempt.write_text(json.dumps(dict(state='prepared_before_send', target=TARGET,
        created_at=datetime.now(timezone.utc).isoformat())), encoding='utf-8')
    try:
        message = client.call('sendMessage', dict(chat_id=chat_id, text=body,
            link_preview_options=dict(is_disabled=True)))
    except DeliveryError as exc:
        case['status'] = 'delivery_unknown' if not isinstance(exc.code, int) else 'delivery_rejected'
        case['delivery'] = dict(sent=None if case['status']=='delivery_unknown' else False,
                                receipt=None, error_code=str(exc.code))
        write_case(path, case)
        raise
    if message.get('chat', {}).get('id') != chat_id or type(message.get('message_id')) is not int:
        case['status']='delivery_receipt_unverified'
        write_case(path,case)
        raise ValueError('Unexpected support delivery receipt')
    case['status']='awaiting_support_reply'
    case['delivery']=dict(sent=True,receipt=dict(chat_id=chat_id,message_id=message['message_id'],
        sent_at=datetime.now(timezone.utc).isoformat(),target=TARGET))
    write_case(path,case)
    attempt.write_text(json.dumps(dict(state='acknowledged_by_telegram',message_id=message['message_id'])),encoding='utf-8')
    return 'sent_and_acknowledged'


def read_replies(client, directory, case):
    delivery=case.get('delivery', {})
    if delivery.get('sent') is not True:
        return 0
    receipt=delivery['receipt']
    updates=client.call('getUpdates',dict(offset=case.get('last_update_id',-1)+1,
        timeout=0,limit=100,allowed_updates=['message']))
    replies=case.setdefault('support_replies',[])
    known={r['message_id'] for r in replies}
    conversation=known|{receipt['message_id']}
    added=0
    for update in updates:
        case['last_update_id']=max(case.get('last_update_id',-1),update['update_id'])
        message=update.get('message',{})
        if (message.get('chat',{}).get('id') != receipt['chat_id']
                or message.get('reply_to_message',{}).get('message_id') not in conversation
                or message.get('message_id') in known):
            continue
        reply=dict(message_id=message['message_id'],date=message.get('date'),
                   text=str(message.get('text',message.get('caption','')))[:6000])
        replies.append(reply);known.add(reply['message_id']);conversation.add(reply['message_id']);added+=1
    if added:case['status']='support_reply_received_needs_analysis'
    write_case(directory/'support_resolution_case.json',case)
    return added


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path('data/gmgn'))
    parser.add_argument('--send',action='store_true')
    parser.add_argument('--read-replies',action='store_true')
    args=parser.parse_args();directory=args.directory
    directory.mkdir(parents=True,exist_ok=True)
    lock=(directory/'support_contact.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:parser.exit(1,'Another support operation is running.\n')
    try:
        case=json.loads((directory/'support_resolution_case.json').read_text(encoding='utf-8'))
        client=Telegram.from_saved_recipient(directory/'telegram_recipient.json')
        chat_id,allowed,status=support_access(client)
        case['telegram_access']=dict(target=TARGET,membership=status,send_allowed=allowed)
        if not allowed and case.get('delivery',{}).get('sent') is not True:
            case['status']='awaiting_group_membership_or_permission'
            case['delivery']=dict(sent=False,receipt=None,reason='Telegram confirms bot is not an admitted sender')
        write_case(directory/'support_resolution_case.json',case)
        print(json.dumps(dict(target=TARGET,membership=status,send_allowed=allowed)))
        if args.send:print('Support send:',send_case(client,directory,case,chat_id,allowed))
        if args.read_replies:print('New direct support replies:',read_replies(client,directory,case))
    except DeliveryError as exc:parser.exit(1,f'Telegram support operation rejected: {exc.code}; no secrets logged.\n')
    except (OSError,ValueError,KeyError,TypeError):parser.exit(1,'Support case/configuration/receipt could not be verified.\n')
    finally:lock.close()


if __name__=='__main__':main()
