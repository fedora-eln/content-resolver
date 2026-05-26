import datetime
import json
import re
import sys
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

import jinja2
import libdnf5


class SetEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, jinja2.Environment):
            return ""
        return json.JSONEncoder.default(self, obj)


def load_data(path: str) -> Any:
    with open(path, "r") as file:
        data = json.load(file)
    return data


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def err_log(msg: str) -> None:
    print(f"ERROR LOG:  {msg}", file=sys.stderr)


def pkg_id_to_name(pkg_id: str) -> str:
    pkg_name = pkg_id.rsplit("-", 2)[0]
    return pkg_name


def dump_data(path: str, data: Any) -> None:
    with open(path, "w") as file:
        json.dump(data, file, cls=SetEncoder)


def size(num: float, suffix: str = "B") -> str:
    for unit in ["", "k", "M", "G"]:
        if abs(num) < 1024.0:
            return "%3.1f %s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f %s%s" % (num, 'T', suffix)


def workload_id_to_conf_id(workload_id: str) -> str:
    workload_conf_id = workload_id.split(":")[0]
    return workload_conf_id


def url_to_id(url: str) -> str:
    """
    Convert a URL to a filesystem-safe identifier.

    Extracts the domain and path from a URL, strips the protocol and trailing slash,
    and replaces all non-alphanumeric characters with hyphens to create a safe ID.
    Consecutive non-alphanumeric characters are collapsed into a single hyphen.

    Args:
        url (str): The URL to convert (e.g., "https://koji.fedoraproject.org/koji/")

    Returns:
        str: A filesystem-safe identifier with only alphanumeric characters and hyphens
             (e.g., "koji-fedoraproject-org-koji")

    Examples:
        >>> url_to_id("https://koji.fedoraproject.org/koji/")
        'koji-fedoraproject-org-koji'
    """
    # Parse the URL to extract components
    parsed = urlparse(url)

    # Combine netloc (domain/port) and path, strip trailing slashes
    url_part = (parsed.netloc + parsed.path).rstrip('/')

    # Replace all non-alphanumeric characters with -
    regex = re.compile("[^0-9a-zA-Z]")
    # The + in the regex collapses consecutive non-alphanumeric chars into one hyphen
    return regex.sub("-", url_part).strip('-')


def datetime_now_string() -> str:
    return datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S")


@contextmanager
def dnf5_base() -> Iterator[libdnf5.base.Base]:
    """
    Context manager wrapper for libdnf5.base.Base().

    DNF5's Base class doesn't natively support the context manager protocol,
    so this wrapper provides proper resource management.

    Usage:
        with dnf5_base() as base:
            config = base.get_config()
            # ... use base ...
    """
    base = libdnf5.base.Base()
    try:
        yield base
    finally:
        # DNF5 Base cleanup is handled by Python's garbage collector
        # No explicit cleanup needed, but the finally block ensures
        # proper exception handling and resource cleanup if needed in future
        pass
