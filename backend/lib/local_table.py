"""In-memory stand-in for the DynamoDB tables the security modules use.

In SOLACE_MODE=aws, quota, blocklist, intake_nonce, idempotency and audit each
talk to a real DynamoDB table. Running locally there is no AWS account, so those
modules call `local_table.get(name, key=(...))` instead and get this tiny
dict-backed table, keyed on the same attribute(s) as the real one.

It implements only what those modules actually send:
  get_item(Key=...), put_item(Item=...), and update_item with
  `ADD #counter :n`, `SET #a = :v`, `SET #a = if_not_exists(#a, :v)`,
  an optional `ConditionExpression` of the form `attr = :v`,
  and ReturnValues="UPDATED_NEW".
Anything else raises, so a new kind of query fails loudly instead of silently.
Data lives in process memory and disappears when the server restarts.
"""
from __future__ import annotations

import re
import threading
from typing import Any

_TABLES: dict[str, "LocalTable"] = {}
_LOCK = threading.Lock()


class ConditionFailed(Exception):
    """Mirrors DynamoDB's ConditionalCheckFailedException."""


def _split_top_level(s: str) -> list[str]:
    """Split on commas that are not inside parentheses."""
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


class LocalTable:
    def __init__(self, name: str, key_fields: tuple[str, ...]) -> None:
        self.name = name
        self.key_fields = key_fields
        self._items: dict[tuple, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _key(self, item: dict[str, Any]) -> tuple:
        return tuple(item[f] for f in self.key_fields)

    def get_item(self, Key: dict[str, Any], **_: Any) -> dict[str, Any]:  # noqa: N803 (boto3 casing)
        with self._lock:
            item = self._items.get(self._key(Key))
            return {"Item": dict(item)} if item is not None else {}

    def put_item(self, Item: dict[str, Any], **_: Any) -> dict[str, Any]:  # noqa: N803
        raise_if_unsupported(_)
        with self._lock:
            self._items[self._key(Item)] = dict(Item)
        return {}

    def update_item(
        self,
        Key: dict[str, Any],  # noqa: N803
        UpdateExpression: str,  # noqa: N803
        ExpressionAttributeValues: dict[str, Any],  # noqa: N803
        ExpressionAttributeNames: dict[str, str] | None = None,  # noqa: N803
        ConditionExpression: str | None = None,  # noqa: N803
        ReturnValues: str | None = None,  # noqa: N803
    ) -> dict[str, Any]:
        names = ExpressionAttributeNames or {}
        vals = ExpressionAttributeValues
        name = lambda token: names.get(token, token)  # noqa: E731

        with self._lock:
            k = self._key(Key)
            item = dict(self._items.get(k) or Key)

            if ConditionExpression:
                m = re.fullmatch(r"\s*(#?\w+)\s*=\s*(:\w+)\s*", ConditionExpression)
                if not m:
                    raise NotImplementedError(f"condition not supported: {ConditionExpression}")
                if item.get(name(m.group(1))) != vals[m.group(2)]:
                    raise ConditionFailed(ConditionExpression)

            updated: dict[str, Any] = {}
            for clause, body in re.findall(r"(ADD|SET)\s+(.+?)(?=\s+(?:ADD|SET)\s+|$)", UpdateExpression.strip()):
                for part in _split_top_level(body):
                    if clause == "ADD":
                        attr, val = part.split()
                        attr = name(attr)
                        item[attr] = item.get(attr, 0) + vals[val]
                        updated[attr] = item[attr]
                        continue
                    lhs, rhs = (x.strip() for x in part.split("=", 1))
                    attr = name(lhs)
                    m = re.fullmatch(r"if_not_exists\(\s*(#?\w+)\s*,\s*(:\w+)\s*\)", rhs)
                    if m:
                        if name(m.group(1)) not in item:
                            item[attr] = vals[m.group(2)]
                    elif rhs in vals:
                        item[attr] = vals[rhs]
                    else:
                        raise NotImplementedError(f"update not supported: {part}")
                    updated[attr] = item[attr]

            self._items[k] = item
        return {"Attributes": updated} if ReturnValues == "UPDATED_NEW" else {}


def raise_if_unsupported(kwargs: dict[str, Any]) -> None:
    if "ConditionExpression" in kwargs:
        raise NotImplementedError("conditional put_item is not supported locally")


def get(name: str, key: tuple[str, ...]) -> LocalTable:
    with _LOCK:
        if name not in _TABLES:
            _TABLES[name] = LocalTable(name, key)
        return _TABLES[name]
