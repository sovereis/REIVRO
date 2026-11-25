from vercel.queue import Message, Topic, subscribe

from server.scop_firewall_vercel import TOPIC, process_message

deliveries = Topic[dict[str, object]](TOPIC)


@subscribe(topic=deliveries, consumer_group="firewall-dry-run", retry_after=30)
async def consume(message: Message[dict[str, object]]) -> None:
    await process_message(message.payload)
