Build Kluis 1.0 from start to finish. Work on your own and don't stop to ask me anything: I only want the finished, tested product.

**Setup**
1. If you're not already in a clone of github.com/Sundowna/kluis, clone it (into ~/kluis if nothing exists).
2. Find `kluis-redesign-handover.zip` (this folder, ~/Downloads or ~) and unzip it into `docs/redesign/`, so you have `docs/redesign/HANDOVER.md` and `docs/redesign/reference/Kluis.dc.html` (the approved clickable prototype: markup = layout and wording, `<script>` = every state; all data in it is sample data), plus `docs/redesign/kit/` (GTK CSS for both themes, tokens, the safe logo, flows.json, and review-log.md with every design decision from my review).
3. Read HANDOVER.md completely. The decisions in §2 and §11 are final.
   (The design canvas, for my reference only, needs my claude.ai sign-in: https://claude.ai/artifact/RYWQYA1ri4UBnewt3YD1nm — everything you need is already in the zip.)

**Build, without checkpoints**
4. Build a feature inventory from the current code and diff it against HANDOVER §9 and §9b; nothing may be dropped. Save the diff as `docs/redesign/inventory.md`.
5. Check every row of HANDOVER §6 against the real, latest `proton-drive` CLI and write `docs/cli-capabilities.md`. Hide UI the CLI can't support; never fake data.
6. Make your own plan as a checklist in `docs/redesign/plan.md` and work through it in small commits on a branch `redesign-1.0`. When something in the spec is unclear, choose the safer option, note it in `docs/redesign/decisions.md`, and carry on.
7. Every flow in §12 (F1–F19) becomes an automated GUI test (Xvfb + mock CLI). Screenshot every step in light and dark mode, at 1440×900 and 1024×640. Every safety rule in §7 has its own test, and the existing 33 sync + 12 photo tests stay green. Fix until everything passes.

**Order of delivery**
8. **First Linux Mint (this machine):** build the `.deb`, install it here, run the full suite and `kluis --selftest` (§8 D) against my account. If the CLI isn't signed in, open the sign-in in my browser once and wait; that's the only thing I'll do. The self-test only touches its own `/Kluis-selftest-*` folder.
9. **Then EndeavourOS:** build the pacman package, then run the install tests and flows F1–F19 in an Arch/EndeavourOS container with KDE (Xvfb) until green.
10. Pass the §10 release gate, bump the version to 1.0.0, push the branch, open a pull request with all screenshots attached, and let GitHub Actions publish the release once CI passes.

**When you're done**, give me exactly:
- The release link and the two download links (.deb for Mint, pacman package for EndeavourOS)
- The one-line install command for her EndeavourOS machine
- Anything you hid because the CLI can't do it, and every entry in `decisions.md`
