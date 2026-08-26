# MiniOS shared GUI resources
#
# Installs the canonical stylesheet to /usr/share/minios/minios.css.
# Used by debhelper (dh) during package builds and usable standalone:
#   make install DESTDIR=/path/to/root

SHAREDIR = usr/share/minios
STYLE    = share/minios.css
PYTHONDIR = usr/lib/python3/dist-packages/minios_gui
PYTHONFILES = minios_gui/__init__.py minios_gui/style.py \
	minios_gui/dialogs.py minios_gui/command.py minios_gui/widgets.py \
	minios_gui/module_display.py minios_gui/completion.py minios_gui/document.py

.PHONY: build test install uninstall clean

build:

test:
	PYTHONPATH=. xvfb-run -a python3 -m pytest -q

install: build
	install -d $(DESTDIR)/$(SHAREDIR)
	install -m 644 $(STYLE) $(DESTDIR)/$(SHAREDIR)/minios.css
	install -d $(DESTDIR)/$(PYTHONDIR)
	install -m 644 $(PYTHONFILES) $(DESTDIR)/$(PYTHONDIR)/

uninstall:
	rm -f $(DESTDIR)/$(SHAREDIR)/minios.css
	rm -rf $(DESTDIR)/$(PYTHONDIR)

clean:
