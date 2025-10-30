"""Command-line entry point for Rat-Trap."""

from __future__ import annotations

try:
    from .gmw_tool import main as _main
except ImportError:
    from gmw_tool import main as _main


def main(argv: list[str] | None = None) -> None:
    """Invoke the Rat-Trap CLI."""

    _main(argv)


if __name__ == "__main__":  # pragma: no cover
    main()
