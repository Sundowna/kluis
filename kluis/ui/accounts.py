"""Account button and menu in the header (decisions D30): Proton's own account menu, in Kluis's look.

Button: initials + account name. Menu: the active account (big initials, name, email), Sign out, then
"Other accounts" with a ⋮ menu (Add another account, Sign out of all accounts) and one row per account;
a click on a row switches to it.
"""
from __future__ import annotations

from gi.repository import GLib, Gtk

from .. import accounts
from ..i18n import _
from .common import a11y, button, clear, hbox, label, popover_menu, styled, vbox


def avatar(email: str, big=False) -> Gtk.Widget:
    lb = label(accounts.initials(email), "k-avatar-text", xalign=0.5)
    box = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    box.pack_start(lb, True, True, 0)
    styled(box, "k-avatar", "k-avatar-big" if big else "")
    size = 64 if big else 32
    box.set_size_request(size, size)
    return box


class AccountButton(Gtk.MenuButton):
    def __init__(self, app):
        super().__init__()
        self.app = app
        styled(self, "k-flat", "k-account-btn")
        self.inner = Gtk.Box(spacing=8)
        self.add(self.inner)
        self.pop = Gtk.Popover.new(self)
        styled(self.pop, "k-menu", "k-account-menu")
        self.body = vbox(spacing=10, margin=12)
        self.body.set_size_request(280, -1)
        self.pop.add(self.body)
        self.set_popover(self.pop)
        self.pop.connect("show", lambda *_: self._fill())
        self.refresh()

    # the button
    def refresh(self):
        email = self.app.settings.account or self.app.manager.email
        clear(self.inner)
        if not email:
            self.hide()
            self.set_no_show_all(True)
            return
        self.set_no_show_all(False)
        self.inner.pack_start(avatar(email), False, False, 0)
        self.inner.pack_start(label(accounts.display_name(email), "k-bold", "k-s13", ellipsize="end", max_chars=14),
                              False, False, 0)
        self.set_tooltip_text(email)
        a11y(self, _("Account: {e}").format(e=email))
        self.show_all()
        if self.pop.get_visible():
            self._fill()

    # the menu
    def _fill(self):
        app = self.app
        email = app.settings.account or app.manager.email
        clear(self.body)
        self.body.pack_start(avatar(email, big=True), False, False, 4)
        self.body.pack_start(label(accounts.display_name(email), "k-h3", "k-bold", xalign=0.5, ellipsize="end",
                                   max_chars=28), False, False, 0)
        self.body.pack_start(label(email, "k-muted", "k-s13", xalign=0.5, ellipsize="middle", max_chars=32),
                             False, False, 0)
        if app.manager.switching:
            self.body.pack_start(label(_("Switching…"), "k-muted", "k-s12", xalign=0.5), False, False, 0)
        out = button(_("Sign out"), self._sign_out, "k-big", name=_("Sign out of {e}").format(e=email))
        self.body.pack_start(out, False, False, 4)

        sep = Gtk.Box()
        styled(sep, "k-divider")
        self.body.pack_start(sep, False, False, 2)
        head = Gtk.Box(spacing=8)
        head.pack_start(label(_("Other accounts"), "k-bold", "k-s13"), True, True, 0)
        more = Gtk.MenuButton()
        more.add(label("⋮", "k-bold", xalign=0.5))
        styled(more, "k-flat")
        more.set_tooltip_text(_("More account actions"))
        a11y(more, _("More account actions"))
        items = [(_("Add another Proton account"), self._add)]
        if accounts.others(app.settings):
            items.append((_("Sign out of all accounts"), self._sign_out_all, True))
        more.set_popover(popover_menu(more, items))
        head.pack_end(more, False, False, 0)
        self.body.pack_start(head, False, False, 0)

        others = accounts.others(app.settings)
        if not others:
            self.body.pack_start(label(_("Use Kluis with a second Proton account, for example a family member's."),
                                       "k-muted", "k-s12", wrap=True, max_chars=36), False, False, 0)
            add = button(_("+ Add another Proton account"), self._add, "k-link")
            add.set_halign(Gtk.Align.START)
            self.body.pack_start(add, False, False, 0)
        for r in others:
            self.body.pack_start(self._row(r), False, False, 0)
        self.body.show_all()

    def _row(self, r: dict) -> Gtk.Widget:
        email = r["email"]
        b = Gtk.Button()
        styled(b, "k-flat", "k-account-row")
        sub = _("Signed out · sign in to switch") if r.get("signed_out") else email
        text = vbox(label(accounts.display_name(email), "k-s13", "k-bold", ellipsize="end", max_chars=24),
                    label(sub, "k-muted", "k-s12", ellipsize="middle", max_chars=28), spacing=0)
        b.add(hbox(avatar(email), text, spacing=10))
        b.set_tooltip_text(_("Switch to {e}").format(e=email))
        a11y(b, _("Switch to {e}").format(e=email))
        b.set_sensitive(not self.app.manager.switching)
        b.connect("clicked", lambda *_: self._switch(email))
        rm = Gtk.Button(label="✕")
        styled(rm, "k-flat")
        rm.set_valign(Gtk.Align.CENTER)
        rm.set_tooltip_text(_("Remove {e} from Kluis").format(e=email))
        a11y(rm, _("Remove {e} from Kluis").format(e=email))
        rm.connect("clicked", lambda *_: self._forget(email))
        row = Gtk.Box(spacing=4)
        row.pack_start(b, True, True, 0)
        row.pack_end(rm, False, False, 0)
        return row

    # actions
    def _later(self, fn):
        self.pop.popdown()
        GLib.idle_add(lambda: (fn(), False)[1])

    def _switch(self, email):
        self._later(lambda: self.app.switch_account(email))

    def _add(self):
        self._later(self.app.add_account)

    def _sign_out(self):
        from .dialogs import confirm
        app = self.app
        email = app.settings.account
        nxt = next((r["email"] for r in accounts.others(app.settings) if not r.get("signed_out")), "")
        text = (_("Kluis switches to {n}. {e}'s folders stop syncing until you sign in again; the files stay on this "
                  "computer and in Proton Drive.").format(n=nxt, e=email) if nxt else
                _("Syncing stops until you sign in again. Your files stay on this computer and in Proton Drive."))
        self.pop.popdown()
        if confirm(self.get_toplevel(), _("Sign out of {e}?").format(e=email), text, _("Sign out"),
                   _("Stay signed in"), destructive=True):
            GLib.idle_add(lambda: (app.sign_out(), False)[1])

    def _sign_out_all(self):
        from .dialogs import confirm
        self.pop.popdown()
        if confirm(self.get_toplevel(), _("Sign out of all accounts?"),
                   _("Syncing stops until you sign in again. Your files stay on this computer and in Proton Drive."),
                   _("Sign out of all"), _("Stay signed in"), destructive=True):
            GLib.idle_add(lambda: (self.app.sign_out_all(), False)[1])

    def _forget(self, email):
        from .dialogs import confirm
        self.pop.popdown()
        if confirm(self.get_toplevel(), _("Remove {e} from Kluis?").format(e=email),
                   _("Kluis forgets this account and its folder list. The files stay on this computer and in "
                     "Proton Drive."), _("Remove"), _("Keep"), destructive=True):
            self.app.forget_account(email)
