"""
purpleteam CLI — three installed commands:

  purpleteam        Spin up N isolated lab segments in Proxmox.
                    Any missing arguments are prompted interactively.
                    Connection defaults come from `purpleteam-setup`.

  purpleteam-setup  Save Proxmox connection defaults to
                    ~/.config/purpleteam/config.json

  purpleteam-init   One-time environment bootstrap: create the SDN simple
                    zone, admin VNet, and admin Debian LXC container.
"""
import argparse
import getpass
import os
import sys
from typing import Optional

from purpleteam import config as cfg_store
from purpleteam import proxmox as px


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _prompt(label: str, default: Optional[str] = None, secret: bool = False) -> str:
    """Prompt the user for a value, showing the existing default if present."""
    if default:
        shown = "****" if secret else default
        prompt_str = f"  {label} [{shown}]: "
    else:
        prompt_str = f"  {label}: "

    value = getpass.getpass(prompt_str) if secret else input(prompt_str).strip()

    if not value and default:
        return default
    if not value:
        print(f"  Error: {label} is required.", file=sys.stderr)
        sys.exit(1)
    return value


def _resolve(
    args,
    attr: str,
    cfg: dict,
    env_key: Optional[str] = None,
    label: Optional[str] = None,
    secret: bool = False,
) -> str:
    """
    Resolve a value in priority order:
      1. CLI flag
      2. Environment variable
      3. Config file default  (from purpleteam-setup)
      4. Interactive prompt
    """
    value = getattr(args, attr, None)
    if value:
        return str(value)

    if env_key:
        value = os.environ.get(env_key)
        if value:
            return value

    value = cfg.get(attr)
    if value:
        return value

    return _prompt(label or attr, secret=secret)


def _parse_int_list(value: str) -> list:
    try:
        return [int(v.strip()) for v in value.split(",") if v.strip()]
    except ValueError:
        print(f"Error: could not parse '{value}' as comma-separated VM IDs.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# purpleteam-setup
# ---------------------------------------------------------------------------

def setup_main() -> None:
    """Entry point for `purpleteam-setup`."""
    existing = cfg_store.load()
    print("Configure Proxmox connection defaults.")
    print(f"Saved to: {cfg_store.path()}\n")
    print("Press Enter to keep the existing value shown in brackets.\n")

    new_cfg = {
        "host":        _prompt("Proxmox host (IP or hostname)", existing.get("host")),
        "user":        _prompt("API user (e.g. root@pam)",      existing.get("user")),
        "token_name":  _prompt("API token name",                existing.get("token_name")),
        "token_value": _prompt("API token value",               existing.get("token_value"), secret=True),
        "node":        _prompt("Default node name",             existing.get("node")),
    }

    cfg_store.save(new_cfg)
    print(f"\nSaved to {cfg_store.path()}")


# ---------------------------------------------------------------------------
# purpleteam (build)
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="purpleteam",
        description=(
            "Spin up N isolated lab segments in Proxmox.\n"
            "Connection defaults are loaded from `purpleteam-setup`.\n"
            "Any missing argument is prompted interactively."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    conn = parser.add_argument_group("connection (defaults from `purpleteam-setup`)")
    conn.add_argument("-H", "--host",        help="Proxmox API host")
    conn.add_argument("-u", "--user",        help="API user (e.g. root@pam)")
    conn.add_argument("-n", "--token-name",  dest="token_name",  help="API token name")
    conn.add_argument("-k", "--token-value", dest="token_value", help="API token value")

    lab = parser.add_argument_group("lab configuration")
    lab.add_argument("-c", "--count",       type=int, help="Number of segments to create")
    lab.add_argument("-t", "--templates",             help="Comma-separated template VM IDs to clone")
    lab.add_argument("-z", "--zone",                  help="SDN simple zone ID")
    lab.add_argument("-p", "--vnet-prefix", dest="vnet_prefix",
                     help="VNet name prefix (e.g. purple → purple1, purple2...)")
    lab.add_argument("-f", "--firewall",    type=int, help="Firewall VM ID to attach each VNet to")
    lab.add_argument("-i", "--start-id",   dest="start_id", type=int,
                     help="Starting VMID for clones; increments sequentially and skips taken IDs. "
                          "Default: Proxmox auto-assign.")

    ci = parser.add_argument_group("cloud-init (applied to each clone)")
    ci.add_argument("--ciuser",       help="Default user account name")
    ci.add_argument("--cipassword",   help="Default user password")
    ci.add_argument("--ipconfig",     default="ip=dhcp", dest="ipconfig",
                    help="IP config for net0 (default: ip=dhcp; e.g. ip=10.0.1.x/24,gw=10.0.1.1)")
    ci.add_argument("--nameserver",   help="DNS nameserver(s), space-separated (e.g. '8.8.8.8 8.8.4.4')")
    ci.add_argument("--searchdomain", help="DNS search domain")
    ci.add_argument("--sshkey",       help="Path to SSH public key file to inject into each clone")

    return parser


def main() -> None:
    """Entry point for `purpleteam`."""
    args = _build_parser().parse_args()
    cfg = cfg_store.load()

    # Connection params — fall back to config file, then prompt
    host        = _resolve(args, "host",        cfg, "PROXMOX_HOST",        "Proxmox host")
    user        = _resolve(args, "user",        cfg, "PROXMOX_USER",        "API user")
    token_name  = _resolve(args, "token_name",  cfg, "PROXMOX_TOKEN_NAME",  "API token name")
    token_value = _resolve(args, "token_value", cfg, "PROXMOX_TOKEN_VALUE", "API token value", secret=True)

    # Lab params — always prompted if missing (not stored in config)
    count_str   = _resolve(args, "count",       {}, label="Number of segments to create")
    templates_s = _resolve(args, "templates",   {}, label="Template VM IDs (comma-separated)")
    zone        = _resolve(args, "zone",        {}, label="SDN zone ID")
    prefix      = _resolve(args, "vnet_prefix", {}, label="VNet name prefix (e.g. labnet)")
    firewall_s  = _resolve(args, "firewall",    {}, label="Firewall VM ID")

    # start_id is optional — prompt only if not given via flag, allow empty for auto-assign
    start_id = args.start_id
    if start_id is None:
        raw = input("  Starting VM ID (Enter for Proxmox auto-assign): ").strip()
        if raw:
            try:
                start_id = int(raw)
            except ValueError:
                print("Error: start ID must be an integer.", file=sys.stderr)
                sys.exit(1)

    try:
        count       = int(count_str)
        templates   = _parse_int_list(templates_s)
        firewall_id = int(str(firewall_s).strip())
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if count < 1:
        print("Error: --count must be at least 1.", file=sys.stderr)
        sys.exit(1)

    # Read SSH public key once if provided
    sshkeys = None
    if args.sshkey:
        try:
            with open(args.sshkey) as fh:
                sshkeys = fh.read().strip()
        except OSError as e:
            print(f"Warning: could not read SSH key file: {e}", file=sys.stderr)

    print(f"\nConnecting to {host} as {user}...")
    proxmox = px.connect(host, user, token_name, token_value)

    # Resolve node, type (qemu/lxc), and name for all templates + firewall
    print("Resolving VM/container locations...")
    all_info = px.resolve_resource_info(proxmox, templates + [firewall_id])
    fw_node  = all_info[firewall_id]["node"]

    # Build a VMID allocator — sequential from start_id (skipping taken IDs),
    # or Proxmox auto-assign if no start_id was given.
    if start_id is not None:
        taken = px.list_all_vmids(proxmox)
        cursor = [start_id]
        def allocate_vmid():
            vid = cursor[0]
            while vid in taken:
                vid += 1
            taken.add(vid)
            cursor[0] = vid + 1
            return vid
    else:
        def allocate_vmid():
            return px.next_vmid(proxmox)

    # Phase 1: Create all VNets, continuing from the highest existing suffix
    existing = px.list_sdn_vnets(proxmox)
    existing_nums = [
        int(v[len(prefix):]) for v in existing
        if v.startswith(prefix) and v[len(prefix):].isdigit()
    ]
    start = max(existing_nums, default=0) + 1
    vnet_names = [f"{prefix}{i}" for i in range(start, start + count)]
    print(f"\nCreating {count} VNet(s) in zone '{zone}' (starting at {prefix}{start})...")
    for vnet_name in vnet_names:
        print(f"  + {vnet_name}")
        px.create_vnet(proxmox, zone, vnet_name)

    # Phase 2: Apply SDN once
    print("Applying SDN configuration...")
    px.apply_sdn(proxmox)

    # Phase 3: Clone VMs/containers and wire networks
    for i, vnet_name in enumerate(vnet_names, start=1):
        print(f"\n[Segment {i}/{count}]  VNet: {vnet_name}")

        for tmpl_id in templates:
            info       = all_info[tmpl_id]
            node       = info["node"]
            tmpl_type  = info["type"]   # 'qemu' or 'lxc'
            tmpl_name  = info["name"]
            new_id     = allocate_vmid()
            clone_name = f"{vnet_name}-{tmpl_name}"

            print(f"  Cloning {tmpl_type.upper()} {tmpl_id} ({tmpl_name}) → {new_id} ({clone_name})...")
            if tmpl_type == "qemu":
                upid = px.clone_vm(proxmox, node, tmpl_id, new_id, clone_name)
            else:
                upid = px.clone_ct(proxmox, node, tmpl_id, new_id, clone_name)
            print(f"    Waiting for task to complete...")
            px.wait_for_task(proxmox, node, upid)
            print(f"    Setting net0 → {vnet_name}")
            if tmpl_type == "qemu":
                px.set_net0(proxmox, node, new_id, vnet_name)
                px.apply_cloudinit_vm(
                    proxmox, node, new_id,
                    ciuser=args.ciuser,
                    cipassword=args.cipassword,
                    ipconfig0=args.ipconfig,
                    nameserver=args.nameserver,
                    searchdomain=args.searchdomain,
                    sshkeys=sshkeys,
                )
            else:
                px.set_ct_net0(proxmox, node, new_id, vnet_name)
                px.apply_cloudinit_ct(
                    proxmox, node, new_id,
                    password=args.cipassword,
                    nameserver=args.nameserver,
                    searchdomain=args.searchdomain,
                )

        slot = px.next_free_net_slot(proxmox, fw_node, firewall_id)
        print(f"  Adding net{slot} → {vnet_name} on firewall VM {firewall_id}")
        px.add_net(proxmox, fw_node, firewall_id, slot, vnet_name)

    print(f"\nDone. {count} segment(s) created successfully.")


# ---------------------------------------------------------------------------
# purpleteam-init
# ---------------------------------------------------------------------------

def init_main() -> None:
    """
    Entry point for `purpleteam-init`.
    One-time bootstrap: creates the SDN simple zone, admin VNet, and an
    admin Debian LXC container — automating sections 2 and 5 of the README.
    """
    cfg = cfg_store.load()

    print("Bootstrap Proxmox lab environment.")
    print("Connection defaults will be loaded from config if available.\n")

    host        = _resolve(_Namespace(), "host",        cfg, "PROXMOX_HOST",        "Proxmox host")
    user        = _resolve(_Namespace(), "user",        cfg, "PROXMOX_USER",        "API user")
    token_name  = _resolve(_Namespace(), "token_name",  cfg, "PROXMOX_TOKEN_NAME",  "API token name")
    token_value = _resolve(_Namespace(), "token_value", cfg, "PROXMOX_TOKEN_VALUE", "API token value", secret=True)
    node        = _resolve(_Namespace(), "node",        cfg, "PROXMOX_NODE",        "Node name")

    zone         = _prompt("SDN zone ID to create",       default="purple")
    admin_vnet   = _prompt("Admin VNet name",              default="purple")
    admin_host   = _prompt("Admin container hostname",     default="admin")
    storage      = _prompt("Storage ID for CT template",   default="local")

    print(f"\nConnecting to {host} as {user}...")
    proxmox = px.connect(host, user, token_name, token_value)

    # SDN zone
    existing_zones = px.list_sdn_zones(proxmox)
    if zone in existing_zones:
        print(f"  Zone '{zone}' already exists — skipping.")
    else:
        print(f"  Creating SDN simple zone '{zone}'...")
        px.create_sdn_zone(proxmox, zone)

    # Admin VNet
    existing_vnets = px.list_sdn_vnets(proxmox)
    if admin_vnet in existing_vnets:
        print(f"  VNet '{admin_vnet}' already exists — skipping.")
    else:
        print(f"  Creating VNet '{admin_vnet}' in zone '{zone}'...")
        px.create_vnet(proxmox, zone, admin_vnet)

    # Apply SDN
    print("  Applying SDN configuration...")
    px.apply_sdn(proxmox)

    # Debian LXC template
    print(f"\nLooking for Debian standard CT template in '{storage}'...")
    result = px.get_debian_template(proxmox, node, storage)

    if isinstance(result, tuple):
        # Not yet downloaded — result is (template_filename, storage)
        template_file, stor = result
        print(f"  Downloading {template_file}...")
        upid = px.download_ct_template(proxmox, node, stor, template_file)
        px.wait_for_task(proxmox, node, upid)
        ostemplate = f"{stor}:vztmpl/{template_file}"
    else:
        ostemplate = result
        print(f"  Using existing template: {ostemplate}")

    # Admin LXC container
    vmid = px.next_vmid(proxmox)
    print(f"\nCreating admin LXC container '{admin_host}' (VMID {vmid}) on '{admin_vnet}'...")
    upid = px.create_lxc(proxmox, node, vmid, admin_host, ostemplate, storage, admin_vnet)
    print(f"  Waiting for container creation...")
    px.wait_for_task(proxmox, node, upid)

    print(f"\nDone. Environment bootstrapped:")
    print(f"  SDN zone:        {zone}")
    print(f"  Admin VNet:      {admin_vnet}")
    print(f"  Admin container: {admin_host} (VMID {vmid})")
    print(f"\nNext step: create the pfSense firewall VM (see environment/README.md).")


class _Namespace:
    """Minimal stand-in for argparse.Namespace when no CLI args are parsed."""
    pass
