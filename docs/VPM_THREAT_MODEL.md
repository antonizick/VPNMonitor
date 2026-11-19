# VPM: Threat model

**Phase 08, written 2026-11-19 10:05 CST.** Each row maps to a passing test or a documented mitigation (acceptance criterion of Phase 08). Test names are in `tests/`; `fi::` means `tests/test_fault_injection.py`.

## What we protect
| Asset | Why it matters |
|---|---|
| **A1 The owner's belief about protection** | The bar is a safety signal. Blue says "this browser's traffic leaves through a VPN". A false **blue** makes the owner act as if protected when he is not (spec S6). This is the primary asset; every other failure is secondary. |
| A2 Privacy of what is on screen | Window titles carry page names and URLs (S1). |
| A3 The desktop's usability | The overlay must never steal clicks or keys, or block the session (S4). |
| A4 The user account | The daemon runs as the user; it must not widen what other local users or processes can do (S3, S5). |

**Reading of the signal.** Red means "not known to be protected". **No bar** means "no browser focused, paused, or the overlay cannot draw". Neither is a claim of safety; only blue is. Where a fault can only be made red-or-hidden, hidden is accepted because it makes no claim.

## Trust boundaries
- **Kernel** (routing table, link kinds, netlink events): trusted. VPN Monitor reports what the kernel would do with the user's packets; it cannot see inside the tunnel.
- **Hyprland IPC** (socket2 events, `j/activewindow`): trusted for focus and monitor; its text may contain hostile window titles, which are dropped at the parser.
- **Same-uid processes**: same trust level as the daemon (they can already kill it, edit its config, or draw their own surfaces). Not defended against.
- **Other local users**: untrusted. They must not control or read the daemon.
- **Remote hosts**: no interaction at all.

## A1: false-blue failure modes
| # | Threat | Mitigation | Evidence |
|---|---|---|---|
| T1 | **Stale reading**: the VPN drops but no new reading arrives (watcher stuck), so an old VPN reading keeps blue | Blue needs a reading younger than `vpn.max_reading_age_s` (10 s); the daemon arms one timer at the reading's expiry, so a silent watcher turns blue into red with no other input (ADR-0013) | `test_engine::test_reading_goes_stale_and_turns_red`, `test_daemon::test_stuck_vpn_watcher_turns_blue_into_red_by_timer` |
| T2 | **Split-tunnel leak**: IPv4 via VPN, IPv6 via Wi-Fi (or the reverse) | Both families are probed; any family routed outside a VPN is a leak → NO_VPN; the engine re-checks routes against a VPN verdict (defence in depth) | `test_vpn::test_combine_table` (all 25 pairs), `test_engine::test_vpn_state_contradicting_routes_is_red`, `test_engine::test_s6_invariant_over_all_combinations` |
| T3 | **Policy-routing surprises**: fwmarks, uid rules, extra tables (ProtonVPN) | `ip route get` is asked as the user's own process, so it honours the same rules as the browser; `ip monitor` also watches `rule` changes; table is logged | Live check Phase 04 (both families via `proton0`, table 245447468); `test_vpn::test_fixture_scenarios`, `test_vpn::test_table_is_named_in_the_detail` |
| T4 | **Kill switch with no tunnel** (everything blocked) shown as blue | "Blocked" alone never gives blue: at least one family must be routed via a VPN | `test_engine::test_vpn_state_contradicting_routes_is_red`, `test_vpn::test_combine_table` |
| T5 | **Unknown interface type** (e.g. policy-based IPsec without an interface) | Only kernel link kinds `wireguard`/`tun` or configured name globs count as VPN; anything else is a leak → red (false red, accepted; README "Honest limits") | `test_vpn::test_classify`, `test_vpn::test_classifier_falls_back_to_names` |
| T6 | **`ip` hangs or is missing** | 1 s timeout per call (bounded main-loop stall); a timeout, missing binary or garbage gives an ERROR route → UNKNOWN → red | `fi::test_ip_route_get_hangs_turns_red_and_is_logged`, `fi::test_ip_route_get_hangs_during_a_recheck_turns_red`, `fi::test_ip_disappears_turns_red`, `fi::test_real_hanging_command_is_cut_off_by_the_timeout`, `test_vpn::test_family_outcomes` |
| T7 | **Watcher death**: `ip monitor` exits and cannot restart, so drops go unseen | Restart with back-off 0.5→30 s; while it is down longer than `max_reading_age_s`, a VPN reading is downgraded to UNKNOWN (red) even though probes still run | `fi::test_ip_monitor_dies_for_good_turns_red_within_the_reading_age`, `fi::test_ip_monitor_recovers_and_blue_needs_a_fresh_probe`, `test_vpn_watcher::test_cannot_spawn_is_retried_and_blue_degrades` |
| T8 | **Crash in a callback or in the engine** | Any exception in the pipeline is logged and fed to the engine as UNKNOWN (red); if the engine itself fails, a blue bar is forced red; a crashed process removes its surface (the compositor destroys it) and systemd restarts it | `test_daemon::test_callback_exception_in_the_vpn_path_is_red_not_blue`, `test_daemon::test_broken_engine_forces_a_blue_bar_red`, `test_daemon::test_reload_replay_failure_is_red_not_blue` |
| T9 | **Hyprland restart / socket closes mid-line** | A half line is never parsed; on hang-up "no focus" is delivered at once (hidden), then reconnect with back-off and the initial state is re-read | `fi::test_hyprland_socket_closes_mid_line_hides_and_recovers`, `test_focus::test_partial_lines_are_buffered_until_complete` and the reconnect tests |
| T10 | **Monitor hot-plug**: the bar stays on a monitor that no longer shows the browser | The bar follows the Decision's monitor only; unplug destroys the surface, replug recreates it; unknown monitor → hidden | `test_overlay::test_overlay_monitor_unplug_and_replug`, `test_overlay::test_overlay_unknown_monitor_logs_and_shows_nothing`, `test_engine::test_monitor_removed_moves_bar` |
| T11 | **Suspend / resume**: `time.monotonic` stops in suspend, so a reading taken before a long sleep would still look fresh on resume | Engine and readings use `CLOCK_BOOTTIME` (counts suspend, ADR-0019): the first event or timer after resume finds the reading stale → red until a fresh probe. Residual: until the first wake-up after resume (at most `recheck_interval_s` + the debounce, usually immediate because Wi-Fi reconnects cause route events), the bar keeps its pre-suspend colour; the lock screen covers it then (ext-session-lock hides all layer surfaces) | `fi::test_resume_after_suspend_is_red_at_the_first_wake_up`, `fi::test_resume_with_no_event_is_red_when_the_pending_timer_fires`, `fi::test_the_daemon_and_the_vpn_watcher_share_the_boot_clock` |
| T12 | **Clock jumps** (NTP, manual date change) | Decisions never read the wall clock; `CLOCK_BOOTTIME` cannot jump. A reading dated in the future (bad injected clock) is invalid → red | `fi::test_wall_clock_jumps_only_change_log_timestamps`, `test_engine::test_future_or_nan_timestamp_is_red` |
| T13 | **Overlay cannot draw** (surface creation fails, layer-shell missing) | Toolkit errors are logged and contained; the daemon keeps deciding and logging, and recovers on the next decision. Without gtk4-layer-shell the daemon refuses to start rather than open a normal window. Result is "no bar" (hidden, no claim) | `fi::test_overlay_surface_creation_fails_daemon_keeps_running`, `test_overlay::test_overlay_toolkit_fault_is_logged_not_raised` |
| T14 | **Log directory unwritable / disk full** stops the daemon, so no indicator at all | The log falls back to stderr (journal) with a `log_degraded` event; a failing write is reported once per file and never raised (Phase 08 fix; before it, an unwritable directory crash-looped the service) | `fi::test_unwritable_log_directory_falls_back_to_stderr`, `fi::test_read_only_existing_log_files_fall_back_to_stderr`, `fi::test_failing_writes_are_reported_once_and_never_raise` |
| T15 | **A red delay in config** keeps a false blue on screen | `indicator.red_confirm_ms` must be 0 (config error otherwise); only blue may be delayed | `fi::test_config_never_allows_a_red_delay`, `test_engine::test_red_is_immediate_even_with_blue_confirm` |
| T16 | **Paused and forgotten** | Pause hides the bar (no claim), lasts until resume or next login, plays a cue and shows a notification; `pause.auto_resume_minutes` optional | `test_daemon::test_pause_hides_and_resume_restores`, `test_daemon::test_pause_auto_resumes_when_configured` |
| T17 | **Tunnel up but dead** (WireGuard interface present, no handshake) | Out of scope by definition (A2): routes still go into the tunnel, so traffic is blocked, not leaked. Blue is correct for "does not leak"; it does not mean "internet works" | README "Honest limits" |
| T18 | **DNS leak** | Out of scope (owner question 5, deferred). README "Honest limits" | Documented |

## A2: privacy
| # | Threat | Mitigation | Evidence |
|---|---|---|---|
| P1 | Titles reach the logs, `status` or the screen | Titles are dropped in the parser; no type has a title field; `TitleGuard` in tests | `test_model` (no title field), `test_focus::test_title_carrying_events_are_reduced_to_their_name`, `test_eventlog::test_engine_decisions_never_log_titles`; real-log audit Phase 08 (no title of any open window, no URL, public IP, MAC or connection name in 117 KB of logs) |
| P2 | Web-app classes reveal sites | Accepted: an Omarchy web app's class contains its host (`brave-maps.google.com__-Default`). These are apps the owner installed, not browsing history. Logs are 0700/0600 and rotated | SECURITY S1, `fi::test_log_files_are_private` |
| P3 | Logs readable by other users | Directory 0700, files created 0600 (Phase 08; earlier files are tightened at start), service `UMask=0077` | `test_eventlog::test_tightens_existing_directory_mode`, `fi::test_log_files_are_private`, `fi::test_existing_loose_log_files_are_tightened`, `fi::test_rotated_files_are_private` |
| P4 | Logs grow without bound | Size rotation: 1 MB × (1 + 3 backups) × 2 files ≈ 8 MB maximum by default | `test_eventlog::test_rotation`, `fi::test_rotated_files_are_private` |
| P5 | Contact with an external host (IP-check service, telemetry) | No socket code in the detector; the unit allows only `AF_UNIX` and `AF_NETLINK`, so the kernel refuses IP sockets | `test_vpn::test_no_network_imports`, `test_overlay::test_overlay_module_has_no_network_or_title_access`, unit file, `systemd-analyze` |

## A3/A4: local attackers and the desktop
| # | Threat | Mitigation | Evidence |
|---|---|---|---|
| L1 | Another user pauses the indicator (making it hide) or reads status | Socket dir 0700, socket 0600, `SO_PEERCRED` uid check, dropped without reply and logged | `test_control::test_directory_and_socket_permissions`, `test_control::test_a_peer_with_another_uid_is_dropped_without_a_reply` |
| L2 | Malformed / oversized control input | One line ≤ 4096 bytes, four fixed commands, everything else rejected and logged (sanitised); no input is executed | `test_control::test_anything_else_is_rejected_and_logged`, `test_control::test_oversized_and_unterminated_requests_are_rejected` |
| L3 | A slow same-uid client stalls the main loop | 0.5 s client timeout. Residual: one such client can delay a decision by up to 0.5 s (same-uid, accepted) | `test_control::test_a_silent_client_is_dropped` |
| L4 | Second daemon fights over the bar | `flock` single-instance lock | `test_control::test_second_instance_is_refused_and_lock_is_reusable` |
| L5 | Overlay steals input | Layer OVERLAY, keyboard NONE, empty input region on every map, exclusive zone 0; refuses to run as a normal window | `test_overlay_wayland` (real GTK), Nick clicked through the live bar (Phase 06) |
| L6 | Privilege: the daemon is a stepping stone | Runs as the user; empty capability set, `NoNewPrivileges`, `ProtectSystem=strict`, read-only home, syscall filter, no namespaces; `systemd-analyze --user security` 1.6 OK. Remaining exposure items are needed (see below) | Phase 08 scan |
| L7 | Child processes inherit `LD_PRELOAD=libgtk4-layer-shell.so` | `ip` gets a cleaned environment; `notify-send` and the sound player only run in the CLI process, which is never preloaded | `test_vpn::test_child_env_drops_only_the_layer_shell_preload` |
| L8 | Shell injection through subprocesses | Every subprocess uses a fixed argv list, never a shell; inputs are our own constants or file paths (ruff `S` rules now on in lint, each exception justified inline) | ruff `S`, bandit (Phase 08: 0 medium/high) |

### systemd exposure items left open (justified)
`PrivateNetwork` (would hide the real routing table), `RestrictAddressFamilies` keeps `AF_NETLINK` (needed by `ip`) and `AF_UNIX` (Wayland, Hyprland, control socket), `ProtectHome` read-only rather than `tmpfs` (the config and the repo live under home), `PrivateDevices`/`DeviceAllow` (GTK may open `/dev/dri`), `MemoryDenyWriteExecute` (breaks GLib/Python closures), `PrivateUsers` and `IPAddressDeny` (no effect or unsupported for user units on this machine; IP sockets are already impossible), `@privileged`/`@resources` syscalls (part of `@system-service`; nothing to gain with no capabilities).

## Scanner results (2026-11-19 09:52 CST)
| Scanner | Result |
|---|---|
| `ruff --select S` (now in the lint config) | 0 after fixes: 4 `assert`s in `src/` replaced by explicit checks; 7 subprocess/exec calls kept with an inline justification (fixed argv, no shell) |
| `bandit -r src` | 0 high, 0 medium; 11 low, all subprocess use reviewed (same calls as above) |
| `uv audit` (dev deps in `uv.lock`) | No known vulnerabilities in 15 packages |
| `gitleaks git` (full history, 47 commits) | No leaks |
| `shellcheck` (`scripts/*.sh`, `scripts/vpn-monitor`) | Clean |
| `systemd-analyze --user security vpn-monitor.service` | 1.6 OK |
