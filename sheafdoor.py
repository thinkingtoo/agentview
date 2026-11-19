"""The sheaf hub's door for the phone: a goal page opened from agentview over tailscale.

The hub listens on the laptop's 127.0.0.1 only and answers only to a Host of 127.0.0.1 or
localhost, and a POST only from an Origin of `http://` + that Host (its DNS-rebinding and
cross-port guards). `tailscale serve` in front of it sends the tailnet name, so the hub
refuses it. This door sits between the two: `tailscale serve --bg --https=8446
http://127.0.0.1:8792` reaches it, and it passes each request to the hub with Host and
Origin said as the hub's own, and nothing else changed.

It lets through only what names the door's own origin ($AGENTVIEW_SHEAF_DOOR, such as
`https://laptop.tailnet.ts.net:8446`): a request whose Host is another name, or that
carries an Origin other than the door's, is refused before the hub sees it. So a page on
the laptop at 127.0.0.1 (which holds the hub's cookie for every port) cannot use the door
to pass the hub's Origin check. The hub still asks its own sign-in: the phone signs in once
through the door with `sheaf signin-url`'s link, its host swapped for the door's.

One request per connection (Connection: close): a document's event stream stays open as
long as the hub holds it, and nothing has to find where one request ends.
"""
import asyncio
import os
import sys
import urllib.parse

DOOR = "AGENTVIEW_SHEAF_DOOR"
LISTEN = int(os.environ.get("AGENTVIEW_SHEAF_DOOR_PORT", "8792"))
HUB = int(os.environ.get("SHEAF_PORT", "27419"))
HEAD_MAX = 64 * 1024
DROPPED = (b"host", b"origin", b"connection", b"keep-alive", b"proxy-connection")


def door_origin():
    """`(origin, host)` of $AGENTVIEW_SHEAF_DOOR: an https origin with a port and nothing
    else, the host as a Host header says it. None when unset or written otherwise."""
    raw = os.environ.get(DOOR, "").strip().rstrip("/")
    try:
        p = urllib.parse.urlsplit(raw)
        port = p.port
    except ValueError:
        return None
    if p.scheme != "https" or not p.hostname or not port or p.path or p.query or p.fragment or "@" in p.netloc:
        return None
    return raw.lower(), f"{p.hostname}:{port}".lower(), p.hostname.lower()


def rewrite(head, door, hub=HUB):
    """The request head `head` (bytes up to and with the blank line) as the hub must get it,
    or None when the door refuses it."""
    origin, host, bare = door
    lines = head.split(b"\r\n")
    request, fields, seen_host = lines[0], [], False
    for line in lines[1:]:
        if not line:
            continue
        name, sep, value = line.partition(b":")
        if not sep:
            return None
        key, value = name.strip().lower(), value.strip().decode("latin-1").lower()
        if key == b"host":
            if seen_host or value not in (host, bare):
                return None
            seen_host = True
        elif key == b"origin" and value != origin:
            return None
        if key == b"origin":
            fields.append(b"Origin: http://127.0.0.1:%d" % hub)
        elif key not in DROPPED:
            fields.append(line)
    if not seen_host:
        return None
    return b"\r\n".join([request, b"Host: 127.0.0.1:%d" % hub, *fields, b"Connection: close", b"", b""])


async def _pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except OSError:
            pass


async def _serve(reader, writer, door):
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        writer.close()
        return
    out = rewrite(head, door)
    if out is None:
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        return
    try:
        hub_r, hub_w = await asyncio.open_connection("127.0.0.1", HUB)
    except OSError:
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        return
    hub_w.write(out)
    await asyncio.gather(_pipe(reader, hub_w), _pipe(hub_r, writer))


async def main():
    door = door_origin()
    if door is None:
        sys.exit(f"sheafdoor: set ${DOOR} to the door's https origin with its port")
    server = await asyncio.start_server(lambda r, w: _serve(r, w, door), "127.0.0.1", LISTEN,
                                        limit=HEAD_MAX)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
