import sys
try:
    from .app import main
except (ImportError, ValueError) as exc:
    print(f'TouchSwitch needs GTK 3 and PyGObject: {exc}\nInstall: sudo apt install python3-gi gir1.2-gtk-3.0 xinput udev', file=sys.stderr)
    sys.exit(1)
sys.exit(main())
