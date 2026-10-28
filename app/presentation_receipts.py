"""Best-effort POS access receipts from the terminal owner's Acorn to the holder."""
import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.emergency_contacts import claim
from app.messages import available
from app.pos_api import invoke

logger = logging.getLogger(__name__)


def schedule_receipt(request, ident, actor, source, label):
    if not available(request.app.state.wallets):
        return
    task = asyncio.create_task(send_receipt(request, ident, actor, source, label))
    tasks = request.app.state.pos_tasks
    tasks.add(task)
    def done(task):
        tasks.discard(task)
        if not task.cancelled():
            task.exception()
    task.add_done_callback(done)


async def send_receipt(request, ident, actor, source, label):
    service = request.app.state.wallets
    lease = None
    try:
        # Namespace separate from emergency contact notices. Durable before publishing;
        # an uncertain send is never retried with a fresh giftwrap/event.
        if not await invoke(claim, service.store, 'holder-receipt:' + ident):
            return
        from app.pos_records import terminal
        name = actor.get('_remote_name') or await invoke(terminal, request, actor)
        recipient = await invoke(service.store.get, source['owner'])
        if (not recipient or recipient['status'] != 'active'
                or recipient['material']['npub'] != source['npub']):
            return
        lease = await invoke(service.store.acquire, actor['owner'])
        merchant = await invoke(service.store.get, actor['owner'])
        if not merchant or merchant['status'] != 'active':
            return
        # Direct local wallet binding: never resolve a social npub or a claimed address.
        public = await invoke(service.backend.public_identity, recipient['material'])
        relay = recipient['material']['relay']
        service.relay(relay)
        service.relay(merchant['material']['relay'])
        handle = await invoke(service.store.preference, actor['owner'])
        sender = f'{handle}@{urlsplit(request.app.state.settings.origin).hostname}' if handle else None
        when = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        message = (f'Record presented: {label}\nTerminal: {name}\nTime: {when}\n'
                   'Your record was accessed for presentation. No record contents are included in this receipt.\n'
                   f'Reference: {ident[:12]}')
        async with asyncio.timeout(15):
            await service.backend.send_wallet_message(merchant['material'],
                {'pubkey': public['hex'], 'relays': [relay]}, message, sender)
    except Exception as exc:
        logger.warning('Presentation receipt unconfirmed error_type=%s', type(exc).__name__)
    finally:
        if lease:
            try:
                await invoke(service.store.release, actor['owner'], lease)
            except Exception:
                logger.warning('Presentation receipt lease release unconfirmed')
