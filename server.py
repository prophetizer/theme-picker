#!/usr/bin/env python3
"""
Web UI wrapping set-theme.sh -- click a theme instead of running the script
by hand. No framework: stdlib plus PyYAML. See CLAUDE.md.

This file is only the entry point the container runs (`python3 server.py`,
working directory = this checkout); the application is the picker/ package.
"""

from picker.handler import main

if __name__ == "__main__":
    main()
