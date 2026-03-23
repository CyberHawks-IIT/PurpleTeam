"""
Proxmox API operations for the lab segment builder.
All functions accept a ProxmoxAPI instance as their first argument.
"""
import time

from proxmoxer import ProxmoxAPI


def connect(host: str, user: str, token_name: str, token_value: str) -> ProxmoxAPI:
    """Return an authenticated ProxmoxAPI session using an API token."""
    return ProxmoxAPI(
        host,
        user=user,
        token_name=token_name,
        token_value=token_value,
        verify_ssl=False,
    )


def resolve_node(proxmox: ProxmoxAPI, vmid: int) -> str:
    """Return the node name that hosts the given VMID (VM or container)."""
    resources = proxmox.cluster.resources.get(type="vm")
    for r in resources:
        if r.get("vmid") == vmid:
            return r["node"]
    raise ValueError(f"VMID {vmid} not found in cluster")


def resolve_resource_info(proxmox: ProxmoxAPI, vmids: list) -> dict:
    """
    Return a dict mapping vmid -> {node, type, name} for each requested VMID.
    A single cluster API call covers both QEMU VMs and LXC containers.
    'type' is either 'qemu' or 'lxc'.
    """
    resources = proxmox.cluster.resources.get(type="vm")
    lookup = {r["vmid"]: r for r in resources}
    result = {}
    for vmid in vmids:
        r = lookup.get(vmid)
        if r is None:
            raise ValueError(f"VMID {vmid} not found in cluster")
        result[vmid] = {
            "node": r["node"],
            "type": r["type"],  # 'qemu' or 'lxc'
            "name": r.get("name", f"vm{vmid}"),
        }
    return result


def resolve_vm_name(proxmox: ProxmoxAPI, node: str, vmid: int) -> str:
    """Return the name of a QEMU VM, falling back to 'vm{vmid}' if unset."""
    cfg = proxmox.nodes(node).qemu(vmid).config.get()
    return cfg.get("name", f"vm{vmid}")


def next_vmid(proxmox: ProxmoxAPI) -> int:
    """Return the next available VMID from the cluster."""
    return int(proxmox.cluster.nextid.get())


def create_vnet(proxmox: ProxmoxAPI, zone: str, vnet_name: str) -> None:
    """Create a VNet in the given SDN simple zone."""
    proxmox.cluster.sdn.vnets.post(vnet=vnet_name, zone=zone)


def apply_sdn(proxmox: ProxmoxAPI) -> None:
    """Apply all pending SDN configuration changes."""
    proxmox.cluster.sdn.put()


def clone_vm(
    proxmox: ProxmoxAPI,
    node: str,
    template_vmid: int,
    new_vmid: int,
    new_name: str,
) -> str:
    """
    Full-clone a VM and return the task UPID for polling.
    The clone lands on the same node as the template.
    """
    upid = proxmox.nodes(node).qemu(template_vmid).clone.post(
        newid=new_vmid,
        name=new_name,
        full=1,
    )
    return upid


def wait_for_task(proxmox: ProxmoxAPI, node: str, upid: str, poll_interval: float = 2.0) -> None:
    """Block until a task finishes. Raises RuntimeError if it fails."""
    while True:
        status = proxmox.nodes(node).tasks(upid).status.get()
        if status.get("status") == "stopped":
            exit_status = status.get("exitstatus", "")
            if exit_status != "OK":
                raise RuntimeError(f"Task {upid} failed with exitstatus={exit_status!r}")
            return
        time.sleep(poll_interval)


def set_net0(proxmox: ProxmoxAPI, node: str, vmid: int, bridge: str) -> None:
    """Replace net0 on a QEMU VM to use the given bridge (VNet name)."""
    proxmox.nodes(node).qemu(vmid).config.put(net0=f"virtio,bridge={bridge}")


def clone_ct(
    proxmox: ProxmoxAPI,
    node: str,
    template_vmid: int,
    new_vmid: int,
    new_hostname: str,
) -> str:
    """Full-clone an LXC container and return the task UPID for polling."""
    return proxmox.nodes(node).lxc(template_vmid).clone.post(
        newid=new_vmid,
        hostname=new_hostname,
        full=1,
    )


def set_ct_net0(proxmox: ProxmoxAPI, node: str, vmid: int, bridge: str) -> None:
    """Replace net0 on an LXC container to use the given bridge (VNet name)."""
    proxmox.nodes(node).lxc(vmid).config.put(net0=f"name=eth0,bridge={bridge},ip=dhcp")


# ---------------------------------------------------------------------------
# Cloud-init configuration
# ---------------------------------------------------------------------------

def apply_cloudinit_vm(
    proxmox: ProxmoxAPI,
    node: str,
    vmid: int,
    *,
    ciuser: str = None,
    cipassword: str = None,
    ipconfig0: str = "ip=dhcp",
    nameserver: str = None,
    searchdomain: str = None,
    sshkeys: str = None,
) -> None:
    """
    Apply Proxmox cloud-init settings to a QEMU VM.
    ipconfig0 maps to net0; defaults to DHCP.
    sshkeys should be the raw public key string (will be URL-encoded).
    """
    import urllib.parse
    params = {"ipconfig0": ipconfig0}
    if ciuser:      params["ciuser"]      = ciuser
    if cipassword:  params["cipassword"]  = cipassword
    if nameserver:  params["nameserver"]  = nameserver
    if searchdomain: params["searchdomain"] = searchdomain
    if sshkeys:     params["sshkeys"]     = urllib.parse.quote(sshkeys, safe="")
    proxmox.nodes(node).qemu(vmid).config.put(**params)


def apply_cloudinit_ct(
    proxmox: ProxmoxAPI,
    node: str,
    vmid: int,
    *,
    password: str = None,
    nameserver: str = None,
    searchdomain: str = None,
) -> None:
    """
    Apply cloud-init-equivalent settings to an LXC container.
    LXC does not support ciuser/sshkeys via the Proxmox cloud-init API;
    those must be configured inside the container at the OS level.
    """
    params = {}
    if password:     params["password"]     = password
    if nameserver:   params["nameserver"]   = nameserver
    if searchdomain: params["searchdomain"] = searchdomain
    if params:
        proxmox.nodes(node).lxc(vmid).config.put(**params)


def next_free_net_slot(proxmox: ProxmoxAPI, node: str, vmid: int) -> int:
    """Return the index of the first unused netN slot (0–31) on a VM."""
    cfg = proxmox.nodes(node).qemu(vmid).config.get()
    for i in range(32):
        if f"net{i}" not in cfg:
            return i
    raise RuntimeError(f"VM {vmid} has no free network interface slots (net0–net31 all used)")


def add_net(proxmox: ProxmoxAPI, node: str, vmid: int, slot: int, bridge: str) -> None:
    """Add a network interface at the given slot index to a VM."""
    proxmox.nodes(node).qemu(vmid).config.put(**{f"net{slot}": f"virtio,bridge={bridge}"})


# ---------------------------------------------------------------------------
# SDN zone helpers
# ---------------------------------------------------------------------------

def list_sdn_zones(proxmox: ProxmoxAPI) -> list:
    """Return a list of existing SDN zone IDs."""
    return [z["zone"] for z in proxmox.cluster.sdn.zones.get()]


def create_sdn_zone(proxmox: ProxmoxAPI, zone_id: str) -> None:
    """Create an SDN simple zone."""
    proxmox.cluster.sdn.zones.post(zone=zone_id, type="simple")


def list_sdn_vnets(proxmox: ProxmoxAPI) -> list:
    """Return a list of existing SDN VNet names."""
    return [v["vnet"] for v in proxmox.cluster.sdn.vnets.get()]


# ---------------------------------------------------------------------------
# LXC container helpers
# ---------------------------------------------------------------------------

def get_debian_template(proxmox: ProxmoxAPI, node: str, storage: str) -> str:
    """
    Return the ostemplate string for the latest Debian standard CT template,
    downloading it from the appliance repository if not already stored.
    Returns a string like 'local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst'.
    """
    # Check already-downloaded templates
    stored = proxmox.nodes(node).storage(storage).content.get(content="vztmpl")
    debian_stored = [
        s for s in stored
        if "debian" in s["volid"].lower() and "standard" in s["volid"].lower()
    ]
    if debian_stored:
        latest = sorted(debian_stored, key=lambda s: s.get("ctime", 0), reverse=True)[0]
        return latest["volid"]

    # Download latest from the appliance repo
    available = proxmox.nodes(node).aplinfo.get()
    candidates = [
        t for t in available
        if "debian" in t.get("package", "").lower() and "standard" in t.get("package", "").lower()
    ]
    if not candidates:
        raise RuntimeError(
            "No Debian standard template found in the appliance repository. "
            "Run 'pveam update' on the node first."
        )
    latest = sorted(candidates, key=lambda t: t.get("version", ""), reverse=True)[0]
    return latest["template"], storage  # caller must download


def download_ct_template(proxmox: ProxmoxAPI, node: str, storage: str, template: str) -> str:
    """Download a CT template to storage. Returns the UPID for task polling."""
    return proxmox.nodes(node).aplinfo.post(storage=storage, template=template)


def create_lxc(
    proxmox: ProxmoxAPI,
    node: str,
    vmid: int,
    hostname: str,
    ostemplate: str,
    storage: str,
    bridge: str,
) -> str:
    """Create an unprivileged Debian LXC container and return the task UPID."""
    return proxmox.nodes(node).lxc.post(
        vmid=vmid,
        hostname=hostname,
        ostemplate=ostemplate,
        storage=storage,
        memory=512,
        net0=f"name=eth0,bridge={bridge},ip=dhcp",
        unprivileged=1,
        start=1,
    )
