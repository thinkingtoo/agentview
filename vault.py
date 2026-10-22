"""The person's login keyring, through the freedesktop Secret Service.

Where a secret Paste's text lives (`paste.py`): the store keeps a record and
the keyring keeps the text. Talked to over D-Bus with `dbus-python`, which is
installed here; the text travels in the message and never in a command line,
where any process of the user could read it from `ps`. Nothing here writes a
file.

An item is found by its attributes, `application=agentview`, `store=<which Paste
store>` and `paste=<id>`: a second store (another state directory, a test) never
sees, and so never sweeps away, the items of the first. The record needs no
reference beyond the Paste's own id and its place. The keyring being
locked, absent or slow is `Unavailable`; a locked one is not asked to unlock
(that is a prompt on a screen, and a session cannot answer it), so the person
unlocks it by logging in. What `Unavailable` says never includes what the
backend said, which could echo the text it was given.
"""
import os

BUS = "org.freedesktop.secrets"
ROOT = "/org/freedesktop/secrets"
SERVICE, COLLECTION, ITEM = (f"org.freedesktop.Secret.{n}" for n in ("Service", "Collection", "Item"))
APPLICATION = "agentview"
TIMEOUT = 10        # seconds for one call, so a keyring that never answers cannot hold a command


LOCKED = "the keyring is locked; log in again, or unlock it, and retry"
PROMPT = "the keyring wants to be unlocked first"


class Unavailable(Exception):
    """The keyring cannot be used right now. The text says why, in words that never carry a secret."""


class Unsure(Unavailable):
    """The request to keep a text went out and no answer came back: the keyring may hold the item."""


def _address():
    return os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path=/run/user/{os.getuid()}/bus"


def _connect():
    try:
        import dbus
        import dbus.bus
    except ImportError:
        raise Unavailable("the keyring cannot be reached: python3-dbus is not installed") from None
    # A connection of its own: nothing shared between the server's threads.
    return dbus, dbus.bus.BusConnection(_address())


class _Session:
    """One conversation with the Secret Service, closed when it ends."""

    def __enter__(self):
        try:
            self.dbus, self.bus = _connect()
            service = self.bus.get_object(BUS, ROOT, introspect=False)
            self.service = self.dbus.Interface(service, SERVICE)
            _, self.session = self.service.OpenSession("plain", self.dbus.String("", variant_level=1),
                                                       timeout=TIMEOUT)
        except Unavailable:
            raise
        except Exception as err:
            self._close_bus()           # `__exit__` does not run when `__enter__` raises
            raise _unavailable(err) from None
        return self

    def _close_bus(self):
        try:
            self.bus.close()
        except Exception:               # no bus yet, or already gone
            pass

    def __exit__(self, kind, err, tb):
        try:
            self.dbus.Interface(self.bus.get_object(BUS, self.session, introspect=False),
                                "org.freedesktop.Secret.Session").Close(timeout=TIMEOUT)
        except Exception:
            pass
        self._close_bus()
        if isinstance(err, Exception) and not isinstance(err, Unavailable):
            raise _unavailable(err) from None

    def interface(self, path, name):
        return self.dbus.Interface(self.bus.get_object(BUS, path, introspect=False), name)

    def collection(self):
        path = self.service.ReadAlias("default", timeout=TIMEOUT)
        if str(path) == "/":
            raise Unavailable("the keyring has no default collection")
        props = self.interface(path, "org.freedesktop.DBus.Properties")
        if props.Get(COLLECTION, "Locked", timeout=TIMEOUT):
            raise Unavailable(LOCKED)
        return path

    def refuse_prompt(self, prompt):
        """A prompt is a dialog on a screen that a session cannot answer. Dismissed, so that it
        cannot appear later and finish what the command has just reported as refused."""
        if str(prompt) == "/":
            return
        try:
            self.interface(prompt, "org.freedesktop.Secret.Prompt").Dismiss(timeout=TIMEOUT)
        except Exception:
            pass
        raise Unavailable(PROMPT)

    def find(self, pid, store):
        unlocked, locked = self.service.SearchItems({"application": APPLICATION, "store": store, "paste": pid},
                                                    timeout=TIMEOUT)
        if locked:
            raise Unavailable(LOCKED)
        return [str(p) for p in unlocked]


def _unavailable(err):
    name = err.get_dbus_name() if hasattr(err, "get_dbus_name") else type(err).__name__
    return Unavailable(f"the keyring cannot be reached ({name})")


def put(pid, text, store):
    """Keep `text` in the keyring as Paste `pid`."""
    with _Session() as s:
        collection = s.collection()
        props = s.dbus.Dictionary(
            {f"{ITEM}.Label": f"agentview paste {pid}",
             f"{ITEM}.Attributes": s.dbus.Dictionary({"application": APPLICATION, "store": store, "paste": pid}, signature="ss")},
            signature="sv")
        secret = s.dbus.Struct((s.session, s.dbus.ByteArray(b""), s.dbus.ByteArray(text.encode("utf-8")),
                                "text/plain; charset=utf-8"), signature="oayays")
        try:
            _, prompt = s.interface(collection, COLLECTION).CreateItem(props, secret, True, timeout=TIMEOUT)
        except Exception as err:
            raise Unsure(_unavailable(err).args[0]) from None
        s.refuse_prompt(prompt)


def get(pid, store):
    """The text of Paste `pid`, or None when the keyring has no such item."""
    with _Session() as s:
        found = s.find(pid, store)
        if not found:
            return None
        _, _, value, _ = s.interface(found[0], ITEM).GetSecret(s.session, timeout=TIMEOUT)
        return bytes(value).decode("utf-8")


def delete(pid, store):
    """Remove Paste `pid`'s item. False when there was none, which is as good as removed."""
    with _Session() as s:
        found = s.find(pid, store)
        for path in found:
            s.refuse_prompt(s.interface(path, ITEM).Delete(timeout=TIMEOUT))
        return bool(found)


def ids(store):
    """The ids of every Paste the keyring holds, for finding what no record points at."""
    with _Session() as s:
        s.collection()
        unlocked, locked = s.service.SearchItems({"application": APPLICATION, "store": store}, timeout=TIMEOUT)
        if locked:
            raise Unavailable(LOCKED)
        found = set()
        for path in unlocked:
            attrs = s.interface(path, "org.freedesktop.DBus.Properties").Get(ITEM, "Attributes", timeout=TIMEOUT)
            if attrs.get("paste"):
                found.add(str(attrs["paste"]))
        return sorted(found)
