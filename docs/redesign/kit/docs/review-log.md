# Design review log — Kluis 1.0 (claude.ai, 2026-11-26)

Everything Walter decided while reviewing the designs and the clickable prototype, in order. Claude Code can't read those chats, so this is the full record. The prototype in `reference/Kluis.dc.html` already reflects every item.

## Direction
1. Out of 10 seeded designs, Walter picked **Starlog**, **Tidepool** and **Heartline**, inspired by **Proton VPN's desktop app**.
2. **Keepers:** Starlog's *timeline*, Tidepool's *"19 of 40" progress bar*, Atlas's *transfer-speed graph* and *map*, and Aurora's *space indicator*.
3. Style: a **companion app to Proton VPN** (dark violet-grey, green glow across the top, floating panels). No Proton logos or name in the brand.

## Home and map
4. The map is the **landing page (Home)**. The sidebar switches to Folders, Photos and the other screens.
5. The "You" pin is **wherever the user appears to be**: the VPN exit when the VPN is on (Adelaide, Lisbon, Cape Town…), otherwise the real location.
6. **No "next sync" countdown.** A desktop sync client watches folders; show what it's watching and when it last acted.

## Layout and chrome
7. Right column = **Quick settings**, **collapsible upwards**. When collapsed the column disappears, the main area takes the space, and its toggle button moves into the header.
8. The Quick settings button has the same size and style as the header buttons: sliders icon + a **chevron that always points down** (state shown by tint).
9. Column order: **⚙ All settings… first** (it opens the old ⋮ menu), then a fading divider, a "Quick settings" heading, then the toggles. The ⋮ header button was removed.
10. **Small gear icon** in the sidebar header opens Settings.
11. **Logo = a safe** ("kluis" means safe).
12. The bottom bar is **Proton-VPN-style**: 🔒 status • duration, a 2×2 grid (Encryption, Space used + mini bar, Uploading N of M + mini bar + ETA, Total today), and a "Current transfer" graph (green solid ↓, red dashed ↑, 0/8/16 axis).
13. The app is a **fixed desktop window** (1440×900), not an endless page. Only the content area scrolls, and on Photos **only the gallery scrolls**.
14. **Scrollbars match the timeline:** a thin grey track line and a green rounded thumb fading downwards.
15. **Every table column is resizable** (Browse, Shared with me).

## Folders and Browse
16. Each synced folder shows its **size**.
17. Browse shows **number of files** per folder (and folder sizes).

## Photos
18. The two cards are headed **Download** and **Upload**.
19. Folder picker: **"Change…" sits next to the path**, and clicking the path opens the folder (no separate "Open folder" button). The same on both cards.
20. Both cards are **collapsible to save space**, start collapsed, the **whole header is clickable**, and the chevron shows the state (down = closed, up = open).
21. The gallery is a **timeline** with **2+ years** of photos grouped by month with year headings.
22. The month **scrubber sits on the right**: the full range with one dot per month, a ring + label on the month in view, the line filling green above it, and a click on a dot scrolling there.
23. Known prototype limit, to fix in the real app: the ring must not jump at the end. Map it to the middle of the viewport and ease across the last screenful.

## Shared with me and Settings
24. Add **Shared with me** (like Proton Drive's): Permissions, Name, Shared by, Shared on (sortable), Sync switch + ⓘ.
25. Each shared item gets a **target folder picker**.
26. Settings gets a **Proton Drive folder location picker** (like Proton Drive's), plus Language and Beta access.

## Delivery decisions
27. End user: **Walter's sister**, on **EndeavourOS (KDE)**, using Proton VPN. Walter won't support it, so it has to be rock solid.
28. The **VPN view is always on**; without a VPN it shows the home location.
29. **Kluis updates: notify only. Proton CLI: always the latest**, never pinned.
30. **No test account, no manual testing.** Prove it with automated end-to-end flows + `kluis --selftest`. **Always include end-to-end flows in handovers.**
31. Claude Code works **autonomously**: **Linux Mint first**, then **EndeavourOS**; Walter only wants the finished product.
