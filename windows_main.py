"""PyInstaller entry point for the Rat-Trap Windows application."""

from multiprocessing import freeze_support

from rat_trap.windows_app import main


if __name__ == "__main__":
    freeze_support()
    main()
